import json,datetime,math,collections,re
import numpy as np
from scipy.optimize import minimize
D=datetime.date.fromisoformat
races=json.load(open('races.json'))
starts=[]
for r in sorted(races,key=lambda r:(r['date'],r['venue'],r['rn'])):
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid'] and x['place']]
    if len(rows)<5 or not r['dist'] or r['surface'] not in('芝','ダート'): continue
    if sum(1 for x in rows if x['place']==1)!=1: continue
    rid=(r['date'],r['venue'],r['rn']); n=len(rows)
    for x in rows: starts.append(dict(rid=rid,date=D(r['date']),hid=x['hid'],place=x['place'],pop=min(x['pop'],18),win=int(x['place']==1),n=n))
byh=collections.defaultdict(list)
for s in starts: byh[s['hid']].append(s)
for h,l in byh.items():
    l.sort(key=lambda s:(s['date'],s['rid']))
    for i,s in enumerate(l):
        prior=[p for p in l[:i] if p['date']<s['date'] and p['n']>1][::-1][:6]   # newest first, valid runs only (B's rule; no 中止 rows exist here)
        if prior:
            w=[0.78**k for k in range(len(prior))]
            P=sum(wk*(p['n']-p['place'])/(p['n']-1) for wk,p in zip(w,prior))/sum(w)
            s['bscore']=(P-0.5)*2.1; s['nprior']=len(prior)
        else: s['bscore']=0.0; s['nprior']=0
byr=collections.defaultdict(list)
for s in starts: byr[s['rid']].append(s)
START=D('2026-04-01')
rs=[]
for rid in sorted(byr):
    if D(rid[0])<START: continue
    l=byr[rid]
    rs.append(dict(rid=rid,date=D(rid[0]),pop=np.array([s['pop'] for s in l]),b=np.array([s['bscore'] for s in l]),win=[s['win'] for s in l].index(1)))
def pop_oh(r):
    P=np.zeros((len(r['pop']),18)); P[np.arange(len(r['pop'])),np.minimum(r['pop'],18)-1]=1; return P
def fit(tr,use_b,l2=1e-2):
    Xs=[np.hstack([pop_oh(r),r['b'][:,None]]) if use_b else pop_oh(r) for r in tr]; ws=[r['win'] for r in tr]; dim=Xs[0].shape[1]
    def f(th):
        ll=0; g=np.zeros(dim)
        for X,w in zip(Xs,ws):
            s=X@th; m=s.max(); e=np.exp(s-m); Z=e.sum(); p=e/Z; ll+=s[w]-m-math.log(Z); g+=X[w]-p@X
        return -ll+l2*th@th,-g+2*l2*th
    return minimize(f,np.zeros(dim),jac=True,method='L-BFGS-B').x
def ll_of(scores,win):
    m=scores.max(); return scores[win]-m-math.log(np.exp(scores-m).sum())
rng=np.random.default_rng(11)
def boot(x,B=4000):
    idx=rng.integers(0,len(x),(B,len(x))); return np.percentile(x[idx].mean(1),[2.5,97.5])
for lab,cut in (('A: テスト9/1以降',D('2026-09-01')),('B: テスト8/1以降',D('2026-08-01'))):
    tr=[r for r in rs if r['date']<cut]; te=[r for r in rs if r['date']>=cut]
    th0=fit(tr,False); th1=fit(tr,True)
    base=np.array([ll_of(pop_oh(r)@th0,r['win']) for r in te])
    bonly=np.array([ll_of(1.35*r['b'],r['win']) for r in te])
    second=np.array([ll_of(np.hstack([pop_oh(r),r['b'][:,None]])@th1,r['win']) for r in te])
    unif=np.array([-math.log(len(r['pop'])) for r in te])
    d1=bonly-base; d2=second-base; d0=bonly-unif
    print(f"\n■ {lab}  訓練{len(tr)}・テスト{len(te)}レース（全頭）")
    print(f"  人気順位だけ(基準)   LL {base.mean():.4f}   全頭同確率 {unif.mean():.4f}")
    print(f"  Bの式だけ(係数1.35)  LL {bonly.mean():.4f}  基準との差 {d1.mean():+.4f} [{boot(d1)[0]:+.4f},{boot(d1)[1]:+.4f}]   同確率との差 {d0.mean():+.4f} [{boot(d0)[0]:+.4f},{boot(d0)[1]:+.4f}]")
    print(f"  人気順位+Bの得点    LL {second.mean():.4f}  基準との差 {d2.mean():+.4f} [{boot(d2)[0]:+.4f},{boot(d2)[1]:+.4f}]  Bの係数={th1[-1]:.3f}（Bの1.35に対して）")
