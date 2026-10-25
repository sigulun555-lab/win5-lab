import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_b2_training_sources.py"
SPEC = importlib.util.spec_from_file_location("audit_b2_training_sources", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TestB2TrainingSourceAudit(unittest.TestCase):
    def test_missing_race_level_dataset_is_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in (
                "data/horse_history/2026-10-25.json",
                "docs/win5/b2-validation-protocol.md",
                "research/factor-validation/b2_features.py",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            candidate = root / "data/win5_races"
            candidate.mkdir(parents=True)
            (candidate / "2026-10-24-1.json").write_text('{"horses":[]}', encoding="utf-8")
            report = MODULE.audit(root)
            self.assertEqual(report["status"], "blocked_missing_or_unverified_sources")
            self.assertFalse(report["checks"]["race_level_training_data"]["exists"])
            self.assertFalse(report["checks"]["win5_candidate_files"]["usable_as_full_race_labels"])
            self.assertTrue(report["blockers"])

    def test_present_paths_only_allow_next_integrity_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in (
                "research/factor-validation/races.json",
                "data/horse_history/2026-10-25.json",
                "docs/win5/b2-validation-protocol.md",
                "research/factor-validation/b2_features.py",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")
            report = MODULE.audit(root)
            self.assertEqual(report["status"], "sources_present_for_next_integrity_audit")
            self.assertIn("does not verify dataset contents", report["not_claimed"][0])


if __name__ == "__main__":
    unittest.main()
