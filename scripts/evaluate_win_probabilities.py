#!/usr/bin/env python3
"""Evaluate WIN5 race-level win probabilities against realized winners.

Input CSV columns:
date,race_key,horse_number,probability,actual_winner
- One row per runner per race.
- actual_winner must be 1 for exactly one runner per race and 0 for all others.
- probability is a percentage (0..100) or fraction (0..1); values within a race
  must sum to 100 or 1 respectively.
- Keep each race's prediction timestamp strictly before race start.
- Use chronological train/validation/test splits outside this script; do not tune
  coefficients on the test period.

This script does not fetch data and does not certify a model by itself.
"""
import csv
import math
import sys
from collections import defaultdict

def main(path):
    races = defaultdict(list)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            races[(row["date"], row["race_key"])].append(row)

    if not races:
        raise SystemExit("No rows found.")

    brier_sum = 0.0
    logloss_sum = 0.0
    top1_hits = 0
    top1_market_hits = 0
    market_races = 0
    count = 0
    calibration = defaultdict(lambda: [0, 0.0, 0.0])

    for key, rows in sorted(races.items()):
        probs = []
        actuals = []
        for row in rows:
            p = float(row["probability"])
            if p > 1:
                p /= 100.0
            if not 0 <= p <= 1:
                raise ValueError(f"{key}: probability outside [0,1]")
            probs.append(p)
            actuals.append(int(row["actual_winner"]))
        if sum(actuals) != 1:
            raise ValueError(f"{key}: expected exactly one actual_winner=1")
        if abs(sum(probs) - 1.0) > 0.005:
            raise ValueError(f"{key}: probabilities sum to {sum(probs):.6f}, not 1")

        brier = sum((p-y)**2 for p, y in zip(probs, actuals)) / len(rows)
        winner_i = actuals.index(1)
        logloss = -math.log(max(1e-15, probs[winner_i]))
        top_i = max(range(len(rows)), key=lambda i: probs[i])
        brier_sum += brier
        logloss_sum += logloss
        top1_hits += int(top_i == winner_i)
        count += 1

        for p, y in zip(probs, actuals):
            bin_id = min(9, int(p * 10))
            calibration[bin_id][0] += 1
            calibration[bin_id][1] += p
            calibration[bin_id][2] += y

    print(f"races={count}")
    print(f"mean_multiclass_brier_per_runner={brier_sum/count:.6f}")
    print(f"mean_winner_log_loss={logloss_sum/count:.6f}")
    print(f"top1_hit_rate={top1_hits/count:.4%}")
    print("calibration_bin,count,mean_predicted,observed_win_rate")
    for b, (n, ps, ys) in sorted(calibration.items()):
        if n:
            print(f"{b/10:.1f}-{(b+1)/10:.1f},{n},{ps/n:.6f},{ys/n:.6f}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: evaluate_win_probabilities.py predictions_with_results.csv")
    main(sys.argv[1])
