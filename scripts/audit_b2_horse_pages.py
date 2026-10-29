#!/usr/bin/env python3
"""Verify a pinned horse-pages gzip snapshot against its retrieval manifest."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path

def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gzip", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--cnames", type=Path, required=True, help="Original gzip input mapping used by the collector")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    compressed = args.gzip.read_bytes()
    raw = gzip.decompress(compressed)
    cnames_compressed = args.cnames.read_bytes()
    cnames_raw = gzip.decompress(cnames_compressed)
    cnames = json.loads(cnames_raw.decode("utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    horses = json.loads(raw.decode("utf-8"))
    if not isinstance(horses, dict):
        raise ValueError("horse-pages JSON must be a horse-ID mapping")
    actual_horses = len(horses)
    actual_runs = 0
    zero_runs = 0
    exactly_four_runs = 0
    one_to_four_runs = 0
    invalid = []
    for hid, horse in horses.items():
        runs = horse.get("runs") if isinstance(horse, dict) else None
        if not isinstance(runs, list):
            invalid.append(str(hid))
            continue
        actual_runs += len(runs)
        zero_runs += int(len(runs) == 0)
        exactly_four_runs += int(len(runs) == 4)
        one_to_four_runs += int(1 <= len(runs) <= 4)
    requested = int(manifest.get("requested", -1))
    succeeded = int(manifest.get("succeeded", -1))
    missing = int(manifest.get("missing", -1))
    missing_ids = manifest.get("missing_horses", [])
    input_ids = set(str(h) for h in cnames) if isinstance(cnames, dict) else set()
    output_ids = set(str(h) for h in horses)
    missing_id_set = set(str(h) for h in missing_ids) if isinstance(missing_ids, list) else set()
    checks = {
        "compressed_sha_matches": sha_bytes(compressed) == manifest.get("horses_json_gz_sha256"),
        "uncompressed_sha_matches": sha_bytes(raw) == manifest.get("horses_json_sha256"),
        "requested_equals_succeeded_plus_missing": requested == succeeded + missing,
        "missing_count_matches_id_list": isinstance(missing_ids, list) and len(missing_ids) == missing,
        "success_count_matches_output_horse_count": succeeded == actual_horses,
        "all_horses_have_runs_list": not invalid,
        "total_runs_matches_manifest": actual_runs == int(manifest.get("total_runs", -1)),
        "zero_run_horses_matches_manifest": zero_runs == int(manifest.get("horses_with_zero_runs", -1)),
        "cnames_sha_matches_manifest": sha_bytes(cnames_raw) == manifest.get("cnames_sha256"),
        "requested_count_matches_cnames": requested == len(input_ids),
        "output_and_missing_ids_partition_input": output_ids.isdisjoint(missing_id_set) and output_ids | missing_id_set == input_ids,
    }
    report = {
        "status": "pass" if all(checks.values()) else "fail",
        "manifest": str(args.manifest),
        "manifest_sha256": sha_bytes(args.manifest.read_bytes()),
        "cnames_input": str(args.cnames),
        "cnames_compressed_sha256": sha_bytes(cnames_compressed),
        "cnames_decompressed_sha256": sha_bytes(cnames_raw),
        "cnames_count": len(input_ids),
        "gzip": str(args.gzip),
        "compressed_sha256": sha_bytes(compressed),
        "uncompressed_sha256": sha_bytes(raw),
        "requested": requested, "succeeded": succeeded, "missing": missing,
        "output_horse_count": actual_horses, "total_runs": actual_runs,
        "zero_run_horses": zero_runs,
        "horses_with_exactly_four_runs_potentially_limited": exactly_four_runs,
        "horses_with_one_to_four_runs": one_to_four_runs,
        "four_run_limit_note": "Exactly four runs may indicate the known overseas-history page limit, but is not sufficient to identify foreign horses; treat as a potential coverage limit only.",
        "invalid_horse_records_first_100": invalid[:100],
        "checks": checks,
        "retrieval": {k: manifest.get(k) for k in ("started_at_jst", "finished_at_jst", "workers", "passes", "cnames_sha256", "script_sha256")},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(checks.values()):
        raise SystemExit("horse-pages integrity audit failed")

if __name__ == "__main__":
    main()
