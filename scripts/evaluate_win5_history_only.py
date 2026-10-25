#!/usr/bin/env python3
"""Evaluate WIN5 win-probability snapshots against recorded winners.

Prediction CSV: date, leg (or win5_order), horse_number (or horse_no), horse_name,
and one probability column in percent (default gpt_exploratory_win_probability_pct;
choose another with --probability-column, e.g. model_prob_pct).
Result CSV: date, leg (or win5_order), winner_no, winner_name; optional scratched_nos
(official 取消・除外 horse numbers for that leg, separated by ; , or space).
Only use a result file after independently verifying all five winners.

Numeric ids are parsed as integers, so "1", "01" and "1.00000" (pandas float export)
are the same leg / horse number.

Metric definitions (all per WIN5 day, 5 races):
- top1_hits / top3_hits: winner is the highest / within the three highest probabilities.
  Ties are broken by lower horse number and reported in `warnings`.
- mean_winner_log_loss: mean over races of -ln(p_winner), p floored at --log-loss-floor
  (default 1e-15, same as evaluate_win_probabilities.py / evaluate_win5_predictions.py).
- multiclass_brier_per_horse: sum over all horses of (p - y)^2 divided by the total
  number of horses (pooled; same as evaluate_win5_predictions.py). Larger fields weigh more.
- brier_per_horse_race_mean: mean over races of [sum((p - y)^2) / n_horses]
  (same as evaluate_win_probabilities.py).
- multiclass_brier_race_sum_mean: mean over races of sum((p - y)^2); the usual
  multiclass Brier score, which does not shrink as the field grows.
- uniform_baseline: the same metrics for p = 1 / n_horses, so a score can be compared
  across fields of different size. Per-horse Brier shrinks as n grows, so it must not be
  compared across days with different field sizes without this baseline.

Scratched horses: if `scratched_nos` is given for a leg, those horses are removed and the
remaining probabilities are renormalised to 100% at evaluation time only (the prediction
file is never modified); this is recorded per race (`renormalised_after_scratch`).
"""
from __future__ import annotations
import argparse
import csv
import math
import re
from pathlib import Path

LEG_KEYS = ("leg", "win5_order")
HORSE_KEYS = ("horse_number", "horse_no")
LEGS = [1, 2, 3, 4, 5]
SUM_TOLERANCE = 0.015


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {path}")
        return list(reader)


def to_int(value, what: str) -> int:
    """'1', '01', ' 1 ' and '1.00000' -> 1. Anything else is an error."""
    s = str(value if value is not None else "").strip()
    if not s:
        raise ValueError(f"Empty {what}")
    try:
        f = float(s)
    except ValueError:
        raise ValueError(f"Invalid {what}: {s!r}")
    if not math.isfinite(f) or f != int(f):
        raise ValueError(f"Invalid {what}: {s!r}")
    return int(f)


def pick(row: dict[str, str], keys: tuple[str, ...], what: str) -> str:
    for k in keys:
        if k in row:
            return k
    raise ValueError(f"CSV missing {what} column (one of {list(keys)})")


def parse_scratched(value) -> set[int]:
    s = str(value or "").strip()
    return {to_int(x, "scratched_nos") for x in re.split(r"[;,\s]+", s) if x}


