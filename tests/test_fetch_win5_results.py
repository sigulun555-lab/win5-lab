import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "collector"))
import fetch_win5_results as f  # noqa: E402

OFFICIAL = "<td>10月24日 （土曜） 14時45分 京都10R 東京10R 新潟11R 京都11R 東京11R</td><td>10月25日 （日曜） 14時40分 東京10R 京都10R 新潟11R 東京11R 京都11R</td><td>10月31日 （土曜） 14時30分 京都9R 東京10R 京都10R 東京11R 京都11R</td>"


def race_block(rn, rows, date="2026年10月25日", venue="東京"):
    trs = "".join(f'<tr> <td class="place">{p}</td><td class="num">{n}</td><td class="horse"><a>{name}</a></td></tr>' for p, n, name in rows)
    return (f'<div class="race_result_unit" id="race_result_{rn}R"><div class="cell date">{date} 4回{venue}9日</div>'
            f'<table>{trs}</table></div>')


class OfficialLegs(unittest.TestCase):
    def test_reads_deadline_and_order_for_the_date(self):
        deadline, legs = f.official_legs(OFFICIAL, "2026-10-25")
        self.assertEqual(deadline, "14:40")
        self.assertEqual(legs, [("東京", 10), ("京都", 10), ("新潟", 11), ("東京", 11), ("京都", 11)])

    def test_other_date_has_other_deadline(self):
        self.assertEqual(f.official_legs(OFFICIAL, "2026-10-24")[0], "14:45")
        self.assertEqual(f.official_legs(OFFICIAL, "2026-10-31")[0], "14:30")

    def test_missing_date_exits(self):
        with self.assertRaises(SystemExit):
            f.official_legs(OFFICIAL, "2026-11-03")


class ParseResults(unittest.TestCase):
    def test_winner_and_scratched(self):
        html = race_block(10, [("1", 3, "A"), ("2", 5, "B"), ("取消", 7, "C"), ("除外", 8, "D")])
        out = f.parse_results(html, "2026-10-25")
        rows = out[("東京", 10)]["rows"]
        self.assertEqual([r["num"] for r in rows if r["place"] == "1"], [3])
        self.assertEqual(sorted(r["num"] for r in rows if r["place"] in ("取消", "除外")), [7, 8])

    def test_other_date_is_ignored(self):
        html = race_block(10, [("1", 3, "A")], date="2026年10月24日")
        self.assertEqual(f.parse_results(html, "2026-10-25"), {})

    def test_dead_heat_has_two_firsts(self):
        html = race_block(11, [("1", 3, "A"), ("1", 4, "B"), ("3", 5, "C")])
        rows = f.parse_results(html, "2026-10-25")[("東京", 11)]["rows"]
        self.assertEqual(len([r for r in rows if r["place"] == "1"]), 2)


class FakeNet:
    def __init__(self, official, srl_links, ses_html):
        self.official, self.srl_links, self.ses_html = official, srl_links, ses_html

    def get(self, url):
        return self.official

    def post(self, path, cname):
        if cname == f.TOP_RESULTS:
            return "".join(f"doAction('/JRADB/accessS.html', '{s}')" for s in self.srl_links)
        if cname.startswith("pw01srl"):
            return f"doAction('/JRADB/accessS.html', 'pw01ses{cname[7:]}')"
        return self.ses_html


class Build(unittest.TestCase):
    def full_html(self, drop=None, dead_heat=None):
        blocks = []
        for rn, venue in [(10, "東京"), (10, "京都"), (11, "新潟"), (11, "東京"), (11, "京都")]:
            if drop == (venue, rn):
                continue
            rows = [("1", 1, "W"), ("2", 2, "X")]
            if dead_heat == (venue, rn):
                rows = [("1", 1, "W"), ("1", 2, "X")]
            blocks.append(race_block(rn, rows, venue=venue))
        return "".join(blocks)

    def test_builds_five_rows(self):
        net = FakeNet(OFFICIAL, ["pw01srl0005202604090020261025/AA"], self.full_html())
        deadline, rows, problems = f.build("2026-10-25", net)
        self.assertEqual(problems, [])
        self.assertEqual(len(rows), 5)
        self.assertEqual({r["winner_no"] for r in rows}, {1})

    def test_missing_race_is_reported_not_guessed(self):
        net = FakeNet(OFFICIAL, ["pw01srl0005202604090020261025/AA"], self.full_html(drop=("京都", 11)))
        _, rows, problems = f.build("2026-10-25", net)
        self.assertEqual(len(rows), 4)
        self.assertTrue(any("京都11R" in p for p in problems))

    def test_dead_heat_is_not_auto_resolved(self):
        net = FakeNet(OFFICIAL, ["pw01srl0005202604090020261025/AA"], self.full_html(dead_heat=("新潟", 11)))
        _, rows, problems = f.build("2026-10-25", net)
        self.assertEqual(len(rows), 4)
        self.assertTrue(any("同着" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
