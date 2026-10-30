#!/usr/bin/env python3
"""Print a read-only summary of a B2 validation artifact (no model fitting, no file changes)."""
import json, sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
val = json.loads((root / "reports/b2-candidate-validation.json").read_text())
f = lambda x: "NA" if x is None else (f"{x:.5f}" if isinstance(x, float) else str(x))
ci = lambda c: "NA" if not c else f"[{f(c[0])},{f(c[1])}]"

print("== META")
for k in ("input_sha256", "implementation_sha256", "output_sha256", "races_loaded", "runner_rows_loaded"):
    print(k, val.get(k))
print("== SPLITS (train/test races)")
for r in val["folds"]:
    print(r["split"], r["train_races"], r["test_races"], r["train_runner_rows"], r["test_runner_rows"])

print("== TABLE1 per split/candidate: LL brier top1 top3 | d_pop ci | pop+cand d mean ci | d_B0orig ci | rawtau1_d_B0tau1 ci")
for r in val["folds"]:
    po = r.get("popularity_only", {}); un = r.get("uniform_all_horses_equal", {})
    print(f"## {r['split']} popularity LL={f(po.get('mean_log_likelihood'))} brier={f(po.get('mean_brier'))} top1={f(po.get('top1_rate'))} top3={f(po.get('top3_rate'))} uniform LL={f(un.get('mean_log_likelihood'))} brier={f(un.get('mean_brier'))}")
    for name, c in r["candidates"].items():
        print("\t".join([
            name, f(c["mean_log_likelihood"]), f(c["mean_brier"]), f(c["top1_rate"]), f(c["top3_rate"]),
            "d_pop " + f(c["delta_vs_popularity_only"]) + ci(c["delta_vs_popularity_only_95_ci"]),
            "pop+cand " + f(c["popularity_plus_candidate_delta_vs_popularity_only"]) + ci(c["popularity_plus_candidate_delta_95_ci"]),
            "d_B0orig " + f(c.get("delta_vs_B0_original")) + ci(c.get("delta_vs_B0_original_95_ci")),
            "raw_tau1_d_B0 " + f(c.get("raw_score_tau_1_delta_vs_B0_tau_1")) + ci(c.get("raw_score_tau_1_delta_vs_B0_tau_1_95_ci")),
        ]))

print("== TABLE2 selected params and coefficients per split/candidate")
for r in val["folds"]:
    print(f"## {r['split']}")
    for name, c in r["candidates"].items():
        p = c["params"]
        coefs = ", ".join(f"{n}={f(v)}" for n, v in zip(c.get("coefficient_names", []), c.get("coefficients", [])))
        print(f"{name}\tl2={p.get('l2')} k={p.get('k')} tau={f(p.get('tau'))} inner={p.get('inner_months')} innerLL={f(p.get('mean_inner_log_likelihood'))}\t{coefs}")

print("== TABLE3 data coverage (final retrospective split; train+test runner observations)")
last = val["folds"][-1]
for name, c in last["candidates"].items():
    print(name, json.dumps(c.get("data_coverage"), ensure_ascii=False))

print("== GRADED / class feature diagnostics from prepared races (train period <= 2026-07-31)")
prep = json.loads((root / "reports/b2-prepared-races.json").read_text())
for pol in ("all", "local_excluded"):
    cls = Counter(); venue = Counter(); nz = Counter(); rows = 0
    for race in prep:
        if race.get("date", "") > "2026-07-31":
            continue
        for row in race.get("rows", []):
            cf = row.get("candidate_features", {}).get(pol, {})
            rows += 1
            for run in cf.get("selected", []):
                venue[run.get("venue_type")] += 1
                if run.get("venue_type") == "JRA":
                    cls[run.get("class_category")] += 1
            for k, v in (cf.get("class_features") or {}).items():
                if v:
                    nz[k] += 1
    print(pol, "runner_rows", rows, "venue_types", dict(venue))
    print(pol, "selected JRA runs by class_category", dict(cls))
    print(pol, "runner rows with nonzero class_features by category", dict(nz))

print("== RACE RECONCILIATION JSON (truncated)")
rec = json.loads((root / "reports/b2-race-dataset-reconciliation.json").read_text())
print("keys", list(rec.keys()))
print(json.dumps(rec, ensure_ascii=False)[:7000])