def evaluate(prediction_path: Path, result_path: Path,
             probability_column: str = "gpt_exploratory_win_probability_pct",
             log_loss_floor: float = 1e-15) -> dict:
    preds = read_rows(prediction_path)
    results = read_rows(result_path)
    if not preds or not results:
        raise ValueError("Prediction and result CSVs must both contain rows")
    leg_p = pick(preds[0], LEG_KEYS, "leg")
    horse_p = pick(preds[0], HORSE_KEYS, "horse number")
    leg_r = pick(results[0], LEG_KEYS, "leg (result)")
    if probability_column not in preds[0]:
        raise ValueError(f"Prediction CSV missing columns: {[probability_column]}")
    for need in ("date", "winner_no"):
        if need not in results[0]:
            raise ValueError(f"Result CSV missing columns: {[need]}")
    if not 0 < log_loss_floor < 1:
        raise ValueError("log_loss_floor must be in (0, 1)")

    date_values = {r.get("date", "").strip() for r in preds}
    if len(date_values) != 1 or "" in date_values:
        raise ValueError("Prediction CSV must contain exactly one non-empty date")
    date = next(iter(date_values))

    winners: dict[int, int] = {}
    scratched: dict[int, set[int]] = {}
    for r in results:
        if r.get("date", "").strip() != date:
            continue
        leg = to_int(r[leg_r], "result leg")
        if not str(r.get("winner_no", "")).strip():
            raise ValueError(f"Result for leg {leg} has an empty winner_no (official result not entered yet)")
        w = to_int(r["winner_no"], f"winner_no (leg {leg})")
        if leg in winners:
            raise ValueError(f"Duplicate result row for leg {leg} (dead heats must be handled explicitly)")
        winners[leg] = w
        scratched[leg] = parse_scratched(r.get("scratched_nos"))
    if sorted(winners) != LEGS:
        raise ValueError(f"Expected exactly five unique results for {date}; found legs {sorted(winners)}")

    grouped: dict[int, list[tuple[dict[str, str], int, float]]] = {}
    seen = set()
    for row in preds:
        leg = to_int(row[leg_p], "prediction leg")
        no = to_int(row[horse_p], f"horse number (leg {leg})")
        key = (leg, no)
        if key in seen:
            raise ValueError(f"Duplicate prediction row: {key}")
        seen.add(key)
        raw = str(row[probability_column]).strip()
        if not raw:
            raise ValueError(f"Empty probability for {key}")
        try:
            p = float(raw) / 100.0
        except ValueError:
            raise ValueError(f"Invalid probability for {key}")
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError(f"Probability out of range for {key}: {p}")
        grouped.setdefault(leg, []).append((row, no, p))
    if sorted(grouped) != LEGS:
        raise ValueError(f"Expected prediction rows for all five legs; found {sorted(grouped)}")

    rows_out = []
    warnings: list[str] = []
    top1_hits = top3_hits = 0
    ll_sum = ll_uni_sum = 0.0
    brier_pool = brier_pool_uni = 0.0
    brier_rm_sum = brier_rm_uni_sum = 0.0
    brier_rs_sum = brier_rs_uni_sum = 0.0
    horse_count = 0
    for leg in LEGS:
        entries = grouped[leg]
        total = sum(p for _, _, p in entries)
        if abs(total - 1.0) > SUM_TOLERANCE:
            raise ValueError(f"Leg {leg} probabilities sum to {total*100:.2f}%, expected about 100%")
        winner = winners[leg]
        removed = scratched[leg]
        if winner in removed:
            raise ValueError(f"Leg {leg}: winner {winner} is listed as scratched")
        missing = removed - {no for _, no, _ in entries}
        if missing:
            raise ValueError(f"Leg {leg}: scratched horse numbers not in the prediction file: {sorted(missing)}")
        renormalised = bool(removed)
        if removed:
            entries = [e for e in entries if e[1] not in removed]
            total = sum(p for _, _, p in entries)
            if total <= 0:
                raise ValueError(f"Leg {leg}: no probability mass left after removing scratched horses")
            entries = [(r, no, p / total) for r, no, p in entries]
            warnings.append(f"leg {leg}: scratched {sorted(removed)} removed, probabilities renormalised at evaluation time")
        win_entries = [e for e in entries if e[1] == winner]
        if len(win_entries) != 1:
            raise ValueError(f"Leg {leg}: winner {winner} matched {len(win_entries)} times")
        n = len(entries)
        ordered = sorted(entries, key=lambda e: (-e[2], e[1]))
        winner_row, _, winner_p = win_entries[0]
        top1 = ordered[0]
        top3_nos = [e[1] for e in ordered[:3]]
        if n > 1 and ordered[0][2] == ordered[1][2]:
            warnings.append(f"leg {leg}: tie for Top-1 (broken by lower horse number)")
        if n > 3 and ordered[2][2] == ordered[3][2]:
            warnings.append(f"leg {leg}: tie at the Top-3 boundary (broken by lower horse number)")
        top1_hits += int(top1[1] == winner)
        in_top3 = winner in top3_nos
        top3_hits += int(in_top3)
        if winner_p < log_loss_floor:
            warnings.append(f"leg {leg}: winner probability {winner_p:.3g} is below the log-loss floor {log_loss_floor:g}")
        ll_sum += -math.log(max(winner_p, log_loss_floor))
        ll_uni_sum += math.log(n)
        sq = sum((p - (1.0 if no == winner else 0.0)) ** 2 for _, no, p in entries)
        sq_uni = sum((1.0 / n - (1.0 if no == winner else 0.0)) ** 2 for _, no, _ in entries)
        brier_pool += sq
        brier_pool_uni += sq_uni
        brier_rm_sum += sq / n
        brier_rm_uni_sum += sq_uni / n
        brier_rs_sum += sq
        brier_rs_uni_sum += sq_uni
        horse_count += n
        rows_out.append({
            "leg": leg, "race": winner_row.get("race_name", winner_row.get("race", "")),
            "winner": f'{winner} {winner_row.get("horse_name", "")}',
            "top1": f'{top1[1]} {top1[0].get("horse_name", "")}',
            "winner_probability_pct": round(winner_p * 100, 3),
            "winner_in_top3": in_top3, "field_size": n, "renormalised_after_scratch": renormalised,
        })
    return {
        "date": date, "races": 5, "probability_column": probability_column,
        "top1_hits": top1_hits, "top3_hits": top3_hits,
        "mean_winner_log_loss": round(ll_sum / 5, 5),
        "multiclass_brier_per_horse": round(brier_pool / horse_count, 6),
        "brier_per_horse_race_mean": round(brier_rm_sum / 5, 6),
        "multiclass_brier_race_sum_mean": round(brier_rs_sum / 5, 5),
        "uniform_baseline": {
            "mean_winner_log_loss": round(ll_uni_sum / 5, 5),
            "multiclass_brier_per_horse": round(brier_pool_uni / horse_count, 6),
            "brier_per_horse_race_mean": round(brier_rm_uni_sum / 5, 6),
            "multiclass_brier_race_sum_mean": round(brier_rs_uni_sum / 5, 5),
        },
        "horses_scored": horse_count, "warnings": warnings, "details": rows_out,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--probability-column", default="gpt_exploratory_win_probability_pct")
    p.add_argument("--log-loss-floor", type=float, default=1e-15)
    args = p.parse_args()
    result = evaluate(args.predictions, args.results, args.probability_column, args.log_loss_floor)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    u = result["uniform_baseline"]
    with args.output.open("w", encoding="utf-8") as f:
        f.write(f'# WIN5確率評価（{result["date"]}・列 {result["probability_column"]}）\n\n')
        f.write("> 結果確定後の事後評価。小標本だけでモデルの優劣を断定しない。\n\n")
        f.write("| 指標 | 結果 | 全頭同確率（1/頭数）の基準 |\n|---|---:|---:|\n")
        f.write(f'| Top-1 | {result["top1_hits"]}/5 | － |\n')
        f.write(f'| 勝ち馬がTop-3内 | {result["top3_hits"]}/5 | － |\n')
        f.write(f'| 勝ち馬平均Log loss（小さいほど良い） | {result["mean_winner_log_loss"]:.5f} | {u["mean_winner_log_loss"]:.5f} |\n')
        f.write(f'| Multiclass Brier 合計/レース平均（小さいほど良い） | {result["multiclass_brier_race_sum_mean"]:.5f} | {u["multiclass_brier_race_sum_mean"]:.5f} |\n')
        f.write(f'| Brier / 馬（全頭プール。evaluate_win5_predictions.py と同じ） | {result["multiclass_brier_per_horse"]:.6f} | {u["multiclass_brier_per_horse"]:.6f} |\n')
        f.write(f'| Brier / 馬（レース平均。evaluate_win_probabilities.py と同じ） | {result["brier_per_horse_race_mean"]:.6f} | {u["brier_per_horse_race_mean"]:.6f} |\n')
        f.write(f'| 評価対象頭数 | {result["horses_scored"]} | |\n\n')
        f.write("| WIN5順 | レース | 頭数 | 勝ち馬 | モデルTop-1 | 勝ち馬確率 | Top-3内 |\n|---:|---|---:|---|---|---:|:---:|\n")
        for r in result["details"]:
            f.write(f'| {r["leg"]} | {r["race"]} | {r["field_size"]} | {r["winner"]} | {r["top1"]} | {r["winner_probability_pct"]:.3f}% | {"はい" if r["winner_in_top3"] else "いいえ"} |\n')
        if result["warnings"]:
            f.write("\n## 警告\n\n" + "".join(f"- {w}\n" for w in result["warnings"]))
        f.write("\n## 注意\n\n- 結果CSVはJRA公式発表と照合してから使用する。\n- 予測CSVを結果を見て修正しない。\n- 市場比較は同一時刻のオッズから作った市場確率と行う。\n- Brier/馬は頭数が多いほど小さくなる。日をまたぐ比較は、基準（1/頭数）との差で見る。\n")
    print({k: v for k, v in result.items() if k not in ("details",)})
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
