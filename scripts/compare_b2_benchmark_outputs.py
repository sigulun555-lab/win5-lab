#!/usr/bin/env python3
"""Compare B2 fit output JSON from identical prepared inputs."""
import argparse, json, math
from pathlib import Path

def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))

def close(a, b, tol, diffs, path="$", limit=20):
    if len(diffs) >= limit:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            diffs.append(f"{path}: key sets differ"); return
        for k in a:
            close(a[k], b[k], tol, diffs, f"{path}.{k}", limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: list lengths differ {len(a)} vs {len(b)}"); return
        for i, (x, y) in enumerate(zip(a, b)):
            close(x, y, tol, diffs, f"{path}[{i}]", limit)
    elif isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        if not math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol):
            diffs.append(f"{path}: {a!r} != {b!r}")
    elif a != b:
        diffs.append(f"{path}: {a!r} != {b!r}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("candidate")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tolerance", type=float, default=1e-10)
    args = ap.parse_args()
    base, cand = load(args.baseline), load(args.candidate)
    diffs = []
    close(base, cand, args.tolerance, diffs)
    report = {"status": "PASS" if not diffs else "FAIL", "tolerance": args.tolerance,
              "baseline_input_sha256": base.get("input_sha256"), "candidate_input_sha256": cand.get("input_sha256"),
              "same_input_sha256": base.get("input_sha256") == cand.get("input_sha256"),
              "differences_count_reported": len(diffs), "differences": diffs}
    if not report["same_input_sha256"]:
        report["status"] = "FAIL"
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(1)

if __name__ == "__main__":
    main()
