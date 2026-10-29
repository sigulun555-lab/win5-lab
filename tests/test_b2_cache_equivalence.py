"""Regression tests for B2 fit-design caching.

The same objective and gradient must be produced whether design arrays are
reused from cache or rebuilt for each fit.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

MODULE_PATH = Path(__file__).resolve().parents[1] / "research" / "factor-validation" / "fit_b2_candidates.py"
SPEC = importlib.util.spec_from_file_location("fit_b2_candidates_under_test", MODULE_PATH)
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


def synthetic_races():
    races = []
    for ri in range(3):
        rows = []
        for j in range(5):
            class_features = {cat: float((j + ri + idx) % 3 == 0)
                              for idx, cat in enumerate(FIT.GAMMA_CATS)}
            base = {
                "base_score": (j - 2) * 0.17 + ri * 0.03,
                "jra_runs_selected": j + ri,
                "class_features": class_features,
                "local_feature": float(j % 2),
                "rating_delta": (j - 2) * 0.1,
            }
            rows.append({
                "winner_share": 1.0 if j == (ri % 5) else 0.0,
                "candidate_features": {"all": base, "local_excluded": base},
            })
        races.append({"rows": rows})
    return races


class FitDesignCacheEquivalenceTests(unittest.TestCase):
    def setUp(self):
        FIT._FIT_DESIGN_CACHE.clear()
        self.old_max = FIT._FIT_DESIGN_CACHE_MAX

    def tearDown(self):
        FIT._FIT_DESIGN_CACHE.clear()
        FIT._FIT_DESIGN_CACHE_MAX = self.old_max

    def capture_objective(self, cache_max):
        FIT._FIT_DESIGN_CACHE.clear()
        FIT._FIT_DESIGN_CACHE_MAX = cache_max
        observed = []

        def fake_minimize(fun, x0, **kwargs):
            x = np.linspace(-0.15, 0.15, len(x0), dtype=float)
            loss, grad = fun(x)
            observed.append((float(loss), np.array(grad, dtype=float)))
            return SimpleNamespace(x=x, success=True, fun=loss, message="test stub")

        spec = {"policy": "all", "class": True, "shrink": True,
                "local": True, "rating": True}
        with patch.object(FIT, "minimize", side_effect=fake_minimize):
            FIT.fit_theta(synthetic_races(), spec, l2=0.01, k=2, tau=0.75)
            # Repeat on the same race objects to exercise the cache-hit path.
            races = synthetic_races()
            FIT.fit_theta(races, spec, l2=0.01, k=2, tau=0.75)
        return observed

    def test_cached_and_rebuilt_designs_have_identical_objective_and_gradient(self):
        # Use identical race objects across both calls so the cache key matches.
        races = synthetic_races()
        observed = []

        def run_with_cache(cache_max):
            FIT._FIT_DESIGN_CACHE.clear()
            FIT._FIT_DESIGN_CACHE_MAX = cache_max
            calls = []

            def fake_minimize(fun, x0, **kwargs):
                x = np.linspace(-0.15, 0.15, len(x0), dtype=float)
                loss, grad = fun(x)
                calls.append((float(loss), np.array(grad, dtype=float)))
                return SimpleNamespace(x=x, success=True, fun=loss, message="test stub")

            with patch.object(FIT, "minimize", side_effect=fake_minimize):
                FIT.fit_theta(races, {"policy": "all", "class": True, "shrink": True,
                                      "local": True, "rating": True}, 0.01, 2, 0.75)
            return calls[0]

        uncached = run_with_cache(0)
        cached = run_with_cache(6)
        self.assertAlmostEqual(uncached[0], cached[0], places=12)
        np.testing.assert_allclose(uncached[1], cached[1], rtol=0, atol=1e-12)


if __name__ == "__main__":
    unittest.main()
