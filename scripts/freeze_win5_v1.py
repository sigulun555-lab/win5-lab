#!/usr/bin/env python3
"""Freeze an already-existing V1 WIN5 estimate without inventing probabilities.

The input must contain exactly five legs and a single consistent GPT estimate
timestamp. Output is immutable by default: an existing output is never replaced.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import math
from pathlib import Path

JST = dt.timezone(dt.timedelta(hours=9))
REQUIRED = {
    "date", "win5_order", "race", "horse_no", "horse_name",
    "gpt_estimated_win_probability_pct", "gpt_info_time_jst",
}


def freeze(input_path: Path, output_path: Path, deadline: str, now: dt.datetime | None = None) -> dict:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen V1: {output_path}")
    if not deadline or len(deadline.split(":")) != 2:
        raise ValueError("deadline must be HH:MM in Japan local time")
    hh, mm = map(int, deadline.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("invalid deadline")
    now = now or dt.datetime.now(JST)
    with input_path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV header missing")
        missing = REQUIRED - set(reader.fieldnames)
        if missing:
            raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
        fields = list(reader.fieldnames)
        rows = list(reader)
    if not rows:
        raise ValueError("No prediction rows")
    dates = {r["date"].strip() for r in rows}
    if len(dates) != 1:
        raise ValueError(f"Expected one date, found {sorted(dates)}")
    date = dt.date.fromisoformat(next(iter(dates)))
    cutoff = dt.datetime.combine(date, dt.time(hh, mm), tzinfo=JST)
    if now.date() == date and now >= cutoff:
        raise ValueError(f"Deadline passed ({cutoff.isoformat()}); refusing to freeze as a pre-deadline forecast")
    if now.date() > date:
        raise ValueError(f"Historical date {date} cannot be frozen as a pre-deadline forecast")
    info_times = {r["gpt_info_time_jst"].strip() for r in rows}
    if len(info_times) != 1 or not next(iter(info_times)):
        raise ValueError(f"GPT estimate timestamps are missing or inconsistent: {sorted(info_times)}")
    try:
        info_time = dt.datetime.strptime(next(iter(info_times)), "%Y-%m-%d %H:%M JST").replace(tzinfo=JST)
    except ValueError as e:
        raise ValueError("gpt_info_time_jst must use YYYY-MM-DD HH:MM JST") from e
    if info_time >= cutoff:
        raise ValueError(f"GPT estimate timestamp {info_time.isoformat()} is not before deadline {cutoff.isoformat()}")
    groups: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        leg = str(r["win5_order"]).strip()
        if leg not in {"1", "2", "3", "4", "5"}:
            raise ValueError(f"Invalid WIN5 leg: {leg}")
        groups.setdefault(leg, []).append(r)
        try:
            p = float(r["gpt_estimated_win_probability_pct"])
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid probability for {leg}/{r['horse_no']}") from e
        if not math.isfinite(p) or p < 0 or p > 100:
            raise ValueError(f"Probability out of range for {leg}/{r['horse_no']}: {p}")
        if not str(r["horse_no"]).strip() or not str(r["horse_name"]).strip():
            raise ValueError(f"Missing horse identity in leg {leg}")
    if set(groups) != {"1", "2", "3", "4", "5"}:
        raise ValueError(f"Expected exactly five legs, found {sorted(groups)}")
    for leg, entries in groups.items():
        if len({r["horse_no"] for r in entries}) != len(entries):
            raise ValueError(f"Duplicate horse number in leg {leg}")
        total = sum(float(r["gpt_estimated_win_probability_pct"]) for r in entries)
        if abs(total - 100.0) > 0.15:
            raise ValueError(f"Leg {leg} V1 probability sum is {total:.2f}%, expected 100%")
    fields += [c for c in ("v1_frozen_at_jst", "v1_deadline_jst", "v1_freeze_status") if c not in fields]
    frozen_at = now.astimezone(JST).strftime("%Y-%m-%d %H:%M:%S JST")
    for r in rows:
        r["v1_frozen_at_jst"] = frozen_at
        r["v1_deadline_jst"] = cutoff.strftime("%Y-%m-%d %H:%M JST")
        r["v1_freeze_status"] = "frozen_pre_deadline"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return {"date": str(date), "legs": len(groups), "horses": len(rows), "gpt_info_time_jst": next(iter(info_times)), "frozen_at_jst": frozen_at, "deadline_jst": cutoff.strftime("%Y-%m-%d %H:%M JST")}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--deadline", required=True, help="Official WIN5 deadline in JST, HH:MM")
    a = p.parse_args()
    print(freeze(a.input, a.output, a.deadline))


if __name__ == "__main__":
    main()
