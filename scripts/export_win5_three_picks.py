#!/usr/bin/env python3
"""Export WIN5 ◎○▲ picks from an existing full-field probability CSV.

This script ranks existing probabilities only. It does not invent or alter probabilities.
Input probabilities are percentages (0..100); input CSV is never modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
from pathlib import Path

LEGS = {1, 2, 3, 4, 5}
MARKS = {1: "◎", 2: "○", 3: "▲"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_picks(
    input_path: Path,
    output_path: Path,
    date: str,
    probability_column: str,
    leg_column: str,
    horse_column: str,
    name_column: str,
) -> dict:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must be different; source predictions are immutable")

    with input_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"CSV header missing: {input_path}")
        required = {"date", probability_column, leg_column, horse_column, name_column}
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
        selected = [r for r in reader if r.get("date", "").strip() == date]

    if not selected:
        dates = set()
        with input_path.open(newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("date", "").strip():
                    dates.add(r["date"].strip())
        raise ValueError(f"No predictions for {date}; dates present: {sorted(dates)}")

    grouped: dict[int, list[tuple[int, str, float]]] = {}
    for row in selected:
        try:
            leg_float = float(row[leg_column])
            horse_float = float(row[horse_column])
            probability = float(row[probability_column]) / 1.0
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid leg, horse number, or probability in row: {row}") from e
        if not math.isfinite(leg_float) or leg_float != int(leg_float) or int(leg_float) not in LEGS:
            raise ValueError(f"Invalid WIN5 leg: {row[leg_column]!r}")
        if not math.isfinite(horse_float) or horse_float != int(horse_float) or horse_float <= 0:
            raise ValueError(f"Invalid horse number: {row[horse_column]!r}")
        if not math.isfinite(probability) or not 0 <= probability <= 100:
            raise ValueError(f"Probability outside 0..100: {row[probability_column]!r}")
        name = str(row[name_column] or "").strip()
        if not name:
            raise ValueError(f"Missing horse name for leg {int(leg_float)}, horse {int(horse_float)}")
        grouped.setdefault(int(leg_float), []).append((int(horse_float), name, probability))

    if set(grouped) != LEGS:
        raise ValueError(f"Expected WIN5 legs 1-5; found {sorted(grouped)}")

    warnings: list[str] = []
    out_rows: list[dict[str, str]] = []
    for leg in sorted(LEGS):
        horses = grouped[leg]
        numbers = [h[0] for h in horses]
        if len(numbers) != len(set(numbers)):
            raise ValueError(f"Duplicate horse number in leg {leg}")
        total = sum(h[2] for h in horses)
        if abs(total - 100.0) > 0.15:
            raise ValueError(f"Leg {leg} probabilities sum to {total:.6f}%, expected 100%")
        ordered = sorted(horses, key=lambda h: (-h[2], h[0]))
        if len(ordered) < 3:
            raise ValueError(f"Leg {leg} has fewer than three horses")
        if ordered[0][2] == ordered[1][2]:
            warnings.append(f"leg {leg}: ◎/○ tie; lower horse number is listed first")
        if ordered[1][2] == ordered[2][2]:
            warnings.append(f"leg {leg}: ○/▲ tie; lower horse number is listed first")
        for rank, (horse_no, horse_name, prob) in enumerate(ordered[:3], start=1):
            out_rows.append({
                "date": date,
                "leg": str(leg),
                "rank": str(rank),
                "mark": MARKS[rank],
                "horse_number": str(horse_no),
                "horse_name": horse_name,
                "win_probability_pct": f"{prob:.6f}",
                "source_csv": str(input_path),
                "source_sha256": file_sha256(input_path),
                "selection_method": "ranked_by_existing_probability_desc_then_horse_number",
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as f:
        fields = ["date", "leg", "rank", "mark", "horse_number", "horse_name",
                  "win_probability_pct", "source_csv", "source_sha256", "selection_method"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(out_rows)

    return {
        "date": date,
        "legs": 5,
        "picks": len(out_rows),
        "source_csv": str(input_path),
        "source_sha256": file_sha256(input_path),
        "output_csv": str(output_path),
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--probability-column", required=True)
    parser.add_argument("--leg-column", default="leg")
    parser.add_argument("--horse-column", default="horse_number")
    parser.add_argument("--name-column", default="horse_name")
    args = parser.parse_args()
    import json
    print(json.dumps(export_picks(
        args.input, args.output, args.date, args.probability_column,
        args.leg_column, args.horse_column, args.name_column,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
