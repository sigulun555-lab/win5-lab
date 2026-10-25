#!/usr/bin/env python3
"""Count how many ◎ candidates (one horse per leg, no probabilities) won.

For picks that have no full-field probabilities (e.g. gpt-morning-provisional-picks.csv).
Log loss / Brier are NOT computed (no probabilities for the other horses), and the output
is never to be mixed with the full-probability evaluation.

  python scripts/evaluate_win5_picks_only.py --date 2026-10-25 \
    --picks data/win5_joint/2026-10-25/gpt-morning-provisional-picks.csv \
    --results data/win5_joint/2026-10-25/win5_official_results.csv \
    --output reports/win5-picks-only-2026-10-25.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from evaluate_win5_model_comparison import LEGS, int_id, read_results, rows


def evaluate_picks(picks_path: Path, date: str, winners: dict[int, int], scratched: dict[int, set[int]]) -> dict:
    picks: dict[int, int] = {}
    names: dict[int, str] = {}
    for r in rows(picks_path):
        if r.get("date", "").strip() != date:
            continue
        leg = int_id(r.get("leg", ""), "pick leg")
        if leg in picks:
            raise ValueError(f"Duplicate pick for leg {leg}")
        picks[leg] = int_id(r.get("horse_number", ""), f"pick horse (leg {leg})")
        names[leg] = r.get("horse_name", "")
    if set(picks) != LEGS:
        raise ValueError(f"Expected one pick for each of legs 1-5 on {date}; found {sorted(picks)}")
    details, hits = [], 0
    for leg in sorted(LEGS):
        hit = picks[leg] == winners[leg]
        hits += int(hit)
        details.append({"leg": leg, "pick_no": picks[leg], "pick_name": names[leg], "winner_no": winners[leg],
                        "hit": hit, "pick_scratched": picks[leg] in scratched.get(leg, set())})
    return {"date": date, "picks_file": str(picks_path), "top1_hits": hits, "legs": 5, "details": details,
            "cautions": ["No probabilities: log loss / Brier not computed.",
                         "Do not mix with full-probability model results.",
                         "Five legs are too few to judge a model."]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--picks", type=Path, required=True)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    winners, scratched = read_results(a.results, a.date)
    out = evaluate_picks(a.picks, a.date, winners, scratched)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print({k: out[k] for k in ("top1_hits", "legs")})
    print(f"Wrote: {a.output}")


if __name__ == "__main__":
    main()
