import csv
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_win5_marks import build_marks, parse_scratched, validate_marks  # noqa: E402

DATE = "2026-10-25"
COLS = ["date", "leg", "horse_number", "horse_name", "race_name", "p"]


def write(path, probs_by_leg):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for leg, items in probs_by_leg.items():
            for no, p in items:
                w.writerow([DATE, f"{leg}.00000", f"{no}.00000", f"H{no}", f"R{leg}", p])


STD = {leg: [(1, "50.5"), (2, "30.25"), (3, "10"), (4, "9.25")] for leg in range(1, 6)}


class Marks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.src = self.d / "p.csv"

    def build(self, probs=None, **kw):
        write(self.src, probs or STD)
        args = dict(path=self.src, date=DATE, prob_col="p", leg_col="leg", horse_col="horse_number", name_col="horse_name",
                    race_col="race_name", model_name="M", market_odds_used="no")
        args.update(kw)
        return build_marks(**args)

    def test_three_distinct_marks_per_leg_with_model_probabilities_copied_as_is(self):
        rows = self.build()
        self.assertEqual(len(rows), 15)
        leg1 = [r for r in rows if r["leg"] == 1]
        self.assertEqual([(r["mark"], r["horse_number"], r["win_probability_pct"]) for r in leg1],
                         [("◎", 1, "50.5"), ("○", 2, "30.25"), ("▲", 3, "10")])

    def test_source_file_is_unchanged_and_sha_recorded(self):
        write(self.src, STD)
        before = self.src.read_bytes()
        rows = self.build()
        self.assertEqual(before, self.src.read_bytes())
        self.assertEqual(rows[0]["source_sha256"], hashlib.sha256(before).hexdigest())

    def test_unknown_facts_stay_unknown(self):
        self.assertEqual(self.build()[0]["prediction_created_at"], "不明")

    def test_ties_are_flagged_and_broken_by_lower_number(self):
        probs = dict(STD)
        probs[1] = [(1, "40"), (2, "40"), (3, "10"), (4, "10")]
        rows = [r for r in self.build(probs) if r["leg"] == 1]
        self.assertEqual([r["horse_number"] for r in rows], [1, 2, 3])
        self.assertTrue(all(r["tie_note"] for r in rows))

    def test_probabilities_must_sum_to_100(self):
        probs = dict(STD)
        probs[2] = [(1, "50"), (2, "30"), (3, "10"), (4, "5")]
        with self.assertRaises(ValueError):
            self.build(probs)

    def test_missing_leg_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build({k: v for k, v in STD.items() if k != 5})

    def test_fewer_than_three_horses_is_rejected(self):
        probs = dict(STD)
        probs[1] = [(1, "60"), (2, "40")]
        with self.assertRaises(ValueError):
            self.build(probs)

    def test_scratched_horse_is_excluded_with_reason_and_time(self):
        rows = self.build(scratched={(1, 1)}, update_reason="競走除外", update_time_jst="2026-10-25 12:00")
        leg1 = [r for r in rows if r["leg"] == 1]
        self.assertEqual([r["horse_number"] for r in leg1], [2, 3, 4])
        self.assertEqual(leg1[0]["update_reason"], "競走除外")
        self.assertEqual(leg1[0]["win_probability_pct"], "30.25")  # still the model's own value, not renormalised

    def test_scratched_requires_reason_and_time(self):
        with self.assertRaises(ValueError):
            self.build(scratched={(1, 1)})

    def test_invalid_market_flag_is_rejected(self):
        with self.assertRaises(ValueError):
            self.build(market_odds_used="maybe")

    def test_duplicate_horse_is_rejected(self):
        probs = dict(STD)
        probs[1] = [(1, "50"), (1, "30"), (3, "10"), (4, "10")]
        with self.assertRaises(ValueError):
            self.build(probs)

    def test_validate_rejects_repeated_horse_and_missing_name(self):
        rows = self.build()
        bad = [dict(r) for r in rows]
        bad[1]["horse_number"] = bad[0]["horse_number"]
        with self.assertRaises(ValueError):
            validate_marks(bad)
        bad = [dict(r) for r in rows]
        bad[0]["horse_name"] = ""
        with self.assertRaises(ValueError):
            validate_marks(bad)

    def test_parse_scratched(self):
        self.assertEqual(parse_scratched("1:5, 2:7;3:1"), {(1, 5), (2, 7), (3, 1)})

    def test_cli_refuses_to_overwrite(self):
        write(self.src, STD)
        out = self.d / "marks.csv"
        cmd = [sys.executable, str(ROOT / "scripts/make_win5_marks.py"), "--date", DATE, "--model-name", "M",
               "--predictions", str(self.src), "--probability-column", "p", "--market-odds-used", "no", "--output", str(out)]
        self.assertEqual(subprocess.run(cmd, capture_output=True, text=True).returncode, 0)
        second = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(second.returncode, 2)
        self.assertIn("already exists", second.stderr)


if __name__ == "__main__":
    unittest.main()
