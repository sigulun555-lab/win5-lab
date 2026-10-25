#!/usr/bin/env python3
"""Compare WIN5 race-level probability snapshots with one common scoring implementation.

Model argument format (repeat --model):
  NAME|CSV_PATH|PROBABILITY_COLUMN|LEG_COLUMN|HORSE_COLUMN

Probability columns are percentages (0..100). Predictions must be frozen before
the race starts. This tool does not fetch results and does not modify inputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

LEGS = {1, 2, 3, 4, 5}
SUM_TOLERANCE = 0.015


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {path}")
        return list(reader)


def int_id(value: str, label: str) -> int:
    s = str(value or "").strip()
    try:
        n = float(s)
    except ValueError as e:
        raise ValueError(f"Invalid {label}: {s!r}") from e
    if not math.isfinite(n) or n != int(n):
        raise ValueError(f"Invalid {label}: {s!r}")
    return int(n)


def read_results(path: Path, date: str) -> tuple[dict[int, int], dict[int, set[int]]]:
    winners: dict[int, int] = {}
    scratched: dict[int, set[int]] = {}
    for row in rows(path):
        if row.get("date", "").strip() != date:
            continue
        leg = int_id(row.get("leg", row.get("win5_order", "")), "result leg")
        if leg in winners:
            raise ValueError(f"Duplicate result for leg {leg}")
        raw_winner = row.get("winner_no", row.get("winning_horse_number", ""))
        if not str(raw_winner or "").strip():
            raise ValueError(f"Winner is blank for leg {leg}; results not final")
        winners[leg] = int_id(raw_winner, f"winner leg {leg}")
        raw = str(row.get("scratched_nos", "") or "").strip()
        scratched[leg] = {int_id(x, "scratched horse") for x in raw.replace(";", " ").replace(",", " ").split()}
    if set(winners) != LEGS:
        raise ValueError(f"Expected results for legs 1-5 on {date}; found {sorted(winners)}")
    return winners, scratched


def validate_log_loss_floor(value) -> float:
    """Accept only a finite number with 0 < value <= 1 (the lower bound of a probability in log loss)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"log_loss_floor must be a number with 0 < value <= 1, got {value!r}")
    if not math.isfinite(value) or not 0 < value <= 1:
        raise ValueError(f"log_loss_floor must be finite with 0 < value <= 1, got {value!r}")
    return float(value)


