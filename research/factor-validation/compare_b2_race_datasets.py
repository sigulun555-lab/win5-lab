#!/usr/bin/env python3
"""Compare the current JRA scrape with the pinned independent race dataset.

Reports exact race-key differences and eligibility reasons by chronological split.
No model fitting or prediction outputs are changed.
"""
from __future__ import annotations
import argparse, collections, gzip, json
from pathlib import Path

def load(path):
    path=Path(path)
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",encoding="utf-8") as f:
        doc=json.load(f)
    if not isinstance(doc,list):
        raise ValueError(f"{path}: expected top-level list")
    return doc

def key(r):
    return (str(r.get("date","")),str(r.get("venue","")).strip(),str(r.get("rn",r.get("race_no",""))))

def row_count_and_winners(r):
    rows=r.get("rows",r.get("runners",[]))
    valid=[]
    for x in rows if isinstance(rows,list) else []:
        if not isinstance(x,dict): continue
        try:
            place=int(str(x.get("place","")).strip())
            pop=int(str(x.get("pop","")).strip())
            num=int(str(x.get("num","")).strip())
        except (TypeError,ValueError):
            continue
        if num>0 and pop>0 and place>0:
            valid.append(x)
    return len(valid),sum(1 for x in valid if str(x.get("place","")).strip()=="1")

def reason(r):
    n,w=row_count_and_winners(r)
    reasons=[]
    surface=str(r.get("surface","")).strip()
    if surface not in ("芝","ダート"): reasons.append("not_flat_turf_dirt:"+ (surface or "EMPTY"))
    if not r.get("dist"): reasons.append("missing_distance")
    if n<5: reasons.append("fewer_than_5_valid_runners")
    if w!=1: reasons.append(f"winner_count_{w}")
    return reasons

def summarize(doc, start, end):
    rows=[r for r in doc if start <= str(r.get("date","")) <= end]
    eligible=[r for r in rows if not reason(r)]
    reason_counts=collections.Counter()
    excluded=[]
    for r in rows:
        rs=reason(r)
        if rs:
            n,w=row_count_and_winners(r)
            excluded.append({"key":key(r),"surface":r.get("surface"),"dist":r.get("dist"),
                             "valid_runners":n,"winner_count":w,"reasons":rs})
            reason_counts.update(rs)
    return {"all_races":len(rows),"eligible_exactly_one_winner":len(eligible),
            "excluded_reason_counts":dict(reason_counts),"excluded_examples":excluded}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--current",required=True)
    ap.add_argument("--reference",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    current,reference=load(a.current),load(a.reference)
    cdict={key(r):r for r in current}; rdict={key(r):r for r in reference}
    ckeys,rkeys=set(cdict),set(rdict)
    only_c=sorted(ckeys-rkeys); only_r=sorted(rkeys-ckeys)
    report={
      "status":"comparison_only_not_model_validation",
      "current":{"path":a.current,"total_races":len(current),
        "train_2025-10_to_2026-07":summarize(current,"2025-10-01","2026-07-31"),
        "test_2026-08_to_2026-10-24":summarize(current,"2026-08-01","2026-10-24"),
        "race_keys_only_here_count":len(only_c),"race_keys_only_here_first_100":only_c[:100]},
      "reference":{"path":a.reference,"total_races":len(reference),
        "train_2025-10_to_2026-07":summarize(reference,"2025-10-01","2026-07-31"),
        "test_2026-08_to_2026-10-24":summarize(reference,"2026-08-01","2026-10-24"),
        "race_keys_only_here_count":len(only_r),"race_keys_only_here_first_100":only_r[:100]},
      "same_race_key_count":len(ckeys&rkeys),
      "warning":"Race-key matching is by date, venue, and race number. Eligibility counts require numeric positive place/pop/num, at least 5 valid runners, distance, surface turf/dirt, and exactly one recorded first-place runner."
    }
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("current","reference")},ensure_ascii=False,indent=2))
    print("CURRENT TEST",json.dumps(report["current"]["test_2026-08_to_2026-10-24"],ensure_ascii=False))
    print("REFERENCE TEST",json.dumps(report["reference"]["test_2026-08_to_2026-10-24"],ensure_ascii=False))
if __name__=="__main__": main()
