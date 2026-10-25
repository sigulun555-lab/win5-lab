#!/usr/bin/env python3
"""Write the required ◎○▲ table (WIN5-JOINT-v1.5 section 12) from a full-probability CSV.

  python scripts/make_win5_marks.py --date 2026-10-25 --model-name GPT-B-history-only \
    --predictions data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv \
    --probability-column gpt_exploratory_win_probability_pct --leg-column leg --horse-column horse_number \
    --market-odds-used no --output data/win5_joint/2026-10-25/gpt-B-marks.csv

Rules enforced:
- all five legs, three distinct horses per leg (◎ ○ ▲ = ranks 1-3 of the model's own probabilities);
- the win probability written for each mark is the model's value copied as-is (never rewritten);
- per-leg probabilities must sum to about 100% (full-field model);
- ties are broken by lower horse number and flagged in `tie_note`;
- scratched horses can be excluded with --scratched LEG:NO[,LEG:NO...] (a reason and time are then required);
- the source file is never modified; its SHA-256 is recorded; unknown facts stay "不明".
"""
from __future__ import annotations
import argparse
import csv
import datetime
import hashlib
import math
from pathlib import Path

MARKS = ["◎", "○", "▲"]
LEGS = [1, 2, 3, 4, 5]
FIELDS = ["date", "leg", "race", "mark", "horse_number", "horse_name", "win_probability_pct", "rank_in_model",
          "tie_note", "model_name", "source_file", "source_sha256", "market_odds_used", "prediction_created_at",
          "update_reason", "update_time_jst", "record_created_at_jst", "rule_version"]
RULE_VERSION = "WIN5-JOINT-v1.5"
SUM_TOLERANCE = 1.5  # percentage points


def to_int(v, what):
    try:
        f = float(str(v).strip())
    except ValueError:
        raise ValueError(f"Invalid {what}: {v!r}")
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"Invalid {what}: {v!r}")
    return int(f)


def parse_scratched(s):
    out = set()
    for tok in (s or "").replace(";", ",").split(","):
        tok = tok.strip()
        if tok:
            leg, no = tok.split(":")
            out.add((to_int(leg, "scratched leg"), to_int(no, "scratched horse")))
    return out


def build_marks(path: Path, date: str, prob_col: str, leg_col: str, horse_col: str, name_col: str, race_col: str,
                model_name: str, market_odds_used: str, created_at: str = "不明", scratched=frozenset(),
                update_reason: str = "", update_time_jst: str = "") -> list[dict]:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if scratched and not (update_reason and update_time_jst):
        raise ValueError("--scratched requires --update-reason and --update-time-jst")
    if market_odds_used not in ("yes", "no", "unknown"):
        raise ValueError("market_odds_used must be yes / no / unknown")
    by: dict[int, list[dict]] = {}
    seen = set()
    for r in rows:
        if "date" in r and r["date"].strip() and r["date"].strip() != date:
            continue
        leg = to_int(r[leg_col], "leg")
        no = to_int(r[horse_col], f"horse (leg {leg})")
        if (leg, no) in seen:
            raise ValueError(f"Duplicate horse {no} in leg {leg}")
        seen.add((leg, no))
        s = str(r[prob_col]).strip()
        try:
            p = float(s)
        except ValueError:
            raise ValueError(f"Invalid probability for leg {leg} horse {no}: {s!r}")
        if not math.isfinite(p) or not 0 <= p <= 100:
            raise ValueError(f"Probability out of range for leg {leg} horse {no}: {s!r}")
        by.setdefault(leg, []).append({"no": no, "p": p, "p_text": s, "name": r.get(name_col, ""), "race": r.get(race_col, "")})
    if sorted(by) != LEGS:
        raise ValueError(f"Expected all five legs; found {sorted(by)}")
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(timespec="seconds")
    out = []
    for leg in LEGS:
        horses = by[leg]
        total = sum(h["p"] for h in horses)
        if abs(total - 100.0) > SUM_TOLERANCE:
            raise ValueError(f"Leg {leg}: probabilities sum to {total:.2f}%, a full-field model must sum to about 100%")
        removed = {no for (l, no) in scratched if l == leg}
        unknown = removed - {h["no"] for h in horses}
        if unknown:
            raise ValueError(f"Leg {leg}: scratched horses not in the file: {sorted(unknown)}")
        live = [h for h in horses if h["no"] not in removed]
        if len(live) < 3:
            raise ValueError(f"Leg {leg}: fewer than three horses left")
        order = sorted(live, key=lambda h: (-h["p"], h["no"]))
        for i, (mark, h) in enumerate(zip(MARKS, order[:3])):
            tie = ""
            if i < len(order) - 1 and order[i + 1]["p"] == h["p"]:
                tie = "次点と同確率（馬番の小さい順で決定）"
            if i > 0 and order[i - 1]["p"] == h["p"]:
                tie = "上位と同確率（馬番の小さい順で決定）"
            out.append({"date": date, "leg": leg, "race": h["race"], "mark": mark, "horse_number": h["no"],
                        "horse_name": h["name"], "win_probability_pct": h["p_text"], "rank_in_model": i + 1,
                        "tie_note": tie, "model_name": model_name, "source_file": str(path), "source_sha256": sha,
                        "market_odds_used": market_odds_used, "prediction_created_at": created_at,
                        "update_reason": update_reason if removed else "", "update_time_jst": update_time_jst if removed else "",
                        "record_created_at_jst": now, "rule_version": RULE_VERSION})
    validate_marks(out)
    return out


