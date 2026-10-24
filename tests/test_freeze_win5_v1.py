import csv
import sys
import tempfile
import unittest
import datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from freeze_win5_v1 import freeze
JST = dt.timezone(dt.timedelta(hours=9))


class FreezeV1Tests(unittest.TestCase):
    def fixture(self, root):
        src = root / "source.csv"
        fields = ["date", "win5_order", "race", "horse_no", "horse_name",
                  "gpt_estimated_win_probability_pct", "gpt_info_time_jst"]
        rows = []
        for leg in range(1, 6):
            rows += [
                {"date":"2026-10-25","win5_order":str(leg),"race":f"R{leg}","horse_no":"1","horse_name":"A","gpt_estimated_win_probability_pct":"60","gpt_info_time_jst":"2026-10-25 10:00 JST"},
                {"date":"2026-10-25","win5_order":str(leg),"race":f"R{leg}","horse_no":"2","horse_name":"B","gpt_estimated_win_probability_pct":"40","gpt_info_time_jst":"2026-10-25 10:00 JST"},
            ]
        with src.open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
        return src

    def test_freezes_valid_five_legs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=self.fixture(root); out=root/"frozen.csv"
            now=dt.datetime(2026,10,25,11,0,tzinfo=JST)
            got=freeze(src,out,"14:45",now)
            self.assertEqual(got["legs"],5)
            self.assertEqual(got["horses"],10)
            with out.open(newline="",encoding="utf-8") as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]["v1_freeze_status"],"frozen_pre_deadline")
            self.assertEqual(rows[0]["gpt_estimated_win_probability_pct"],"60")

    def test_rejects_after_deadline_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=self.fixture(root); out=root/"frozen.csv"
            now=dt.datetime(2026,10,25,15,0,tzinfo=JST)
            with self.assertRaises(ValueError): freeze(src,out,"14:45",now)
            self.assertFalse(out.exists())

    def test_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); src=self.fixture(root); out=root/"frozen.csv"; out.write_text("keep")
            with self.assertRaises(FileExistsError): freeze(src,out,"14:45",dt.datetime(2026,10,25,11,0,tzinfo=JST))
            self.assertEqual(out.read_text(),"keep")


if __name__ == "__main__":
    unittest.main()
