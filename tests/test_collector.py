import datetime, json, os, sys, tempfile, types, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import jra_odds_snapshot as c  # noqa: E402

JST = c.JST
DATE = datetime.date(2026, 10, 24)

OFFICIAL_HTML = """<table><tr><td>10月18日<span class="youbi">（日曜）</span></td><td><span class="close"><span class="buy"><strong>14時40分</strong></span></span></td>
<td><span class="detail"><span class="inner"><span class="race">東京10R</span></span></span></td></tr>
<tr>
<td>10月24日<span class="youbi">（土曜）</span></td>
<td>
<span class="close"><span class="buy"><strong>14時45分</strong></span></span>
</td>
<td><span class="detail"><span class="inner"><span class="race">京都10R</span></span></span></td>
<td><span class="detail"><span class="inner"><span class="race">東京10R</span></span></span></td>
<td><span class="detail"><span class="inner"><span class="race">新潟11R</span></span></span></td>
<td><span class="detail"><span class="inner"><span class="race">京都11R</span></span></span></td>
<td><span class="detail"><span class="inner"><span class="race">東京11R</span></span></span></td>
</tr></table>"""

W5 = [("京都", 10, 1), ("東京", 10, 2), ("新潟", 11, 3), ("京都", 11, 4), ("東京", 11, 5)]


def race_row(no, hhmm, cname, leg=None):
    h, m = hhmm.split(":")
    cls = "time on" if leg else "time"
    t = f"<strong>{int(h)}時{m}分</strong>" if leg else f"{int(h)}時{m}分"
    w5 = f'<a href="#"><img src="x.png" alt="ウインファイヴ {leg}レース目"></a>' if leg else ""
    return (f'<tr><th scope="row" class="race_num"><a href="/JRADB/accessD.html?CNAME={cname}"><img alt="{no}レース"></a></th>'
            f'<td class="{cls}">{t}</td><td class="race_name"><div>レース{no}</div></td><td class="win5">{w5}</td></tr>')


def venue_html(name, rows):
    return f"<html>2026年10月24日（土曜）4回{name}8日 " + "<table>" + "".join(rows) + "</table></html>" + " " * 6000


def race_html(odds_time, nums):
    horses = "".join(
        f'<tr><td class="waku">1</td><td class="num">{n}</td><td class="horse">馬{n} {2.0 + n} ({n} 番人気 ) (1.0.0.1)</td>'
        f'<td class="jockey">牡4/鹿 55.0 kg 騎手{n}</td></tr>' for n in nums)
    return (f"<html>発走時刻：<strong>15時00分</strong>天候小雨芝稍重 1,600メートル オッズは{odds_time}現在 "
            f'<table>{horses}</table></html>' + " " * 6000)


class FakeNet:
    def __init__(self, w5_flags=True, drop_flag=None, extra_flag=False, official_ok=True, odds_time="14時20分"):
        self.calls = 0
        self.official_ok = official_ok
        self.odds_time = odds_time
        venues = {"京都": [(10, "14:50", 1), (11, "15:30", 4), (12, "16:00", None)], "東京": [(10, "15:01", 2), (11, "15:45", 5)],
                  "新潟": [(11, "15:15", 3), (9, "13:00", None)]}
        self.pages = {"pw01dli00/F3": "".join(
            f"doAction('/JRADB/accessD.html','pw01drl00{i}2026040820261024/AA');" for i in range(3)) + " " * 6000}
        for i, (vn, rs) in enumerate(venues.items()):
            rows = []
            for no, t, leg in rs:
                flag = leg if (w5_flags and (vn, no) != drop_flag) else None
                rows.append(race_row(no, t, f"pw01dde01{i}{no:02d}/AB", flag))
                self.pages[f"pw01dde01{i}{no:02d}/AB"] = race_html(self.odds_time, [1, 2, 3])
            if extra_flag and vn == "京都":
                rows.append(race_row(12, "16:00", "pw01dde0199/AB", 3))   # 公式にない印が付いたレース
            self.pages[f"pw01drl00{i}2026040820261024/AA"] = venue_html(vn, rows)

    def post(self, path, cname):
        self.calls += 1
        return self.pages.get(cname)

    def get(self, url):
        self.calls += 1
        return OFFICIAL_HTML + " " * 6000 if self.official_ok else None


