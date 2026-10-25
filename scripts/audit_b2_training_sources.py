#!/usr/bin/env python3
"""Report whether repository data can support the preregistered B2 backtest.

This is a source-availability audit, not a model evaluation. It never downloads
data, guesses labels, or treats WIN5 prediction candidates as historical results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def audit(root: Path) -> dict:
    expected = {
        "race_level_training_data": root / "research/factor-validation/races.json",
        "horse_history_snapshot": root / "data/horse_history/2026-10-25.json",
        "b2_protocol": root / "docs/win5/b2-validation-protocol.md",
        "b2_feature_code": root / "research/factor-validation/b2_features.py",
    }
    checks = {
        key: {"path": str(path.relative_to(root)), "exists": path.is_file(),
              "bytes": path.stat().st_size if path.is_file() else None}
        for key, path in expected.items()
    }
    candidate_dir = root / "data/win5_races"
    candidate_files = sorted(candidate_dir.glob("*.json")) if candidate_dir.is_dir() else []
    # These files describe selected WIN5 candidates/probabilities, not all runners
    # with observed finish labels and popularity for historical training.
    checks["win5_candidate_files"] = {
        "path": str(candidate_dir.relative_to(root)),
        "exists": candidate_dir.is_dir(),
        "count": len(candidate_files),
        "usable_as_full_race_labels": False,
    }
    blockers = []
    if not checks["race_level_training_data"]["exists"]:
        blockers.append(
            "Missing research/factor-validation/races.json: no committed race-level "
            "historical dataset was found at the path used by the existing validation code."
        )
    if not checks["horse_history_snapshot"]["exists"]:
        blockers.append("Missing horse-history snapshot required for the current history audit.")
    if checks["win5_candidate_files"]["count"] and not checks["race_level_training_data"]["exists"]:
        blockers.append(
            "WIN5 candidate JSON files are not a substitute for complete historical race results."
        )
    ready = (
        checks["race_level_training_data"]["exists"]
        and checks["horse_history_snapshot"]["exists"]
        and checks["b2_protocol"]["exists"]
        and checks["b2_feature_code"]["exists"]
    )
    return {
        "audit_type": "b2_training_source_availability_only",
        "status": "sources_present_for_next_integrity_audit" if ready else "blocked_missing_or_unverified_sources",
        "checks": checks,
        "blockers": blockers,
        "not_claimed": [
            "This audit does not verify dataset contents or coverage.",
            "This audit does not establish leakage-free features.",
            "This audit does not fit coefficients or evaluate B2.",
        ],
        "next_step": (
            "Inspect the race-level dataset schema and run integrity/leakage checks."
            if ready else
            "Recover or rebuild the complete historical race-level dataset with date, venue, "
            "race ID, runner ID, finish position, and popularity; record source and retrieval metadata."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(audit(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
