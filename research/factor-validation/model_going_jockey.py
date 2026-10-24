import json,datetime,math,collections,itertools,bisect
import numpy as np
from scipy.optimize import minimize
races=json.load(open('races.json')); D=datetime.date.fromisoformat
def gbucket(g): return '良' if g=='良' else ('稍重' if g=='稍重' else '重不良')
starts=[]
for r in sorted(races,key=lambda r:(r['date'],r['venue'],r['rn'])):
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid']]
    if len(rows)<5 or r['dist'] is None or r['surface'] not in ('芝','ダート') or not r['going']: continue
    if len([x for x in rows if x['place']==1])!=1: continue
    rid=(r['date'],r['venue'],r['rn']); n=len(rows)
    for x in rows:
        starts.append(dict(rid=rid,date=D(r['date']),hid=x['hid'],place=x['place'],pop=min(x['pop'],18),win=1 if x['place']==1 else 0,n=n,surface=r['surface'],gb=gbucket(r['going']),jockey=x['jockey']))
WIN=180
# horse: results on similar going within 180 days
byh=collections.defaultdict(list)
for s in starts: byh[s['hid']].append(s)
def quant(p): return 0.0 if not p['place'] else (1-(p['place']-1)/max(1,p['n']-1))
for h,l in byh.items():
    l.sort(key=lambda s:(s['date'],s['rid']))
    for i,s in enumerate(l):
        pr=[p for p in l[:i] if p['date']<s['date'] and (s['date']-p['date']).days<=WIN and p['surface']==s['surface'] and p['gb']==s['gb']]
        n=len(pr); ssum=sum(quant(p) for p in pr)
        s['h_n']=n; s['h_going']=(ssum+0.5*2)/(n+2)-0.5
# jockey within 180 days (overall and on same going bucket)
def prefix(key):
    d=collections.defaultdict(list)
    for s in sorted(starts,key=lambda s:s['date']): d[key(s)].append((s['date'].toordinal(),s['win']))
    return {k:([x[0] for x in v],[0]+list(itertools.accumulate(x[1] for x in v))) for k,v in d.items()}
PJ=prefix(lambda s:s['jockey']); PJG=prefix(lambda s:(s['jockey'],s['gb']))
def wr(P,k,date,K=30):
    if k not in P: return 0.0
    ds,pre=P[k]; D0=date.toordinal(); hi=bisect.bisect_left(ds,D0); lo=bisect.bisect_left(ds,D0-WIN)
    rides=hi-lo; wins=pre[hi]-pre[lo]
    return ((wins+0.07*K)/(rides+K)-0.07)*10
for s in starts:
    s['j_all']=wr(PJ,s['jockey'],s['date']); s['j_going']=wr(PJG,(s['jockey'],s['gb']),s['date'])
    s['hj']=s['h_going']*s['j_all']
FE=['h_going','j_all','j_going','hj']
byr=collections.defaultdict(list)
for s in starts: byr[s['rid']].append(s)
START=datetime.date(2026,4,1)
rids=[rid for rid in sorted(byr) if D(rid[0])>=START]
# ---------- full-field and top-3 subsets
def full_races(filter_wet=False):
    out=[]
    for rid in rids:
        l=byr[rid]
        if filter_wet and l[0]['gb']=='良': continue
        out.append(dict(rid=rid,date=l[0]['date'],pop=np.array([s['pop'] for s in l]),X=np.array([[s[f] for f in FE] for s in l]),win=int(np.argmax([s['win'] for s in l]))))
    return out
def top3_races(filter_wet=False):
    out=[]
    for rid in rids:
        l=byr[rid]
        if filter_wet and l[0]['gb']=='良': continue
        top=sorted([s for s in l if s['pop']<=3],key=lambda s:s['pop'])
        if [s['pop'] for s in top]!=[1,2,3] or sum(s['win'] for s in top)!=1: continue
        out.append(dict(rid=rid,date=top[0]['date'],pop=np.array([1,2,3]),X=np.array([[s[f] for f in FE] for s in top]),win=[s['win'] for s in top].index(1)))
    return out
