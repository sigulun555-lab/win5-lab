#!/usr/bin/env python3
"""Evaluate WIN5 race-level win probabilities against recorded winners.

This evaluates each of the five races separately, not the joint probability of
hitting all five WIN5 legs. Small samples must not be interpreted as proof of
model superiority.
"""
from __future__ import annotations
import argparse
import csv
import math
from pathlib import Path

DEFAULT_COLUMNS = {
    "v1": "gpt_estimated_win_probability_pct",
    "v2": "gpt_v2_market_adjusted_probability_pct",
    "market": "market_normalized_probability_pct",
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {path}")
        return list(reader.fieldnames), list(reader)


def evaluate(prediction_path: Path, result_path: Path) -> dict:
    fields, rows = read_csv(prediction_path)
    _, results = read_csv(result_path)
    required = {"win5_order", "race", "horse_no"}
    if not required.issubset(fields):
        raise ValueError("Prediction CSV requires win5_order, race, horse_no")
    for col in DEFAULT_COLUMNS.values():
        if col not in fields:
            raise ValueError(f"Prediction CSV missing probability column: {col}")
    for col in ("win5_order", "winner_no"):
        if not any(col in r for r in results):
            raise ValueError(f"Result CSV missing column: {col}")

    winners = {str(r["win5_order"]).strip(): str(r["winner_no"]).strip()
               for r in results if str(r.get("win5_order", "")).strip()}
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        leg = str(row.get("win5_order", "")).strip()
        if leg:
            groups.setdefault(leg, []).append(row)
    if len(groups) != 5 or set(groups) != set(winners):
        raise ValueError(f"Expected matching five WIN5 legs; predictions={sorted(groups)}, results={sorted(winners)}")

    scores = {name: {"top1_hits": 0, "log_loss_sum": 0.0, "brier_sum": 0.0, "horse_count": 0}
              for name in DEFAULT_COLUMNS}
    detail = []
    for leg in sorted(groups, key=int):
        entries = groups[leg]
        winner = winners[leg]
        matched = [r for r in entries if str(r["horse_no"]).strip() == winner]
        if len(matched) != 1:
            raise ValueError(f"Leg {leg}: winner {winner} matched {len(matched)} times")
        winner_row = matched[0]
        item = {"win5_order": int(leg), "race": winner_row.get("race", ""), "winner_no": winner,
                "winner_name": winner_row.get("horse_name", "")}
        for name, col in DEFAULT_COLUMNS.items():
            probs = []
            for r in entries:
                try:
                    p = float(r[col]) / 100.0
                except (TypeError, ValueError):
                    raise ValueError(f"Invalid probability in leg {leg}, horse {r.get('horse_no')}, column {col}")
                if not math.isfinite(p) or p < 0 or p > 1:
                    raise ValueError(f"Probability out of range in leg {leg}, horse {r.get('horse_no')}: {p}")
                probs.append((r, p))
            total = sum(p for _, p in probs)
            if abs(total - 1.0) > 0.015:
                raise ValueError(f"Leg {leg} {col} probabilities sum to {total * 100:.2f}%, expected about 100%")
            top = max(probs, key=lambda x: x[1])[0]
            win_p = next(p for r, p in probs if r is winner_row)
            scores[name]["top1_hits"] += int(str(top["horse_no"]).strip() == winner)
            scores[name]["log_loss_sum"] += -math.log(max(win_p, 1e-15))
            scores[name]["brier_sum"] += sum((p - (1.0 if str(r["horse_no"]).strip() == winner else 0.0)) ** 2 for r, p in probs)
            scores[name]["horse_count"] += len(probs)
            item[f"{name}_top1"] = f'{top["horse_no"]} {top.get("horse_name", "")}'
            item[f"{name}_winner_probability_pct"] = round(win_p * 100, 2)
        detail.append(item)
    summary = {}
    for name, s in scores.items():
        summary[name] = {
            "top1_hits": s["top1_hits"],
            "races": 5,
            "top1_hit_rate_pct": round(s["top1_hits"] / 5 * 100, 2),
            "mean_winner_log_loss": round(s["log_loss_sum"] / 5, 5),
            "multiclass_brier_per_horse": round(s["brier_sum"] / s["horse_count"], 6),
            "horses_scored": s["horse_count"],
        }
    return {"summary": summary, "races": detail}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--predictions", type=Path, required=True)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = evaluate(a.predictions, a.results)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", encoding="utf-8") as f:
        f.write("# WIN5予想の結果評価\n\n")
        f.write("> 5レースの事後評価。標本数が少ないため、モデルの優劣を確定するものではありません。\n\n")
        f.write("## 指標\n\n| 系統 | 1着1位的中 | 平均Log loss（勝ち馬） | Brier（馬単位平均） |\n|---|---:|---:|---:|\n")
        labels = {"v1": "V1（GPT推定）", "v2": "V2（市場補正）", "market": "市場確率"}
        for key, label in labels.items():
            s = result["summary"][key]
            f.write(f'| {label} | {s["top1_hits"]}/5 | {s["mean_winner_log_loss"]:.5f} | {s["multiclass_brier_per_horse"]:.6f} |\n')
        f.write("\n## レース別\n\n| レース | 1着馬 | V1最上位 | V2最上位 | 市場最上位 | 勝ち馬V1確率 | 勝ち馬V2確率 |\n|---|---|---|---|---|---:|---:|\n")
        for r in result["races"]:
            f.write(f'| {r["race"]} | {r["winner_no"]} {r["winner_name"]} | {r["v1_top1"]} | {r["v2_top1"]} | {r["market_top1"]} | {r["v1_winner_probability_pct"]:.2f}% | {r["v2_winner_probability_pct"]:.2f}% |\n')
        f.write("\n## 注意\n\n- Log lossは小さいほど良く、Brierも小さいほど良い指標です。\n- V2は市場オッズ変動を反映したシナリオで、独立に学習したモデルではありません。\n- この5レースだけで優劣や将来の的中率を断定しません。継続して開催ごとに蓄積し、締切前の同一時点データで評価してください。\n")
    print(result["summary"])
    print(f"Wrote: {a.output}")


if __name__ == "__main__":
    main()
