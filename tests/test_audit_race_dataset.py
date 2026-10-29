import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_race_dataset.py"
SPEC = importlib.util.spec_from_file_location("audit_race_dataset", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def race(date="2026-01-01", venue="東京", rn=1, surface="芝", dist=1600):
    return {"date": date, "venue": venue, "rn": rn, "surface": surface, "dist": dist,
            "rows": [
                {"num": i, "pop": i, "hid": f"h{i}", "place": i}
                for i in range(1, 7)
            ]}


class TestRaceDatasetAudit(unittest.TestCase):
    def test_valid_race_passes_basic_integrity(self):
        report = MODULE.audit([race()])
        self.assertEqual(report["status"], "pass_basic_integrity_not_leakage_validation")
        self.assertEqual(report["eligible_for_preregistered_b2_filter"], 1)
        self.assertEqual(report["races_with_exactly_one_valid_first_place"], 1)

    def test_duplicate_race_key_is_a_reported_warning_not_a_blocker(self):
        # Duplicates are deduplicated deterministically downstream (b2_dataset_prep / reconciliation);
        # the audit must still report them and must not pass silently.
        report = MODULE.audit([race(), race()])
        self.assertEqual(report["status"], "pass_basic_integrity_with_warnings")
        self.assertIn("duplicate_race_key", report["issue_counts"])
        self.assertTrue(report["duplicate_race_keys_first_100"])
        self.assertTrue(any("Duplicate" in w for w in report["warnings"]))

    def test_invalid_date_and_missing_winner_are_reported(self):
        item = race(date="not-a-date")
        item["rows"] = [{"num": i, "pop": i, "hid": f"h{i}", "place": i + 1} for i in range(1, 7)]
        report = MODULE.audit([item])
        self.assertEqual(report["status"], "blocked_integrity_issues")
        self.assertIn("invalid_date", report["issue_counts"])
        self.assertEqual(report["races_with_exactly_one_valid_first_place"], 0)


if __name__ == "__main__":
    unittest.main()
