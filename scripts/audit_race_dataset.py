#!/usr/bin/env python3
"""Validate races.json produced by parse_ses.py before any B2 model fitting."""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import json
from pathlib import Path


def audit(doc: object) -> dict:
    if not isinstance(doc, list):
        return {"status": "blocked_invalid_top_level", "race_count": 0,
                "blockers": ["Top-level dataset must be a JSON list of races."]}
    race_keys = collections.Counter()
    date_counts = collections.Counter()
    surface_counts = collections.Counter()
    issues = collections.Counter()
    examples = []
    eligible = 0
    runner_rows = 0
    winner_races = 0
    valid_pop_place_rows = 0
    for idx, race in enumerate(doc):
        if not isinstance(race, dict):
            issues["non_object_race"] += 1
            continue
        date = race.get("date")
        try:
            dt.date.fromisoformat(str(date))
            date_counts[str(date)] += 1
        except (ValueError, TypeError):
            issues["invalid_date"] += 1
        venue, rn = str(race.get("venue") or "").strip(), race.get("rn")
        try:
            rn = int(rn)
        except (ValueError, TypeError):
            rn = None
        if not venue:
            issues["missing_venue"] += 1
        if rn is None:
            issues["invalid_race_number"] += 1
        if date and venue and rn is not None:
            race_keys[(str(date), venue, rn)] += 1
        surface_counts[str(race.get("surface") or "<EMPTY>")] += 1
        rows = race.get("rows")
        if not isinstance(rows, list):
            issues["missing_rows_list"] += 1
            continue
        runner_rows += len(rows)
        valid_rows = []
        for row in rows:
            if not isinstance(row, dict):
                issues["non_object_runner"] += 1
                continue
            missing = [k for k in ("num", "pop", "hid", "place") if row.get(k) in (None, "", 0) and k != "place"]
            # place=0 is invalid too, but use a distinct required check.
            if row.get("place") in (None, "", 0):
                missing.append("place")
            if missing:
                issues["runner_missing_" + ",".join(missing)] += 1
            if all(row.get(k) not in (None, "") for k in ("num", "pop", "hid", "place")):
                try:
                    num, pop, place = int(row["num"]), int(row["pop"]), int(row["place"])
                    if num > 0 and pop > 0 and place > 0:
                        valid_rows.append(row)
                        valid_pop_place_rows += 1
                    else:
                        issues["nonpositive_runner_value"] += 1
                except (ValueError, TypeError):
                    issues["nonnumeric_runner_value"] += 1
        wins = sum(1 for row in valid_rows if row.get("place") == 1 or str(row.get("place")) == "1")
        if wins == 1:
            winner_races += 1
        if len(valid_rows) >= 5 and race.get("dist") and race.get("surface") in ("芝", "ダート") and wins == 1:
            eligible += 1
        else:
            issues["race_not_eligible_for_existing_model_filter"] += 1
        if len(examples) < 12 and (len(valid_rows) < 5 or wins != 1):
            examples.append({"index": idx, "date": date, "venue": venue, "rn": rn,
                             "valid_runner_rows": len(valid_rows), "winner_count": wins})
    duplicate_keys = [{"date": k[0], "venue": k[1], "rn": k[2], "count": v}
                      for k, v in race_keys.items() if v > 1]
    if duplicate_keys:
        issues["duplicate_race_key"] += len(duplicate_keys)
    date_min = min(date_counts) if date_counts else None
    date_max = max(date_counts) if date_counts else None
    blockers = []
    if not doc:
        blockers.append("Dataset contains no races.")
    if not eligible:
        blockers.append("No races meet the existing model's minimum eligibility filter.")
    if duplicate_keys:
        blockers.append("Duplicate (date, venue, race number) keys exist.")
    if issues["invalid_date"] or issues["missing_venue"] or issues["invalid_race_number"]:
        blockers.append("Race identity fields are missing or invalid.")
    return {
        "status": "pass_basic_integrity_not_leakage_validation" if not blockers else "blocked_integrity_issues",
        "race_count": len(doc),
        "runner_rows": runner_rows,
        "rows_with_numeric_num_pop_hid_place": valid_pop_place_rows,
        "races_with_exactly_one_valid_first_place": winner_races,
        "eligible_for_existing_model_filter": eligible,
        "date_min": date_min,
        "date_max": date_max,
        "date_counts": dict(sorted(date_counts.items())),
        "surface_counts": dict(surface_counts.most_common()),
        "issue_counts": dict(issues.most_common()),
        "duplicate_race_keys_first_100": duplicate_keys[:100],
        "problem_race_examples_first_12": examples,
        "blockers": blockers,
        "limitations": [
            "Passing this audit does not prove source completeness or leakage-free features.",
            "Rows failing eligibility filters are reported, not imputed.",
            "Check historical data source, retrieval timestamps, coverage, and strict prior-only feature generation separately."
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, nargs="?", default=Path("research/factor-validation/races.json"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    try:
        doc = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked_input_unreadable", "input": str(args.input),
                          "blockers": [str(exc)]}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    report = audit(doc)
    report["input"] = str(args.input)
    output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    print(output, end="")
    if report["status"] == "blocked_integrity_issues":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