def evaluate_model(spec: str, date: str, winners: dict[int, int],
                   scratched: dict[int, set[int]], log_loss_floor: float = 1e-15) -> dict:
    log_loss_floor = validate_log_loss_floor(log_loss_floor)
    parts = spec.split("|")
    if len(parts) != 5:
        raise ValueError("--model must be NAME|CSV_PATH|PROBABILITY_COLUMN|LEG_COLUMN|HORSE_COLUMN")
    name, raw_path, prob_col, leg_col, horse_col = parts
    source = Path(raw_path)
    grouped: dict[int, dict[int, float]] = {}
    names: dict[tuple[int, int], str] = {}
    dates = set()
    for row in rows(source):
        row_date = row.get("date", "").strip()
        if row_date:
            dates.add(row_date)
        if row_date != date:
            continue
        leg = int_id(row.get(leg_col, ""), f"{name} leg")
        horse = int_id(row.get(horse_col, ""), f"{name} horse")
        if leg not in LEGS:
            raise ValueError(f"{name}: unexpected leg {leg}")
        if horse in grouped.setdefault(leg, {}):
            raise ValueError(f"{name}: duplicate horse {horse} in leg {leg}")
        raw = str(row.get(prob_col, "") or "").strip()
        try:
            p = float(raw) / 100.0
        except ValueError as e:
            raise ValueError(f"{name}: invalid probability for leg {leg}, horse {horse}: {raw!r}") from e
        if not math.isfinite(p) or p < 0 or p > 1:
            raise ValueError(f"{name}: probability outside 0..100 for leg {leg}, horse {horse}")
        grouped[leg][horse] = p
        names[(leg, horse)] = row.get("horse_name", row.get("horse", ""))

    if set(grouped) != LEGS:
        hint = f" (dates present in the file: {sorted(dates)})" if not grouped else ""
        raise ValueError(f"{name}: expected predictions for legs 1-5 on {date}, found {sorted(grouped)}{hint}")
    details = []
    warnings: list[str] = []
    top1_hits = top3_hits = 0
    logloss = brier_sum = brier_per_horse_sum = 0.0
    horse_count = 0
    uniform_logloss = uniform_brier_sum = uniform_brier_per_horse_sum = 0.0
    for leg in sorted(LEGS):
        probs = grouped[leg]
        removed = scratched.get(leg, set())
        if winners[leg] in removed:
            raise ValueError(f"{name}: winner in scratched_nos for leg {leg}")
        already_excluded = removed - set(probs)
        if already_excluded:
            warnings.append(f"leg {leg}: scratched {sorted(already_excluded)} not in the prediction file (excluded before the forecast); nothing to remove")
        removed = removed & set(probs)
        if removed:
            probs = {h: p for h, p in probs.items() if h not in removed}
            total = sum(probs.values())
            if total <= 0:
                raise ValueError(f"{name}: no probability mass left after scratches in leg {leg}")
            probs = {h: p / total for h, p in probs.items()}
        total = sum(probs.values())
        if abs(total - 1.0) > SUM_TOLERANCE:
            raise ValueError(f"{name}: leg {leg} probabilities sum to {total:.4f}, expected 1.0")
        winner = winners[leg]
        if winner not in probs:
            raise ValueError(f"{name}: winner {winner} missing from prediction leg {leg}")
        ordered = sorted(probs.items(), key=lambda x: (-x[1], x[0]))
        top1, top3 = ordered[0][0], {h for h, _ in ordered[:3]}
        wp = probs[winner]
        if len(ordered) > 1 and ordered[0][1] == ordered[1][1]:
            warnings.append(f"leg {leg}: tie for Top-1 (broken by lower horse number)")
        if len(ordered) > 3 and ordered[2][1] == ordered[3][1]:
            warnings.append(f"leg {leg}: tie at the Top-3 boundary (broken by lower horse number)")
        if wp < log_loss_floor:
            warnings.append(f"leg {leg}: winner probability {wp:.3g} is below the log-loss floor {log_loss_floor:g}")
        n = len(probs)
        sq = sum((p - (1.0 if h == winner else 0.0)) ** 2 for h, p in probs.items())
        uni_sq = (1.0 - 1.0 / n) ** 2 + (n - 1) * (1.0 / n) ** 2
        top1_hits += int(top1 == winner)
        top3_hits += int(winner in top3)
        logloss += -math.log(max(wp, log_loss_floor))
        brier_sum += sq
        brier_per_horse_sum += sq / n
        uniform_logloss += math.log(n)
        uniform_brier_sum += uni_sq
        uniform_brier_per_horse_sum += uni_sq / n
        horse_count += n
        details.append({
            "leg": leg, "winner_no": winner, "winner_name": names.get((leg, winner), ""),
            "top1_no": top1, "top1_name": names.get((leg, top1), ""),
            "winner_probability_pct": round(wp * 100, 5), "field_size": n,
            "winner_in_top3": winner in top3, "scratched_removed": sorted(removed),
        })
    return {
        "name": name, "source": str(source), "date": date, "legs": 5,
        "top1_hits": top1_hits, "top3_hits": top3_hits,
        "mean_winner_log_loss": round(logloss / 5, 6),
        "multiclass_brier_race_sum_mean": round(brier_sum / 5, 6),
        "brier_per_horse_race_mean": round(brier_per_horse_sum / 5, 6),
        "multiclass_brier_per_horse_pooled": round(brier_sum / horse_count, 6),
        "uniform_baseline": {
            "mean_winner_log_loss": round(uniform_logloss / 5, 6),
            "multiclass_brier_race_sum_mean": round(uniform_brier_sum / 5, 6),
            "brier_per_horse_race_mean": round(uniform_brier_per_horse_sum / 5, 6),
            "multiclass_brier_per_horse_pooled": round(uniform_brier_sum / horse_count, 6),
        },
        "horses_scored": horse_count, "warnings": warnings, "details": details,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", required=True)
    ap.add_argument("--results", type=Path, required=True)
    ap.add_argument("--model", action="append", required=True, help="Repeat: NAME|CSV_PATH|PROBABILITY_COLUMN|LEG_COLUMN|HORSE_COLUMN")
    ap.add_argument("--output", type=Path, required=True, help="Output JSON report")
    ap.add_argument("--log-loss-floor", type=float, default=1e-15, help="lower bound of the winner probability in log loss")
    args = ap.parse_args()
    try:
        args.log_loss_floor = validate_log_loss_floor(args.log_loss_floor)
    except ValueError as e:
        ap.error(str(e))
    winners, scratched = read_results(args.results, args.date)
    reports = [evaluate_model(spec, args.date, winners, scratched, args.log_loss_floor) for spec in args.model]
    if len({r["name"] for r in reports}) != len(reports):
        raise ValueError("Model names must be unique")
    payload = {
        "date": args.date,
        "results_source_file": str(args.results),
        "method": "same implementation for all models; probabilities are percent; no input files modified",
        "models": reports,
        "cautions": [
            "Only compare forecasts made before the corresponding race start.",
            "Market probabilities are a benchmark, not an independent predictive model.",
            "Different odds timestamps are not a fair same-time comparison.",
            "Five legs from one WIN5 date are a very small sample; do not infer model superiority.",
            "Pooled Brier per horse depends on field sizes; inspect the race-sum and race-mean metrics and uniform baseline too.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({r["name"]: {k: r[k] for k in ("top1_hits", "top3_hits", "mean_winner_log_loss", "multiclass_brier_race_sum_mean", "brier_per_horse_race_mean", "multiclass_brier_per_horse_pooled")} for r in reports}, ensure_ascii=False, indent=2))
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
