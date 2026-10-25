import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_win5_model_comparison import evaluate_model, read_results  # noqa: E402

DATE = "2026-10-25"


class Edges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def run_model(self, probs, winner="1", scratched="", fields=("date", "leg", "horse_number", "horse_name", "p"), drop_date=False, **kw):
        rows = [{"date": DATE, "leg": str(l), "horse_number": str(h), "horse_name": f"H{h}", "p": p}
                for l in range(1, 6) for h, p in probs]
        if drop_date:
            fields = [f for f in fields if f != "date"]
            rows = [{k: v for k, v in r.items() if k != "date"} for r in rows]
        with (self.d / "p.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(fields)); w.writeheader(); w.writerows(rows)
        with (self.d / "r.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "leg", "winner_no", "scratched_nos"]); w.writeheader()
            w.writerows([{"date": DATE, "leg": str(l), "winner_no": winner, "scratched_nos": scratched if l == 1 else ""} for l in range(1, 6)])
        winners, sc = read_results(self.d / "r.csv", DATE)
        return evaluate_model(f"M|{self.d / 'p.csv'}|p|leg|horse_number", DATE, winners, sc, **kw)

    def test_scratched_horse_already_absent_from_prediction_is_not_fatal(self):
        r = self.run_model([(1, 50), (2, 30), (3, 20)], scratched="9")
        self.assertEqual(r["top1_hits"], 5)
        self.assertTrue(any("not in the prediction file" in w for w in r["warnings"]))

    def test_scratched_horse_in_prediction_is_removed_and_renormalised(self):
        r = self.run_model([(1, 50), (2, 30), (3, 20)], scratched="3")
        leg1 = r["details"][0]
        self.assertEqual(leg1["field_size"], 2)
        self.assertAlmostEqual(leg1["winner_probability_pct"], 62.5, places=3)

    def test_winner_scratched_is_still_rejected(self):
        with self.assertRaises(ValueError):
            self.run_model([(1, 50), (2, 30), (3, 20)], scratched="1")

    def test_top1_tie_is_reported(self):
        r = self.run_model([(1, 40), (2, 40), (3, 20)], winner="2")
        self.assertTrue(any("tie for Top-1" in w for w in r["warnings"]))
        self.assertEqual(r["top1_hits"], 0)

    def test_top3_boundary_tie_is_reported(self):
        r = self.run_model([(1, 40), (2, 25), (3, 15), (4, 15), (5, 5)])
        self.assertTrue(any("Top-3 boundary" in w for w in r["warnings"]))

    def test_zero_winner_probability_is_floored_and_warned(self):
        r = self.run_model([(1, 50), (2, 50), (3, 0)], winner="3")
        self.assertTrue(any("below the log-loss floor" in w for w in r["warnings"]))
        self.assertGreater(r["mean_winner_log_loss"], 30)

    def test_log_loss_floor_is_configurable(self):
        r = self.run_model([(1, 50), (2, 50), (3, 0)], winner="3", log_loss_floor=1e-6)
        self.assertLess(r["mean_winner_log_loss"], 15)

    def test_prediction_without_date_column_explains_why(self):
        with self.assertRaises(ValueError):
            self.run_model([(1, 50), (2, 30), (3, 20)], drop_date=True)

    def test_prediction_for_a_different_date_lists_dates_present(self):
        rows = [{"date": "2026-10-24", "leg": str(l), "horse_number": "1", "horse_name": "x", "p": 100} for l in range(1, 6)]
        with (self.d / "p.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "leg", "horse_number", "horse_name", "p"]); w.writeheader(); w.writerows(rows)
        with (self.d / "r.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "leg", "winner_no", "scratched_nos"]); w.writeheader()
            w.writerows([{"date": DATE, "leg": str(l), "winner_no": "1", "scratched_nos": ""} for l in range(1, 6)])
        winners, sc = read_results(self.d / "r.csv", DATE)
        with self.assertRaises(ValueError) as cm:
            evaluate_model(f"M|{self.d / 'p.csv'}|p|leg|horse_number", DATE, winners, sc)
        self.assertIn("2026-10-24", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
