import json,datetime,math,collections,itertools,statistics
import numpy as np
from scipy.optimize import minimize
races=json.load(open('races.json'))
D=datetime.date.fromisoformat
def secs(t):
    if not t: return None
    try:
        if ':' in t: m,s=t.split(':'); return int(m)*60+float(s)
        return float(t)
    except: return None
CB={'未勝利':0,'新馬':0,'1勝クラス':1,'2勝クラス':2,'3勝クラス':3,'オープン':4}
def wetb(g): return 'good' if g=='良' else 'wet'
# ---- standard times from winners
win_times=collections.defaultdict(list)
R=[]
for r in races:
    rows=[x for x in r['rows'] if x['num'] is not None and x['pop'] is not None and x['hid']]
    if len(rows)<5 or r['dist'] is None or r['surface'] not in ('芝','ダート') or r['going'] is None: continue
    w=[x for x in rows if x['place']==1]
    if len(w)!=1: continue
    wt=secs(w[0]['time']); 
    if wt is None: continue
    cb=CB.get(r['cls'],2)
    rr=dict(r,rows=rows,winner_time=wt,cb=cb,wet=wetb(r['going']),rid=(r['date'],r['venue'],r['rn']))
    R.append(rr)
    for key in [(r['venue'],r['surface'],r['detail'],r['dist'],rr['wet'],cb),(r['surface'],r['dist'],rr['wet'],cb),(r['surface'],r['dist'],cb),(r['surface'],r['dist'])]:
        win_times[key].append(wt)
def std_time(r):
    for key in [(r['venue'],r['surface'],r['detail'],r['dist'],r['wet'],r['cb']),(r['surface'],r['dist'],r['wet'],r['cb']),(r['surface'],r['dist'],r['cb']),(r['surface'],r['dist'])]:
        l=win_times.get(key)
        if l and len(l)>=5: return statistics.median(l)
    return None
# ---- per-start records with speed rating and 3F percentile
starts=[]
for r in sorted(R,key=lambda r:r['rid']):
    st=std_time(r)
    f3s=sorted([x['f3'] for x in r['rows'] if x['f3']])
    for x in r['rows']:
        t=secs(x['time']); rating=((st-t)/r['dist']*1000) if (st and t) else None
        f3p=(f3s.index(x['f3'])/max(1,len(f3s)-1)) if x['f3'] in f3s else None
        starts.append(dict(rid=r['rid'],date=D(r['date']),hid=x['hid'],place=x['place'],pop=x['pop'],win=1 if x['place']==1 else 0,rating=rating,f3p=f3p))
byh=collections.defaultdict(list)
for s in starts: byh[s['hid']].append(s)
for h,l in byh.items():
    l.sort(key=lambda s:(s['date'],s['rid']))
    for i,s in enumerate(l):
        prev=[p for p in l[:i] if p['date']<s['date']][::-1][:3]
        rs=[p['rating'] for p in prev if p['rating'] is not None]; fs=[p['f3p'] for p in prev if p['f3p'] is not None]
        s['r_best']=max(rs) if rs else None; s['r_last']=prev[0]['rating'] if prev and prev[0]['rating'] is not None else None
        s['f3avg']=sum(fs)/len(fs) if fs else None
byr=collections.defaultdict(list)
for s in starts: byr[s['rid']].append(s)
# ---- top-3 subset races
FE=['r_best','r_last','f3avg']
sub=[]
for rid,l in sorted(byr.items()):
    top=sorted([s for s in l if s['pop']<=3],key=lambda s:s['pop'])
    if len(top)!=3 or [s['pop'] for s in top]!=[1,2,3]: continue
    if sum(s['win'] for s in top)!=1: continue
    if any(s[f] is None for s in top for f in FE): continue
    sub.append(dict(rid=rid,date=top[0]['date'],X=np.array([[s[f] for f in FE] for s in top]),pop=[1,2,3],win=[s['win'] for s in top].index(1)))
