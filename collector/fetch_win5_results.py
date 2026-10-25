#!/usr/bin/env python3
"""JRA公式の開催日結果ページから、WIN5対象5レースの1着馬を取り出して結果CSVを作る（標準ライブラリのみ）。

  python3 collector/fetch_win5_results.py --date 2026-10-25 --output data/win5_joint/2026-10-25/win5_official_results.csv

- 対象5レースは、JRA公式の「WIN5対象レース一覧」の並び（会場・レース番号）で決める。
- 5レースすべてで、1着がちょうど1頭、着順が確定している場合だけ書き出す。1つでも欠ける・同着がある・
  結果が未確定のときは、何も書かずに終了コード2で終わる（推測で埋めない）。
- 予想ファイルには一切触らない。出力は結果CSVのみ（date, leg, winner_no, winner_name, scratched_nos,
  official_source, verified_at_jst）。scratched_nos は、結果ページで「取消」「除外」と表示された馬番。
- `--verify` で、別の結果CSV（列 date, leg, winner_no）と突き合わせる（過去開催での動作確認用）。
"""
import argparse
import csv
import datetime
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jra_odds_snapshot as c  # noqa: E402

TOP_RESULTS = "pw01sli00/AF"  # 「レース結果」トップ（当月の開催日リンクがある）


def text(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def official_legs(official_html, date):
    """公式一覧の行 `M月D日 （曜） HH時MM分 <5レース>` から (締切, [(会場, レース番号)...]) を返す。"""
    d = datetime.date.fromisoformat(date)
    t = re.sub(r"\s+", " ", c.text(official_html))
    m = re.search(rf"{d.month}月{d.day}日 （[^）]*） (\d+)時(\d+)分((?: \S+?\d+R){{5}})", t)
    if not m:
        raise SystemExit(f"公式のWIN5対象レース一覧に {date} の行が見つかりません")
    legs = re.findall(r"(\S+?)(\d+)R", m.group(3))
    return f"{int(m.group(1)):02d}:{m.group(2)}", [(v, int(n)) for v, n in legs]


def find_day_pages(net, date):
    d8 = date.replace("-", "")
    ym = d8[:6]
    h = net.post("/JRADB/accessS.html", TOP_RESULTS)
    if not h:
        raise SystemExit("レース結果トップを取得できませんでした")
    seen = set()
    while True:
        days = re.findall(r"doAction\('/JRADB/accessS\.html',\s*'(pw01srl\w+" + d8 + r"/\w+)'\)", h)
        if days:
            return sorted(set(days))
        months = dict(re.findall(r"doAction\('/JRADB/accessS\.html',\s*'(pw01skl10(\d{6})/\w+)'\)", h))
        months = {v: k for k, v in months.items()}
        if ym not in months or ym in seen:
            raise SystemExit(f"{date} の開催日リンクが見つかりません（結果が未公開の可能性）")
        seen.add(ym)
        h = net.post("/JRADB/accessS.html", months[ym])
        if not h:
            raise SystemExit("月の一覧を取得できませんでした")


def parse_results(ses_html, date):
    """開催日の結果ページから、{(会場, レース番号): {'rows': [...]}} を返す。"""
    out = {}
    parts = re.split(r'<div class="race_result_unit" id="race_result_(\d+)R">', ses_html)
    for k in range(1, len(parts), 2):
        rn = int(parts[k])
        b = parts[k + 1]
        m = re.search(r'class="cell date">(\d{4})年(\d+)月(\d+)日.*?(\d+)回(\S+?)(\d+)日', b, re.S)
        if not m:
            continue
        got = datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        if got != date:
            continue
        venue = m.group(5)
        rows = []
        for tr in re.findall(r"<tr>(\s*<td class=\"place\">.*?)</tr>", b, re.S):
            def cell(cls):
                mm = re.search(r'<td class="' + cls + r'"[^>]*>(.*?)</td>', tr, re.S)
                return mm.group(1) if mm else ""
            place = text(cell("place"))
            num = text(cell("num"))
            name = text(re.sub(r'<div class="icon.*?</div>', "", cell("horse")))
            rows.append({"place": place, "num": int(num) if num.isdigit() else None, "name": name})
        out[(venue, rn)] = {"rows": rows}
    return out


def build(date, net=None):
    net = net or c.Net()
    official = net.get(c.OFFICIAL_URL)
    if not official:
        raise SystemExit("JRA公式のWIN5対象レース一覧を取得できませんでした")
    deadline, legs = official_legs(official, date)
    results = {}
    for srl in find_day_pages(net, date):
        h = net.post("/JRADB/accessS.html", srl)
        if not h:
            continue
        ses = [b for b in re.findall(r"doAction\('/JRADB/accessS\.html',\s*'(pw01ses\w+/\w+)'\)", h)]
        ses = [s for s in ses if srl.replace("pw01srl", "").split("/")[0] in s] or ses
        if not ses:
            continue
        sh = net.post("/JRADB/accessS.html", ses[0])
        if sh:
            results.update(parse_results(sh, date))
    now = datetime.datetime.now(c.JST).isoformat(timespec="seconds")
    rows, problems = [], []
    for i, (venue, rn) in enumerate(legs, 1):
        r = results.get((venue, rn))
        if not r:
            problems.append(f"leg {i} {venue}{rn}R: 結果ページが見つかりません（未確定または未公開）")
            continue
        firsts = [x for x in r["rows"] if x["place"] == "1"]
        if len(firsts) != 1:
            problems.append(f"leg {i} {venue}{rn}R: 1着が{len(firsts)}頭（同着・未確定は自動処理しません）")
            continue
        scratched = sorted(x["num"] for x in r["rows"] if x["place"] in ("取消", "除外") and x["num"] is not None)
        rows.append({"date": date, "leg": i, "winner_no": firsts[0]["num"], "winner_name": firsts[0]["name"],
                     "scratched_nos": ";".join(map(str, scratched)),
                     "official_source": "JRA公式 開催日結果ページ（https://www.jra.go.jp/JRADB/accessS.html）",
                     "verified_at_jst": now})
    return deadline, rows, problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--verify", type=Path, help="突き合わせる結果CSV（date, leg, winner_no または winning_horse_number）。過去開催での動作確認用")
    a = ap.parse_args(argv)
    deadline, rows, problems = build(a.date)
    if problems or len(rows) != 5:
        print("書き出しません：" + " / ".join(problems), file=sys.stderr)
        raise SystemExit(2)
    if a.verify:
        ref = {}
        for r in csv.DictReader(a.verify.open(encoding="utf-8-sig")):
            v = str(r.get("winner_no") or r.get("winning_horse_number") or "").strip()
            if v:
                ref[(r["date"], int(float(r["leg"])))] = int(float(v))
        if not any(k[0] == a.date for k in ref):
            raise SystemExit(f"--verify のCSVに {a.date} の行がありません")
        bad = [(r["leg"], r["winner_no"], ref.get((a.date, r["leg"]))) for r in rows if ref.get((a.date, r["leg"])) != r["winner_no"]]
        print("verify:", "一致" if not bad else f"不一致 {bad}")
        if bad:
            raise SystemExit(3)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"締切 {deadline}、1着馬 {[(r['leg'], r['winner_no'], r['winner_name']) for r in rows]}")
    print(f"Wrote: {a.output}")


if __name__ == "__main__":
    main()
