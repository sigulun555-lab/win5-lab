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
from collections import OrderedDict
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

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
    "B2-d-no-rating": {"policy": "all", "class": False, "shrink": False, "local": False, "rating": False},
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

def candidate_design(row, spec, k):
    f = feat(row, spec["policy"])
    base = float(f.get("base_score", 0.0))
    cols = []
    if spec["class"]:
        cols.extend(float(f.get("class_features", {}).get(cat, 0.0)) for cat in GAMMA_CATS)
    if spec["local"]:
        cols.append(float(f.get("local_feature", 0.0)))
    shrink = (int(f.get("jra_runs_selected", 0)) / (int(f.get("jra_runs_selected", 0)) + k)
              if spec["shrink"] and int(f.get("jra_runs_selected", 0)) + k else (0.0 if spec["shrink"] else 1.0))
    base *= shrink
    cols = [x * shrink for x in cols]
    if spec["rating"]:
        cols.append(float(f.get("rating_delta", 0.0)))
    return base, np.asarray(cols, dtype=float)

# Bounded cache for fit designs reused across the L2/tau search grid.
_FIT_DESIGN_CACHE = OrderedDict()
_FIT_DESIGN_CACHE_MAX = 6


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
    # The design arrays depend on races/spec/k, but not on L2 or tau.
    cache_key = (
        tuple(id(race) for race in races),
        spec.get("policy", "all"), bool(spec.get("class")), bool(spec.get("local")),
        bool(spec.get("shrink")), bool(spec.get("rating")), int(k),
    )
    cached = _FIT_DESIGN_CACHE.get(cache_key)
    if cached is not None:
        _FIT_DESIGN_CACHE.move_to_end(cache_key)
        bases, matrices, targets, mask = cached
    else:
        n_races = len(races)
        max_field = max(len(race["rows"]) for race in races)
        n_features = len(names)
        bases = np.zeros((n_races, max_field), dtype=float)
        matrices = np.zeros((n_races, max_field, n_features), dtype=float)
        targets = np.zeros((n_races, max_field), dtype=float)
        mask = np.zeros((n_races, max_field), dtype=bool)
        for i, race in enumerate(races):
            designs = [candidate_design(row, spec, k) for row in race["rows"]]
            n = len(designs)
            bases[i, :n] = [x[0] for x in designs]
            matrices[i, :n, :] = np.vstack([x[1] for x in designs])
            targets[i, :n] = target_vec(race)
            mask[i, :n] = True
        _FIT_DESIGN_CACHE[cache_key] = (bases, matrices, targets, mask)
        _FIT_DESIGN_CACHE.move_to_end(cache_key)
        while len(_FIT_DESIGN_CACHE) > _FIT_DESIGN_CACHE_MAX:
            _FIT_DESIGN_CACHE.popitem(last=False)

    def objective(theta):
        # Stable, vectorized conditional-logit objective and exact gradient.
        # Excluded padded entries have zero probability and zero target weight.
        scores = bases + np.einsum("rfd,d->rf", matrices, theta)
        z = scores / float(tau)
        z[~mask] = -np.inf
        log_norm = logsumexp(z, axis=1)
        z_safe = np.where(mask, z, 0.0)
        loss = l2 * float(theta @ theta)
        loss += float(np.sum(log_norm - np.sum(targets * z_safe, axis=1)))
        p = np.exp(z - log_norm[:, None])
        grad = 2.0 * l2 * theta
        grad += np.einsum("rfd,rf->d", matrices, p - targets) / float(tau)
        return loss, grad
    initial = np.zeros(len(names), dtype=float)
    result = minimize(
        objective, initial, jac=True, method="L-BFGS-B", bounds=bounds,
        options={"maxiter": 2000, "maxls": 50, "maxcor": 20, "ftol": 1e-12, "gtol": 1e-7},
    )
    if not result.success or not np.isfinite(result.fun):
        # Retry from the first solution (if finite) with a more conservative line search.
        retry_start = result.x if np.all(np.isfinite(result.x)) else initial
        retry = minimize(
            objective, retry_start, jac=True, method="L-BFGS-B", bounds=bounds,
            options={"maxiter": 4000, "maxls": 100, "maxcor": 10, "ftol": 1e-10, "gtol": 1e-6},
        )
        result = retry
    if not result.success or not np.isfinite(result.fun):
        grad = objective(result.x)[1] if np.all(np.isfinite(result.x)) else np.asarray([float("inf")])
        grad_norm = float(np.max(np.abs(grad))) if grad.size else 0.0
        raise RuntimeError(
            "coefficient fit did not converge: " + str(result.message)
            + f"; objective={result.fun}; projected_gradient_inf={grad_norm}"
        )
    return result.x

