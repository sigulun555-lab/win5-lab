import json,datetime,math,sys,collections
import numpy as np
from scipy.optimize import minimize
races=json.load(open('races.json'))
D=lambda s: datetime.date.fromisoformat(s)
# ---- starts
starts=[]
for r in sorted(races,key=lambda r:(r['date'],r['venue'],r['rn'])):
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid']]
    if len(rows)<5 or r['dist'] is None or r['surface'] not in ('芝','ダート'): continue
    wins=[x for x in rows if x['place']==1]
    if len(wins)!=1: continue
    rid=(r['date'],r['venue'],r['rn'])
    for x in rows:
        starts.append(dict(rid=rid,date=D(r['date']),hid=x['hid'],place=x['place'],pop=min(x['pop'],18),wt=x['wt'],surface=r['surface'],dist=r['dist'],win=1 if x['place']==1 else 0,n=len(rows)))
print('starts',len(starts),'races',len({s['rid'] for s in starts}))
# ---- history features
byh=collections.defaultdict(list)
for s in starts: byh[s['hid']].append(s)
for h,l in byh.items(): l.sort(key=lambda s:(s['date'],s['rid']))
FEATS=['form_good','form_bad','cond_good','cond_bad','cond_none','rest150','wt_up','wt_down']
for h,l in byh.items():
    for i,s in enumerate(l):
        prev=[p for p in l[:i] if p['date']<s['date']][::-1]      # most recent first
        f=dict.fromkeys(FEATS,0)
        s['nprev']=len(prev)
        l3=[p['place'] for p in prev[:3] if p['place']]
        if len(l3)>=3:
            if sum(1 for x in l3 if x<=3)>=2 and max(l3)<=5: f['form_good']=1
            elif min(l3)>=9: f['form_bad']=1
        l4=prev[:4]
        sel=[p for p in l4 if p['surface']==s['surface'] and abs(p['dist']-s['dist'])<=200 and p['place']]
        if any(p['place']<=3 for p in sel): f['cond_good']=1
        elif len(sel)>=2 and all(p['place']>=8 for p in sel): f['cond_bad']=1
        elif not sel and len(prev)>=3: f['cond_none']=1
        if prev:
            if (s['date']-prev[0]['date']).days>150: f['rest150']=1
            if prev[0]['wt'] and s['wt']:
                dw=s['wt']-prev[0]['wt']
                if dw>=2: f['wt_up']=1
                elif dw<=-2: f['wt_down']=1
        s.update(f)
# ---- design
import os
sp=os.environ.get('SPLIT','A')
TRAIN,TEST={'A':((datetime.date(2026,4,1),datetime.date(2026,8,31)),(datetime.date(2026,9,1),datetime.date(2026,10,24))),'B':((datetime.date(2026,4,1),datetime.date(2026,7,31)),(datetime.date(2026,8,1),datetime.date(2026,10,24))),'C':((datetime.date(2026,6,1),datetime.date(2026,10,24)),(datetime.date(2026,4,1),datetime.date(2026,5,31)))}[sp]
def build(lo,hi):
    ss=[s for s in starts if lo<=s['date']<=hi]
    ss.sort(key=lambda s:s['rid'])
    rid=[s['rid'] for s in ss]
    idx=[];pos=0;seg=[]
    for k,(r,grp) in enumerate(__import__('itertools').groupby(rid)):
        n=len(list(grp)); seg.append((pos,pos+n)); pos+=n
    P=np.zeros((len(ss),18)); 
    for i,s in enumerate(ss): P[i,s['pop']-1]=1
    F=np.array([[s[f] for f in FEATS] for s in ss],float)
    win=np.array([s['win'] for s in ss]); starts_idx=np.array([a for a,b in seg])
    return dict(P=P,F=F,win=win,seg=seg,ss=ss,st=starts_idx)
tr=build(*TRAIN); te=build(*TEST)
print('train races',len(tr['seg']),'starts',len(tr['win']),'| test races',len(te['seg']),'starts',len(te['win']))
def design(d,cols):
    return np.hstack([d['P'],d['F'][:,cols]]) if cols else d['P']
def nll_grad(theta,X,d,l2):
    s=X@theta; seg=d['seg']
    ll=0; g=np.zeros_like(theta)
    for a,b in seg:
        z=s[a:b]; m=z.max(); e=np.exp(z-m); Z=e.sum(); p=e/Z
        w=np.argmax(d['win'][a:b])
        ll+=z[w]-m-math.log(Z)
        g+=X[a+w]-p@X[a:b]
    return -ll+l2*theta@theta, -g+2*l2*theta
def fit(cols,l2=1e-2):
    X=design(tr,cols); th=np.zeros(X.shape[1])
    r=minimize(nll_grad,th,args=(X,tr,l2),jac=True,method='L-BFGS-B')
    return r.x
def race_ll(theta,cols,d,fixed_extra=None):
    X=design(d,cols); s=X@theta
    if fixed_extra is not None: s=s+fixed_extra
    out=np.empty(len(d['seg']))
    for k,(a,b) in enumerate(d['seg']):
        z=s[a:b]; m=z.max(); out[k]=z[np.argmax(d['win'][a:b])]-m-math.log(np.exp(z-m).sum())
    return out
