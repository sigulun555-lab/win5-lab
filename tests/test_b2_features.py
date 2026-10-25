import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "research" / "factor-validation" / "b2_features.py"
SPEC = importlib.util.spec_from_file_location("b2_features", MODULE_PATH)
b2_features = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b2_features)
eligible_prior_runs = b2_features.eligible_prior_runs
b_score = b2_features.b_score
classify_venue = b2_features.classify_venue
classify_race_class = b2_features.classify_race_class

class B2FeatureTests(unittest.TestCase):
    def setUp(self):
        self.runs = [
            {"date":"2026年01月01日","venue":"東京","class":"新馬","field":"10","place":"2"},
            {"date":"2026年02月01日","venue":"名古屋","class":"A級","field":"12","place":"4"},
            {"date":"2026年03月01日","venue":"京都","class":"未勝利","field":"8","place":"3"},
            {"date":"2026年04月01日","venue":"東京","class":"1勝クラス","field":"9","place":"1"},
            {"date":"2026年05月01日","venue":"東京","class":"三宮S","field":"10","place":"5"},
            {"date":"2026年06月01日","venue":"東京","class":"G3","field":"11","place":"3"},
            {"date":"2026年07月01日","venue":"東京","class":"2勝クラス","field":"12","place":"6"},
        ]

    def test_future_and_same_day_runs_never_used(self):
        got=eligible_prior_runs(self.runs,"2026-05-01")
        self.assertTrue(all(x["_parsed_date"] < "2026-05-01" for x in got))
        self.assertEqual(len(got),3)

    def test_local_excluded_before_six_run_cut(self):
        got=eligible_prior_runs(self.runs,"2026-08-01",local_policy="exclude",max_runs=6)
        self.assertEqual(len(got),6)
        self.assertTrue(all(x["_venue_type"] != "LOCAL" for x in got))
        self.assertNotIn("2026-02-01",[x["_parsed_date"] for x in got])

    def test_venue_classification_is_not_fuzzy(self):
        self.assertEqual(classify_venue("東京"),"JRA")
        self.assertEqual(classify_venue("名古屋"),"LOCAL")
        self.assertEqual(classify_venue("名古"),"UNCLASSIFIABLE")

    def test_class_classification_is_conservative(self):
        self.assertEqual(classify_race_class("新馬","JRA"),"DEBUT")
        self.assertEqual(classify_race_class("未勝利","JRA"),"MAIDEN")
        self.assertEqual(classify_race_class("三宮S","JRA"),"UNKNOWN_JRA")
        self.assertEqual(classify_race_class("G3","JRA"),"GRADED")
        self.assertEqual(classify_race_class("G3","LOCAL"),"LOCAL")
        self.assertEqual(classify_race_class("","JRA"),"UNKNOWN_JRA")
        self.assertEqual(classify_race_class("未勝利","UNCLASSIFIABLE"),"UNCLASSIFIABLE")

    def test_class_gamma_applies_and_debut_is_reference(self):
        base=b_score(self.runs,"2026-05-01")["score"]
        adjusted=b_score(self.runs,"2026-05-01",class_gamma={"MAIDEN":1.0})["score"]
        self.assertNotEqual(base,adjusted)
        with self.assertRaises(ValueError):
            b_score(self.runs,"2026-05-01",class_gamma={"DEBUT":0.1})

    def test_local_weight_downweight_matches_frozen_formula(self):
        result=b_score(self.runs,"2026-08-01",local_eta=-0.5)
        local=[d for d in result["details"] if d["venue_type"]=="LOCAL"]
        self.assertTrue(local)
        self.assertAlmostEqual(local[0]["effective_weight"],local[0]["base_weight"]*0.5)

    def test_exclude_policy_requires_zero_local_eta(self):
        with self.assertRaises(ValueError):
            b_score(self.runs,"2026-08-01",local_policy="exclude",local_eta=-0.2)

    def test_future_perturbation_does_not_change_score(self):
        a=b_score(self.runs,"2026-05-01")["score"]
        altered=self.runs+[{"date":"2027年01月01日","venue":"東京","class":"G1","field":"18","place":"1"}]
        b=b_score(altered,"2026-05-01")["score"]
        self.assertEqual(a,b)

    def test_invalid_finish_is_ignored(self):
        rows=self.runs+[{"date":"2026年04月20日","venue":"東京","field":"12","place":"中止"}]
        got=eligible_prior_runs(rows,"2026-05-01")
        self.assertNotIn("2026-04-20",[x["_parsed_date"] for x in got])

if __name__ == "__main__":
    unittest.main()
