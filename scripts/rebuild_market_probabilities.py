#!/usr/bin/env python3
"""Rebuild normalized market probabilities from latest observed win odds.

This intentionally does not modify GPT model probabilities. Market probabilities
are 1 / latest_observed_win_odds normalized within each race.
"""
from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

ODDS_COL = "latest_observed_win_odds"
MARKET_COL = "market_normalized_probability_pct"
RACE_COL = "race"
HORSE_COL = "horse_name"


def rebuild(input_path: Path, output_path: Path) -> dict[str, float]:
    with input_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV header is missing")
        required = {ODDS_COL, MARKET_COL, RACE_COL, HORSE_COL, "gpt_estimated_win_probability_pct"}
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(f"Required columns missing: {', '.join(missing)}")
        fields = list(reader.fieldnames)
        rows = list(reader)

    if not rows:
        raise ValueError("CSV has no data rows")

    by_race: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        race = (row.get(RACE_COL) or "").strip()
        horse = (row.get(HORSE_COL) or "").strip()
        if not race or not horse:
            raise ValueError("Each row must have race and horse_name")
        try:
            odds = float(row.get(ODDS_COL, ""))
        except (TypeError, ValueError):
            raise ValueError(f"Missing/invalid latest observed odds: {race} / {horse}")
        if not math.isfinite(odds) or odds <= 1.0:
            raise ValueError(f"Odds must be finite and > 1.0: {race} / {horse}: {odds}")
        by_race[race].append(row)

    sums: dict[str, float] = {}
    for race, race_rows in by_race.items():
        raw = [1.0 / float(row[ODDS_COL]) for row in race_rows]
        total = sum(raw)
        probabilities = [v / total * 100.0 for v in raw]
        # Largest-remainder rounding guarantees exactly 100.00% per race.
        cents = [math.floor(p * 100.0) for p in probabilities]
        remaining = 10000 - sum(cents)
        order = sorted(range(len(cents)), key=lambda i: (probabilities[i] * 100.0 - cents[i]), reverse=True)
        for i in order[:remaining]:
            cents[i] += 1
        for row, value in zip(race_rows, cents):
            row[MARKET_COL] = f"{value / 100.0:.2f}"
        sums[race] = sum(float(row[MARKET_COL]) for row in race_rows)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)

    return sums


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sums = rebuild(args.input, args.output)
    bad = {race: total for race, total in sums.items() if abs(total - 100.0) > 1e-9}
    print(f"Races: {len(sums)}")
    for race, total in sums.items():
        print(f"{race}: {total:.2f}%")
    if bad:
        raise SystemExit(f"Market probability sum validation failed: {bad}")
    print(f"Wrote: {args.output}")
    print("GPT estimated probabilities were preserved unchanged.")


if __name__ == "__main__":
    main()
