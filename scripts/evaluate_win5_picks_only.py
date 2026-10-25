#!/usr/bin/env python3
"""Count how many ◎ (and, if given, ◎○▲) won, for picks with or without probabilities.

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
    """picks CSV: one row per pick. Without a `mark` column each row is the ◎ of its leg (old format).
    With a `mark` column (◎ ○ ▲) the Top-3 mark hit rate is also computed; it is only reported when
    every leg has all three marks (marks_complete)."""
    by_leg: dict[int, dict[str, int]] = {}
    names: dict[tuple[int, str], str] = {}
    for r in rows(picks_path):
        if r.get("date", "").strip() != date:
            continue
        leg = int_id(r.get("leg", ""), "pick leg")
        mark = (r.get("mark") or "◎").strip()
        if mark not in ("◎", "○", "▲"):
            raise ValueError(f"Unknown mark {mark!r} in leg {leg}")
        if mark in by_leg.setdefault(leg, {}):
            raise ValueError(f"Duplicate {mark} for leg {leg}")
        by_leg[leg][mark] = int_id(r.get("horse_number", ""), f"pick horse (leg {leg})")
        names[(leg, mark)] = r.get("horse_name", "")
    if set(by_leg) != LEGS:
        raise ValueError(f"Expected picks for each of legs 1-5 on {date}; found {sorted(by_leg)}")
    for leg, marks in by_leg.items():
        if "◎" not in marks:
            raise ValueError(f"Leg {leg} has no ◎")
        if len(set(marks.values())) != len(marks):
            raise ValueError(f"Leg {leg}: marks must be different horses, found {marks}")
    complete = all(len(m) == 3 for m in by_leg.values())
    details, hits, hits3 = [], 0, 0
    for leg in sorted(LEGS):
        marks = by_leg[leg]
        hit = marks["◎"] == winners[leg]
        in3 = winners[leg] in marks.values()
        hits += int(hit)
        hits3 += int(in3)
        details.append({"leg": leg, "honmei_no": marks["◎"], "honmei_name": names[(leg, "◎")], "winner_no": winners[leg],
                        "hit": hit, "marks": {m: n for m, n in marks.items()}, "winner_in_marks": in3,
                        "honmei_scratched": marks["◎"] in scratched.get(leg, set())})
    return {"date": date, "picks_file": str(picks_path), "top1_hits": hits, "legs": 5,
            "marks_complete": complete, "top3_marks_hits": hits3 if complete else None, "details": details,
            "cautions": ["Log loss / Brier are not computed here (use evaluate_win5_model_comparison.py for full-field models).",
                         "Do not mix picks-only results with full-probability model results.",
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
    print({k: out[k] for k in ("top1_hits", "top3_marks_hits", "marks_complete", "legs")})
    print(f"Wrote: {a.output}")


if __name__ == "__main__":
    main()
