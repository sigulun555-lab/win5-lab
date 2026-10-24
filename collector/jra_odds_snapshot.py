#!/usr/bin/env python3
"""JRA公式の出馬表ページから、これから発走するレースの単勝オッズを保存する（標準ライブラリのみ）。

  python3 collector/jra_odds_snapshot.py                 # 今日(JST)の、これから75分以内に発走するレース
  python3 collector/jra_odds_snapshot.py --date 2026-10-24 --window-min 120
  python3 collector/jra_odds_snapshot.py --all           # 今日の全レース（動作確認用）

1レース×1回の取得ごとに、data/odds/<日付>.jsonl に1行を追記します（追記のみ、上書きなし）。
同じレースで、JRAの「オッズは○時○分現在」が前回と同じときは、保存しません。
目的：実際の単勝オッズを基準にした予想の検証に使うため、発走前のオッズを貯めます（お金を賭けない記録）。
"""
import argparse, datetime, html, json, os, re, sys, time, urllib.request, urllib.parse

BASE = "https://www.jra.go.jp"
JST = datetime.timezone(datetime.timedelta(hours=9))
UA = "Mozilla/5.0 (win5-lab odds snapshot; contact via repository)"


def post(path, cname, retries=3):
    data = urllib.parse.urlencode({"cname": cname}).encode()
    for k in range(retries):
        try:
            req = urllib.request.Request(BASE + path, data=data, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
            if len(body) > 5000:
                return body.decode("cp932", errors="replace")
        except Exception as e:  # noqa: BLE001
            print(f"  取得失敗({path} {cname}): {e}", file=sys.stderr)
        time.sleep(2 * (k + 1))
    return None


def text(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def venue_pages(index_html, date8):
    """出馬表トップから、対象日の開催（競馬場）ページの cname を集める。"""
    out = []
    for m in re.finditer(r"doAction\('/JRADB/accessD\.html',\s*'(pw01drl\d+" + date8 + r"/[0-9A-F]+)'\)", index_html):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def races_on_venue(v_html):
    """開催ページの表から、レース番号・発走時刻・レース名・WIN5対象かどうか・出馬表の cname を取り出す。"""
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", v_html, re.S):
        mc = re.search(r'class="race_num"[^>]*>.*?CNAME=(pw01dde\d+/[0-9A-F]+)', tr, re.S)
        mt = re.search(r'<td class="time[^"]*">\s*(?:<strong>)?\s*(\d+)時(\d+)分', tr)
        if not (mc and mt):
            continue
        rn = re.search(r"pw01dde01\d{2}\d{6}\d{2}(\d{2})\d{8}/", mc.group(1))
        mw = re.search(r'<td class="win5">(.*?)</td>', tr, re.S)
        out.append({
            "cname": mc.group(1),
            "race_no": int(rn.group(1)) if rn else None,
            "post_time": f"{int(mt.group(1)):02d}:{mt.group(2)}",
            "name": text(re.search(r'<td class="race_name">(.*?)</td>', tr, re.S).group(1)) if re.search(r'<td class="race_name">', tr) else "",
            "win5": bool(mw and re.search(r"\S", re.sub(r"<[^>]+>", "", mw.group(1)))) or bool(mw and "img" in mw.group(1)),
        })
    return out


def parse_race(h):
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    flat = re.sub(r"(\|\s*)+", "|", re.sub(r"<[^>]+>", "|", plain))
    flat = re.sub(r"\s*\n\s*", "", flat)
    mo = re.search(r"オッズは(\d+)時(\d+)分現在", re.sub(r"<[^>]+>", "", plain))
    odds_time = f"{int(mo.group(1)):02d}:{mo.group(2)}" if mo else None
    hd = re.search(r"発走時刻：\|(\d+)時(\d+)分\|天候\|(.*?)\|(芝|ダート|障害.*?)\|(.*?)\|", flat)
    surface = going = weather = None
    if hd:
        weather, surface, going = hd.group(3), hd.group(4), hd.group(5)
    dist = re.search(r"([\d,]{4,5})\|メートル", flat)
    cls = re.search(r'<div class="cell class">(.*?)</div>', plain, re.S)
    rname = re.search(r'class="race_name">(.*?)<', plain, re.S)
    horses = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", plain, re.S):
        if 'class="num"' not in tr or 'class="horse"' not in tr:
            continue
        cells = {}
        for cls_, body in re.findall(r'<td class="([a-z_ ]+)"[^>]*>(.*?)</td>', tr, re.S):
            cells.setdefault(cls_.split()[0], text(body))
        if not cells.get("num", "").isdigit():
            continue
        ht = cells.get("horse", "")
        mh = re.match(r"(\S+) (\d+\.\d) \((\d+) 番人気", ht)
        jt = cells.get("jockey", "")
        mj = re.match(r"(\S+) (\d+\.\d) kg (.+)", jt)
        horses.append({
            "num": int(cells["num"]),
            "name": mh.group(1) if mh else ht.split(" ")[0],
            "odds": float(mh.group(2)) if mh else None,
            "pop": int(mh.group(3)) if mh else None,
            "sexage": mj.group(1) if mj else None,
            "wt": float(mj.group(2)) if mj else None,
            "jockey": mj.group(3) if mj else jt,
            "status": "" if mh else ht[:40],
        })
    return {
        "odds_time": odds_time, "weather": weather, "surface": surface, "going": going,
        "dist": int(dist.group(1).replace(",", "")) if dist else None,
        "cls": text(cls.group(1)) if cls else None, "race_name": text(rname.group(1)) if rname else None,
        "horses": horses,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD（既定：今日のJST）")
    ap.add_argument("--window-min", type=int, default=75, help="今から何分以内に発走するレースを取るか")
    ap.add_argument("--all", action="store_true", help="時刻に関係なく全レースを取る")
    ap.add_argument("--out", default=os.path.join("data", "odds"))
    ap.add_argument("--delay", type=float, default=0.4, help="リクエストの間隔（秒）")
    a = ap.parse_args()
    now = datetime.datetime.now(JST)
    date = datetime.date.fromisoformat(a.date) if a.date else now.date()
    date8 = date.strftime("%Y%m%d")
    idx = post("/JRADB/accessD.html", "pw01dli00/F3")
    if not idx:
        print("出馬表トップを取得できませんでした。", file=sys.stderr); return 1
    vps = venue_pages(idx, date8)
    if not vps:
        print(f"{date} の開催は見つかりませんでした（開催なし、または出馬表が未掲載）。"); return 0
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"{date}.jsonl")
    seen = set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                d = json.loads(line); seen.add((d["venue_code"], d["race_no"], d["odds_time"]))
            except Exception:  # noqa: BLE001
                pass
    saved = 0
    for vc in vps:
        time.sleep(a.delay)
        vh = post("/JRADB/accessD.html", vc)
        if not vh:
            continue
        vname = re.search(r"(\d+回(\S+?)\d+日)", text(vh))
        venue = vname.group(2) if vname else vc[8:10]
        vcode = vc[len("pw01drl00"):len("pw01drl00") + 2]
        for rc in races_on_venue(vh):
            ph, pm = map(int, rc["post_time"].split(":"))
            post_dt = datetime.datetime.combine(date, datetime.time(ph, pm), JST)
            minutes = (post_dt - now).total_seconds() / 60
            if not a.all and not (-2 <= minutes <= a.window_min):
                continue
            time.sleep(a.delay)
            rh = post("/JRADB/accessD.html", rc["cname"])
            if not rh:
                continue
            r = parse_race(rh)
            key = (vcode, rc["race_no"], r["odds_time"])
            if not r["odds_time"] or key in seen or not r["horses"]:   # 発走後は結果ページになり、オッズがない
                continue
            seen.add(key)
            rec = {"fetched_at": now.isoformat(timespec="seconds"), "date": str(date), "venue": venue, "venue_code": vcode,
                   "race_no": rc["race_no"], "post_time": rc["post_time"], "win5": rc["win5"], "source": "JRA公式 出馬表"}
            rec.update(r)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            saved += 1
            print(f"保存: {venue}{rc['race_no']}R 発走{rc['post_time']} オッズ{r['odds_time']}現在 {len(r['horses'])}頭")
    print(f"{date}: {saved}件を保存しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