def args(out, **kw):
    d = dict(date=str(DATE), scope="both", window_min=75, all=False, out=out)
    d.update(kw)
    return types.SimpleNamespace(**d)


NOW = datetime.datetime(2026, 10, 24, 14, 20, tzinfo=JST)


class Parse(unittest.TestCase):
    def test_official_row_for_the_date(self):
        o = c.parse_official(OFFICIAL_HTML, DATE)
        self.assertEqual(o["deadline"], "14:45")
        self.assertEqual([(r["leg"], r["venue"], r["race_no"]) for r in o["races"]],
                         [(1, "京都", 10), (2, "東京", 10), (3, "新潟", 11), (4, "京都", 11), (5, "東京", 11)])

    def test_official_missing_date(self):
        self.assertIsNone(c.parse_official(OFFICIAL_HTML, datetime.date(2026, 10, 25)))

    def test_race_rows_with_strong_time_and_win5_leg(self):
        rows = c.races_on_venue(venue_html("京都", [race_row(10, "14:50", "pw01dde0108/AB", 1), race_row(9, "13:00", "pw01dde0109/AB")]))
        self.assertEqual([(r["race_no"], r["post_time"], r["win5_leg"], r["win5"]) for r in rows], [(10, "14:50", 1, True), (9, "13:00", None, False)])

    def test_parse_race(self):
        r = c.parse_race(race_html("14時20分", [1, 2]))
        self.assertEqual(r["odds_time"], "14:20")
        self.assertEqual([(h["num"], h["odds"], h["pop"]) for h in r["horses"]], [(1, 3.0, 1), (2, 4.0, 2)])


class Verify(unittest.TestCase):
    OFF = c.parse_official(OFFICIAL_HTML, DATE)

    def test_ok(self):
        self.assertTrue(c.verify_win5(self.OFF, W5)["ok"])

    def test_missing(self):
        v = c.verify_win5(self.OFF, W5[:-1])
        self.assertFalse(v["ok"]); self.assertEqual(v["missing"], [["東京", 11]])

    def test_extra(self):
        v = c.verify_win5(self.OFF, W5 + [("東京", 12, 5)])
        self.assertFalse(v["ok"]); self.assertEqual(v["extra"], [["東京", 12]])

    def test_duplicate(self):
        v = c.verify_win5(self.OFF, W5 + [("京都", 10, 1)])
        self.assertFalse(v["ok"]); self.assertEqual(v["duplicates"], [["京都", 10]])

    def test_leg_mismatch(self):
        v = c.verify_win5(self.OFF, [("京都", 10, 2), ("東京", 10, 1)] + W5[2:])
        self.assertFalse(v["ok"]); self.assertEqual(sorted(v["leg_mismatch"]), [["京都", 10], ["東京", 10]])

    def test_official_unavailable(self):
        self.assertFalse(c.verify_win5(None, W5)["ok"])


