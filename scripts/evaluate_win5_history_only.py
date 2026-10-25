#!/usr/bin/env python3
"""Evaluate history-only WIN5 probability snapshots against recorded winners.

Prediction CSV schema: date, leg, horse_number, horse_name,
gpt_exploratory_win_probability_pct.
Result CSV schema: date, leg, winner_no, winner_name.
Only use a result file after independently verifying all five winners.
"""
from __future__ import annotations
import argparse
import csv
import math
from pathlib import Path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {path}")
        return list(reader)


def evaluate(prediction_path: Path, result_path: Path) -> dict:
    preds = read_rows(prediction_path)
    results = read_rows(result_path)
    if not preds or not results:
        raise ValueError("Prediction and result CSVs must both contain rows")
    date_values = {r.get("date", "").strip() for r in preds}
    if len(date_values) != 1 or "" in date_values:
        raise ValueError("Prediction CSV must contain exactly one non-empty date")
    date = next(iter(date_values))
    required_p = {"leg", "horse_number", "horse_name", "gpt_exploratory_win_probability_pct"}
    required_r = {"date", "leg", "winner_no"}
    if not required_p.issubset(preds[0]):
        raise ValueError(f"Prediction CSV missing columns: {sorted(required_p - set(preds[0]))}")
    if not required_r.issubset(results[0]):
        raise ValueError(f"Result CSV missing columns: {sorted(required_r - set(results[0]))}")
    results = [r for r in results if r.get("date", "").strip() == date]
    winners = {r["leg"].strip(): r["winner_no"].strip() for r in results}
    if len(winners) != 5 or set(winners) != {"1", "2", "3", "4", "5"}:
        raise ValueError(f"Expected exactly five unique results for {date}; found legs {sorted(winners)}")
    grouped: dict[str, list[tuple[dict[str, str], float]]] = {}
    seen = set()
    for row in preds:
        if row.get("date", "").strip() != date:
            continue
        leg = row["leg"].strip()
        key = (leg, row["horse_number"].strip())
        if key in seen:
            raise ValueError(f"Duplicate prediction row: {key}")
        seen.add(key)
        try:
            p = float(row["gpt_exploratory_win_probability_pct"]) / 100.0
        except (TypeError, ValueError):
            raise ValueError(f"Invalid probability for {key}")
        if not math.isfinite(p) or not 0 <= p <= 1:
            raise ValueError(f"Probability out of range for {key}: {p}")
        grouped.setdefault(leg, []).append((row, p))
    if set(grouped) != {"1", "2", "3", "4", "5"}:
        raise ValueError(f"Expected prediction rows for all five legs; found {sorted(grouped)}")
    rows_out = []
    top1_hits = top3_hits = 0
    log_loss_sum = brier_sum = 0.0
    horse_count = 0
    for leg in sorted(grouped, key=int):
        entries = grouped[leg]
        total = sum(p for _, p in entries)
        if abs(total - 1.0) > 0.015:
            raise ValueError(f"Leg {leg} probabilities sum to {total*100:.2f}%, expected about 100%")
        winner = winners[leg]
        win_entries = [(r, p) for r, p in entries if r["horse_number"].strip() == winner]
        if len(win_entries) != 1:
            raise ValueError(f"Leg {leg}: winner {winner} matched {len(win_entries)} times")
        ordered = sorted(entries, key=lambda x: x[1], reverse=True)
        winner_row, winner_p = win_entries[0]
        top1 = ordered[0][0]
        in_top3 = any(r["horse_number"].strip() == winner for r, _ in ordered[:3])
        top1_hits += int(top1["horse_number"].strip() == winner)
        top3_hits += int(in_top3)
        log_loss_sum += -math.log(max(winner_p, 1e-15))
        brier_sum += sum((p - (1.0 if r["horse_number"].strip() == winner else 0.0)) ** 2 for r, p in entries)
        horse_count += len(entries)
        rows_out.append({
            "leg": int(leg), "race": winner_row.get("race_name", ""),
            "winner": f'{winner} {winner_row.get("horse_name", "")}',
            "top1": f'{top1["horse_number"]} {top1["horse_name"]}',
            "winner_probability_pct": round(winner_p * 100, 3),
            "winner_in_top3": in_top3,
        })
    return {
        "date": date, "races": 5, "top1_hits": top1_hits, "top3_hits": top3_hits,
        "mean_winner_log_loss": round(log_loss_sum / 5, 5),
        "multiclass_brier_per_horse": round(brier_sum / horse_count, 6),
        "horses_scored": horse_count, "details": rows_out,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = evaluate(args.predictions, args.results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        f.write(f'# WIN5履歴のみ探索モデル評価（{result["date"]}）\n\n')
        f.write("> 結果確定後の事後評価。小標本だけでモデルの優劣を断定しない。\n\n")
        f.write("| 指標 | 結果 |\n|---|---:|\n")
        f.write(f'| Top-1 | {result["top1_hits"]}/5 |\n')
        f.write(f'| 勝ち馬がTop-3内 | {result["top3_hits"]}/5 |\n')
        f.write(f'| 勝ち馬平均Log loss（小さいほど良い） | {result["mean_winner_log_loss"]:.5f} |\n')
        f.write(f'| Multiclass Brier / 馬（小さいほど良い） | {result["multiclass_brier_per_horse"]:.6f} |\n')
        f.write(f'| 評価対象頭数 | {result["horses_scored"]} |\n\n')
        f.write("| WIN5順 | レース | 勝ち馬 | モデルTop-1 | 勝ち馬確率 | Top-3内 |\n|---:|---|---|---|---:|:---:|\n")
        for r in result["details"]:
            f.write(f'| {r["leg"]} | {r["race"]} | {r["winner"]} | {r["top1"]} | {r["winner_probability_pct"]:.3f}% | {"はい" if r["winner_in_top3"] else "いいえ"} |\n')
        f.write("\n## 注意\n\n- 結果CSVはJRA公式発表と照合してから使用する。\n- 予測CSVを結果を見て修正しない。\n- 市場比較は同一時刻のオッズから作った市場確率と行う。\n")
    print({k: v for k, v in result.items() if k != "details"})
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
