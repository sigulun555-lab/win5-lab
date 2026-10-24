import json,datetime,math,collections,itertools,sys
import numpy as np
from scipy.optimize import minimize
races=json.load(open('races.json'))
D=lambda s: datetime.date.fromisoformat(s)
starts=[]
for r in sorted(races,key=lambda r:(r['date'],r['venue'],r['rn'])):
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid']]
    if len(rows)<5 or r['dist'] is None or r['surface'] not in ('芝','ダート'): continue
    if len([x for x in rows if x['place']==1])!=1: continue
    rid=(r['date'],r['venue'],r['rn'])
    for x in rows:
        c3=x['c3'] or x['c4']
        starts.append(dict(rid=rid,date=D(r['date']),hid=x['hid'],place=x['place'],pop=min(x['pop'],18),wt=x['wt'],surface=r['surface'],dist=r['dist'],going=r['going'],
            win=1 if x['place']==1 else 0,n=len(rows),jockey=x['jockey'],trainer=x['trainer'],c3f=(c3/len(rows)) if c3 else None,bw=x['bw']))
OLD=['form_good','form_bad','cond_good','cond_bad','cond_none','rest150','wt_up','wt_down']
NEW=['j_wr','j_change','t_wr','front_alone','front_crowd','closer_pace','closer_slow','g_good','g_bad','bw_up10','bw_down10']
FEATS=OLD+NEW
NOTE={'j_wr':'騎手の直近勝率(+0.1あたり)','t_wr':'調教師の直近勝率(+0.1あたり)','j_change':'騎手の乗り替わり','front_alone':'逃げ・先行型が1頭だけ','front_crowd':'逃げ・先行型が3頭以上(その馬が先行型)',
 'closer_pace':'差し・追込型で、先行型が3頭以上','closer_slow':'差し・追込型で、先行型が1頭以下','g_good':'今回と同じ重い馬場で3着内の実績','g_bad':'重い馬場で2回以上、すべて8着以下','bw_up10':'馬体重が前走比+10kg以上','bw_down10':'馬体重が前走比-10kg以下'}
# horse-history features
byh=collections.defaultdict(list)
for s in starts: byh[s['hid']].append(s)
for h,l in byh.items(): l.sort(key=lambda s:(s['date'],s['rid']))
HEAVY=('稍重','重','不良')
for h,l in byh.items():
    for i,s in enumerate(l):
        prev=[p for p in l[:i] if p['date']<s['date']][::-1]
        f=dict.fromkeys(FEATS,0.0)
        l3=[p['place'] for p in prev[:3] if p['place']]
        if len(l3)>=3:
            if sum(1 for x in l3 if x<=3)>=2 and max(l3)<=5: f['form_good']=1
            elif min(l3)>=9: f['form_bad']=1
        sel=[p for p in prev[:4] if p['surface']==s['surface'] and abs(p['dist']-s['dist'])<=200 and p['place']]
        if any(p['place']<=3 for p in sel): f['cond_good']=1
        elif len(sel)>=2 and all(p['place']>=8 for p in sel): f['cond_bad']=1
        elif not sel and len(prev)>=3: f['cond_none']=1
        if prev:
            if (s['date']-prev[0]['date']).days>150: f['rest150']=1
            if prev[0]['wt'] and s['wt']:
                dw=s['wt']-prev[0]['wt']
                if dw>=2: f['wt_up']=1
                elif dw<=-2: f['wt_down']=1
            if prev[0]['jockey'] and s['jockey'] and prev[0]['jockey']!=s['jockey']: f['j_change']=1
            if prev[0]['bw'] and s['bw']:
                d=s['bw']-prev[0]['bw']
                if d>=10: f['bw_up10']=1
                elif d<=-10: f['bw_down10']=1
        if s['going'] in HEAVY:
            hv=[p for p in prev[:6] if p['surface']==s['surface'] and p['going'] in HEAVY and p['place']]
            if any(p['place']<=3 for p in hv): f['g_good']=1
            elif len(hv)>=2 and all(p['place']>=8 for p in hv): f['g_bad']=1
        st=[p['c3f'] for p in prev[:3] if p['c3f'] is not None]
        s['style']=sum(st)/len(st) if len(st)>=2 else None
        s.update(f)
