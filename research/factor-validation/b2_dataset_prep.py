#!/usr/bin/env python3
"""Prepare leakage-safe B2 rows from parse_ses.py races.json.

This script deliberately does not fit coefficients or make adoption claims.
Historical runs are joined by horse ID; only strictly earlier dates are eligible.
Races with multiple recorded winners are excluded per preregistered eligibility.
"""
from __future__ import annotations
import argparse, collections, datetime as dt, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from b2_features import b_score, candidate_feature_summary, classify_venue, classify_race_class

def iso(value):
    if value is None: return None
    text=str(value).strip()
    for fmt in ("%Y-%m-%d","%Y年%m月%d日","%Y/%m/%d","%Y.%m.%d"):
        try: return dt.datetime.strptime(text,fmt).date()
        except (TypeError,ValueError): pass
    return None

def _prior_result_class_map(result_races, cutoff):
    """Map runners to class only from unique, single-winner races strictly before cutoff."""
    matches=collections.defaultdict(list)
    for race in result_races if isinstance(result_races,list) else []:
        if not isinstance(race,dict):
            continue
        day=iso(race.get("date"))
        if day is None or (cutoff is not None and day >= cutoff):
            continue
        venue=str(race.get("venue") or "").strip()
        cls=str(race.get("cls") or race.get("class") or "").strip()
        rows=race.get("rows",[])
        winners=[x for x in rows if isinstance(x,dict) and str(x.get("place","")).strip()=="1" and x.get("hid")] if isinstance(rows,list) else []
        if not venue or not cls or len(winners)!=1:
            continue
        for row in rows:
            if isinstance(row,dict) and row.get("hid"):
                matches[(day.isoformat(),venue,str(row["hid"]))].append(cls)
    # Duplicate source matches remain unresolved rather than relying on file order.
    return {key:vals[0] for key,vals in matches.items() if len(vals)==1}


def _history_seed(bundle, cutoff, result_races=None):
    """Return numeric prior runs; attach class only from a unique earlier result race."""
    horses=bundle.get("horses",{}) if isinstance(bundle,dict) and isinstance(bundle.get("horses"),dict) else (bundle if isinstance(bundle,dict) else {})
    class_map=_prior_result_class_map(result_races or [], None) if result_races else {}
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
            venue=str(run.get("venue","") or "").strip()
            # Horse-history pages often omit class. Join by date, venue and runner ID;
            # ambiguous/missing matches stay unknown, and only earlier results are eligible.
            resolved_class=class_map.get((date.isoformat(),venue,str(hid)), "")
            raw_class=resolved_class or run.get("class","")
            seeded[str(hid)].append({
                "date":date.isoformat(), "venue":venue,
                "class":raw_class, "field":field, "place":place,
                "rt":run.get("rt", run.get("rating", ""))
            })
    for hid in seeded:
        seeded[hid].sort(key=lambda x:x["date"])
    return seeded

def supported_history_schema(bundle):
    if not isinstance(bundle,dict):
        return False
    if isinstance(bundle.get("horses"),dict):
        return True
    return any(isinstance(v,dict) and isinstance(v.get("runs"),list) for v in bundle.values())


