import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from export_win5_three_picks import export_picks  # noqa: E402

DATE = "2026-10-25"


class ThreePickExporterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "probabilities.csv"
        self.output = self.root / "picks.csv"
        self.fields = ["date", "leg", "horse_number", "horse_name", "probability"]
        self.rows = []
        for leg in range(1, 6):
            self.rows.extend([
                {"date": DATE, "leg": leg, "horse_number": 1, "horse_name": "Horse A", "probability": 50},
                {"date": DATE, "leg": leg, "horse_number": 2, "horse_name": "Horse B", "probability": 30},
                {"date": DATE, "leg": leg, "horse_number": 3, "horse_name": "Horse C", "probability": 20},
            ])
        self.write_source()

    def write_source(self):
        with self.source.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=self.fields)
            w.writeheader()
            w.writerows(self.rows)

    def run_export(self):
        return export_picks(self.source, self.output, DATE, "probability", "leg", "horse_number", "horse_name")

    def test_exports_exactly_three_ranked_picks_for_each_leg(self):
        result = self.run_export()
        self.assertEqual(result["picks"], 15)
        with self.output.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 15)
        self.assertEqual([r["mark"] for r in rows[:3]], ["◎", "○", "▲"])
        self.assertEqual([r["horse_number"] for r in rows[:3]], ["1", "2", "3"])
        self.assertTrue(all(r["source_sha256"] == result["source_sha256"] for r in rows))

    def test_does_not_modify_source_and_refuses_overwrite(self):
        original = self.source.read_bytes()
        self.run_export()
        self.assertEqual(self.source.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            self.run_export()

    def test_tie_is_reported_and_lower_horse_number_breaks_tie(self):
        for row in self.rows:
            if row["leg"] == 1:
                row["probability"] = {1: 40, 2: 40, 3: 20}[row["horse_number"]]
        self.write_source()
        result = self.run_export()
        self.assertTrue(any("◎/○ tie" in w for w in result["warnings"]))

    def test_probability_sum_must_be_approximately_100(self):
        for row in self.rows:
            if row["leg"] == 2 and row["horse_number"] == 1:
                row["probability"] = 40
        self.write_source()
        with self.assertRaisesRegex(ValueError, "sum to"):
            self.run_export()

    def test_duplicate_horse_is_rejected(self):
        self.rows.append(dict(self.rows[0]))
        self.write_source()
        with self.assertRaisesRegex(ValueError, "Duplicate horse"):
            self.run_export()

    def test_missing_date_is_explained(self):
        with self.assertRaisesRegex(ValueError, "dates present"):
            export_picks(self.source, self.output, "2026-10-24", "probability", "leg", "horse_number", "horse_name")


if __name__ == "__main__":
    unittest.main()
