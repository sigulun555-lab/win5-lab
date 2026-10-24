import re,subprocess,os,sys,json,time
from concurrent.futures import ThreadPoolExecutor
BASE='https://www.jra.go.jp'
def post(path,cname,out=None):
    for _ in range(3):
        r=subprocess.run(['curl','-s','-m','40','-A','Mozilla/5.0',BASE+path,'-X','POST','-d','cname='+cname],capture_output=True)
        if r.returncode==0 and len(r.stdout)>5000:
            return r.stdout.decode('cp932',errors='replace')
        time.sleep(1.5)
    return None
def cnames(html): return set(re.findall(r"doAction\('(/JRADB/access[A-Z0-9]+\.html)',\s*'([^']+)'\)",html))
# 1) months (chain back)
months={}
start='pw01skl00202610/C3'
todo=[('202610',start),('202609','pw01skl10202609/3B'),('202510','pw01skl10202510/1E')]
seen=set()
while todo:
    ym,cn=todo.pop()
    if ym in seen: continue
    seen.add(ym)
    h=post('/JRADB/accessS.html',cn)
    if not h: print('fail month',ym); continue
    months[ym]=sorted(b for a,b in cnames(h) if b.startswith('pw01srl1') or b.startswith('pw01srl0'))
    for a,b in cnames(h):
        m=re.match(r'pw01skl10(\d{6})/',b)
        if m and '202510'<=m.group(1)<='202610' and m.group(1) not in seen: todo.append((m.group(1),b))
        m=re.match(r'pw01skl00(\d{6})/',b)
        if m and '202510'<=m.group(1)<='202610' and m.group(1) not in seen: todo.append((m.group(1),b))
    print('month',ym,len(months[ym]),flush=True); time.sleep(0.3)
days=sorted({b for v in months.values() for b in v})
print('venue-days',len(days),flush=True)
json.dump(months,open('months.json','w'))
def getday(cn):
    sid=cn.replace('pw01srl','').split('/')[0]
    fn=f'ses/{sid}.html'
    if os.path.exists(fn) and os.path.getsize(fn)>50000: return sid,'cached'
    h=post('/JRADB/accessS.html',cn)
    if not h: return sid,'fail-srl'
    ses=[b for a,b in cnames(h) if b.startswith('pw01ses')]
    # prefer the ses link matching this venue-day id
    ses=[b for b in ses if sid in b] or ses
    if not ses: return sid,'no-ses'
    h2=post('/JRADB/accessS.html',ses[0])
    if not h2: return sid,'fail-ses'
    open(fn,'w',encoding='utf-8').write(h2)
    time.sleep(0.2)
    return sid,'ok'
t0=time.time(); res={}
with ThreadPoolExecutor(max_workers=5) as ex:
    for i,(sid,st) in enumerate(ex.map(getday,days),1):
        res[sid]=st
        if i%20==0: print(i,len(days),int(time.time()-t0),'s',flush=True)
from collections import Counter
print(Counter(res.values()))
json.dump(res,open('crawl_status.json','w'))