alln=sum(1 for rid,l in byr.items() if len(l)>=5)
print('top3候補がそろい・1着が3頭の中にいて・3頭とも速さの指標がある レース:',len(sub),'/ 全',alln,'レース')
sub=[r for r in sub if r['date']>=datetime.date(2026,1,1)]
print('2026年以降(助走期間を除く):',len(sub),'レース')
# pop-rank-only baseline & feature columns
def make(rs,cols):
    n=len(rs); X=np.zeros((n,3,2+len(cols))); y=np.array([r['win'] for r in rs])
    for i,r in enumerate(rs):
        X[i,1,0]=1; X[i,2,1]=1
        for j,c in enumerate(cols): X[i,:,2+j]=r['X'][:,FE.index(c)]
    return X,y
def nll(th,X,y,l2=1e-2):
    s=X@th; s=s-s.max(1,keepdims=True); lse=np.log(np.exp(s).sum(1)); ll=(s[np.arange(len(y)),y]-lse).sum()
    p=np.exp(s-lse[:,None]); g=X[np.arange(len(y)),y].sum(0)-(p[:,:,None]*X).sum((0,1))
    return -ll+l2*th@th,-g+2*l2*th
def fit(X,y): return minimize(nll,np.zeros(X.shape[2]),args=(X,y),jac=True,method='L-BFGS-B').x
def per_race(th,X,y):
    s=X@th; s=s-s.max(1,keepdims=True); lse=np.log(np.exp(s).sum(1)); return s[np.arange(len(y)),y]-lse,(np.argmax(s,1)==y).astype(float)
subs=sorted(sub,key=lambda r:r['date'])
K=5; folds=np.array_split(np.arange(len(subs)),K)
rng=np.random.default_rng(5)
def boot(x,B=4000):
    idx=rng.integers(0,len(x),(B,len(x))); return np.percentile(x[idx].mean(1),[2.5,97.5])
configs={'基準(人気順だけ)':[], '前走までの速さ(最高)':['r_best'],'直近走の速さ':['r_last'],'上がり3Fの順位(平均)':['f3avg'],'速さ3つ全部':['r_best','r_last','f3avg']}
oof={k:[] for k in configs}; oofacc={k:[] for k in configs}
for k,test_idx in enumerate(folds):
    tr=[subs[i] for i in range(len(subs)) if i not in set(test_idx)]; te=[subs[i] for i in test_idx]
    for name,cols in configs.items():
        Xtr,ytr=make(tr,cols); th=fit(Xtr,ytr); Xte,yte=make(te,cols); ll,acc=per_race(th,Xte,yte)
        oof[name].append(ll); oofacc[name].append(acc)
res={}
base=np.concatenate(oof['基準(人気順だけ)']); base_acc=np.concatenate(oofacc['基準(人気順だけ)'])
print(f'\n◎○▲(人気上位3頭)の中から1着馬を選ぶ検証（{K}分割の交差検証、{len(subs)}レース）')
print(f'基準：1着馬の確率の対数尤度 {base.mean():.4f}、1番人気を選んだ的中率 {base_acc.mean():.3f}')
for name in configs:
    if name.startswith('基準'): continue
    ll=np.concatenate(oof[name]); acc=np.concatenate(oofacc[name]); d=ll-base; lo,hi=boot(d); da=acc-base_acc; alo,ahi=boot(da)
    print(f' {name:14s} Δ対数尤度 {d.mean():+.4f} [{lo:+.4f},{hi:+.4f}] {"◎有意" if lo>0 else ""}  選んだ馬の的中率 {acc.mean():.3f} (基準比 {da.mean():+.3f} [{alo:+.3f},{ahi:+.3f}])')
    res[name]=dict(delta=float(d.mean()),ci=[float(lo),float(hi)],acc=float(acc.mean()),acc_delta=float(da.mean()),acc_ci=[float(alo),float(ahi)])
# fitted coefficients on all data
for name in ['前走までの速さ(最高)','上がり3Fの順位(平均)','速さ3つ全部']:
    cols=configs[name]; X,y=make(subs,cols); th=fit(X,y); print(' 全期間の推定:',name,{c:round(float(b),3) for c,b in zip(['2番人気','3番人気']+cols,th)})
# how big is the rating scale
rt=np.array([s['rating'] for s in starts if s['rating'] is not None]); print('\n速さ指標(秒/1000m、標準より速いほど+) 分布: 平均 %.2f 標準偏差 %.2f'%(rt.mean(),rt.std()))
json.dump(dict(n_races=len(subs),base_ll=float(base.mean()),base_acc=float(base_acc.mean()),results=res),open('model4_result.json','w'),ensure_ascii=False,indent=1)
