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

print("== RACE RECONCILIATION: date counts of keys present only in current data")
cur = rec.get("current", {})
only = cur.get("race_keys_only_here_first_100", [])
print("only_here_count", cur.get("race_keys_only_here_count"), "listed", len(only))
print("by date", dict(Counter(k[0] for k in only)))
print("test_period_key_difference_counts", json.dumps(rec.get("test_period_key_difference_counts"), ensure_ascii=False))
print("test_period_key_difference_details", json.dumps(rec.get("test_period_key_difference_details"), ensure_ascii=False)[:3000])
print("same_race_key_count", rec.get("same_race_key_count"))
print("reference", json.dumps({k: v for k, v in (rec.get("reference") or {}).items() if "first_100" not in k and "examples" not in k}, ensure_ascii=False)[:2500])

print("== TABLE4 candidate minus B0-refit, per-race log-likelihood difference, bootstrap 95% CI (seed 7, 4000; from stored predictions)")
import math
import numpy as np
label = {}
for race in prep:
    label[race.get("race_id")] = {str(r.get("hid")): float(r.get("winner_share", 0.0)) for r in race.get("rows", [])}

def race_ll(pred):
    y = label.get(pred.get("race_id"), {})
    return sum(y.get(str(h["hid"]), 0.0) * math.log(max(h["probability"], 1e-15)) for h in pred["horses"])

def boot(d, seed=7, n=4000):
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(d), size=(n, len(d)))
    m = d[ix].mean(axis=1)
    return [float(x) for x in np.percentile(m, [2.5, 97.5])]

for r in val["folds"]:
    base = {p["race_id"]: race_ll(p) for p in r["candidates"]["B0-refit"]["predictions"]}
    print(f"## {r['split']} (difference = candidate - B0-refit; positive = candidate better)")
    for name, c in r["candidates"].items():
        if name in ("B0-original", "B0-refit"):
            continue
        d = np.asarray([race_ll(p) - base[p["race_id"]] for p in c["predictions"]], dtype=float)
        lo, hi = boot(d)
        print(f"{name}\tmean {d.mean():+.5f} [{lo:+.5f},{hi:+.5f}] races {len(d)}")

print("== TABLE5 variability and day-clustering of the primary difference (B2-full-b1-rating - B0-refit), per split")
primary = "B2-full-b1-rating"
date_of = {r["race_id"]: r["date"] for r in prep}

def anova_icc(values, groups):
    """One-way random-effects ICC(1) with unbalanced groups (Wu/Fleiss-Cuzick style n0)."""
    vals = np.asarray(values, dtype=float); g = np.asarray(groups)
    labels, inv = np.unique(g, return_inverse=True)
    k = len(labels); n = len(vals)
    ni = np.bincount(inv).astype(float)
    means = np.bincount(inv, weights=vals) / ni
    grand = vals.mean()
    msb = (ni * (means - grand) ** 2).sum() / (k - 1)
    msw = ((vals - means[inv]) ** 2).sum() / (n - k)
    n0 = (n - (ni ** 2).sum() / n) / (k - 1)
    return float((msb - msw) / (msb + (n0 - 1) * msw)), k, float(ni.mean())

def boot_by_day(d, days, seed=7, n=4000):
    labels, inv = np.unique(days, return_inverse=True)
    idx = [np.where(inv == i)[0] for i in range(len(labels))]
    rng = np.random.default_rng(seed)
    means = np.empty(n)
    for b in range(n):
        pick = rng.integers(0, len(labels), size=len(labels))
        means[b] = np.concatenate([d[idx[i]] for i in pick]).mean()
    return [float(x) for x in np.percentile(means, [2.5, 97.5])]

for r in val["folds"]:
    base = {p["race_id"]: race_ll(p) for p in r["candidates"]["B0-refit"]["predictions"]}
    c = r["candidates"][primary]
    ids = [p["race_id"] for p in c["predictions"]]
    d = np.asarray([race_ll(p) - base[p["race_id"]] for p in c["predictions"]], dtype=float)
    days = [date_of[i] for i in ids]
    icc, k, m = anova_icc(d, days)
    deff = 1 + (m - 1) * max(icc, 0.0)
    se_ind = d.std(ddof=1) / math.sqrt(len(d))
    lo, hi = boot(d); dlo, dhi = boot_by_day(d, days)
    print(f"{r['split']}: races {len(d)} days {k} mean_per_day {m:.1f} mean {d.mean():+.5f} sd {d.std(ddof=1):.4f} icc_by_day {icc:+.4f} design_effect {deff:.3f} "
          f"se_indep {se_ind:.5f} se_cluster_approx {se_ind*math.sqrt(deff):.5f} race_boot [{lo:+.4f},{hi:+.4f}] day_boot [{dlo:+.4f},{dhi:+.4f}]")
