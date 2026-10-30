"""Regression tests for B2 fit-design caching.

The same objective and gradient must be produced when design arrays are
rebuilt versus reused from the bounded cache.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

MODULE_PATH = Path(__file__).resolve().parents[1] / "fit_b2_candidates.py"
SPEC = importlib.util.spec_from_file_location("fit_b2_candidates_under_test", MODULE_PATH)
FIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIT)


def synthetic_races():
    races = []
    for ri in range(3):
        rows = []
        for j in range(5):
            class_features = {
                cat: float((j + ri + idx) % 3 == 0)
                for idx, cat in enumerate(FIT.GAMMA_CATS)
            }
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
        races.append({"race_id": f"synthetic-{ri}", "rows": rows})
    return races


class FitDesignCacheEquivalenceTests(unittest.TestCase):
    def setUp(self):
        FIT._FIT_DESIGN_CACHE.clear()
        self.old_max = FIT._FIT_DESIGN_CACHE_MAX

    def tearDown(self):
        FIT._FIT_DESIGN_CACHE.clear()
        FIT._FIT_DESIGN_CACHE_MAX = self.old_max

    def test_cached_and_rebuilt_designs_have_identical_objective_and_gradient(self):
        races = synthetic_races()
        model_spec = {
            "policy": "all", "class": True, "shrink": True,
            "local": True, "rating": True,
        }

        def run_with_cache(cache_max, repeat):
            FIT._FIT_DESIGN_CACHE.clear()
            FIT._FIT_DESIGN_CACHE_MAX = cache_max
            calls = []

            def fake_minimize(fun, x0, **kwargs):
                x = np.linspace(-0.15, 0.15, len(x0), dtype=float)
                loss, grad = fun(x)
                calls.append((float(loss), np.array(grad, dtype=float)))
                return SimpleNamespace(x=x, success=True, fun=loss, message="test stub")

            with patch.object(FIT, "minimize", side_effect=fake_minimize):
                for _ in range(repeat):
                    FIT.fit_theta(races, model_spec, 0.01, 2, 0.75)
            return calls

        uncached = run_with_cache(cache_max=0, repeat=1)[0]
        cached_calls = run_with_cache(cache_max=24, repeat=2)
        self.assertEqual(len(cached_calls), 2)
        # First cached call builds arrays; second call must reuse the same arrays.
        np.testing.assert_allclose(cached_calls[0][0], cached_calls[1][0], rtol=0, atol=1e-12)
        np.testing.assert_allclose(cached_calls[0][1], cached_calls[1][1], rtol=0, atol=1e-12)
        np.testing.assert_allclose(uncached[0], cached_calls[1][0], rtol=0, atol=1e-12)
        np.testing.assert_allclose(uncached[1], cached_calls[1][1], rtol=0, atol=1e-12)

    def test_cache_key_changes_for_k_race_content_and_candidate_spec(self):
        races = synthetic_races()
        spec = {
            "policy": "all", "class": True, "shrink": True,
            "local": True, "rating": True,
        }
        base = FIT._fit_design_cache_key(races, spec, 2)
        self.assertNotEqual(base, FIT._fit_design_cache_key(races, spec, 3))
        changed_races = synthetic_races()
        changed_races[0]["race_id"] += "-different"
        self.assertNotEqual(base, FIT._fit_design_cache_key(changed_races, spec, 2))
        changed_spec = {**spec, "policy": "local_excluded"}
        self.assertNotEqual(base, FIT._fit_design_cache_key(races, changed_spec, 2))

    def test_cached_design_arrays_are_read_only(self):
        races = synthetic_races()
        model_spec = {
            "policy": "all", "class": True, "shrink": True,
            "local": True, "rating": True,
        }

        def fake_minimize(fun, x0, **kwargs):
            loss, grad = fun(np.zeros_like(x0))
            return SimpleNamespace(x=np.zeros_like(x0), success=True, fun=loss, message="test stub")

        with patch.object(FIT, "minimize", side_effect=fake_minimize):
            FIT.fit_theta(races, model_spec, 0.01, 2, 0.75)
        self.assertEqual(len(FIT._FIT_DESIGN_CACHE), 1)
        arrays = next(iter(FIT._FIT_DESIGN_CACHE.values()))
        for array in arrays:
            self.assertFalse(array.flags.writeable)
            with self.assertRaises(ValueError):
                array.flat[0] = array.flat[0]

    def test_candidate_coverage_uses_nested_selected_runs_not_top_level_prior_runs(self):
        rows = [{
            "prior_runs": 99,
            "candidate_features": {
                "all": {
                    "selected_runs": 1,
                    "selected": [{
                        "venue_type": "JRA",
                        "rating": 88.0,
                        "class_category": "MAIDEN",
                    }],
                },
                "local_excluded": {"selected_runs": 0, "selected": []},
            },
        }]
        coverage = FIT.candidate_data_coverage(rows, "all")
        self.assertEqual(coverage["selected_history_run_observations"], 1)
        self.assertEqual(coverage["runner_observations_with_no_selected_prior_runs"], 0)
        self.assertEqual(coverage["selected_jra_numeric_rating_runs"], 1)


if __name__ == "__main__":
    unittest.main()