def prepare(races, aliases=None, horse_history=None):
    first_date=min((d for d in (iso(r.get("date")) for r in races) if d), default=None)
    by_horse=_history_seed(horse_history or {}, first_date, races) if first_date else collections.defaultdict(list)
    cleaned=[]
    for race in sorted(races, key=lambda r:(str(r.get("date","")),str(r.get("venue","")),int(r.get("rn") or 0))):
        date=iso(race.get("date"))
        if date is None: continue
        rows=race.get("rows",[])
        # Field size includes starters with nonnumeric finishes; those runners themselves
        # are excluded from model rows and historical percentile features.
        race_field_size=sum(
            1 for x in rows if isinstance(x,dict) and
            str(x.get("num","")).strip().isdigit() and int(str(x.get("num","")).strip()) > 0
        ) if isinstance(rows,list) else 0
        valid=[]
        for row in rows if isinstance(rows,list) else []:
            if not isinstance(row,dict) or not row.get("hid"): continue
            try:
                num=int(row["num"]); pop=int(row["pop"]) if row.get("pop") not in (None,"") else None
            except (TypeError,ValueError):
                try:
                    num=int(row["num"])
                except (TypeError,ValueError):
                    continue
                pop=None
            if num<1: continue
            place=row.get("place")
            try: place=int(place) if place not in (None,"") else None
            except (TypeError,ValueError): place=None
            if place is None or place < 1 or place > race_field_size: continue
            valid.append((row,num,pop,place))
        winners=[x for x in valid if x[3]==1]
        # Preregistered eligibility requires exactly one recorded first-place runner.
        # Multi-winner races are excluded before any model fitting; never fractional-label them.
        if len(valid)<5 or len(winners)!=1 or not race.get("dist") or race.get("surface") not in ("芝","ダート"):
            continue
        rid=f"{date.isoformat()}|{race.get('venue')}|{race.get('rn')}"
        out=[]
        for row,num,pop,place in valid:
            hist=by_horse.get(str(row["hid"]),[])
            # b_score independently enforces strict date < target date.
            features=b_score(hist,date.isoformat(),aliases=aliases)
            all_features=candidate_feature_summary(hist,date.isoformat(),aliases=aliases,local_policy="downweight")
            no_local_features=candidate_feature_summary(hist,date.isoformat(),aliases=aliases,local_policy="exclude")
            out.append({
                "hid":str(row["hid"]), "num":num, "pop":min(pop,18) if pop is not None and pop >= 1 else None,
                "place":place, "winner_share":(1.0 if place==1 else 0.0),
                "b2_score":features["score"], "prior_runs":features["selected_runs"],
                "jra_prior_runs":features["jra_runs_selected"],
                "candidate_features":{"all":all_features,"local_excluded":no_local_features},
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
                "field":race_field_size,"place":place
            })
    return cleaned

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--aliases",type=Path)
    ap.add_argument("--horse-history",type=Path, help="Optional JRA horse-history snapshot; only runs before the earliest race date are used as seed history.")
    args=ap.parse_args()
    races_raw=json.loads(args.input.read_text(encoding="utf-8"))
    # The collector can emit duplicate records for the same race. Prevent duplicate
    # race/runner rows from leaking into model fitting; prefer the most complete result.
    deduped={}
    duplicate_keys=[]
    def race_key(r):
        return (str(iso(r.get("date")) or r.get("date","")),str(r.get("venue","")).strip(),str(r.get("rn",r.get("race_no",""))))
    def completeness(r):
        rows=r.get("rows",[])
        if not isinstance(rows,list):
            return (0,0,0)
        numeric_finishers = sum(
            1 for x in rows if isinstance(x,dict) and x.get("hid") not in (None,"")
            and str(x.get("num","")).strip().isdigit() and int(str(x.get("num","")).strip()) > 0
            and str(x.get("place","")).strip().isdigit() and int(str(x.get("place","")).strip()) > 0
        )
        populated_popularity = sum(
            1 for x in rows if isinstance(x,dict) and x.get("pop") not in (None,"")
            and str(x.get("pop","")).strip().isdigit() and int(str(x.get("pop","")).strip()) > 0
        )
        return (numeric_finishers, populated_popularity, len(rows))
    for race in races_raw:
        k=race_key(race)
        if k in deduped:
            duplicate_keys.append(k)
            if completeness(race)>completeness(deduped[k]):
                deduped[k]=race
        else:
            deduped[k]=race
    races=list(deduped.values())
    aliases=json.loads(args.aliases.read_text(encoding="utf-8")) if args.aliases else None
    horse_history=json.loads(args.horse_history.read_text(encoding="utf-8")) if args.horse_history else None
    prepared=prepare(races,aliases,horse_history)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    payload=json.dumps(prepared,ensure_ascii=False,indent=2)+"\n"
    args.out.write_text(payload,encoding="utf-8")
    print(json.dumps({"status":"prepared_not_fitted","input_races_raw":len(races_raw),"duplicate_race_key_count":len(duplicate_keys),"input_races_deduplicated":len(races),
        "prepared_races":len(prepared),"prepared_runner_rows":sum(len(r["rows"]) for r in prepared),
        "multi_winner_races_in_prepared":sum(r["winner_count"]>1 for r in prepared),
        "multi_winner_races_excluded":sum(
            1 for r in races
            if len([x for x in r.get("rows",[]) if isinstance(x,dict) and str(x.get("place","")).strip()=="1"]) > 1
            and str(r.get("surface","")).strip() in ("芝","ダート") and r.get("dist")
        ),
        "seed_history_horses":len(_history_seed(horse_history or {}, min((d for d in (iso(r.get("date")) for r in races) if d), default=dt.date.max), races)) if horse_history else 0,
        "horse_history_schema_supported":supported_history_schema(horse_history) if horse_history else False,
        "horse_history_warning":"Horse-history input is not a supported horse-ID to {profile,runs} mapping; no prior race history can be seeded from this file." if horse_history and not supported_history_schema(horse_history) else None,
        "seed_class_join":"strictly-prior result race by date+venue+runner ID; ambiguous/missing classes remain unknown",
        "seed_history_cutoff":min((r["date"] for r in prepared),default=None),
        "date_min":min((r["date"] for r in prepared),default=None),
        "date_max":max((r["date"] for r in prepared),default=None),
        "sha256":hashlib.sha256(payload.encode()).hexdigest(),
        "output":str(args.out)},ensure_ascii=False,indent=2))
if __name__=="__main__": main()
