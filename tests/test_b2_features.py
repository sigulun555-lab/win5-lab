import datetime as dt
import unittest
from research.factor_validation.b2_features import eligible_prior_runs, b_score, classify_venue
class B2FeatureTests(unittest.TestCase):
    def setUp(self):
        self.runs = [
            {"date":"2026年01月01日","venue":"東京","field":"10","place":"2"},
            {"date":"2026年02月01日","venue":"名古屋","field":"12","place":"4"},
            {"date":"2026年03月01日","venue":"京都","field":"8","place":"3"},
            {"date":"2026年04月01日","venue":"東京","field":"9","place":"1"},
            {"date":"2026年05月01日","venue":"東京","field":"10","place":"5"},
            {"date":"2026年06月01日","venue":"東京","field":"11","place":"3"},
            {"date":"2026年07月01日","venue":"東京","field":"12","place":"6"},
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
    def test_future_perturbation_does_not_change_score(self):
        a=b_score(self.runs,"2026-05-01")["score"]
        altered=self.runs+[{"date":"2027年01月01日","venue":"東京","field":"18","place":"1"}]
        b=b_score(altered,"2026-05-01")["score"]
        self.assertEqual(a,b)
    def test_invalid_finish_is_ignored(self):
        rows=self.runs+[{"date":"2026年04月20日","venue":"東京","field":"12","place":"中止"}]
        got=eligible_prior_runs(rows,"2026-05-01")
        self.assertNotIn("2026-04-20",[x["_parsed_date"] for x in got])
if __name__ == "__main__": unittest.main()