def design(r,cols):
    P=np.zeros((len(r['pop']),18)); P[np.arange(len(r['pop'])),np.minimum(r['pop'],18)-1]=1
    return np.hstack([P,r['X'][:,[FE.index(c) for c in cols]]]) if cols else P
def fit(rs,cols,l2=1e-2):
    Xs=[design(r,cols) for r in rs]; ws=[r['win'] for r in rs]; dim=Xs[0].shape[1]
    def f(th):
        ll=0; g=np.zeros(dim)
        for X,w in zip(Xs,ws):
            s=X@th; m=s.max(); e=np.exp(s-m); Z=e.sum(); p=e/Z; ll+=s[w]-m-math.log(Z); g+=X[w]-p@X
        return -ll+l2*th@th,-g+2*l2*th
    return minimize(f,np.zeros(dim),jac=True,method='L-BFGS-B').x
def evalr(th,rs,cols):
    ll=[];acc=[]
    for r in rs:
        s=design(r,cols)@th; m=s.max(); ll.append(s[r['win']]-m-math.log(np.exp(s-m).sum())); acc.append(float(np.argmax(s)==r['win']))
    return np.array(ll),np.array(acc)
rng=np.random.default_rng(3)
def boot(x,B=4000):
    idx=rng.integers(0,len(x),(B,len(x))); return np.percentile(x[idx].mean(1),[2.5,97.5])
CFG={'馬の同馬場成績(半年)':['h_going'],'騎手の成績(半年)':['j_all'],'騎手の同馬場成績(半年)':['j_going'],
     '馬×騎手(全体)':['h_going','j_all'],'馬×騎手(同馬場)':['h_going','j_going'],'3つ全部':['h_going','j_all','j_going'],'3つ+掛け合わせ':['h_going','j_all','j_going','hj']}
def run(label,rs,K=5):
    rs=sorted(rs,key=lambda r:r['date']); folds=np.array_split(np.arange(len(rs)),K)
    oof={k:[] for k in ['base']+list(CFG)}; oa={k:[] for k in ['base']+list(CFG)}
    for te_idx in folds:
        te_set=set(te_idx); tr=[rs[i] for i in range(len(rs)) if i not in te_set]; te=[rs[i] for i in te_idx]
        for name,cols in [('base',[])]+list(CFG.items()):
            th=fit(tr,cols); ll,acc=evalr(th,te,cols); oof[name].append(ll); oa[name].append(acc)
    base=np.concatenate(oof['base']); ba=np.concatenate(oa['base'])
    print(f'\n■ {label}（{len(rs)}レース、5分割の交差検証）基準 対数尤度 {base.mean():.4f}、基準の本命的中率 {ba.mean():.3f}')
    res={}
    for name in CFG:
        ll=np.concatenate(oof[name]); ac=np.concatenate(oa[name]); d=ll-base; lo,hi=boot(d); da=ac-ba; alo,ahi=boot(da)
        print(f'  {name:16s} Δ対数尤度 {d.mean():+.5f} [{lo:+.5f},{hi:+.5f}] {"◎有意" if lo>0 else ""}   的中率 {ac.mean():.3f}（基準比 {da.mean():+.4f} [{alo:+.4f},{ahi:+.4f}]）')
        res[name]=dict(delta=float(d.mean()),ci=[float(lo),float(hi)],acc=float(ac.mean()),acc_delta=float(da.mean()))
    return dict(n=len(rs),base_ll=float(base.mean()),base_acc=float(ba.mean()),res=res)
out={}
print('データ: 半年(180日)以内の過去だけを使用。検証対象は2026-04-01以降（助走期間6か月）。')
print('馬の同馬場成績の平均件数:',np.mean([s['h_n'] for s in starts if s['date']>=START]).round(2),' 件数0の馬の割合:',np.mean([s['h_n']==0 for s in starts if s['date']>=START]).round(3))
out['top3']=run('◎○▲＝人気上位3頭の中から1着馬を選ぶ',top3_races())
out['top3_wet']=run('同・稍重〜不良のレースだけ',top3_races(True))
out['full']=run('全頭（出走馬すべて）',full_races())
json.dump(out,open('model5_result.json','w'),ensure_ascii=False,indent=1)