class Run(unittest.TestCase):
    def read(self, p):
        with open(p, encoding="utf-8") as f:
            return [json.loads(l) for l in f]

    def test_normal_day(self):
        with tempfile.TemporaryDirectory() as out:
            code, log = c.run(args(out, window_min=120), FakeNet(), NOW)   # 15:45発走の東京11Rも窓に入れる
            self.assertEqual(code, 0, log["issues"])
            s = self.read(os.path.join(out, "win5", "2026-10-24.jsonl"))
            self.assertEqual(len(s), 1)
            self.assertEqual([(r["venue"], r["race_no"], r["leg"]) for r in s[0]["races"]], W5)   # ちょうど5レース、順番どおり
            self.assertEqual(len({(r["venue"], r["race_no"]) for r in s[0]["races"]}), 5)
            a = self.read(os.path.join(out, "2026-10-24.jsonl"))
            self.assertEqual(sum(1 for r in a if r["win5"]), 5)                                    # 通常の収集にもWIN5の印が付く
            self.assertTrue(any(not r["win5"] for r in a))                                          # 通常レースが混ざるのは設計どおり
            lg = self.read(os.path.join(out, "logs", "2026-10-24.jsonl"))[0]
            for k in ("run_at", "sources", "official", "flagged", "verification", "saved"):
                self.assertIn(k, lg)
            self.assertTrue(lg["verification"]["ok"])

    def test_second_run_same_odds_not_duplicated(self):
        with tempfile.TemporaryDirectory() as out:
            c.run(args(out), FakeNet(), NOW)
            code, log = c.run(args(out), FakeNet(), NOW)
            self.assertEqual(code, 0)
            self.assertEqual(len(self.read(os.path.join(out, "win5", "2026-10-24.jsonl"))), 1)
            self.assertEqual(log["saved"]["all"], 0)

    def test_new_odds_time_appends(self):
        with tempfile.TemporaryDirectory() as out:
            c.run(args(out), FakeNet(odds_time="14時20分"), NOW)
            c.run(args(out), FakeNet(odds_time="14時30分"), NOW + datetime.timedelta(minutes=10))
            self.assertEqual(len(self.read(os.path.join(out, "win5", "2026-10-24.jsonl"))), 2)

    def test_missing_flag_blocks_win5_set(self):
        with tempfile.TemporaryDirectory() as out:
            code, log = c.run(args(out), FakeNet(drop_flag=("東京", 11)), NOW)
            self.assertEqual(code, 2)
            self.assertFalse(os.path.exists(os.path.join(out, "win5", "2026-10-24.jsonl")))
            self.assertTrue(any("東京11R" in i for i in log["issues"]))

    def test_duplicate_flag_blocks_win5_set(self):
        with tempfile.TemporaryDirectory() as out:
            code, log = c.run(args(out), FakeNet(extra_flag=True), NOW)
            self.assertEqual(code, 2)
            self.assertFalse(os.path.exists(os.path.join(out, "win5", "2026-10-24.jsonl")))

    def test_official_unavailable_blocks_win5_set(self):
        with tempfile.TemporaryDirectory() as out:
            code, log = c.run(args(out), FakeNet(official_ok=False), NOW)
            self.assertEqual(code, 2)
            self.assertFalse(os.path.exists(os.path.join(out, "win5", "2026-10-24.jsonl")))

    def test_scope_all_does_not_write_win5(self):
        with tempfile.TemporaryDirectory() as out:
            code, _ = c.run(args(out, scope="all"), FakeNet(), NOW)
            self.assertEqual(code, 0)
            self.assertFalse(os.path.exists(os.path.join(out, "win5")))

    def test_scope_win5_does_not_write_all(self):
        with tempfile.TemporaryDirectory() as out:
            code, _ = c.run(args(out, scope="win5"), FakeNet(), NOW)
            self.assertEqual(code, 0)
            self.assertFalse(os.path.exists(os.path.join(out, "2026-10-24.jsonl")))

    def test_after_first_race_no_win5_set(self):
        with tempfile.TemporaryDirectory() as out:
            code, log = c.run(args(out), FakeNet(), datetime.datetime(2026, 10, 24, 15, 0, tzinfo=JST))
            self.assertEqual(code, 0)
            self.assertFalse(log["saved"]["win5_set"])

    def test_no_meeting_day(self):
        with tempfile.TemporaryDirectory() as out:
            code, log = c.run(args(out, date="2026-10-27"), FakeNet(), NOW)
            self.assertEqual(code, 0)
            self.assertTrue(log["issues"])


if __name__ == "__main__":
    unittest.main()