# race-level pace features
byr=collections.defaultdict(list)
for s in starts: byr[s['rid']].append(s)
for rid,l in byr.items():
    nF=sum(1 for s in l if s['style'] is not None and s['style']<=0.2)
    known=sum(1 for s in l if s['style'] is not None)
    for s in l:
        if s['style'] is None or known<max(5,len(l)//2): continue
        if s['style']<=0.2:
            if nF==1: s['front_alone']=1
            elif nF>=3: s['front_crowd']=1
        elif s['style']>=0.65:
            if nF>=3: s['closer_pace']=1
            elif nF<=1: s['closer_slow']=1
# rolling jockey / trainer win rate (strictly earlier dates)
def roll(key,fname):
    stats=collections.defaultdict(lambda:[0,0])
    for date,grp in itertools.groupby(sorted(starts,key=lambda s:s['date']),key=lambda s:s['date']):
        grp=list(grp)
        for s in grp:
            r,w=stats[s[key]]; s[fname]=((w+0.07*30)/(r+30)-0.07)*10
        for s in grp:
            stats[s[key]][0]+=1; stats[s[key]][1]+=s['win']
roll('jockey','j_wr'); roll('trainer','t_wr')
def build(lo,hi):
    ss=sorted([s for s in starts if lo<=s['date']<=hi],key=lambda s:s['rid'])
    seg=[];pos=0
    for r,grp in itertools.groupby([s['rid'] for s in ss]):
        n=len(list(grp)); seg.append((pos,pos+n)); pos+=n
    P=np.zeros((len(ss),18))
    for i,s in enumerate(ss): P[i,s['pop']-1]=1
    F=np.array([[s[f] for f in FEATS] for s in ss],float)
    return dict(P=P,F=F,win=np.array([s['win'] for s in ss]),seg=seg)
SPL={'A':((datetime.date(2026,4,1),datetime.date(2026,8,31)),(datetime.date(2026,9,1),datetime.date(2026,10,24))),
     'B':((datetime.date(2026,4,1),datetime.date(2026,7,31)),(datetime.date(2026,8,1),datetime.date(2026,10,24))),
     'C':((datetime.date(2026,6,1),datetime.date(2026,10,24)),(datetime.date(2026,4,1),datetime.date(2026,5,31)))}
def design(d,cols): return np.hstack([d['P'],d['F'][:,cols]]) if cols else d['P']
def nll_grad(th,X,d,l2):
    s=X@th; ll=0; g=np.zeros_like(th)
    for a,b in d['seg']:
        z=s[a:b]; m=z.max(); e=np.exp(z-m); Z=e.sum(); p=e/Z; w=np.argmax(d['win'][a:b])
        ll+=z[w]-m-math.log(Z); g+=X[a+w]-p@X[a:b]
    return -ll+l2*th@th,-g+2*l2*th
def fit(tr,cols,l2=1e-2):
    X=design(tr,cols); return minimize(nll_grad,np.zeros(X.shape[1]),args=(X,tr,l2),jac=True,method='L-BFGS-B').x
def race_ll(th,cols,d):
    s=design(d,cols)@th; out=np.empty(len(d['seg']))
    for k,(a,b) in enumerate(d['seg']):
        z=s[a:b]; m=z.max(); out[k]=z[np.argmax(d['win'][a:b])]-m-math.log(np.exp(z-m).sum())
    return out
rng=np.random.default_rng(11)
def boot(x,B=3000):
    idx=rng.integers(0,len(x),(B,len(x))); return np.percentile(x[idx].mean(1),[2.5,97.5])
out={}
for sp,(TR,TE) in SPL.items():
    tr=build(*TR); te=build(*TE); th0=fit(tr,[]); ll0=race_ll(th0,[],te)
    print(f'\n=== 分割{sp}: 訓練{TR[0]}〜{TR[1]}({len(tr["seg"])}レース) / テスト{TE[0]}〜{TE[1]}({len(te["seg"])}レース) 基準LL {ll0.mean():.4f}')
    out[sp]={}
    for f in NEW:
        j=FEATS.index(f); th=fit(tr,[j]); d=race_ll(th,[j],te)-ll0; lo,hi=boot(d)
        out[sp][f]=dict(mult=float(math.exp(th[-1])),delta=float(d.mean()),lo=float(lo),hi=float(hi),n_test=int((te['F'][:,j]!=0).sum()))
        print(f"  {f:12s} ×{math.exp(th[-1]):.3f}  Δ{d.mean():+.5f} [{lo:+.5f},{hi:+.5f}] {'◎有意' if lo>0 else ''} 該当(テスト){int((te['F'][:,j]!=0).sum())}")
    cols=[FEATS.index(f) for f in NEW]; th=fit(tr,cols); d=race_ll(th,cols,te)-ll0; lo,hi=boot(d)
    print(f"  新要素すべて  Δ{d.mean():+.5f} [{lo:+.5f},{hi:+.5f}]"); out[sp]['ALL_NEW']=dict(delta=float(d.mean()),lo=float(lo),hi=float(hi))
    cols=list(range(len(FEATS))); th=fit(tr,cols); d=race_ll(th,cols,te)-ll0; lo,hi=boot(d)
    print(f"  旧+新すべて   Δ{d.mean():+.5f} [{lo:+.5f},{hi:+.5f}]"); out[sp]['ALL']=dict(delta=float(d.mean()),lo=float(lo),hi=float(hi))
json.dump(out,open('model3_result.json','w'),ensure_ascii=False,indent=1)
print('\n要素の意味:');[print(' ',k,v) for k,v in NOTE.items()]