def tune_candidate(train, spec, is_b0=False, progress_label=None):
    if not train:
        raise ValueError("empty training split")
    last = train[-1]["_day"]
    months = sorted({(r["_day"].year, r["_day"].month) for r in train})
    months = months[-3:]
    if len(months) != 3:
        raise ValueError("need three inner validation months; got " + repr(months))
    combos = []
    has_coefficients = bool(spec.get("class") or spec.get("local") or spec.get("rating"))
    l2_values = L2_GRID if has_coefficients and not is_b0 else (0.01,)
    k_values = K_GRID if spec.get("shrink") and not is_b0 else (0,)
    tau_values = TAU_GRID
    total_combos = len(l2_values) * len(k_values) * len(tau_values)
    combo_index = 0
    for l2 in l2_values:
        for k in k_values:
            for tau in tau_values:
                combo_index += 1
                if progress_label and (combo_index == 1 or combo_index % 8 == 0 or combo_index == total_combos):
                    print(
                        f"[B2-progress] {progress_label}: grid {combo_index}/{total_combos} "
                        f"(l2={l2}, k={k}, tau={tau})",
                        flush=True,
                    )
                block_means = []
                for year, month in months:
                    start = dt.date(year, month, 1)
                    end = add_month(start, 1)
                    inner_train = [r for r in train if r["_day"] < start]
                    inner_val = [r for r in train if start <= r["_day"] < end]
                    if not inner_train or not inner_val:
                        continue
                    if is_b0:
                        scorer = b0_score
                    else:
                        try:
                            theta = fit_theta(inner_train, spec, l2, k, tau)
                        except RuntimeError as exc:
                            raise RuntimeError(
                                f"inner fit failed for candidate_spec={spec}, l2={l2}, k={k}, tau={tau}, "
                                f"block={year:04d}-{month:02d}: {exc}"
                            ) from exc
                        scorer = lambda row, t=theta, kk=k, ss=spec: raw_score(row, ss, t, kk)
                    block_scores = model_ll(inner_val, scorer, tau)
                    if len(block_scores):
                        block_means.append(float(np.mean(block_scores)))
                # All three preregistered expanding-window validation blocks are required;
                # average the three block means equally rather than weighting by race count.
                if len(block_means) != 3:
                    continue
                combos.append((float(np.mean(block_means)), l2, k, tau))
    if not combos:
        raise ValueError("no valid inner rolling-origin combinations")
    # Highest mean log likelihood; ties: larger L2, smaller k, tau nearest 1.0.
    combos.sort(key=lambda x: (-x[0], -x[1], x[2], abs(x[3] - 1.0), x[3]))
    best = combos[0]
    theta = np.zeros(0) if is_b0 else fit_theta(train, spec, best[1], best[2], best[3])
    return {"mean_inner_log_likelihood": best[0], "l2": best[1] if has_coefficients and not is_b0 else None, "k": best[2],
            "tau": best[3], "theta": theta.tolist(), "inner_months": [f"{y:04d}-{m:02d}" for y, m in months]}

def popularity_matrix(race):
    # Missing final popularity contributes no popularity feature; do not invent a rank.
    matrix = np.zeros((len(race["rows"]), 18), dtype=float)
    for i, row in enumerate(race["rows"]):
        try:
            value = int(row.get("pop"))
        except (TypeError, ValueError):
            continue
        if value >= 1:
            matrix[i, min(value, 18) - 1] = 1.0
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
    if not res.success or not np.isfinite(res.fun):
        raise RuntimeError("popularity model fit did not converge: " + str(res.message))
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

