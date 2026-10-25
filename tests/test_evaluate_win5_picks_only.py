import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_win5_model_comparison import read_results  # noqa: E402
from evaluate_win5_picks_only import evaluate_picks  # noqa: E402

DATE = "2026-10-25"


class Picks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def go(self, picks, winners, scratched=None):
        with (self.d / "p.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "leg", "horse_number", "horse_name"])
            for leg, no in picks.items():
                w.writerow([DATE, leg, no, f"H{no}"])
        with (self.d / "r.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["date", "leg", "winner_no", "scratched_nos"])
            for leg, no in winners.items():
                w.writerow([DATE, leg, no, (scratched or {}).get(leg, "")])
        win, sc = read_results(self.d / "r.csv", DATE)
        return evaluate_picks(self.d / "p.csv", DATE, win, sc)

    def test_counts_hits_only_by_horse_number(self):
        r = self.go({1: 2, 2: 6, 3: 7, 4: 4, 5: 8}, {1: 2, 2: 3, 3: 14, 4: 4, 5: 9})
        self.assertEqual(r["top1_hits"], 2)
        self.assertEqual([d["hit"] for d in r["details"]], [True, False, False, True, False])

    def test_decimal_formatted_numbers(self):
        r = self.go({1: "2.00000", 2: "6.00000", 3: "7.00000", 4: "4.00000", 5: "8.00000"}, {i: 1 for i in range(1, 6)})
        self.assertEqual(r["top1_hits"], 0)

    def test_missing_leg_is_rejected(self):
        with self.assertRaises(ValueError):
            self.go({1: 2, 2: 6, 3: 7, 4: 4}, {i: 1 for i in range(1, 6)})

    def test_duplicate_leg_is_rejected(self):
        with (self.d / "p.csv").open("w", newline="", encoding="utf-8") as f:
            f.write("date,leg,horse_number,horse_name\n" + "".join(f"{DATE},{l},1,x\n" for l in (1, 1, 2, 3, 4, 5)))
        with (self.d / "r.csv").open("w", newline="", encoding="utf-8") as f:
            f.write("date,leg,winner_no,scratched_nos\n" + "".join(f"{DATE},{l},1,\n" for l in range(1, 6)))
        win, sc = read_results(self.d / "r.csv", DATE)
        with self.assertRaises(ValueError):
            evaluate_picks(self.d / "p.csv", DATE, win, sc)

    def test_scratched_pick_is_flagged_not_hidden(self):
        r = self.go({i: 5 for i in range(1, 6)}, {i: 1 for i in range(1, 6)}, scratched={1: "5"})
        self.assertTrue(r["details"][0]["pick_scratched"])

    def test_unfinished_results_are_rejected(self):
        with (self.d / "p.csv").open("w", newline="", encoding="utf-8") as f:
            f.write("date,leg,horse_number,horse_name\n" + "".join(f"{DATE},{l},1,x\n" for l in range(1, 6)))
        with (self.d / "r.csv").open("w", newline="", encoding="utf-8") as f:
            f.write("date,leg,winner_no,scratched_nos\n" + "".join(f"{DATE},{l},,\n" for l in range(1, 6)))
        with self.assertRaises(ValueError):
            read_results(self.d / "r.csv", DATE)

    def test_real_picks_file_parses(self):
        path = ROOT / "data/win5_joint/2026-10-25/gpt-morning-provisional-picks.csv"
        if not path.exists():
            self.skipTest("picks file not present")
        with (self.d / "r.csv").open("w", newline="", encoding="utf-8") as f:
            f.write("date,leg,winner_no,scratched_nos\n" + "".join(f"{DATE},{l},2,\n" for l in range(1, 6)))
        win, sc = read_results(self.d / "r.csv", DATE)
        r = evaluate_picks(path, DATE, win, sc)
        self.assertEqual(r["legs"], 5)
        self.assertEqual([d["pick_no"] for d in r["details"]], [2, 6, 7, 4, 8])


if __name__ == "__main__":
    unittest.main()
