#!/usr/bin/env python3
"""Benchmark cached vs uncached B2 candidate tuning on the pinned prepared dataset."""
import argparse
import datetime as dt
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).resolve().with_name("fit_b2_candidates.py")
SPEC = importlib.util.spec_from_file_location("fit_b2_candidates_benchmark", MODULE_PATH)
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


def run(train, model_spec, cache_size, label):
    FIT._FIT_DESIGN_CACHE.clear()
    FIT._FIT_DESIGN_CACHE_MAX = cache_size
    started = time.perf_counter()
    result = FIT.tune_candidate(train, model_spec, progress_label=label)
    elapsed = time.perf_counter() - started
    FIT._FIT_DESIGN_CACHE.clear()
    return result, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("prepared_races", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    races = FIT.load_races(args.prepared_races)
    if len(races) < 100:
        raise SystemExit(f"Refusing benchmark: only {len(races)} prepared races")
    months = sorted({(r["_day"].year, r["_day"].month) for r in races})
    if len(months) < 4:
        raise SystemExit(f"Refusing benchmark: need at least 4 months, got {len(months)}")

    # Use the most feature-rich preregistered model and the same full rolling
    # three-month inner validation grid in both runs.
    model_spec = FIT.CANDIDATES["B2-full-b2-rating"]
    print(json.dumps({
        "event": "benchmark_setup",
        "prepared_races": len(races),
        "runner_rows": sum(len(r["rows"]) for r in races),
        "months": [f"{y:04d}-{m:02d}" for y, m in months],
        "candidate": "B2-full-b2-rating",
        "grid_combinations": len(FIT.L2_GRID) * len(FIT.K_GRID) * len(FIT.TAU_GRID),
    }), flush=True)

    # Run uncached first, then cached, using exactly the same race objects and
    # candidate configuration. A short one-time benchmark, not the full suite.
    uncached, uncached_seconds = run(races, model_spec, 0, "uncached")
    cached, cached_seconds = run(races, model_spec, 24, "cached")
    np.testing.assert_allclose(
        np.asarray(uncached["theta"]), np.asarray(cached["theta"]),
        rtol=0, atol=1e-8,
    )
    for key in ("l2", "k", "tau", "inner_months"):
        if uncached[key] != cached[key]:
            raise AssertionError(f"Selected parameter mismatch for {key}: {uncached[key]} != {cached[key]}")
    if not np.isclose(uncached["mean_inner_log_likelihood"], cached["mean_inner_log_likelihood"], rtol=0, atol=1e-10):
        raise AssertionError("mean_inner_log_likelihood differs")

    speedup = uncached_seconds / cached_seconds if cached_seconds else None
    report = {
        "status": "passed",
        "dataset": str(args.prepared_races),
        "prepared_races": len(races),
        "runner_rows": sum(len(r["rows"]) for r in races),
        "candidate": "B2-full-b2-rating",
        "grid_combinations": len(FIT.L2_GRID) * len(FIT.K_GRID) * len(FIT.TAU_GRID),
        "uncached_seconds": round(uncached_seconds, 3),
        "cached_seconds": round(cached_seconds, 3),
        "speedup": round(speedup, 3) if speedup is not None else None,
        "time_reduction_percent": round((1 - cached_seconds / uncached_seconds) * 100, 2) if uncached_seconds else None,
        "selected_params": {k: cached[k] for k in ("l2", "k", "tau", "inner_months", "mean_inner_log_likelihood")},
        "theta_max_abs_diff": float(np.max(np.abs(np.asarray(uncached["theta"]) - np.asarray(cached["theta"])))) if cached["theta"] else 0.0,
        "comparison_scope": "one full-grid, feature-rich candidate tuning on the real prepared historical dataset; not the complete 10-candidate multi-split workflow",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
