#!/usr/bin/env python3
"""Compare the scored folds from B2 fit outputs, excluding expected provenance differences."""
import argparse, json, math
from pathlib import Path

def close(a, b, tol, diffs, path="$", limit=30):
    if len(diffs) >= limit: return
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            diffs.append(f"{path}: key sets differ"); return
        for k in a: close(a[k], b[k], tol, diffs, f"{path}.{k}", limit)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: list lengths differ {len(a)} vs {len(b)}"); return
        for i, (x, y) in enumerate(zip(a, b)): close(x, y, tol, diffs, f"{path}[{i}]", limit)
    elif isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        if not math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol):
            diffs.append(f"{path}: {a!r} != {b!r}")
    elif a != b: diffs.append(f"{path}: {a!r} != {b!r}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("baseline"); ap.add_argument("candidate"); ap.add_argument("--out", required=True)
    ap.add_argument("--tolerance", type=float, default=1e-10); args=ap.parse_args()
    base=json.loads(Path(args.baseline).read_text()); cand=json.loads(Path(args.candidate).read_text())
    diffs=[]
    same_input=base.get("input_sha256")==cand.get("input_sha256")
    if not same_input: diffs.append("input_sha256 differs")
    for key in ("races_loaded","runner_rows_loaded","selected_history_run_observations","selected_jra_run_observations"):
        if base.get(key)!=cand.get(key): diffs.append(f"$.{key}: {base.get(key)!r} != {cand.get(key)!r}")
    close(base.get("folds"),cand.get("folds"),args.tolerance,diffs,"$.folds")
    report={"status":"PASS" if not diffs else "FAIL","tolerance":args.tolerance,
            "baseline_input_sha256":base.get("input_sha256"),"candidate_input_sha256":cand.get("input_sha256"),
            "same_input_sha256":same_input,"compared":"all folds, model parameters, metrics, and per-horse predictions; provenance hashes excluded",
            "differences_count_reported":len(diffs),"differences":diffs}
    Path(args.out).write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))
    if report["status"]!="PASS": raise SystemExit(1)
if __name__=="__main__": main()
