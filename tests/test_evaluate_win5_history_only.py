import csv
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_win5_history_only import evaluate  # noqa: E402

COL = "gpt_exploratory_win_probability_pct"
DATE = "2026-10-25"


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def make_preds(probs_by_leg, fmt=str):
    """probs_by_leg: {leg: [(horse_no, pct), ...]}"""
    rows = []
    for leg, items in probs_by_leg.items():
        for no, pct in items:
            rows.append({"date": DATE, "leg": fmt(leg), "horse_number": fmt(no),
                         "horse_name": f"H{no}", "race_name": f"R{leg}", COL: str(pct)})
    return ["date", "leg", "horse_number", "horse_name", "race_name", COL], rows


def make_results(winners, extra=None):
    rows = [{"date": DATE, "leg": str(leg), "winner_no": str(w), "winner_name": f"H{w}"}
            for leg, w in winners.items()]
    if extra:
        rows.extend(extra)
    return ["date", "leg", "winner_no", "winner_name", "scratched_nos"], rows


STD = {leg: [(1, 50), (2, 30), (3, 20)] for leg in range(1, 6)}


class Base(unittest.TestCase):
    def run_eval(self, preds=None, results=None, pred_fmt=str, **kw):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(preds or STD, pred_fmt)
            rf, rr = make_results(results or {1: 1, 2: 1, 3: 1, 4: 1, 5: 1})
            write_csv(d / "p.csv", pf, pr)
            write_csv(d / "r.csv", rf, rr)
            return evaluate(d / "p.csv", d / "r.csv", **kw)


class Metrics(Base):
    def test_hand_computed_values(self):
        # winners: leg1..5 -> 1,1,1,2,3 with probs 50/30/20
        got = self.run_eval(results={1: 1, 2: 1, 3: 1, 4: 2, 5: 3})
        self.assertEqual(got["top1_hits"], 3)
        self.assertEqual(got["top3_hits"], 5)
        ll = (3 * -math.log(0.5) + -math.log(0.3) + -math.log(0.2)) / 5
        self.assertAlmostEqual(got["mean_winner_log_loss"], ll, places=5)
        sq_win1 = (0.5 - 1) ** 2 + 0.3 ** 2 + 0.2 ** 2
        sq_win2 = 0.5 ** 2 + (0.3 - 1) ** 2 + 0.2 ** 2
        sq_win3 = 0.5 ** 2 + 0.3 ** 2 + (0.2 - 1) ** 2
        total = 3 * sq_win1 + sq_win2 + sq_win3
        self.assertAlmostEqual(got["multiclass_brier_race_sum_mean"], total / 5, places=5)
        self.assertAlmostEqual(got["multiclass_brier_per_horse"], total / 15, places=6)
        self.assertAlmostEqual(got["brier_per_horse_race_mean"], total / 5 / 3, places=6)

    def test_uniform_baseline(self):
        got = self.run_eval()
        self.assertAlmostEqual(got["uniform_baseline"]["mean_winner_log_loss"], math.log(3), places=5)
        # uniform over 3 horses, one winner: (2/3)^2 + 2*(1/3)^2 = 2/3
        self.assertAlmostEqual(got["uniform_baseline"]["multiclass_brier_race_sum_mean"], 2 / 3, places=5)

    def test_brier_pooled_vs_race_mean_differ_for_unequal_fields(self):
        preds = dict(STD)
        preds[5] = [(i, 10) for i in range(1, 11)]  # 10 horses, uniform
        got = self.run_eval(preds=preds, results={1: 1, 2: 1, 3: 1, 4: 1, 5: 1})
        self.assertNotAlmostEqual(got["multiclass_brier_per_horse"], got["brier_per_horse_race_mean"], places=4)
        self.assertEqual(got["horses_scored"], 4 * 3 + 10)

    def test_values_match_existing_evaluate_win5_predictions_definition(self):
        # pooled definition == scripts/evaluate_win5_predictions.py (sum / total horses)
        got = self.run_eval(results={1: 2, 2: 2, 3: 2, 4: 2, 5: 2})
        sq = 0.5 ** 2 + (0.3 - 1) ** 2 + 0.2 ** 2
        self.assertAlmostEqual(got["multiclass_brier_per_horse"], sq / 3, places=6)


