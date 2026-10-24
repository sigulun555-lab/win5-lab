#!/usr/bin/env python3
"""指定した開催日の出走馬について、JRA公式の競走馬情報ページから過去の出走成績を保存する（標準ライブラリのみ）。
お金を賭けない、記録上の検証用。保存するのは参考情報で、勝率の補正には使わない（rules 第9項）。

  python3 collector/horse_history.py --date 2026-10-25 --out data/horse_history

出力：<out>/<日付>.json
  races: 開催日のレース一覧（会場・番号・WIN5の印・出走馬の馬番／馬名／騎手／斤量／hid）
  horses: hid ごとの、過去の出走成績（年月日・場・レース名・距離・馬場・頭数・人気・着順・騎手・斤量・馬体重・タイム・Rt・1着馬）
          と、プロフィール（父・母の父など）
取得できなかったものは、そのまま欠けた状態にする（推測で埋めない）。
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jra_odds_snapshot as c  # noqa: E402

JST = c.JST


def race_runners(h):
    """出馬表のページから、馬番・馬名・騎手・斤量・hid を取り出す。"""
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", plain, re.S):
        if 'class="num"' not in tr or 'class="horse"' not in tr:
            continue
        mn = re.search(r'<td class="num"[^>]*>(.*?)</td>', tr, re.S)
        num = c.text(mn.group(1)) if mn else ""
        mh = re.search(r'accessU\.html\?CNAME=(pw01dud\w+/\w+)', tr)
        mname = re.search(r'<div class="name">(.*?)</div>', tr, re.S)
        mj = re.search(r'<p class="jockey">(.*?)</p>', tr, re.S)
        mw = re.search(r'<p class="weight">(.*?)</p>', tr, re.S)
        if not num.isdigit() or not mh:
            continue
        out.append({
            "num": int(num),
            "name": c.text(mname.group(1)) if mname else None,
            "jockey": c.text(mj.group(1)) if mj else None,
            "weight": c.text(mw.group(1)) if mw else None,
            "hid": mh.group(1),
        })
    return out


def parse_horse(h):
    """競走馬情報ページから、プロフィールと過去の出走成績を取り出す。"""
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    prof = {}
    for k in ("父", "母", "母の父", "性別", "馬齢", "毛色", "調教師名"):
        m = re.search(r"<dt>\s*" + k + r"\s*</dt>\s*<dd>(.*?)</dd>", plain, re.S)
        if m:
            prof[k] = c.text(m.group(1))
    runs = []
    for tbl in re.findall(r'<table class="basic narrow-xy striped">(.*?)</table>', plain, re.S):
        if "年月日" not in tbl:
            continue
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", tbl, re.S):
            tds = [c.text(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) < 12 or not re.match(r"\d{4}年\d+月\d+日", tds[0]):
                continue
            runs.append({
                "date": tds[0], "venue": tds[1], "race": tds[2], "course": tds[3], "going": tds[4],
                "field": tds[5], "pop": tds[6], "place": tds[7], "jockey": tds[8], "weight": tds[9],
                "bw": tds[10], "time": tds[11], "rt": tds[12] if len(tds) > 12 else "",
                "winner": tds[13] if len(tds) > 13 else "",
            })
    return {"profile": prof, "runs": runs}


def run(date, out_dir, workers=4):
    d8 = date.replace("-", "")
    net = c.Net()
    idx = net.post("/JRADB/accessD.html", "pw01dli00/F3")
    if not idx:
        raise SystemExit("出馬表トップを取得できませんでした")
    venues = c.venue_pages(idx, d8)
    races = []
    for vc in venues:
        vh = net.post("/JRADB/accessD.html", vc[1] if isinstance(vc, tuple) else vc)
        if not vh:
            print(f"開催ページの取得失敗: {vc}", file=sys.stderr)
            continue
        vname = c.venue_name(vh)
        for rc in c.races_on_venue(vh):
            rh = net.post("/JRADB/accessD.html", rc["cname"])
            if not rh:
                print(f"出馬表の取得失敗: {vname}{rc['race_no']}R", file=sys.stderr)
                continue
            info = c.parse_race(rh)
            races.append({"venue": vname, "race_no": rc["race_no"], "name": rc["name"], "post_time": rc["post_time"],
                          "win5_leg": rc.get("win5_leg"), "surface": info["surface"], "dist": info["dist"],
                          "going": info["going"], "runners": race_runners(rh)})
    hids = sorted({r["hid"] for race in races for r in race["runners"]})
    print(f"{len(races)}レース、{len(hids)}頭")

    def one(hid):
        h = c.Net().post("/JRADB/accessU.html", hid)
        return hid, (parse_horse(h) if h else None)

    horses = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (hid, v) in enumerate(ex.map(one, hids), 1):
            if v is not None:
                horses[hid] = v
            if i % 50 == 0:
                print(i, "/", len(hids), flush=True)
    missing = [h for h in hids if h not in horses]
    rec = {"date": date, "fetched_at": datetime.datetime.now(JST).isoformat(timespec="seconds"),
           "source": "JRA公式 出馬表・競走馬情報", "missing_horses": missing, "races": races, "horses": horses}
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, separators=(",", ":"))
    print(f"保存: {path}（取得できなかった馬 {len(missing)}頭）")
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="開催日 YYYY-MM-DD")
    ap.add_argument("--out", default="data/horse_history")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args(argv)
    run(a.date, a.out, a.workers)


if __name__ == "__main__":
    main()
