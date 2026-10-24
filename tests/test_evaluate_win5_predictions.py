import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_win5_predictions import evaluate


class EvaluateWin5Tests(unittest.TestCase):
    def test_evaluates_five_legs_and_scores(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pred = root / "pred.csv"
            result = root / "result.csv"
            fields = ["win5_order", "race", "horse_no", "horse_name",
                      "gpt_estimated_win_probability_pct",
                      "gpt_v2_market_adjusted_probability_pct",
                      "market_normalized_probability_pct"]
            rows = []
            winners = []
            for leg in range(1, 6):
                rows.extend([
                    {"win5_order": str(leg), "race": f"R{leg}", "horse_no": "1", "horse_name": "Winner",
                     fields[4]: "70", fields[5]: "60", fields[6]: "65"},
                    {"win5_order": str(leg), "race": f"R{leg}", "horse_no": "2", "horse_name": "Other",
                     fields[4]: "30", fields[5]: "40", fields[6]: "35"},
                ])
                winners.append({"win5_order": str(leg), "race": f"R{leg}", "winner_no": "1"})
            with pred.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
            with result.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["win5_order", "race", "winner_no"]); w.writeheader(); w.writerows(winners)
            got = evaluate(pred, result)
            self.assertEqual(got["summary"]["v1"]["top1_hits"], 5)
            self.assertEqual(got["summary"]["v2"]["top1_hits"], 5)
            self.assertEqual(len(got["races"]), 5)

    def test_rejects_missing_winner(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); pred = root / "pred.csv"; result = root / "result.csv"
            fields = ["win5_order", "race", "horse_no", "horse_name",
                      "gpt_estimated_win_probability_pct",
                      "gpt_v2_market_adjusted_probability_pct",
                      "market_normalized_probability_pct"]
            rows=[]; winners=[]
            for leg in range(1,6):
                rows.append({"win5_order":str(leg),"race":f"R{leg}","horse_no":"1","horse_name":"A",
                             fields[4]:"100",fields[5]:"100",fields[6]:"100"})
                winners.append({"win5_order":str(leg),"race":f"R{leg}","winner_no":"9"})
            with pred.open("w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            with result.open("w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=["win5_order","race","winner_no"]);w.writeheader();w.writerows(winners)
            with self.assertRaises(ValueError): evaluate(pred,result)


if __name__ == "__main__":
    unittest.main()
