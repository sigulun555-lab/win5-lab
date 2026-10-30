"""B2.1 class-labeling tests: explicit grade icon only, default behaviour unchanged, prior-only joins preserved."""
import importlib.util
from pathlib import Path
import unittest

FV = Path(__file__).resolve().parents[1] / "research" / "factor-validation"

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, FV / file)
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(FV))
    spec.loader.exec_module(mod)
    return mod

PARSE = load("parse_ses_under_test", "parse_ses.py")
PREP = load("b2_dataset_prep_under_test", "b2_dataset_prep.py")
FEAT = load("b2_features_under_test", "b2_features.py")

# Header copied from the real JRA result page of the 秋華賞 (2026-10-18), trimmed to the parsed parts.
def page(name_html, cls="オープン", day="2026年10月18日（日曜） 4回京都7日"):
    return f'''<div class="race_result_unit" id="race_result_11R">
<table class="basic narrow-xy striped"><caption><div class="race_header"><div class="left"><div class="date_line"><div class="inner">
<div class="cell date">{day}</div><div class="cell time">発走時刻：<strong>15時40分</strong></div>
<div class="cell baba"><ul><li class="weather"><span class="inner"><span class="cap">天候</span><span class="txt">晴</span></span></li><li class="turf"><span class="inner"><span class="cap">芝</span><span class="txt">良</span></span></li></ul></div></div></div>
<div class="race_title"><div class="inner"><div class="txt"><h2><span class="main"><span class="cap"><span class="num">第31回</span></span><span class="race_name">{name_html}</span></span></h2>
<div class="type"><div class="cell category">3歳</div><div class="cell class">{cls}</div><div class="cell rule">（国際）牝（指定）</div><div class="cell weight">馬齢</div>
<div class="cell course"><span class="cap">コース：</span>2,000<span class="unit">メートル</span><span class="detail">（芝・右）</span></div></div></div></div></div></div></caption></table></div>'''

def parse(html, tmp):
    f = Path(tmp) / "x.html"
    f.write_text(html, encoding="utf-8")
    return PARSE.parse_file(str(f))

class ParseGrade(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()

    def test_g1_icon_is_captured_and_class_text_unchanged(self):
        r = parse(page('秋華賞<span class="grade_icon lg"><img src="/JRADB/img/grade/icon_grade_g1.png" alt="G&#8544;" /></span>'), self.tmp)[0]
        self.assertEqual((r["name"], r["cls"], r["grade"], r["grade_icon"], r["grade_alt"]), ("秋華賞", "オープン", "G1", "g1", "GⅠ"))

    def test_g2_g3_icons(self):
        for stem, want in (("g2", "G2"), ("g3", "G3")):
            r = parse(page(f'札幌記念<span class="grade_icon lg"><img src="/JRADB/img/grade/icon_grade_{stem}.png" alt="x" /></span>'), self.tmp)[0]
            self.assertEqual(r["grade"], want)

    def test_unrecognised_icon_is_recorded_but_not_mapped(self):
        r = parse(page('ある競走<span class="grade_icon"><img src="/JRADB/img/grade/icon_grade_l.png" alt="L" /></span>'), self.tmp)[0]
        self.assertEqual((r["grade"], r["grade_icon"]), ("", "l"))

    def test_no_icon_means_no_grade_and_name_is_never_used(self):
        r = parse(page("天皇賞"), self.tmp)[0]   # name looks like a G1 but the page shows no icon
        self.assertEqual((r["grade"], r["grade_icon"]), ("", ""))

class Labeling(unittest.TestCase):
    def test_v1_is_unchanged(self):
        self.assertEqual(PREP.race_class_label({"cls": "オープン", "grade": "G1"}, "v1"), "オープン")
        self.assertEqual(PREP.race_class_label({"cls": "オープン", "grade": "G1"}), "オープン")

    def test_v2_uses_explicit_grade_only_for_open_class(self):
        self.assertEqual(PREP.race_class_label({"cls": "オープン", "grade": "G2"}, "v2"), "G2")
        self.assertEqual(PREP.race_class_label({"cls": "オープン", "grade": ""}, "v2"), "オープン")
        self.assertEqual(PREP.race_class_label({"cls": "3勝クラス", "grade": "G3"}, "v2"), "3勝クラス")
        self.assertEqual(PREP.race_class_label({"cls": "オープン", "grade": "L"}, "v2"), "オープン")
        self.assertEqual(PREP.race_class_label({"cls": "新馬", "grade": ""}, "v2"), "新馬")

    def test_graded_label_classifies_as_graded_and_open_stays_open(self):
        self.assertEqual(FEAT.classify_race_class("G1", "JRA"), "GRADED")
        self.assertEqual(FEAT.classify_race_class("オープン", "JRA"), "OP_L")

    def test_debut_stays_the_reference_and_is_not_merged_into_maiden(self):
        self.assertEqual(FEAT.classify_race_class("新馬", "JRA"), "DEBUT")
        self.assertEqual(FEAT.classify_race_class("未勝利", "JRA"), "MAIDEN")

def r(date, rn, cls, grade="", winner="h1"):
    ids = ["h1", "h2", "h3", "h4", "h5"]
    rows = [{"hid": h, "num": i + 1, "pop": i + 1, "place": 1 if h == winner else (i + 2 if h < winner else i + 1)} for i, h in enumerate(ids)]
    # keep places a clean 1..5 permutation
    order = [winner] + [h for h in ids if h != winner]
    for place, h in enumerate(order, 1):
        next(x for x in rows if x["hid"] == h)["place"] = place
    return {"date": date, "venue": "東京", "rn": rn, "surface": "芝", "dist": 2000, "cls": cls, "grade": grade, "rows": rows}

class PreparedHistory(unittest.TestCase):
    def setUp(self):
        self.races = [r("2026-01-10", 11, "オープン", "G1"), r("2026-02-10", 11, "1勝クラス")]

    def class_of_history_run(self, labeling):
        out = PREP.prepare(self.races, class_labeling=labeling)
        target = next(x for x in out if x["date"] == "2026-02-10")
        sel = target["rows"][0]["candidate_features"]["all"]["selected"]
        return [run["class_category"] for run in sel]

    def test_v1_history_run_is_open_class(self):
        self.assertEqual(self.class_of_history_run("v1"), ["OP_L"])

    def test_v2_history_run_becomes_graded(self):
        self.assertEqual(self.class_of_history_run("v2"), ["GRADED"])

    def test_same_day_and_future_races_never_supply_class(self):
        # the only G1 race is on the target date itself: no prior class may come from it
        races = [r("2026-02-10", 11, "オープン", "G1"), r("2026-02-10", 12, "1勝クラス")]
        out = PREP.prepare(races, class_labeling="v2")
        for race in out:
            for row in race["rows"]:
                self.assertEqual(row["candidate_features"]["all"]["selected"], [])

if __name__ == "__main__":
    unittest.main()
