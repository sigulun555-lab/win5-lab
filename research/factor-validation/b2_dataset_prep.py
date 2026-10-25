#!/usr/bin/env python3
"""Prepare leakage-safe B2 rows from parse_ses.py races.json.

This script deliberately does not fit coefficients or make adoption claims.
Historical runs are joined by horse ID; only strictly earlier dates are eligible.
Races with dead-heat winners are retained with fractional winner labels.
"""
from __future__ import annotations
import argparse, collections, datetime as dt, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from b2_features import b_score

def iso(value):
    try: return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError): return None

def _history_seed(bundle, cutoff):
    """Return only numeric historical runs strictly before cutoff from horse-history snapshots."""
    horses=bundle.get("horses",{}) if isinstance(bundle,dict) else {}
    seeded=collections.defaultdict(list)
    if not isinstance(horses,dict):
        return seeded
    for hid, horse in horses.items():
        runs=horse.get("runs",[]) if isinstance(horse,dict) else []
        for run in runs if isinstance(runs,list) else []:
            if not isinstance(run,dict):
                continue
            date=iso(run.get("date"))
            if date is None or date >= cutoff:
                continue
            try:
                place=int(str(run.get("place","")).strip())
                field=int(str(run.get("field","")).strip())
            except (TypeError,ValueError):
                continue
            if field < 2 or place < 1 or place > field:
                continue
            seeded[str(hid)].append({
                "date":date.isoformat(), "venue":run.get("venue",""),
                "class":run.get("class",""), "field":field, "place":place
            })
    for hid in seeded:
        seeded[hid].sort(key=lambda x:x["date"])
    return seeded

def prepare(races, aliases=None, horse_history=None):
    first_date=min((d for d in (iso(r.get("date")) for r in races) if d), default=None)
    by_horse=_history_seed(horse_history or {}, first_date) if first_date else collections.defaultdict(list)
    cleaned=[]
    for race in sorted(races, key=lambda r:(str(r.get("date","")),str(r.get("venue","")),int(r.get("rn") or 0))):
        date=iso(race.get("date"))
        if date is None: continue
        rows=race.get("rows",[])
        valid=[]
        for row in rows if isinstance(rows,list) else []:
            if not isinstance(row,dict) or not row.get("hid"): continue
            try:
                num=int(row["num"]); pop=int(row["pop"]) if row.get("pop") not in (None,"") else None
            except (TypeError,ValueError): continue
            if num<1: continue
            place=row.get("place")
            try: place=int(place) if place not in (None,"") else None
            except (TypeError,ValueError): place=None
            valid.append((row,num,pop,place))
        winners=[x for x in valid if x[3]==1]
        # Keep multi-winner races; label each recorded winner equally.
        if len(valid)<5 or not winners or not race.get("dist") or race.get("surface") not in ("芝","ダート"):
            continue
        rid=f"{date.isoformat()}|{race.get('venue')}|{race.get('rn')}"
        out=[]
        for row,num,pop,place in valid:
            if pop is None or pop<1: continue
            hist=by_horse.get(str(row["hid"]),[])
            # b_score independently enforces strict date < target date.
            features=b_score(hist,date.isoformat(),aliases=aliases)
            out.append({
                "hid":str(row["hid"]), "num":num, "pop":min(pop,18),
                "place":place, "winner_share":(1.0/len(winners) if place==1 else 0.0),
                "b2_score":features["score"], "prior_runs":features["selected_runs"],
                "jra_prior_runs":features["jra_runs_selected"],
                "class":race.get("cls",""), "race_id":rid
            })
        if len(out)<5: continue
        cleaned.append({"race_id":rid,"date":date.isoformat(),"venue":race.get("venue"),
                        "rn":race.get("rn"),"surface":race.get("surface"),"dist":race.get("dist"),
                        "class":race.get("cls",""),"rows":out,"winner_count":len(winners)})
        # Add today's run to horse history only after all horses in today's race have been scored.
        # Features on the same date never use same-day runs.
        for row,num,pop,place in valid:
            if place is None: continue
            by_horse[str(row["hid"])].append({
                "date":date.isoformat(),"venue":race.get("venue"),"class":race.get("cls",""),
                "field":len(valid),"place":place
            })
    return cleaned

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--aliases",type=Path)
    ap.add_argument("--horse-history",type=Path, help="Optional JRA horse-history snapshot; only runs before the earliest race date are used as seed history.")
    args=ap.parse_args()
    races=json.loads(args.input.read_text(encoding="utf-8"))
    aliases=json.loads(args.aliases.read_text(encoding="utf-8")) if args.aliases else None
    horse_history=json.loads(args.horse_history.read_text(encoding="utf-8")) if args.horse_history else None
    prepared=prepare(races,aliases,horse_history)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(prepared,ensure_ascii=False,indent=2)+"\n"
    args.out.write_text(payload,encoding="utf-8")
    print(json.dumps({"status":"prepared_not_fitted","input_races":len(races),
        "prepared_races":len(prepared),"prepared_runner_rows":sum(len(r["rows"]) for r in prepared),
        "multi_winner_races":sum(r["winner_count"]>1 for r in prepared),
        "seed_history_horses":len(_history_seed(horse_history or {}, min((d for d in (iso(r.get("date")) for r in races) if d), default=dt.date.max))) if horse_history else 0,
        "seed_history_cutoff":min((r["date"] for r in prepared),default=None),
        "date_min":min((r["date"] for r in prepared),default=None),
        "date_max":max((r["date"] for r in prepared),default=None),
        "sha256":hashlib.sha256(payload.encode()).hexdigest(),
        "output":str(args.out)},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
