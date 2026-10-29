#!/usr/bin/env python3
"""Fit preregistered B2 candidate models and emit immutable evaluation outputs.

Input must be the leakage-safe prepared race JSON from b2_dataset_prep.py.
This script does not mutate original B predictions. Historical final popularity is
only a retrospective benchmark, not evidence of pre-off operational performance.
"""
from __future__ import annotations
import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

L2_GRID = (0.001, 0.01, 0.1)
K_GRID = (0, 1, 2, 3, 5, 8)
TAU_GRID = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)
GAMMA_CATS = ("MAIDEN", "1WIN", "2WIN", "3WIN", "OP_L", "GRADED", "UNKNOWN_JRA")
FIXED_B0_TAU = 1.0 / 1.35

CANDIDATES = {
    "B2-a": {"policy": "all", "class": True, "shrink": False, "local": False, "rating": False},
    "B2-b1": {"policy": "local_excluded", "class": False, "shrink": False, "local": False, "rating": False},
    "B2-b2": {"policy": "all", "class": False, "shrink": False, "local": True, "rating": False},
    "B2-c": {"policy": "all", "class": False, "shrink": True, "local": False, "rating": False},
    "B2-d": {"policy": "all", "class": False, "shrink": False, "local": False, "rating": True},
    "B2-full-b1-no-rating": {"policy": "local_excluded", "class": True, "shrink": True, "local": False, "rating": False},
    "B2-full-b1-rating": {"policy": "local_excluded", "class": True, "shrink": True, "local": False, "rating": True},
    "B2-full-b2-no-rating": {"policy": "all", "class": True, "shrink": True, "local": True, "rating": False},
    "B2-full-b2-rating": {"policy": "all", "class": True, "shrink": True, "local": True, "rating": True},
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if path and Path(path).is_file() else None

def month_start(value):
    return dt.date(value.year, value.month, 1)

def add_month(value, n=1):
    idx = value.year * 12 + (value.month - 1) + n
    return dt.date(idx // 12, idx % 12 + 1, 1)

def load_races(path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("input must be a top-level list of prepared races")
    races = []
    for race in raw:
        day = dt.date.fromisoformat(race["date"])
        rows = race.get("rows", [])
        if int(race.get("winner_count", 0)) != 1 or len(rows) < 5:
            continue
        if sum(float(r.get("winner_share", 0.0)) for r in rows) != 1.0:
            continue
        races.append({**race, "_day": day})
    races.sort(key=lambda r: (r["_day"], str(r.get("race_id", ""))))
    return races

def feat(row, policy):
    return row.get("candidate_features", {}).get("local_excluded" if policy == "local_excluded" else "all", {})

def raw_score(row, spec, theta=None, k=0):
    f = feat(row, spec["policy"])
    base = float(f.get("base_score", 0.0))
    n_jra = int(f.get("jra_runs_selected", 0))
    if spec["class"] and theta is not None:
        for j, cat in enumerate(GAMMA_CATS):
            base += float(theta[j]) * float(f.get("class_features", {}).get(cat, 0.0))
    offset = len(GAMMA_CATS) if spec["class"] else 0
    if spec["local"] and theta is not None:
        base += float(theta[offset]) * float(f.get("local_feature", 0.0))
        offset += 1
    if spec["shrink"]:
        base *= (n_jra / (n_jra + k)) if n_jra + k else 0.0
    if spec["rating"] and theta is not None:
        base += float(theta[offset]) * float(f.get("rating_delta", 0.0))
    return base

def b0_score(row):
    f = feat(row, "all")
    return float(f.get("base_score", 0.0)) + 0.025 * float(f.get("rating_delta", 0.0))

def softmax(scores, tau=1.0):
    z = np.asarray(scores, dtype=float) / float(tau)
    z -= np.max(z)
    e = np.exp(np.clip(z, -700, 700))
    return e / e.sum()

def target_vec(race):
    return np.asarray([float(r.get("winner_share", 0.0)) for r in race["rows"]], dtype=float)

def model_ll(races, score_fn, tau=1.0):
    vals = []
    for race in races:
        scores = [score_fn(row) for row in race["rows"]]
        p = softmax(scores, tau)
        y = target_vec(race)
        vals.append(float(np.sum(y * np.log(np.clip(p, 1e-15, 1.0)))))
    return np.asarray(vals)

def fit_theta(races, spec, l2, k, tau=1.0):
    names = []
    if spec["class"]:
        names.extend(GAMMA_CATS)
    if spec["local"]:
        names.append("eta_LOCAL")
    if spec["rating"]:
        names.append("rho")
    if not names:
        return np.zeros(0, dtype=float)
    bounds = [(-1.0, 0.0) if name == "eta_LOCAL" else (None, None) for name in names]
    def objective(theta):
        loss = l2 * float(theta @ theta)
        grad = 2.0 * l2 * theta
        for race in races:
            scores = np.asarray([raw_score(row, spec, theta, k) for row in race["rows"]], dtype=float)
            p = softmax(scores, tau)
            y = target_vec(race)
            loss -= float(y @ np.log(np.clip(p, 1e-15, 1.0)))
            # Numerical gradient is used below because features include candidate-specific shrinkage.
        return loss
    result = minimize(objective, np.zeros(len(names)), method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": 500, "ftol": 1e-10})
    if not np.isfinite(result.fun):
        raise RuntimeError("non-finite coefficient fit: " + str(result.message))
    return result.x

def tune_candidate(train, spec, is_b0=False):
    if not train:
        raise ValueError("empty training split")
    last = train[-1]["_day"]
    months = sorted({(r["_day"].year, r["_day"].month) for r in train})
    months = months[-3:]
    if len(months) != 3:
        raise ValueError("need three inner validation months; got " + repr(months))
    combos = []
    l2_values = L2_GRID if not is_b0 else (0.01,)
    k_values = K_GRID if spec.get("shrink") and not is_b0 else (0,)
    tau_values = TAU_GRID if not is_b0 else TAU_GRID
    for l2 in l2_values:
        for k in k_values:
            for tau in tau_values:
                block_ll = []
                for year, month in months:
                    start = dt.date(year, month, 1)
                    end = add_month(start, 1)
                    inner_train = [r for r in train if r["_day"] < start]
                    inner_val = [r for r in train if start <= r["_day"] < end]
                    if not inner_train or not inner_val:
                        continue
                    if is_b0:
                        theta = np.zeros(0)
                        scorer = b0_score
                    else:
                        theta = fit_theta(inner_train, spec, l2, k, tau)
                        scorer = lambda row, t=theta, kk=k: raw_score(row, spec, t, kk)
                    block_ll.extend(model_ll(inner_val, scorer, tau).tolist())
                if len(block_ll) < 3:
                    continue
                combos.append((float(np.mean(block_ll)), l2, k, tau))
    if not combos:
        raise ValueError("no valid inner rolling-origin combinations")
    # Highest mean log likelihood; ties: larger L2, smaller k, tau nearest 1.0.
    combos.sort(key=lambda x: (-x[0], -x[1], x[2], abs(x[3] - 1.0), x[3]))
    best = combos[0]
    theta = np.zeros(0) if is_b0 else fit_theta(train, spec, best[1], best[2], best[3])
    return {"mean_inner_log_likelihood": best[0], "l2": best[1], "k": best[2],
            "tau": best[3], "theta": theta.tolist(), "inner_months": [f"{y:04d}-{m:02d}" for y, m in months]}

def popularity_matrix(race):
    pop = np.asarray([min(max(int(row.get("pop", 18)), 1), 18) for row in race["rows"]], dtype=int)
    matrix = np.zeros((len(pop), 18), dtype=float)
    matrix[np.arange(len(pop)), pop - 1] = 1.0
    return matrix

def fit_popularity(races, extra_scores=None, l2=0.01):
    def objective(theta):
        loss = l2 * float(theta @ theta)
        grad = 2.0 * l2 * theta
        for i, race in enumerate(races):
            X = popularity_matrix(race)
            if extra_scores is not None:
                X = np.column_stack([X, np.asarray(extra_scores[i], dtype=float)])
            p = softmax(X @ theta, 1.0)
            y = target_vec(race)
            loss -= float(y @ np.log(np.clip(p, 1e-15, 1.0)))
            grad -= X.T @ (y - p)
        return loss, grad
    d = 18 + (1 if extra_scores is not None else 0)
    res = minimize(objective, np.zeros(d), jac=True, method="L-BFGS-B", options={"maxiter": 500, "ftol": 1e-10})
    if not np.isfinite(res.fun):
        raise RuntimeError("popularity model fit failed: " + str(res.message))
    return res.x

def popularity_ll(races, theta, extra_scores=None):
    out = []
    for i, race in enumerate(races):
        X = popularity_matrix(race)
        if extra_scores is not None:
            X = np.column_stack([X, np.asarray(extra_scores[i], dtype=float)])
        out.append(float(target_vec(race) @ np.log(np.clip(softmax(X @ theta, 1.0), 1e-15, 1.0))))
    return np.asarray(out)

def bootstrap_ci(delta, seed=7, n_boot=4000):
    if len(delta) == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(delta), size=(n_boot, len(delta)))
    means = np.mean(delta[ix], axis=1)
    return [float(x) for x in np.percentile(means, [2.5, 97.5])]

def race_brier(race, probabilities):
    y = target_vec(race)
    p = np.asarray(probabilities, dtype=float)
    return float(np.sum((p - y) ** 2))

def score_summary(races, scorer, tau):
    ll = []
    brier = []
    top1 = []
    top3 = []
    for race in races:
        scores = [scorer(row) for row in race["rows"]]
        p = softmax(scores, tau)
        y = target_vec(race)
        ll.append(float(y @ np.log(np.clip(p, 1e-15, 1.0))))
        brier.append(race_brier(race, p))
        winner = int(np.argmax(y))
        order = np.argsort(-p)
        top1.append(float(order[0] == winner))
        top3.append(float(winner in order[:min(3, len(order))]))
    return {
        "mean_log_likelihood": float(np.mean(ll)) if ll else None,
        "mean_brier": float(np.mean(brier)) if brier else None,
        "top1_rate": float(np.mean(top1)) if top1 else None,
        "top3_rate": float(np.mean(top3)) if top3 else None,
        "_ll": np.asarray(ll, dtype=float),
    }

def evaluate_split(train, test, split_name):
    report = {"split": split_name, "train_races": len(train), "test_races": len(test), "candidates": {}}
    all_specs = {"B0-original": None, "B0-refit": None, **CANDIDATES}
    if not train or not test:
        report["status"] = "insufficient_train_or_test_races"
        return report

    pop_theta = fit_popularity(train)
    pop_test_ll = popularity_ll(test, pop_theta)
    report["popularity_only"] = {
        "mean_log_likelihood": float(pop_test_ll.mean()),
        "delta_vs_uniform_95_ci": bootstrap_ci(pop_test_ll - np.asarray([-math.log(len(r['rows'])) for r in test])),
    }
    uniform_ll = np.asarray([-math.log(len(r["rows"])) for r in test], dtype=float)
    uniform_brier = np.asarray([1.0 - 1.0 / len(r["rows"]) for r in test], dtype=float)
    report["uniform_all_horses_equal"] = {
        "mean_log_likelihood": float(uniform_ll.mean()),
        "mean_brier": float(uniform_brier.mean()),
    }
    b0_ll = None
    staged = {}
    for name, spec in all_specs.items():
        if name == "B0-original":
            params = {"l2": None, "k": 0, "tau": FIXED_B0_TAU, "theta": [], "inner_months": []}
            scorer = b0_score
        elif name == "B0-refit":
            params = tune_candidate(train, {"policy": "all", "class": False, "shrink": False, "local": False, "rating": False}, is_b0=True)
            scorer = b0_score
        else:
            params = tune_candidate(train, spec)
            theta = np.asarray(params["theta"], dtype=float)
            k = params["k"]
            scorer = lambda row, s=spec, t=theta, kk=k: raw_score(row, s, t, kk)

        summary = score_summary(test, scorer, params["tau"])
        ll = summary.pop("_ll")
        if name == "B0-original":
            b0_ll = ll
        scores = [[scorer(row) for row in race["rows"]] for race in test]
        probs = [softmax(s, params["tau"]).tolist() for s in scores]
        # Final popularity is a retrospective benchmark only; it is not treated as pre-off information.
        extra_train = [[scorer(row) for row in race["rows"]] for race in train]
        combined_theta = fit_popularity(train, extra_train, l2=0.01)
        combined_ll = popularity_ll(test, combined_theta, scores)
        combined_delta = combined_ll - pop_test_ll
        delta_pop = ll - pop_test_ll
        delta_uniform = ll - uniform_ll
        staged[name] = {
            "params": {k: v for k, v in params.items() if k != "theta"},
            "coefficients": params.get("theta", []),
            **summary,
            "delta_vs_popularity_only": float(delta_pop.mean()),
            "delta_vs_popularity_only_95_ci": bootstrap_ci(delta_pop),
            "delta_vs_uniform_95_ci": bootstrap_ci(delta_uniform),
            "popularity_plus_candidate_mean_log_likelihood": float(combined_ll.mean()),
            "popularity_plus_candidate_delta_vs_popularity_only": float(combined_delta.mean()),
            "popularity_plus_candidate_delta_95_ci": bootstrap_ci(combined_delta),
            "predictions": [
                {"race_id": race.get("race_id"), "date": race["date"],
                 "horses": [{"hid": row.get("hid"), "num": row.get("num"), "probability": probs[i][j]}
                            for j, row in enumerate(race["rows"])]}
                for i, race in enumerate(test)
            ],
        }

    for name, record in staged.items():
        ll = score_summary(test, b0_score, FIXED_B0_TAU)["_ll"]
        candidate_ll = np.asarray([
            sum(float(h.get("winner_share", 0.0)) * math.log(max(h.get("probability", 0.0), 1e-15))
                for h in race["rows"])
            for race in test
        ]) if False else None
        if name == "B0-original":
            record["delta_vs_B0_original"] = 0.0
            record["delta_vs_B0_original_95_ci"] = [0.0, 0.0]
        else:
            # Recover this candidate's per-race log likelihood from the reported probabilities.
            pred_by_race = {p["race_id"]: p for p in record["predictions"]}
            cand_ll = []
            for race in test:
                pred = pred_by_race.get(race.get("race_id"))
                if pred is None:
                    cand_ll.append(float("nan"))
                    continue
                prob_by_hid = {str(h["hid"]): h["probability"] for h in pred["horses"]}
                cand_ll.append(sum(float(row.get("winner_share", 0.0)) * math.log(max(prob_by_hid.get(str(row.get("hid")), 0.0), 1e-15)) for row in race["rows"]))
            d = np.asarray(cand_ll, dtype=float) - b0_ll
            record["delta_vs_B0_original"] = float(np.nanmean(d))
            record["delta_vs_B0_original_95_ci"] = bootstrap_ci(d[np.isfinite(d)])
        report["candidates"][name] = record
    return report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--spec", type=Path, default=Path("docs/win5/2026-10-25-gpt-b2-model-spec.md"))
    ap.add_argument("--aliases", type=Path, default=Path("research/factor-validation/b2_venue_aliases.json"))
    args = ap.parse_args()
    races = load_races(args.input)
    def between(lo, hi):
        return [r for r in races if dt.date.fromisoformat(lo) <= r["_day"] <= dt.date.fromisoformat(hi)]
    folds = [
        ("F1_2026-04", "2026-03-31", "2026-04-01", "2026-04-30"),
        ("F2_2026-05", "2026-04-30", "2026-05-01", "2026-05-31"),
        ("F3_2026-06", "2026-05-31", "2026-06-01", "2026-06-30"),
        ("F4_2026-07", "2026-06-30", "2026-07-01", "2026-07-31"),
    ]
    reports = []
    for name, train_end, test_start, test_end in folds:
        train = between("2025-10-01", train_end)
        test = between(test_start, test_end)
        reports.append(evaluate_split(train, test, name))
    final_train = between("2025-10-01", "2026-07-31")
    final_test = between("2026-08-01", "2026-10-24")
    reports.append(evaluate_split(final_train, final_test, "retrospective_test_2026-08_to_2026-10-24"))
    payload = {
        "status": "candidate_fit_and_predictions_only_validation_requires_independent_review",
        "warning": "Uses final popularity from result pages; retrospective benchmark only, not proof of pre-off operational performance. 2026-08 onward is not fully unseen because B results were previously discussed. Do not adopt without preregistered forward validation.",
        "input": str(args.input), "input_sha256": sha(args.input),
        "spec": str(args.spec), "spec_sha256": sha(args.spec),
        "aliases": str(args.aliases), "aliases_sha256": sha(args.aliases),
        "implementation_sha256": sha(__file__),
        "races_loaded": len(races),
        "folds": reports,
        "forward_validation_required_from": "2026-10-25",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in payload.items() if k != "folds"}, ensure_ascii=False, indent=2))
    for report in reports:
        print(report["split"], "train", report["train_races"], "test", report["test_races"])
        for name, result in report["candidates"].items():
            print(name, "LL", result["mean_log_likelihood"], "delta-pop", result["delta_vs_popularity_only"],
                  "combined CI", result["popularity_plus_candidate_delta_95_ci"])
if __name__ == "__main__":
    main()
