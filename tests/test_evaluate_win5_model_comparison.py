import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_win5_model_comparison import evaluate_model, read_results  # noqa: E402

DATE = "2026-10-25"


def write_csv(path, fields, data):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(data)


class CommonEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.pred = self.d / "pred.csv"
        self.res = self.d / "results.csv"
        self.fields = ["date", "leg", "horse_number", "horse_name", "prob_pct"]
        self.pred_rows = [
            {"date": DATE, "leg": str(leg), "horse_number": str(h), "horse_name": f"H{h}", "prob_pct": p}
            for leg in range(1, 6)
            for h, p in ((1, 50), (2, 30), (3, 20))
        ]
        self.result_rows = [
            {"date": DATE, "leg": str(leg), "winner_no": "1", "scratched_nos": ""}
            for leg in range(1, 6)
        ]
        write_csv(self.pred, self.fields, self.pred_rows)
        write_csv(self.res, ["date", "leg", "winner_no", "scratched_nos"], self.result_rows)

    def evaluate(self):
        winners, scratched = read_results(self.res, DATE)
        return evaluate_model(
            f"GPT|{self.pred}|prob_pct|leg|horse_number", DATE, winners, scratched
        )

    def test_same_code_returns_expected_top1_and_scores(self):
        result = self.evaluate()
        self.assertEqual(result["top1_hits"], 5)
        self.assertEqual(result["top3_hits"], 5)
        self.assertEqual(result["legs"], 5)
        self.assertEqual(result["horses_scored"], 15)
        self.assertLess(result["mean_winner_log_loss"], result["uniform_baseline"]["mean_winner_log_loss"])

    def test_decimal_formatted_ids_are_accepted(self):
        for row in self.pred_rows:
            row["leg"] = f'{int(row["leg"])}.00000'
            row["horse_number"] = f'{int(row["horse_number"])}.00000'
        write_csv(self.pred, self.fields, self.pred_rows)
        result = self.evaluate()
        self.assertEqual(result["top1_hits"], 5)

    def test_duplicate_horse_is_rejected(self):
        self.pred_rows.append(dict(self.pred_rows[0]))
        write_csv(self.pred, self.fields, self.pred_rows)
        with self.assertRaisesRegex(ValueError, "duplicate horse"):
            self.evaluate()

    def test_probability_sum_is_checked(self):
        for row in self.pred_rows:
            if row["leg"] == "2" and row["horse_number"] == "1":
                row["prob_pct"] = 40
        write_csv(self.pred, self.fields, self.pred_rows)
        with self.assertRaisesRegex(ValueError, "sum to"):
            self.evaluate()

    def test_missing_winner_is_rejected(self):
        for row in self.result_rows:
            if row["leg"] == "3":
                row["winner_no"] = "99"
        write_csv(self.res, ["date", "leg", "winner_no", "scratched_nos"], self.result_rows)
        with self.assertRaisesRegex(ValueError, "winner 99 missing"):
            self.evaluate()

    def test_scratch_is_removed_and_probabilities_renormalised(self):
        self.result_rows[0]["scratched_nos"] = "3"
        write_csv(self.res, ["date", "leg", "winner_no", "scratched_nos"], self.result_rows)
        result = self.evaluate()
        self.assertEqual(result["details"][0]["field_size"], 2)
        self.assertEqual(result["details"][0]["scratched_removed"], [3])

    def test_duplicate_result_leg_is_rejected(self):
        self.result_rows.append(dict(self.result_rows[0]))
        write_csv(self.res, ["date", "leg", "winner_no", "scratched_nos"], self.result_rows)
        with self.assertRaisesRegex(ValueError, "Duplicate result"):
            read_results(self.res, DATE)


if __name__ == "__main__":
    unittest.main()
