#!/usr/bin/env python3
"""Sample-size, boundary and futility calculations for the B2 forward-validation proposal.

Everything is a normal approximation for the mean of per-race log-likelihood differences:
  Z = mean / (sigma / sqrt(n_eff)),  one-sided, alpha = 0.025.
Inputs are explicit command-line values; nothing here reads prediction data.
Group-sequential part: K equally spaced looks, O'Brien-Fleming-type boundaries c*sqrt(K/k).
"""
import argparse, json, math
import numpy as np
from statistics import NormalDist

N = NormalDist()
z = N.inv_cdf

def n_required(delta, sigma, power, alpha=0.025, deff=1.0):
    return deff * ((z(1 - alpha) + z(power)) * sigma / delta) ** 2

def obf_constant(K, alpha, paths=2_000_000, seed=7):
    """Find c so that P(any Z_k >= c*sqrt(K/k)) = alpha under H0 (Monte Carlo, equal information)."""
    rng = np.random.default_rng(seed)
    inc = rng.standard_normal((paths, K))
    s = np.cumsum(inc, axis=1)
    zk = s / np.sqrt(np.arange(1, K + 1))
    shape = np.sqrt(K / np.arange(1, K + 1))
    lo, hi = 1.5, 3.0
    for _ in range(40):
        c = (lo + hi) / 2
        rej = (zk >= c * shape).any(axis=1).mean()
        lo, hi = (c, hi) if rej > alpha else (lo, c)
    return (lo + hi) / 2, shape

def simulate(K, bounds, theta_total, futility_z=None, paths=1_000_000, seed=11):
    """theta_total = expected Z at full information. Returns P(reject at some look), P(stop early for futility)."""
    rng = np.random.default_rng(seed)
    inc = rng.standard_normal((paths, K)) + theta_total / math.sqrt(K)
    s = np.cumsum(inc, axis=1)
    zk = s / np.sqrt(np.arange(1, K + 1))
    alive = np.ones(paths, bool); rej = np.zeros(paths, bool); fut = np.zeros(paths, bool)
    for k in range(K):
        hit = alive & (zk[:, k] >= bounds[k]); rej |= hit; alive &= ~hit
        if futility_z is not None and k < K - 1 and futility_z[k] is not None:
            f = alive & (zk[:, k] < futility_z[k]); fut |= f; alive &= ~f
    return float(rej.mean()), float(fut.mean())

def conditional_power_threshold(t, c_final, theta_total, cp_floor):
    """Z threshold at information fraction t below which CP(theta) < cp_floor (final boundary c_final)."""
    B = c_final - theta_total * (1 - t) - z(1 - cp_floor) * math.sqrt(1 - t)
    return B / math.sqrt(t)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sigma", type=float, default=0.17)
    ap.add_argument("--deff", type=float, default=1.0, help="design effect for day clustering (1 = independent races)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    out = {"inputs": {"sigma": a.sigma, "alpha_one_sided": 0.025, "design_effect": a.deff,
                      "approximation": "normal, independent races unless design_effect != 1"}}
    deltas = [0.003, 0.005, 0.007, 0.010]
    out["n_required"] = {f"power{int(p*100)}": {str(d): round(n_required(d, a.sigma, p, deff=a.deff)) for d in deltas} for p in (0.7, 0.8, 0.9)}
    K = 3
    c, shape = obf_constant(K, 0.025)
    bounds = [c * s for s in shape]
    out["obf_K3"] = {"constant": round(c, 4), "boundaries_z": [round(b, 3) for b in bounds],
                     "note": "one-sided Z-statistic boundaries; not ordinary 95% CI limits"}
    # type I and power for the sequential design, with total n chosen as fixed-sample n for power 80% at delta
    seq = {}
    for d in deltas:
        n_fixed = n_required(d, a.sigma, 0.8, deff=a.deff)
        theta = d / a.sigma * math.sqrt(n_fixed / a.deff)
        p_rej, _ = simulate(K, bounds, theta)
        seq[str(d)] = {"n_fixed_power80": round(n_fixed), "sequential_power_at_that_n": round(p_rej, 3)}
        # inflation: smallest n giving 80% sequential power
        lo, hi = n_fixed, n_fixed * 1.2
        for _ in range(14):
            mid = (lo + hi) / 2
            th = d / a.sigma * math.sqrt(mid / a.deff)
            if simulate(K, bounds, th, paths=300_000)[0] < 0.8: lo = mid
            else: hi = mid
        seq[str(d)]["n_sequential_power80"] = round(hi)
        seq[str(d)]["inflation_factor"] = round(hi / n_fixed, 3)
    out["sequential_power"] = seq
    p0, _ = simulate(K, bounds, 0.0)
    out["type_I_error_check"] = round(p0, 4)
    # futility at look 2 via conditional power under the design alternative
    d = 0.007
    n_total = n_required(d, a.sigma, 0.7, deff=a.deff)
    theta = d / a.sigma * math.sqrt(n_total / a.deff)
    fz = conditional_power_threshold(2 / 3, bounds[2], theta, 0.10)
    p_rej, p_fut = simulate(K, bounds, theta, futility_z=[None, fz, None])
    p_rej0, p_fut0 = simulate(K, bounds, 0.0, futility_z=[None, fz, None])
    out["futility_look2"] = {
        "alternative_delta": d, "n_total": round(n_total), "theta_total": round(theta, 3),
        "rule": "stop at look 2 if Z_2 < threshold (conditional power at the design alternative < 10%, non-binding)",
        "z_threshold": round(fz, 3),
        "mean_difference_threshold_at_look2": round(fz * a.sigma / math.sqrt((2 / 3) * n_total / a.deff), 5),
        "power_with_futility": round(p_rej, 3), "p_stop_futility_under_alternative": round(p_fut, 3),
        "p_stop_futility_under_null": round(p_fut0, 3),
    }
    txt = json.dumps(out, ensure_ascii=False, indent=2)
    print(txt)
    if a.out:
        open(a.out, "w").write(txt + "\n")
