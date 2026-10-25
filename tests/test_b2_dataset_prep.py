import importlib.util
from pathlib import Path
import unittest

P=Path(__file__).resolve().parents[1]/"research"/"factor-validation"/"b2_dataset_prep.py"
S=importlib.util.spec_from_file_location("b2_dataset_prep",P)
M=importlib.util.module_from_spec(S); S.loader.exec_module(M)

def race(date, rn, rows, cls="未勝利"):
    return {"date":date,"venue":"東京","rn":rn,"surface":"芝","dist":1600,"cls":cls,"rows":rows}

class TestB2DatasetPrep(unittest.TestCase):
    def test_only_prior_dates_and_class_join(self):
        races=[
            race("2026-01-01",1,[{"hid":"h1","num":1,"pop":1,"place":1},{"hid":"h2","num":2,"pop":2,"place":2},{"hid":"h3","num":3,"pop":3,"place":3},{"hid":"h4","num":4,"pop":4,"place":4},{"hid":"h5","num":5,"pop":5,"place":5}], "新馬"),
            race("2026-02-01",1,[{"hid":"h1","num":1,"pop":1,"place":2},{"hid":"h2","num":2,"pop":2,"place":1},{"hid":"h3","num":3,"pop":3,"place":3},{"hid":"h4","num":4,"pop":4,"place":4},{"hid":"h5","num":5,"pop":5,"place":5}], "未勝利"),
        ]
        out=M.prepare(races)
        target=next(x for x in out if x["date"]=="2026-02-01")
        h1=next(x for x in target["rows"] if x["hid"]=="h1")
        self.assertEqual(h1["prior_runs"],1)
        self.assertEqual(h1["b2_score"],0.0) # debut is a neutral prior
        self.assertEqual(target["class"],"未勝利")

    def test_dead_heat_is_retained_fractionally(self):
        rows=[{"hid":f"h{i}","num":i,"pop":i,"place":1 if i in (1,2) else i} for i in range(1,7)]
        out=M.prepare([race("2026-01-01",1,rows)])
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["winner_count"],2)
        self.assertAlmostEqual(sum(x["winner_share"] for x in out[0]["rows"]),1.0)

if __name__=="__main__": unittest.main()