def candidate_data_coverage(runner_rows, policy):
    key = "local_excluded" if policy == "local_excluded" else "all"
    selected = [
        run
        for row in runner_rows
        for run in row.get("candidate_features", {}).get(key, {}).get("selected", [])
    ]
    jra = [run for run in selected if run.get("venue_type") == "JRA"]
    numeric_rating = sum(run.get("rating") is not None for run in jra)
    unknown_class = sum(run.get("class_category") == "UNKNOWN_JRA" for run in jra)
    return {
        "feature_runner_observations": len(runner_rows),
        "selected_history_run_observations": len(selected),
        "selected_jra_run_observations": len(jra),
        "selected_jra_numeric_rating_runs": numeric_rating,
        "selected_jra_rating_coverage": numeric_rating / len(jra) if jra else None,
        "selected_jra_unknown_class_runs": unknown_class,
        "selected_jra_unknown_class_rate": unknown_class / len(jra) if jra else None,
        "selected_unclassifiable_venue_runs": sum(run.get("venue_type") == "UNCLASSIFIABLE" for run in selected),
        "runner_observations_with_no_selected_prior_runs": sum(
            not row.get("candidate_features", {}).get(key, {}).get("selected_runs", 0)
            for row in runner_rows
        ),
    }


def coefficient_names(spec):
    if not isinstance(spec, dict):
        return []
    names = list(GAMMA_CATS) if spec.get("class") else []
    if spec.get("local"):
        names.append("eta_LOCAL")
    if spec.get("rating"):
        names.append("rho")
    return names


