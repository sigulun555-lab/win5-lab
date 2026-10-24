import json,datetime,math,collections,sys
import numpy as np
from scipy.optimize import minimize
D=datetime.date.fromisoformat
races=json.load(open('races.json'))
def agen(a):
    import re
    m=re.search(r'(\d+)',a or ''); return int(m.group(1)) if m else 0
starts=[]
for r in sorted(races,key=lambda r:(r['date'],r['venue'],r['rn'])):
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid'] and x['place']]
    if len(rows)<5 or not r['dist'] or r['surface'] not in('芝','ダート'): continue
    if sum(1 for x in rows if x['place']==1)!=1: continue
    rid=(r['date'],r['venue'],r['rn']); n=len(rows)
    for x in rows:
        starts.append(dict(rid=rid,date=D(r['date']),venue=r['venue'],surface=r['surface'],dist=r['dist'],hid=x['hid'],place=x['place'],pop=min(x['pop'],18),win=int(x['place']==1),n=n,age=agen(x['age'])))
byh=collections.defaultdict(list)
for s in starts: byh[s['hid']].append(s)
FE=['last_over','avg3_over','course_good','course_ran','dist_up','dist_down','young','first_run']
for h,l in byh.items():
    l.sort(key=lambda s:(s['date'],s['rid']))
    for i,s in enumerate(l):
        pr=[p for p in l[:i] if p['date']<s['date']]
        f=dict.fromkeys(FE,0.0)
        if pr:
            L=pr[-1]; f['last_over']=(L['pop']-L['place'])/L['n']
            ov=[(p['pop']-p['place'])/p['n'] for p in pr[-3:]]; f['avg3_over']=sum(ov)/len(ov)
            cs=[p for p in pr if p['venue']==s['venue'] and p['surface']==s['surface'] and abs(p['dist']-s['dist'])<=100]
            f['course_ran']=1.0 if cs else 0.0; f['course_good']=1.0 if any(p['place']<=3 for p in cs) else 0.0
            dd=s['dist']-L['dist']; f['dist_up']=1.0 if dd>=200 else 0.0; f['dist_down']=1.0 if dd<=-200 else 0.0
        else: f['first_run']=1.0
        f['young']=1.0 if 0<s['age']<=3 else 0.0
        s.update(f)
byr=collections.defaultdict(list)
for s in starts: byr[s['rid']].append(s)
START=D('2026-04-01')
def build(top3):
    out=[]
    for rid in sorted(byr):
        if D(rid[0])<START: continue
        l=byr[rid]
        if top3:
            t=sorted([s for s in l if s['pop']<=3],key=lambda s:s['pop'])
            if [s['pop'] for s in t]!=[1,2,3] or sum(s['win'] for s in t)!=1: continue
            l=t
        out.append(dict(rid=rid,date=D(rid[0]),pop=np.array([s['pop'] for s in l]),X=np.array([[s[f] for f in FE] for s in l]),win=[s['win'] for s in l].index(1)))
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
rng=np.random.default_rng(5)
def boot(x,B=4000):
    idx=rng.integers(0,len(x),(B,len(x))); return np.percentile(x[idx].mean(1),[2.5,97.5])
SPL={'A':(D('2026-09-01'),None,D('2026-09-01')),'B':(D('2026-08-01'),None,D('2026-08-01'))}
CFG=[(f,[f]) for f in FE if f!='first_run']+[('全部',[f for f in FE])]
out={}
for top3 in (True,False):
    rs=build(top3); lab='top3' if top3 else 'full'
    for sp,(cut,_,_) in SPL.items():
        tr=[r for r in rs if r['date']<cut]; te=[r for r in rs if r['date']>=cut]
        th0=fit(tr,[]); ll0,a0=evalr(th0,te,[])
        print(f'\n■ {lab} 分割{sp}: 訓練{len(tr)}・テスト{len(te)}レース 基準LL {ll0.mean():.4f} 的中率 {a0.mean():.3f}')
        for name,cols in CFG:
            th=fit(tr,cols); ll,a=evalr(th,te,cols); d=ll-ll0; lo,hi=boot(d)
            coef=th[18:]
            print(f'  {name:12s} ΔLL {d.mean():+.5f} [{lo:+.5f},{hi:+.5f}] {"◎" if lo>0 else ""} 的中率差 {a.mean()-a0.mean():+.4f}  係数 {np.round(coef,3).tolist() if len(coef)<=2 else ""}')
            out[f'{lab}_{sp}_{name}']=dict(delta=float(d.mean()),ci=[float(lo),float(hi)],n_test=len(te))
json.dump(out,open('mh_result.json','w'),ensure_ascii=False,indent=1)
