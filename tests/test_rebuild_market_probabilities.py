import csv
import tempfile
import unittest
from pathlib import Path

from rebuild_market_probabilities import rebuild


class RebuildMarketProbabilitiesTests(unittest.TestCase):
    def test_market_probabilities_sum_to_100_and_gpt_values_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "input.csv"
            dst = root / "output.csv"
            fields = [
                "race", "horse_name", "latest_observed_win_odds",
                "market_normalized_probability_pct", "gpt_estimated_win_probability_pct",
            ]
            rows = [
                {"race": "Race A", "horse_name": "Horse 1", "latest_observed_win_odds": "2.0",
                 "market_normalized_probability_pct": "", "gpt_estimated_win_probability_pct": "55.00"},
                {"race": "Race A", "horse_name": "Horse 2", "latest_observed_win_odds": "4.0",
                 "market_normalized_probability_pct": "", "gpt_estimated_win_probability_pct": "45.00"},
                {"race": "Race B", "horse_name": "Horse 3", "latest_observed_win_odds": "3.0",
                 "market_normalized_probability_pct": "", "gpt_estimated_win_probability_pct": "25.00"},
                {"race": "Race B", "horse_name": "Horse 4", "latest_observed_win_odds": "3.0",
                 "market_normalized_probability_pct": "", "gpt_estimated_win_probability_pct": "75.00"},
            ]
            with src.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)

            sums = rebuild(src, dst)
            self.assertEqual(sums, {"Race A": 100.0, "Race B": 100.0})
            with dst.open(newline="", encoding="utf-8") as f:
                result = list(csv.DictReader(f))
            self.assertEqual([r["market_normalized_probability_pct"] for r in result],
                             ["66.67", "33.33", "50.00", "50.00"])
            self.assertEqual([r["gpt_estimated_win_probability_pct"] for r in result],
                             ["55.00", "45.00", "25.00", "75.00"])

    def test_invalid_odds_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "input.csv"
            dst = root / "output.csv"
            fields = [
                "race", "horse_name", "latest_observed_win_odds",
                "market_normalized_probability_pct", "gpt_estimated_win_probability_pct",
            ]
            with src.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"race": "Race A", "horse_name": "Horse 1",
                                 "latest_observed_win_odds": "0", "gpt_estimated_win_probability_pct": "100"})
            with self.assertRaises(ValueError):
                rebuild(src, dst)


if __name__ == "__main__":
    unittest.main()
