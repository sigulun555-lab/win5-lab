#!/usr/bin/env python3
"""Compare the current JRA scrape with the pinned independent race dataset.

Reports exact race-key differences and eligibility reasons by chronological split.
No model fitting or prediction outputs are changed.
"""
from __future__ import annotations
import argparse, collections, gzip, json, datetime as dt
from pathlib import Path

def load(path):
    path=Path(path)
    opener=gzip.open if path.suffix==".gz" else open
    with opener(path,"rt",encoding="utf-8") as f:
        doc=json.load(f)
    if not isinstance(doc,list):
        raise ValueError(f"{path}: expected top-level list")
    return doc

def normalized_date(value):
    text=str(value or "").strip()
    for fmt in ("%Y-%m-%d","%Y/%m/%d","%Y.%m.%d","%Y年%m月%d日"):
        try:
            return dt.datetime.strptime(text,fmt).date().isoformat()
        except ValueError:
            pass
    return text

def normalized_race_no(value):
    try:
        return str(int(str(value).strip()))
    except (ValueError,TypeError):
        return str(value or "").strip()

def key(r):
    return (normalized_date(r.get("date")),str(r.get("venue","")).strip(),
            normalized_race_no(r.get("rn",r.get("race_no",""))))

def row_count_and_winners(r):
    # Eligibility is based on numeric finishers and valid runner numbers, not popularity.
    # Missing final popularity is retained and reported separately.
    rows=r.get("rows",r.get("runners",[]))
    rows = rows if isinstance(rows, list) else []
    field_size = sum(
        1 for x in rows if isinstance(x, dict)
        and str(x.get("num", "")).strip().isdigit()
        and int(str(x.get("num", "")).strip()) > 0
    )
    valid=[]
    for x in rows:
        if not isinstance(x,dict) or x.get("hid") in (None, ""): continue
        try:
            place=int(str(x.get("place","")).strip())
            num=int(str(x.get("num","")).strip())
        except (TypeError,ValueError):
            continue
        if num>0 and place>0 and place<=field_size:
            valid.append(x)
    return len(valid),sum(1 for x in valid if str(x.get("place","")).strip()=="1")

def missing_popularity_count(r):
    rows=r.get("rows",r.get("runners",[]))
    return sum(1 for x in rows if isinstance(x,dict) and x.get("place") not in (None,"") and x.get("num") not in (None,"") and x.get("pop") in (None,"")) if isinstance(rows,list) else 0

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
    rows=[r for r in doc if start <= normalized_date(r.get("date")) <= end]
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
            "missing_popularity_runner_rows":sum(missing_popularity_count(r) for r in rows),
            "excluded_reason_counts":dict(reason_counts),"excluded_examples":excluded}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--current",required=True)
    ap.add_argument("--reference",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    current_raw,reference_raw=load(a.current),load(a.reference)
    def dedupe(doc):
        out={}
        duplicates=[]
        for r in doc:
            k=key(r)
            if k in out:
                duplicates.append(k)
                # Keep the record with more populated result rows, deterministically.
                def completeness(x):
                    rows=x.get("rows",x.get("runners",[]))
                    if not isinstance(rows,list):
                        return (0,0,0)
                    numeric_finishers = sum(
                        1 for z in rows if isinstance(z,dict) and z.get("hid") not in (None,"")
                        and str(z.get("num","")).strip().isdigit() and int(str(z.get("num","")).strip()) > 0
                        and str(z.get("place","")).strip().isdigit() and int(str(z.get("place","")).strip()) > 0
                    )
                    populated_popularity = sum(
                        1 for z in rows if isinstance(z,dict) and z.get("pop") not in (None,"")
                        and str(z.get("pop","")).strip().isdigit() and int(str(z.get("pop","")).strip()) > 0
                    )
                    return (numeric_finishers, populated_popularity, len(rows))
                if completeness(r)>completeness(out[k]): out[k]=r
            else: out[k]=r
        return list(out.values()),duplicates
    current,current_duplicates=dedupe(current_raw)
    reference,reference_duplicates=dedupe(reference_raw)
    cdict={key(r):r for r in current}; rdict={key(r):r for r in reference}
    ckeys,rkeys=set(cdict),set(rdict)
    only_c=sorted(ckeys-rkeys); only_r=sorted(rkeys-ckeys)
    def describe_record(record):
        if record is None:
            return None
        n,w=row_count_and_winners(record)
        return {
            "key": key(record), "surface": record.get("surface"), "dist": record.get("dist"),
            "numeric_finishers": n, "winner_count": w, "eligibility_reasons": reason(record),
            "missing_popularity_rows": missing_popularity_count(record),
        }
    test_difference_details = []
    for side, keys, source in (("current_only", only_c, cdict), ("reference_only", only_r, rdict)):
        for k in keys:
            if "2026-08-01" <= k[0] <= "2026-10-24":
                test_difference_details.append({
                    "side": side, "key": k,
                    "record": describe_record(source.get(k)),
                })
    report={
      "status":"comparison_only_not_model_validation",
      "current":{"path":a.current,"total_races_raw":len(current_raw),"total_races_deduplicated":len(current),"duplicate_race_key_count":len(current_duplicates),"duplicate_race_keys_first_100":current_duplicates[:100],
        "train_2025-10_to_2026-07":summarize(current,"2025-10-01","2026-07-31"),
        "test_2026-08_to_2026-10-24":summarize(current,"2026-08-01","2026-10-24"),
        "race_keys_only_here_count":len(only_c),"race_keys_only_here_first_100":only_c[:100]},
      "reference":{"path":a.reference,"total_races_raw":len(reference_raw),"total_races_deduplicated":len(reference),"duplicate_race_key_count":len(reference_duplicates),"duplicate_race_keys_first_100":reference_duplicates[:100],
        "train_2025-10_to_2026-07":summarize(reference,"2025-10-01","2026-07-31"),
        "test_2026-08_to_2026-10-24":summarize(reference,"2026-08-01","2026-10-24"),
        "race_keys_only_here_count":len(only_r),"race_keys_only_here_first_100":only_r[:100]},
      "same_race_key_count":len(ckeys&rkeys),
      "test_period_key_difference_counts":{
        "current_only":sum(1 for k in only_c if "2026-08-01" <= k[0] <= "2026-10-24"),
        "reference_only":sum(1 for k in only_r if "2026-08-01" <= k[0] <= "2026-10-24"),
      },
      "test_period_key_difference_details":test_difference_details,
      "warning":"Race-key matching is by date, venue, and race number. Eligibility counts require numeric positive place/num, at least 5 numeric finishers, distance, surface turf/dirt, and exactly one recorded first-place runner. Missing final popularity is retained for B2 and counted separately; it is not an exclusion reason."
    }
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("current","reference")},ensure_ascii=False,indent=2))
    print("CURRENT TEST",json.dumps(report["current"]["test_2026-08_to_2026-10-24"],ensure_ascii=False))
    print("REFERENCE TEST",json.dumps(report["reference"]["test_2026-08_to_2026-10-24"],ensure_ascii=False))
if __name__=="__main__": main()