def top1(theta,cols,d,fixed_extra=None):
    X=design(d,cols); s=X@theta
    if fixed_extra is not None: s=s+fixed_extra
    return np.mean([d['win'][a:b][np.argmax(s[a:b])]==1 for a,b in d['seg']])
rng=np.random.default_rng(7)
def boot(delta,B=4000):
    n=len(delta); idx=rng.integers(0,n,(B,n)); m=delta[idx].mean(1); return np.percentile(m,[2.5,97.5])
res={}
th0=fit([]); ll0=race_ll(th0,[],te)
print(f'\n[テスト期間 {TEST[0]}〜{TEST[1]}] 基準（人気順のみ）: 1レースあたり対数尤度 {ll0.mean():.4f}  ◎的中率(人気1位={top1(th0,[],te):.3f})')
res['baseline']=dict(ll=float(ll0.mean()),top1=float(top1(th0,[],te)),races=len(ll0))
# my hypothesised multipliers (as used in today's prediction)
MULT=dict(form_good=1.06,form_bad=0.90,cond_good=1.04,cond_bad=0.93,cond_none=0.96,rest150=0.95,wt_up=0.97,wt_down=1.03)
def hyp_extra(d):
    lm=d['F']@np.array([math.log(MULT[f]) for f in FEATS])
    # clamp the product to [0.80,1.20] as in the prediction rule
    # recompute product exactly per horse
    prod=np.exp(lm); prod=np.clip(prod,0.80,1.20); return np.log(prod)
llh=race_ll(th0,[],te,hyp_extra(te)); dh=llh-ll0
print(f'今日の予想に使った倍率（仮説）を人気順の基準に掛けた場合: Δ対数尤度 {dh.mean():+.4f}  95%区間 {boot(dh)}  ◎的中率 {top1(th0,[],te,hyp_extra(te)):.3f}')
res['hypothesis']=dict(delta=float(dh.mean()),ci=[float(x) for x in boot(dh)],top1=float(top1(th0,[],te,hyp_extra(te))))
# single-factor fitted
print('\n要素ごとの検証（訓練期間で係数を推定→テスト期間で評価）')
print(f"{'要素':10s} 該当頭数(訓練/テスト)  推定倍率  Δ対数尤度(テスト)  95%区間  採用判定")
res['factors']={}
for j,f in enumerate(FEATS):
    th=fit([j]); beta=th[-1]; ll=race_ll(th,[j],te); d=ll-ll0; lo,hi=boot(d)
    ntr=int(tr['F'][:,j].sum()); nte=int(te['F'][:,j].sum())
    # SE of beta from observed information on train
    X=design(tr,[j]); s=X@th; H=np.zeros((X.shape[1],X.shape[1]))
    for a,b in tr['seg']:
        z=s[a:b]; e=np.exp(z-z.max()); p=e/e.sum(); Xa=X[a:b]; mu=p@Xa; H+= (Xa.T*p)@Xa-np.outer(mu,mu)
    se=math.sqrt(np.linalg.inv(H+1e-6*np.eye(len(H)))[-1,-1])
    ok='採用候補' if lo>0 else ('効果なし/不明' )
    print(f"{f:10s} {ntr:6d}/{nte:5d}   ×{math.exp(beta):.3f}(±{se:.2f}対数) {d.mean():+.5f}   [{lo:+.5f},{hi:+.5f}]  {ok}")
    res['factors'][f]=dict(n_train=ntr,n_test=nte,mult=float(math.exp(beta)),beta=float(beta),se=float(se),delta=float(d.mean()),ci=[float(lo),float(hi)])
# full model
cols=list(range(len(FEATS))); thf=fit(cols); llf=race_ll(thf,cols,te); df=llf-ll0
print(f"\n全要素まとめて推定: Δ対数尤度 {df.mean():+.5f} 95%区間 {boot(df)} ◎的中率 {top1(thf,cols,te):.3f}")
print('推定倍率:',{f:round(math.exp(b),3) for f,b in zip(FEATS,thf[18:])})
res['full']=dict(delta=float(df.mean()),ci=[float(x) for x in boot(df)],top1=float(top1(thf,cols,te)),mult={f:float(math.exp(b)) for f,b in zip(FEATS,thf[18:])})
# baseline win rate by popularity (train+test), for reference
allw=collections.defaultdict(lambda:[0,0])
for s in starts:
    if s['date']>=TRAIN[0]: allw[s['pop']][0]+=s['win']; allw[s['pop']][1]+=1
res['pop_winrate']={k:[v[0],v[1],v[0]/v[1]] for k,v in sorted(allw.items())}
print('\n人気別の1着率(4月以降):',{k:round(v[2]*100,1) for k,v in list(res['pop_winrate'].items())[:6]})
json.dump(res,open('model_result_%s.json'%sp,'w'),ensure_ascii=False,indent=1)
