"""Tests for the B2 real-data benchmark numeric comparator."""
import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_b2_benchmark_outputs.py"
SPEC = importlib.util.spec_from_file_location("compare_b2_benchmark_outputs", MODULE_PATH)
COMPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPARE)


class BenchmarkComparisonToleranceTests(unittest.TestCase):
    def test_accepts_expected_sub_1e_8_float_roundoff(self):
        diffs = []
        COMPARE.close(
            {"metric": -2.0530269437425503},
            {"metric": -2.0530269439981153},
            1e-8,
            diffs,
        )
        self.assertEqual(diffs, [])

    def test_rejects_differences_above_tolerance(self):
        diffs = []
        COMPARE.close({"prediction": 0.5}, {"prediction": 0.500001}, 1e-8, diffs)
        self.assertEqual(len(diffs), 1)
        self.assertIn("$.prediction", diffs[0])

    def test_still_rejects_structural_mismatches(self):
        diffs = []
        COMPARE.close({"a": 1.0}, {"b": 1.0}, 1e-8, diffs)
        self.assertEqual(len(diffs), 1)
        self.assertIn("key sets differ", diffs[0])


if __name__ == "__main__":
    unittest.main()