class Parsing(Base):
    def test_float_formatted_ids_like_the_real_csv(self):
        got = self.run_eval(pred_fmt=lambda x: f"{x}.00000")
        self.assertEqual(got["top1_hits"], 5)

    def test_zero_padded_ids(self):
        got = self.run_eval(pred_fmt=lambda x: f"{x:02d}")
        self.assertEqual(got["top1_hits"], 5)

    def test_real_prediction_csv_header_is_accepted(self):
        path = ROOT / "data/win5_joint/2026-10-25/gpt-exploratory-history-only-probabilities.csv"
        if not path.exists():
            self.skipTest("prediction snapshot not present")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            with path.open(newline="", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            win = {}
            for r in rows:
                win.setdefault(int(float(r["leg"])), int(float(r["horse_number"])))
            rf, rr = make_results(win)
            write_csv(d / "r.csv", rf, rr)
            got = evaluate(path, d / "r.csv")
            self.assertEqual(got["races"], 5)
            self.assertEqual(got["horses_scored"], len(rows))

    def test_alternate_column_names(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            rows = [{"date": DATE, "win5_order": str(leg), "horse_no": str(no), "horse_name": f"H{no}", "model_prob_pct": str(p)}
                    for leg, items in STD.items() for no, p in items]
            write_csv(d / "p.csv", ["date", "win5_order", "horse_no", "horse_name", "model_prob_pct"], rows)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            write_csv(d / "r.csv", rf, rr)
            got = evaluate(d / "p.csv", d / "r.csv", probability_column="model_prob_pct")
            self.assertEqual(got["top1_hits"], 5)


class Rejections(Base):
    def assertRejects(self, **kw):
        with self.assertRaises(ValueError):
            self.run_eval(**kw)

    def test_duplicate_horse_number(self):
        preds = dict(STD)
        preds[2] = [(1, 50), (1, 30), (3, 20)]
        self.assertRejects(preds=preds)

    def test_missing_leg_in_predictions(self):
        preds = {k: v for k, v in STD.items() if k != 4}
        self.assertRejects(preds=preds)

    def test_missing_leg_in_results(self):
        self.assertRejects(results={1: 1, 2: 1, 3: 1, 4: 1})

    def test_probability_sum_too_low(self):
        preds = dict(STD)
        preds[3] = [(1, 40), (2, 30), (3, 20)]
        self.assertRejects(preds=preds)

    def test_probability_sum_too_high(self):
        preds = dict(STD)
        preds[3] = [(1, 60), (2, 30), (3, 20)]
        self.assertRejects(preds=preds)

    def test_winner_not_in_field(self):
        self.assertRejects(results={1: 1, 2: 1, 3: 99, 4: 1, 5: 1})

    def test_negative_or_over_100_probability(self):
        preds = dict(STD)
        preds[1] = [(1, 120), (2, -10), (3, -10)]
        self.assertRejects(preds=preds)

    def test_empty_probability_cell(self):
        preds = dict(STD)
        preds[1] = [(1, ""), (2, 30), (3, 20)]
        self.assertRejects(preds=preds)

    def test_nan_probability(self):
        preds = dict(STD)
        preds[1] = [(1, "nan"), (2, 30), (3, 20)]
        self.assertRejects(preds=preds)

    def test_unfilled_result_template(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rows = [{"date": DATE, "leg": str(i), "winner_no": "", "winner_name": ""} for i in range(1, 6)]
            write_csv(d / "r.csv", ["date", "leg", "winner_no", "winner_name"], rows)
            with self.assertRaises(ValueError) as cm:
                evaluate(d / "p.csv", d / "r.csv")
            self.assertIn("not entered", str(cm.exception))

    def test_duplicate_result_row_for_a_leg(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)}, extra=[{"date": DATE, "leg": "3", "winner_no": "2", "winner_name": "H2"}])
            write_csv(d / "r.csv", rf, rr)
            with self.assertRaises(ValueError):
                evaluate(d / "p.csv", d / "r.csv")

    def test_results_for_a_different_date_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            rr = rr + [{"date": "2026-10-18", "leg": "1", "winner_no": "2", "winner_name": "x"}]
            write_csv(d / "r.csv", rf, rr)
            self.assertEqual(evaluate(d / "p.csv", d / "r.csv")["top1_hits"], 5)

    def test_mixed_dates_in_prediction_file(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            pr[0]["date"] = "2026-10-24"
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            write_csv(d / "r.csv", rf, rr)
            with self.assertRaises(ValueError):
                evaluate(d / "p.csv", d / "r.csv")


class EdgeCases(Base):
    def test_zero_probability_for_winner_is_floored_and_warned(self):
        preds = dict(STD)
        preds[1] = [(1, 50), (2, 50), (3, 0)]
        got = self.run_eval(preds=preds, results={1: 3, 2: 1, 3: 1, 4: 1, 5: 1})
        self.assertTrue(any("below the log-loss floor" in w for w in got["warnings"]))
        self.assertTrue(math.isfinite(got["mean_winner_log_loss"]))
        self.assertGreater(got["mean_winner_log_loss"], 6.0)  # -ln(1e-15)/5 ~ 6.9

    def test_zero_probability_floor_is_configurable(self):
        preds = dict(STD)
        preds[1] = [(1, 50), (2, 50), (3, 0)]
        got = self.run_eval(preds=preds, results={1: 3, 2: 1, 3: 1, 4: 1, 5: 1}, log_loss_floor=1e-6)
        self.assertLess(got["mean_winner_log_loss"], 4.0)

    def test_tie_for_top1_is_reported_and_broken_by_lower_horse_number(self):
        preds = dict(STD)
        preds[1] = [(1, 40), (2, 40), (3, 20)]
        got = self.run_eval(preds=preds, results={1: 2, 2: 1, 3: 1, 4: 1, 5: 1})
        self.assertTrue(any("tie for Top-1" in w for w in got["warnings"]))
        self.assertEqual(got["top1_hits"], 4)  # leg 1 winner 2 loses the tie to horse 1

    def test_scratched_horse_is_removed_and_probabilities_renormalised(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            rr[0]["scratched_nos"] = "3"
            write_csv(d / "r.csv", rf, rr)
            got = evaluate(d / "p.csv", d / "r.csv")
            leg1 = got["details"][0]
            self.assertTrue(leg1["renormalised_after_scratch"])
            self.assertEqual(leg1["field_size"], 2)
            self.assertAlmostEqual(leg1["winner_probability_pct"], 62.5, places=3)  # 50 / 80
            self.assertEqual(got["horses_scored"], 4 * 3 + 2)

    def test_winner_listed_as_scratched_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            rr[0]["scratched_nos"] = "1"
            write_csv(d / "r.csv", rf, rr)
            with self.assertRaises(ValueError):
                evaluate(d / "p.csv", d / "r.csv")

    def test_scratched_number_not_in_prediction_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            rr[0]["scratched_nos"] = "9"
            write_csv(d / "r.csv", rf, rr)
            with self.assertRaises(ValueError):
                evaluate(d / "p.csv", d / "r.csv")

    def test_prediction_file_is_not_modified(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            write_csv(d / "r.csv", rf, rr)
            before = (d / "p.csv").read_bytes()
            evaluate(d / "p.csv", d / "r.csv")
            self.assertEqual(before, (d / "p.csv").read_bytes())


class FloorValidation(Base):
    def test_invalid_floors_are_rejected(self):
        for v in (0, -1e-9, 1.0000001, 2, float("nan"), float("inf")):
            with self.assertRaises(ValueError, msg=repr(v)):
                self.run_eval(log_loss_floor=v)

    def test_boundary_floors_are_accepted(self):
        for v in (1e-15, 1.0):
            self.assertEqual(self.run_eval(log_loss_floor=v)["top1_hits"], 5)


class Cli(Base):
    def test_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pf, pr = make_preds(STD)
            write_csv(d / "p.csv", pf, pr)
            rf, rr = make_results({i: 1 for i in range(1, 6)})
            write_csv(d / "r.csv", rf, rr)
            out = d / "o" / "report.md"
            r = subprocess.run([sys.executable, str(ROOT / "scripts/evaluate_win5_history_only.py"),
                                "--predictions", str(d / "p.csv"), "--results", str(d / "r.csv"),
                                "--output", str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = out.read_text(encoding="utf-8")
            self.assertIn("Top-1", text)
            self.assertIn("全頭同確率", text)


if __name__ == "__main__":
    unittest.main()
