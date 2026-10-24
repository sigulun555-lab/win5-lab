import re,glob,json,html as H,datetime
def txt(x): return re.sub(r'\s+',' ',H.unescape(re.sub(r'<[^>]+>',' ',x))).strip()
def parse_file(fn):
    s=open(fn,encoding='utf-8',errors='replace').read()
    out=[]
    parts=re.split(r'<div class="race_result_unit" id="race_result_(\d+)R">',s)
    for k in range(1,len(parts),2):
        rn=int(parts[k]); b=parts[k+1]
        m=re.search(r'class="cell date">(\d{4})年(\d+)月(\d+)日.*?(\d+)回(\S+?)(\d+)日',b,re.S)
        if not m: continue
        date=datetime.date(int(m.group(1)),int(m.group(2)),int(m.group(3))); venue=m.group(5)
        wx=re.search(r'class="weather">.*?class="txt">(.*?)</span>',b,re.S); dur=re.search(r'<li class="(?:durt|turf|jump|steeple)[^"]*">.*?class="cap">(.*?)</span><span class="txt">(.*?)</span>',b,re.S)
        surface=txt(dur.group(1)) if dur else None; going=txt(dur.group(2)) if dur else None
        cat=re.search(r'class="cell category">(.*?)</div>',b,re.S); cls=re.search(r'class="cell class">(.*?)</div>',b,re.S)
        rname=re.search(r'class="race_name">(.*?)</span>',b,re.S)
        cd=re.search(r'class="cell course">.*?</span>([\d,]+)<span class="unit">メートル</span><span class="detail">（(.*?)）',b,re.S)
        dist=int(cd.group(1).replace(',','')) if cd else None; detail=cd.group(2) if cd else ''
        rows=[]
        for tr in re.findall(r'<tr>\s*<td class="place">(.*?)</tr>',b,re.S):
            pass
        for tr in re.findall(r'<tr>(\s*<td class="place">.*?)</tr>',b,re.S):
            def cell(c):
                mm=re.search(r'<td class="'+c+r'"[^>]*>(.*?)</td>',tr,re.S); return mm.group(1) if mm else ''
            place=txt(cell('place')); num=txt(cell('num'))
            hc=re.search(r'CNAME=(pw01dud\w+/\w+)',cell('horse')); hid=hc.group(1).split('/')[0] if hc else None
            name=txt(re.sub(r'<div class="icon.*?</div>','',cell('horse')))
            wt=re.search(r'[\d.]+',txt(cell('weight'))); pop=re.search(r'\d+',txt(cell('pop')))
            hw=re.search(r'(\d+)',txt(cell('h_weight')))
            jk=re.sub(r'^[▲△☆◇★\s]+','',txt(cell('jockey'))); tr_=txt(cell('trainer'))
            cor={}
            for ttl,v in re.findall(r'<li title="(\d)コーナー通過順位">(\d+)</li>',cell('corner')): cor[int(ttl)]=int(v)
            rows.append(dict(jockey=jk,trainer=tr_,c3=cor.get(3),c4=cor.get(4),c1=cor.get(1),c2=cor.get(2),place=int(place) if place.isdigit() else None,place_raw=place,num=int(num) if num.isdigit() else None,hid=hid,name=name,age=txt(cell('age')),
                wt=float(wt.group(0)) if wt else None,pop=int(pop.group(0)) if pop else None,bw=int(hw.group(1)) if hw else None,time=txt(cell('time'))))
        out.append(dict(date=str(date),venue=venue,rn=rn,surface=surface,going=going,weather=txt(wx.group(1)) if wx else None,cat=txt(cat.group(1)) if cat else '',cls=txt(cls.group(1)) if cls else '',
                        name=txt(rname.group(1)) if rname else '',dist=dist,detail=detail,rows=rows))
    return out
if __name__=='__main__':
    races=[]
    for fn in sorted(glob.glob('ses/*.html')):
        races+=parse_file(fn)
    json.dump(races,open('races.json','w'),ensure_ascii=False)
    n=sum(len(r['rows']) for r in races)
    print(len(races),'races',n,'rows')
    bad=[r for r in races if not r['rows'] or r['dist'] is None]
    print('bad',len(bad))
    from collections import Counter
    print(Counter(r['surface'] for r in races)); print(Counter(r['going'] for r in races).most_common(6))
    print(races[0]['rows'][0],races[0]['dist'],races[0]['date'],races[0]['venue'])
