import csv, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from build_gpt_v2_scenario import build

class V2ScenarioTests(unittest.TestCase):
    def test_alpha_zero_preserves_v1_distribution_and_sums_to_100(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); src=p/"in.csv"; dst=p/"out.csv"
            fields=["race","horse_name","win_odds","latest_observed_win_odds","gpt_estimated_win_probability_pct"]
            rows=[
                {"race":"A","horse_name":"a","win_odds":"4","latest_observed_win_odds":"2","gpt_estimated_win_probability_pct":"25"},
                {"race":"A","horse_name":"b","win_odds":"2","latest_observed_win_odds":"4","gpt_estimated_win_probability_pct":"75"},
            ]
            with src.open("w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
            self.assertEqual(build(src,dst,0),{"A":100.0})
            with dst.open(newline="",encoding="utf-8") as f: got=list(csv.DictReader(f))
            self.assertEqual([x["gpt_v2_market_adjusted_probability_pct"] for x in got],["25.00","75.00"])
            self.assertEqual([x["gpt_estimated_win_probability_pct"] for x in got],["25","75"])
    def test_invalid_odds_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); src=p/"in.csv"; dst=p/"out.csv"
            fields=["race","horse_name","win_odds","latest_observed_win_odds","gpt_estimated_win_probability_pct"]
            with src.open("w",newline="",encoding="utf-8") as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
                w.writerow({"race":"A","horse_name":"a","win_odds":"1","latest_observed_win_odds":"2","gpt_estimated_win_probability_pct":"100"})
            with self.assertRaises(ValueError): build(src,dst)
if __name__=="__main__": unittest.main()
