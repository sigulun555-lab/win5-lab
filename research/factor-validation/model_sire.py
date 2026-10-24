import json,datetime,math,collections
import numpy as np
from scipy.optimize import minimize
D=datetime.date.fromisoformat
races=json.load(open('races.json')); sires=json.load(open('sires.json'))
def db(d): return 0 if d<=1400 else 1 if d<=1800 else 2 if d<=2200 else 3
def gb(g): return '良' if g=='良' else '重'
# pop-rank baseline win rate by field size bucket (global; used only to define "expected")
base=collections.defaultdict(lambda:[0,0])
for r in races:
    rows=[x for x in r['rows'] if x['pop'] and x['place']]
    if len(rows)<5: continue
    nb=min(len(rows)//4,4)
    for x in rows:
        k=(nb,min(x['pop'],10)); base[k][0]+=1; base[k][1]+= x['place']==1
exp=lambda nb,p: base[(nb,min(p,10))][1]/max(1,base[(nb,min(p,10))][0])
bydate=collections.defaultdict(list)
for r in sorted(races,key=lambda r:(r['date'],r['venue'],r['rn'])):
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid'] in sires and x['place']]
    if len(rows)<5 or not r['dist'] or r['surface'] not in('芝','ダート'): continue
    if sum(1 for x in rows if x['place']==1)!=1: continue
    bydate[r['date']].append((r,rows))
FE=['sire_surf','sire_dist','sire_going','dam_surf','dam_dist']
K=40.0
stat=collections.defaultdict(lambda:[0.0,0])  # key -> [sum(win-exp), n]
def val(k):
    s,n=stat[k]; return (s/(n+K))*10 if n else 0.0
starts=[]
for d in sorted(bydate):
    pend=[]
    for r,rows in bydate[d]:
        n=len(rows); nb=min(n//4,4); rid=(r['date'],r['venue'],r['rn'])
        for x in rows:
            si=sires[x['hid']]['父']; da=sires[x['hid']]['母の父']
            f=dict(sire_surf=val(('s',si,r['surface'])),sire_dist=val(('sd',si,r['surface'],db(r['dist']))),sire_going=val(('sg',si,r['surface'],gb(r['going'] or ''))),
                   dam_surf=val(('d',da,r['surface'])),dam_dist=val(('dd',da,r['surface'],db(r['dist']))))
            starts.append(dict(rid=rid,date=D(d),pop=min(x['pop'],18),win=int(x['place']==1),**f))
            e=exp(nb,x['pop']); w=int(x['place']==1)-e
            for k in [('s',si,r['surface']),('sd',si,r['surface'],db(r['dist'])),('sg',si,r['surface'],gb(r['going'] or '')),('d',da,r['surface']),('dd',da,r['surface'],db(r['dist']))]: pend.append((k,w))
    for k,w in pend: stat[k][0]+=w; stat[k][1]+=1   # update after the day
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
rng=np.random.default_rng(7)
def boot(x,B=4000):
    idx=rng.integers(0,len(x),(B,len(x))); return np.percentile(x[idx].mean(1),[2.5,97.5])
CFG=[(f,[f]) for f in FE]+[('父(3つ)',['sire_surf','sire_dist','sire_going']),('母の父(2つ)',['dam_surf','dam_dist']),('全部',FE)]
out={}
for top3 in (True,False):
    rs=build(top3); lab='top3' if top3 else 'full'
    for sp,cut in {'A':D('2026-09-01'),'B':D('2026-08-01')}.items():
        tr=[r for r in rs if r['date']<cut]; te=[r for r in rs if r['date']>=cut]
        th0=fit(tr,[]); ll0,a0=evalr(th0,te,[])
        print(f'\n■ {lab} 分割{sp}: 訓練{len(tr)}・テスト{len(te)}レース 基準LL {ll0.mean():.4f} 的中率 {a0.mean():.3f}')
        for name,cols in CFG:
            th=fit(tr,cols); ll,a=evalr(th,te,cols); d=ll-ll0; lo,hi=boot(d)
            print(f'  {name:12s} ΔLL {d.mean():+.5f} [{lo:+.5f},{hi:+.5f}] {"◎" if lo>0 else ""} 的中率差 {a.mean()-a0.mean():+.4f}')
            out[f'{lab}_{sp}_{name}']=dict(delta=float(d.mean()),ci=[float(lo),float(hi)],n_test=len(te))
json.dump(out,open('ms_result.json','w'),ensure_ascii=False,indent=1)
