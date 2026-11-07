#!/usr/bin/env python3
"""Create GPT's exploratory history-only WIN5 probabilities and ◎○▲ marks."""
import csv, json, math, os, re, sys
from datetime import datetime, timezone

DATE = "2026-11-07"
SRC = f"data/horse_history/{DATE}.json"
OUT = f"data/win5_joint/{DATE}"
WEIGHTS = 0.78
TEMP = 1.35

def num(x):
    if x is None: return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(x).replace(",", ""))
    return float(m.group()) if m else None

def main():
    with open(SRC, encoding="utf-8") as f: doc = json.load(f)
    rows = []
    for race in doc.get("races", []):
        if not race.get("win5_leg"): continue
        leg = int(race["win5_leg"])
        for h in race.get("runners", []):
            hist = doc.get("horses", {}).get(h.get("hid"), {})
            valid = []
            for run in hist.get("runs", []):
                place, field = num(run.get("place")), num(run.get("field"))
                if place is None or field is None or field <= 1 or place < 1 or place > field: continue
                valid.append((run, place, field))
            valid = valid[:6]
            if valid:
                ws = [WEIGHTS ** i for i in range(len(valid))]
                p = sum(w * ((f - pos)/(f - 1)) for w, (_,pos,f) in zip(ws,valid)) / sum(ws)
                rated = [(w,num(r.get("rt"))) for w,(r,_,_) in zip(ws,valid) if num(r.get("rt")) is not None]
                t = sum(w*v for w,v in rated)/sum(w for w,_ in rated) if rated else None
                score = (p - .5)*2.1 + ((t-90)*.025 if t is not None else 0)
            else:
                p, t, score = None, None, 0.0
            rows.append({"date":DATE,"leg":leg,"venue":race.get("venue"),"race_no":race.get("race_no"),
                "race_name":race.get("name"),"horse_no":h.get("num"),"horse_name":h.get("name"),
                "hid":h.get("hid"),"jockey":h.get("jockey"),"weight":h.get("weight"),
                "valid_runs":len(valid),"rank_percentile":p,"weighted_rating":t,"score":score,
                "missing_history":not bool(hist),"no_valid_runs":len(valid)==0})
    if not rows: raise SystemExit("No WIN5 runners found")
    for leg in range(1,6):
        group=[x for x in rows if x["leg"]==leg]
        if not group: raise SystemExit(f"WIN5 leg {leg} missing")
        mx=max(x["score"] for x in group)
        qs=[math.exp((x["score"]-mx)*TEMP) for x in group]
        z=sum(qs)
        for x,q in zip(group,qs): x["probability_pct"]=q/z*100
        ranked=sorted(group,key=lambda x:(-x["probability_pct"],x["horse_no"]))
        for i,x in enumerate(ranked[:3]): x["mark"]=["◎","○","▲"][i]
    os.makedirs(OUT,exist_ok=True)
    csvpath=f"{OUT}/gpt-exploratory-history-only-probabilities.csv"
    fields=list(rows[0].keys())
    with open(csvpath,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        for x in sorted(rows,key=lambda x:(x["leg"],x["horse_no"])):
            w.writerow({k:(f"{x[k]:.6f}" if isinstance(x.get(k),float) else x.get(k)) for k in fields})
    md=[f"# GPT WIN5 {DATE} — exploratory history-only marks","",
        "**Status:** exploratory / uncalibrated; not a calibrated true win probability.",
        "**Market odds used:** no. **Claude predictions used:** no.",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}","",
        "| Leg | Race | Mark | Horse | Probability | Valid runs |","|---:|---|---|---|---:|---:|"]
    for x in sorted(rows,key=lambda x:(x["leg"],-x["probability_pct"],x["horse_no"])):
        if x.get("mark"):
            md.append(f"| {x['leg']} | {x['race_name']} | {x['mark']} | {x['horse_no']} {x['horse_name']} | {x['probability_pct']:.2f}% | {x['valid_runs']} |")
    missing=sum(x["missing_history"] for x in rows)
    no_runs=sum(x["no_valid_runs"] for x in rows)
    md += ["",f"- Runners: {len(rows)}",f"- Missing history records: {missing}",f"- No valid numeric runs: {no_runs}","",
        "Each leg is softmax-normalized to 100%. The score follows the documented 2026-10-25 v0 exploratory method. No course/class/distance/jockey/odds adjustment."]
    with open(f"{OUT}/gpt-exploratory-marks.md","w",encoding="utf-8") as f:f.write("\n".join(md)+"\n")
    meta={"date":DATE,"model":"gpt-exploratory-history-only-v0","market_odds_used":False,
      "claude_predictions_used":False,"formula":"weighted rank percentile (0.78^i), weighted numeric rating, score=(P-.5)*2.1+(T-90)*.025; softmax temperature 1.35",
      "runners":len(rows),"legs":{str(i):{"runners":sum(x["leg"]==i for x in rows),
      "probability_sum":round(sum(x["probability_pct"] for x in rows if x["leg"]==i),8)} for i in range(1,6)},
      "missing_history_records":missing,"no_valid_runs":no_runs,"created_at_utc":datetime.now(timezone.utc).isoformat()}
    with open(f"{OUT}/gpt-exploratory-metadata.json","w",encoding="utf-8") as f:json.dump(meta,f,ensure_ascii=False,indent=2)
    print(json.dumps(meta,ensure_ascii=False,indent=2))
    if len(rows)!=67 or any(meta["legs"][str(i)]["runners"]==0 for i in range(1,6)):
        raise SystemExit("Runner count/leg validation failed; outputs are diagnostic only")
if __name__=="__main__":main()