def validate_marks(rows: list[dict]) -> None:
    """Five legs, exactly ◎ ○ ▲ per leg, three distinct horses, names present."""
    legs = {}
    for r in rows:
        legs.setdefault(int(r["leg"]), []).append(r)
    if sorted(legs) != LEGS:
        raise ValueError(f"Marks must cover all five legs; found {sorted(legs)}")
    for leg, rs in legs.items():
        if sorted(r["mark"] for r in rs) != sorted(MARKS):
            raise ValueError(f"Leg {leg}: need exactly one each of ◎ ○ ▲, found {[r['mark'] for r in rs]}")
        nos = [int(r["horse_number"]) for r in rs]
        if len(set(nos)) != 3:
            raise ValueError(f"Leg {leg}: ◎○▲ must be three different horses, found {nos}")
        if any(not str(r["horse_name"]).strip() for r in rs):
            raise ValueError(f"Leg {leg}: horse name is required for every mark")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--model-name", required=True)
    ap.add_argument("--predictions", type=Path, required=True)
    ap.add_argument("--probability-column", required=True)
    ap.add_argument("--leg-column", default="leg")
    ap.add_argument("--horse-column", default="horse_number")
    ap.add_argument("--name-column", default="horse_name")
    ap.add_argument("--race-column", default="race_name")
    ap.add_argument("--market-odds-used", required=True, choices=["yes", "no", "unknown"])
    ap.add_argument("--prediction-created-at", default="不明")
    ap.add_argument("--scratched", default="")
    ap.add_argument("--update-reason", default="")
    ap.add_argument("--update-time-jst", default="")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--force", action="store_true", help="overwrite an existing marks file (not allowed after the deadline)")
    a = ap.parse_args()
    if a.output.exists() and not a.force:
        ap.error(f"{a.output} already exists; marks files are not overwritten (use a new name for an updated version)")
    try:
        rows = build_marks(a.predictions, a.date, a.probability_column, a.leg_column, a.horse_column, a.name_column,
                           a.race_column, a.model_name, a.market_odds_used, a.prediction_created_at,
                           parse_scratched(a.scratched), a.update_reason, a.update_time_jst)
    except ValueError as e:
        ap.error(str(e))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    for leg in LEGS:
        print(leg, [(r["mark"], r["horse_number"], r["horse_name"], r["win_probability_pct"]) for r in rows if r["leg"] == leg])
    print(f"Wrote: {a.output}")


if __name__ == "__main__":
    main()
