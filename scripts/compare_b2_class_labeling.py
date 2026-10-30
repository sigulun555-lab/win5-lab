#!/usr/bin/env python3
"""Compare B2 candidates fitted on class-labeling v1 (existing result) vs v2 (B2.1). Read-only.

Per split: mean log-likelihood v1, v2 and v2-v1 with a race-level bootstrap 95% CI (seed 7, 4000),
plus the chosen hyperparameters and coefficients. Labels come from the prepared v2 races.
"""
import json, math, sys
import numpy as np
from pathlib import Path

v1 = json.loads(Path(sys.argv[1]).read_text()); v2 = json.loads(Path(sys.argv[2]).read_text())
prep = json.loads(Path(sys.argv[3]).read_text())
label = {r["race_id"]: {x["hid"]: x["winner_share"] for x in r["rows"]} for r in prep}

def race_ll(pred):
    y = label[pred["race_id"]]
    return sum(y.get(str(h["hid"]), 0.0) * math.log(max(h["probability"], 1e-15)) for h in pred["horses"])

def boot(d, seed=7, n=4000):
    ix = np.random.default_rng(seed).integers(0, len(d), size=(n, len(d)))
    return [float(x) for x in np.percentile(d[ix].mean(axis=1), [2.5, 97.5])]

print("inputs:", v1.get("input_sha256"), v2.get("input_sha256"))
print("implementation_sha256 v1/v2:", v1.get("implementation_sha256"), v2.get("implementation_sha256"))
f = lambda x: f"{x:+.5f}"
for r1, r2 in zip(v1["folds"], v2["folds"]):
    assert r1["split"] == r2["split"]
    print(f"## {r1['split']}  test_races v1={r1['test_races']} v2={r2['test_races']}")
    for name, c2 in r2["candidates"].items():
        c1 = r1["candidates"][name]
        p1 = {p["race_id"]: race_ll(p) for p in c1["predictions"]}
        d = np.asarray([race_ll(p) - p1[p["race_id"]] for p in c2["predictions"] if p["race_id"] in p1], dtype=float)
        lo, hi = boot(d) if len(d) else (float("nan"),) * 2
        print(f"{name:22s} LL v1 {c1['mean_log_likelihood']:.5f} v2 {c2['mean_log_likelihood']:.5f} diff(v2-v1) {f(d.mean())} [{f(lo)},{f(hi)}]  n={len(d)}")
last1, last2 = v1["folds"][-1], v2["folds"][-1]
print("== final split hyperparameters / coefficients")
for name in ("B2-a", "B2-full-b1-rating", "B2-full-b1-no-rating", "B2-full-b2-rating"):
    for tag, last in (("v1", last1), ("v2", last2)):
        c = last["candidates"][name]; p = c["params"]
        coefs = ", ".join(f"{n}={v:.5f}" for n, v in zip(c["coefficient_names"], c["coefficients"]))
        print(f"{name} {tag}: l2={p['l2']} k={p['k']} tau={p['tau']:.3f} | {coefs}")