def evaluate_split(train, test, split_name):
    report = {
        "split": split_name,
        "train_races": len(train),
        "test_races": len(test),
        "train_runner_rows": sum(len(r["rows"]) for r in train),
        "test_runner_rows": sum(len(r["rows"]) for r in test),
        "candidates": {},
    }
    all_specs = {"B0-original": None, "B0-refit": None, **CANDIDATES}
    if not train or not test:
        report["status"] = "insufficient_train_or_test_races"
        return report

    pop_theta = fit_popularity(train)
    pop_test_ll = popularity_ll(test, pop_theta)
    pop_brier, pop_top1, pop_top3 = [], [], []
    for race in test:
        p = softmax(popularity_matrix(race) @ pop_theta, 1.0)
        y = target_vec(race)
        winner = int(np.argmax(y))
        order = np.argsort(-p)
        pop_brier.append(race_brier(race, p))
        pop_top1.append(float(order[0] == winner))
        pop_top3.append(float(winner in order[:min(3, len(order))]))
    uniform_ll = np.asarray([-math.log(len(r["rows"])) for r in test], dtype=float)
    report["popularity_only"] = {
        "mean_log_likelihood": float(pop_test_ll.mean()),
        "mean_brier": float(np.mean(pop_brier)),
        "top1_rate": float(np.mean(pop_top1)),
        "top3_rate": float(np.mean(pop_top3)),
        "delta_vs_uniform_95_ci": bootstrap_ci(pop_test_ll - uniform_ll),
    }
    uniform_brier = np.asarray([1.0 - 1.0 / len(r["rows"]) for r in test], dtype=float)
    report["uniform_all_horses_equal"] = {
        "mean_log_likelihood": float(uniform_ll.mean()),
        "mean_brier": float(uniform_brier.mean()),
    }
    b0_ll = None
    staged = {}
    for candidate_index, (name, spec) in enumerate(all_specs.items(), start=1):
        print(f"[B2-progress] {split_name}: candidate {candidate_index}/{len(all_specs)} start: {name}", flush=True)
        if name == "B0-original":
            params = {"l2": None, "k": 0, "tau": FIXED_B0_TAU, "theta": [], "inner_months": []}
            scorer = b0_score
        elif name == "B0-refit":
            params = tune_candidate(train, {"policy": "all", "class": False, "shrink": False, "local": False, "rating": False}, is_b0=True, progress_label=f"{split_name}/{name}")
            scorer = b0_score
        else:
            params = tune_candidate(train, spec, progress_label=f"{split_name}/{name}")
            theta = np.asarray(params["theta"], dtype=float)
            k = params["k"]
            scorer = lambda row, s=spec, t=theta, kk=k: raw_score(row, s, t, kk)

        summary = score_summary(test, scorer, params["tau"])
        raw_tau_summary = score_summary(test, scorer, 1.0)
        ll = summary.pop("_ll")
        raw_tau_ll = raw_tau_summary.pop("_ll")
        if name == "B0-original":
            b0_ll = ll
        scores = [[scorer(row) for row in race["rows"]] for race in test]
        probs = [softmax(s, params["tau"]).tolist() for s in scores]
        probs_tau_1 = [softmax(s, 1.0).tolist() for s in scores]
        # Final popularity is a retrospective benchmark only; it is not treated as pre-off information.
        extra_train = [[scorer(row) for row in race["rows"]] for race in train]
        combined_theta = fit_popularity(train, extra_train, l2=0.01)
        combined_ll = popularity_ll(test, combined_theta, scores)
        combined_delta = combined_ll - pop_test_ll
        delta_pop = ll - pop_test_ll
        delta_uniform = ll - uniform_ll
        policy = spec.get("policy", "all") if isinstance(spec, dict) else "all"
        staged[name] = {
            "params": {k: v for k, v in params.items() if k != "theta"},
            "coefficient_names": coefficient_names(spec),
            "coefficients": params.get("theta", []),
            "data_coverage_scope": "all runner observations in this fold's train and test sets",
            "data_coverage": candidate_data_coverage([row for race in train + test for row in race["rows"]], policy),
            **summary,
            "raw_score_tau_1_metrics": raw_tau_summary,
            "raw_score_tau_1_delta_vs_popularity_only": float((raw_tau_ll - pop_test_ll).mean()),
            "raw_score_tau_1_delta_vs_popularity_only_95_ci": bootstrap_ci(raw_tau_ll - pop_test_ll),
            "delta_vs_popularity_only": float(delta_pop.mean()),
            "delta_vs_popularity_only_95_ci": bootstrap_ci(delta_pop),
            "delta_vs_uniform_95_ci": bootstrap_ci(delta_uniform),
            "popularity_plus_candidate_mean_log_likelihood": float(combined_ll.mean()),
            "popularity_plus_candidate_delta_vs_popularity_only": float(combined_delta.mean()),
            "popularity_plus_candidate_delta_95_ci": bootstrap_ci(combined_delta),
            "predictions": [
                {"race_id": race.get("race_id"), "date": race["date"],
                 "horses": [{"hid": row.get("hid"), "num": row.get("num"),
                             "raw_score": scores[i][j],
                             "probability_tau_1": probs_tau_1[i][j],
                             "probability": probs[i][j]}
                            for j, row in enumerate(race["rows"])]}
                for i, race in enumerate(test)
            ],
        }

    b0_tau1_ll = score_summary(test, b0_score, 1.0)["_ll"]
    for name, record in staged.items():
        pred_by_race = {p["race_id"]: p for p in record["predictions"]}
        raw_tau1_ll = []
        for race in test:
            pred = pred_by_race.get(race.get("race_id"))
            if pred is None:
                raw_tau1_ll.append(float("nan"))
                continue
            prob_by_hid = {str(h["hid"]): h["probability_tau_1"] for h in pred["horses"]}
            raw_tau1_ll.append(sum(
                float(row.get("winner_share", 0.0)) * math.log(max(prob_by_hid.get(str(row.get("hid")), 0.0), 1e-15))
                for row in race["rows"]
            ))
        raw_d = np.asarray(raw_tau1_ll, dtype=float) - b0_tau1_ll
        record["raw_score_tau_1_delta_vs_B0_tau_1"] = float(np.nanmean(raw_d))
        record["raw_score_tau_1_delta_vs_B0_tau_1_95_ci"] = bootstrap_ci(raw_d[np.isfinite(raw_d)])
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
    ap.add_argument("--history-manifest", type=Path)
    ap.add_argument("--history-audit", type=Path)
    ap.add_argument("--race-reconciliation", type=Path)
    ap.add_argument("--prep-script", type=Path, default=Path("research/factor-validation/b2_dataset_prep.py"))
    ap.add_argument("--features-script", type=Path, default=Path("research/factor-validation/b2_features.py"))
    args = ap.parse_args()
    races = load_races(args.input)
    runner_rows = [row for race in races for row in race["rows"]]
    selected_runs = [run for row in runner_rows for run in row.get("candidate_features", {}).get("all", {}).get("selected", [])]
    jra_selected = [run for run in selected_runs if run.get("venue_type") == "JRA"]
    rating_observed = sum(run.get("rating") is not None for run in jra_selected)
    unknown_jra = sum(run.get("class_category") == "UNKNOWN_JRA" for run in jra_selected)
    unclassifiable_venues = sum(run.get("venue_type") == "UNCLASSIFIABLE" for run in selected_runs)
    no_prior_history_rows = sum(int(row.get("prior_runs", 0) or 0) == 0 for row in runner_rows)
    missing_popularity_rows = sum(row.get("pop") in (None, "") for row in runner_rows)
    history_manifest = json.loads(args.history_manifest.read_text(encoding="utf-8")) if args.history_manifest else None
    history_audit = json.loads(args.history_audit.read_text(encoding="utf-8")) if args.history_audit else None
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
        "prep_implementation": str(args.prep_script), "prep_implementation_sha256": sha(args.prep_script),
        "features_implementation": str(args.features_script), "features_implementation_sha256": sha(args.features_script),
        "venue_alias_builder_implementation_sha256": sha(Path("research/factor-validation/build_b2_venue_aliases.py")),
        "race_reconciliation_implementation_sha256": sha(Path("research/factor-validation/compare_b2_race_datasets.py")),
        "race_dataset_audit_implementation_sha256": sha(Path("scripts/audit_race_dataset.py")),
        "horse_history_audit_implementation_sha256": sha(Path("scripts/audit_b2_horse_pages.py")),
        "history_manifest": str(args.history_manifest) if args.history_manifest else None,
        "history_manifest_sha256": sha(args.history_manifest) if args.history_manifest else None,
        "history_audit": str(args.history_audit) if args.history_audit else None,
        "history_audit_sha256": sha(args.history_audit) if args.history_audit else None,
        "history_audit_summary": ({k: history_audit.get(k) for k in ("status", "requested", "succeeded", "missing", "success_rate", "missing_rate", "output_horse_count", "total_runs", "zero_run_horses", "zero_run_horse_rate", "horses_with_exactly_four_runs_potentially_limited", "horses_with_one_to_four_runs", "compressed_sha256", "uncompressed_sha256")} if history_audit else None),
        "history_manifest_summary": ({k: history_manifest.get(k) for k in ("started_at_jst", "finished_at_jst", "requested", "succeeded", "missing", "horses_with_zero_runs", "total_runs", "cnames_sha256", "horses_json_sha256", "horses_json_gz_sha256", "script_sha256")} if history_manifest else None),
        "race_reconciliation": str(args.race_reconciliation) if args.race_reconciliation else None,
        "race_reconciliation_sha256": sha(args.race_reconciliation) if args.race_reconciliation else None,
        "races_loaded": len(races),
        "runner_rows_loaded": len(runner_rows),
        "runner_rows_with_no_usable_prior_history": no_prior_history_rows,
        "runner_rows_with_no_usable_prior_history_rate": no_prior_history_rows / len(runner_rows) if runner_rows else None,
        "runner_rows_missing_final_popularity": missing_popularity_rows,
        "runner_rows_missing_final_popularity_rate": missing_popularity_rows / len(runner_rows) if runner_rows else None,
        "selected_history_run_observations": len(selected_runs),
        "selected_jra_run_observations": len(jra_selected),
        "selected_jra_runs_with_numeric_rating": rating_observed,
        "selected_jra_rating_coverage": rating_observed / len(jra_selected) if jra_selected else None,
        "selected_jra_runs_unknown_class": unknown_jra,
        "selected_jra_unknown_class_rate": unknown_jra / len(jra_selected) if jra_selected else None,
        "selected_runs_with_unclassifiable_venue": unclassifiable_venues,

        "folds": reports,
        "forward_validation_required_from": "2026-10-25",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_digest = sha(args.out)
    output_sidecar = args.out.with_suffix(".sha256")
    output_sidecar.write_text(f"{output_digest}  {args.out.name}\n", encoding="ascii")
    print(json.dumps({"output": str(args.out), "output_sha256": output_digest,
                      "output_sha256_sidecar": str(output_sidecar),
                      "metadata": {k: v for k, v in payload.items() if k != "folds"}}, ensure_ascii=False, indent=2))
    for report in reports:
        print(report["split"], "train", report["train_races"], "test", report["test_races"])
        for name, result in report["candidates"].items():
            print(name, "LL", result["mean_log_likelihood"], "delta-pop", result["delta_vs_popularity_only"],
                  "combined CI", result["popularity_plus_candidate_delta_95_ci"])
if __name__ == "__main__":
    main()
