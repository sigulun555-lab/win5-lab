#!/usr/bin/env python3
"""JRA公式の出馬表ページから単勝オッズを保存する（標準ライブラリのみ）。お金を賭けない、記録上の検証用。

  python3 collector/jra_odds_snapshot.py                       # 既定：scope=both（下の2つを両方）
  python3 collector/jra_odds_snapshot.py --scope all           # 通常の収集：これから発走するレースを odds/<日付>.jsonl に追記
  python3 collector/jra_odds_snapshot.py --scope win5          # WIN5だけ：公式の対象5レースを照合し、odds/win5/<日付>.jsonl に5レース1組で追記

収集は2つに分けています。
  all   ：発走前のレースを1レース1行で保存（検証用データ）。WIN5のレースにも win5=true と win5_leg(1〜5) を付ける。
  win5  ：JRA公式の「WIN5対象レース」一覧を取得し、開催ページの印と会場・レース番号で照合する。
          対象がちょうど5レースで、欠落・余分・重複・順番違いがないときだけ、5レース1組で保存する。
          1つでも合わなければ保存せず、理由をログに残して、終了コード2で終わる。
実行のたびに、取得元・取得時刻・対象レース一覧・照合結果・保存結果を odds/logs/<日付>.jsonl に1行追記する。
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://www.jra.go.jp"
OFFICIAL_URL = BASE + "/kouza/win5/info/racelist.html"
JST = datetime.timezone(datetime.timedelta(hours=9))
UA = "Mozilla/5.0 (win5-lab odds snapshot; contact via repository)"


# ---------------------------------------------------------------- 取得
class Net:
    """JRA公式への取得。テストでは、同じ形のダミーに差し替える。"""

    def __init__(self, delay=0.4):
        self.delay = delay
        self.calls = 0

    def _read(self, req, retries=3):
        for k in range(retries):
            try:
                time.sleep(self.delay)
                self.calls += 1
                with urllib.request.urlopen(req, timeout=40) as r:
                    body = r.read()
                if len(body) > 5000:
                    return body.decode("cp932", errors="replace")
            except Exception as e:  # noqa: BLE001
                print(f"  取得失敗({req.full_url}): {e}", file=sys.stderr)
            time.sleep(2 * (k + 1))
        return None

    def post(self, path, cname):
        data = urllib.parse.urlencode({"cname": cname}).encode()
        return self._read(urllib.request.Request(BASE + path, data=data, headers={"User-Agent": UA}))

    def get(self, url):
        return self._read(urllib.request.Request(url, headers={"User-Agent": UA}))


def text(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


# ---------------------------------------------------------------- 解析
def venue_pages(index_html, date8):
    """出馬表トップから、対象日の開催（競馬場）ページの cname を集める。"""
    out = []
    for m in re.finditer(r"doAction\('/JRADB/accessD\.html',\s*'(pw01drl\d+" + date8 + r"/[0-9A-F]+)'\)", index_html):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def venue_name(v_html):
    m = re.search(r"(\d+回(\S+?)\d+日)", text(v_html))
    return m.group(2) if m else None


def races_on_venue(v_html):
    """開催ページの表から、レース番号・発走時刻・レース名・WIN5の印（何レース目か）・出馬表の cname を取り出す。"""
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", v_html, re.S):
        mc = re.search(r'class="race_num"[^>]*>.*?CNAME=(pw01dde\d+/[0-9A-F]+)', tr, re.S)
        mt = re.search(r'<td class="time[^"]*">\s*(?:<strong>)?\s*(\d+)時(\d+)分', tr)
        if not (mc and mt):
            continue
        rn = re.search(r'alt="(\d+)レース"', tr)
        mw = re.search(r'<td class="win5">(.*?)</td>', tr, re.S)
        leg = None
        if mw:
            ml = re.search(r"ウインファイヴ\s*(\d)\s*レース目", mw.group(1))
            if ml:
                leg = int(ml.group(1))
        name = re.search(r'<td class="race_name">(.*?)</td>', tr, re.S)
        out.append({
            "cname": mc.group(1),
            "race_no": int(rn.group(1)) if rn else None,
            "post_time": f"{int(mt.group(1)):02d}:{mt.group(2)}",
            "name": text(name.group(1)) if name else "",
            "win5_leg": leg,
            "win5": leg is not None,
        })
    return out


def parse_official(page_html, date):
    """JRA公式の「WIN5対象レース」一覧から、指定日の行（締切時刻と5レース）を取り出す。"""
    for m in re.finditer(r"<tr>\s*<td>(\d+)月(\d+)日<span class=\"youbi\">（.曜）</span></td>(.*?)</tr>", page_html, re.S):
        if (int(m.group(1)), int(m.group(2))) != (date.month, date.day):
            continue
        body = m.group(3)
        mt = re.search(r"<strong>(\d+)時(\d+)分</strong>", body)
        races = []
        for i, r in enumerate(re.findall(r'<span class="race">(\D+?)(\d+)R</span>', body), 1):
            races.append({"leg": i, "venue": r[0].strip(), "race_no": int(r[1])})
        return {"date": str(date), "deadline": f"{int(mt.group(1)):02d}:{mt.group(2)}" if mt else None,
                "races": races, "source": OFFICIAL_URL}
    return None


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


# ---------------------------------------------------------------- 照合
def verify_win5(official, flagged):
    """公式の対象5レースと、開催ページの印を、会場・レース番号・順番で照合する。

    official: parse_official() の結果（None なら公式が取れていない）
    flagged : [(venue, race_no, leg)]  開催ページで WIN5 の印が付いていたレース（重複もそのまま渡す）
    """
    issues = []
    if not official or not official.get("races"):
        return {"ok": False, "count": len(flagged), "issues": ["公式の対象レース一覧を取得できない、または該当日の行がない"],
                "missing": [], "extra": [], "duplicates": [], "leg_mismatch": []}
    off = {(r["venue"], r["race_no"]): r["leg"] for r in official["races"]}
    if len(official["races"]) != 5:
        issues.append(f"公式の対象が5レースではない（{len(official['races'])}レース）")
    if len(off) != len(official["races"]):
        issues.append("公式の対象に重複がある")
    seen = {}
    for v, n, leg in flagged:
        seen.setdefault((v, n), []).append(leg)
    missing = sorted(k for k in off if k not in seen)
    extra = sorted(k for k in seen if k not in off)
    dups = sorted(k for k, legs in seen.items() if len(legs) > 1)
    mism = sorted(k for k, legs in seen.items() if k in off and legs[0] != off[k])
    if missing:
        issues.append("公式にあって開催ページに印がない：" + "、".join(f"{v}{n}R" for v, n in missing))
    if extra:
        issues.append("公式にないのに印が付いている：" + "、".join(f"{v}{n}R" for v, n in extra))
    if dups:
        issues.append("印が重複している：" + "、".join(f"{v}{n}R" for v, n in dups))
    if mism:
        issues.append("順番（何レース目か）が公式と違う：" + "、".join(f"{v}{n}R" for v, n in mism))
    return {"ok": not issues, "count": len(flagged), "issues": issues,
            "missing": [list(k) for k in missing], "extra": [list(k) for k in extra],
            "duplicates": [list(k) for k in dups], "leg_mismatch": [list(k) for k in mism]}


def jsonl_read(path):
    out = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                pass
    return out


def jsonl_append(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 本体
def run(a, net, now):
    """1回ぶんの収集。(終了コード, ログ1行) を返す。"""
    date = datetime.date.fromisoformat(a.date) if a.date else now.date()
    date8 = date.strftime("%Y%m%d")
    log = {"run_at": now.isoformat(timespec="seconds"), "date": str(date), "scope": a.scope, "window_min": a.window_min,
           "github_run_id": os.environ.get("GITHUB_RUN_ID"), "sources": {}, "official": None, "flagged": [],
           "verification": None, "saved": {"all": 0, "win5_set": False}, "issues": [], "exit_code": 0}
    page_cache = {}

    def fetch_race(cname):
        if cname not in page_cache:
            page_cache[cname] = net.post("/JRADB/accessD.html", cname)
        return page_cache[cname]

    idx = net.post("/JRADB/accessD.html", "pw01dli00/F3")
    log["sources"]["index"] = "POST /JRADB/accessD.html cname=pw01dli00/F3"
    if not idx:
        log["issues"].append("出馬表トップを取得できない"); log["exit_code"] = 1
        return 1, log
    vps = venue_pages(idx, date8)
    log["sources"]["venue_pages"] = vps
    if not vps:
        log["issues"].append("対象日の開催が見つからない（開催なし、または出馬表が未掲載）")
        return 0, log

    venues = []  # (venue, cname, rows)
    for vc in vps:
        vh = net.post("/JRADB/accessD.html", vc)
        if not vh:
            log["issues"].append(f"開催ページを取得できない：{vc}"); continue
        venues.append((venue_name(vh) or vc[8:10], vc[len("pw01drl00"):len("pw01drl00") + 2], races_on_venue(vh)))
    flagged = [(v, r["race_no"], r["win5_leg"]) for v, _c, rows in venues for r in rows if r["win5"]]
    log["flagged"] = [list(x) for x in flagged]

    official = None
    if a.scope in ("win5", "both"):
        oh = net.get(OFFICIAL_URL)
        log["sources"]["official_list"] = OFFICIAL_URL
        official = parse_official(oh, date) if oh else None
        log["official"] = official
        log["verification"] = verify_win5(official, flagged)
        log["issues"] += log["verification"]["issues"]

    out_all = os.path.join(a.out, f"{date}.jsonl")
    out_set = os.path.join(a.out, "win5", f"{date}.jsonl")

    # ---- all：発走前のレースを1レース1行で
    if a.scope in ("all", "both"):
        seen = {(d["venue_code"], d["race_no"], d["odds_time"]) for d in jsonl_read(out_all)}
        for venue, vcode, rows in venues:
            for rc in rows:
                ph, pm = map(int, rc["post_time"].split(":"))
                minutes = (datetime.datetime.combine(date, datetime.time(ph, pm), JST) - now).total_seconds() / 60
                if not a.all and not (-2 <= minutes <= a.window_min):
                    continue
                rh = fetch_race(rc["cname"])
                if not rh:
                    log["issues"].append(f"出馬表を取得できない：{venue}{rc['race_no']}R"); continue
                r = parse_race(rh)
                key = (vcode, rc["race_no"], r["odds_time"])
                if not r["odds_time"] or key in seen or not r["horses"]:   # 発走後は結果ページになり、オッズがない
                    continue
                seen.add(key)
                rec = {"fetched_at": log["run_at"], "date": str(date), "venue": venue, "venue_code": vcode,
                       "race_no": rc["race_no"], "post_time": rc["post_time"], "win5": rc["win5"], "win5_leg": rc["win5_leg"],
                       "source": "JRA公式 出馬表"}
                rec.update(r)
                jsonl_append(out_all, rec)
                log["saved"]["all"] += 1

    # ---- win5：公式の5レースを照合できたときだけ、5レース1組で
    if a.scope in ("win5", "both"):
        v = log["verification"]
        if not v["ok"]:
            log["exit_code"] = 2
        else:
            by_key = {(venue, rc["race_no"]): rc for venue, _vc, rows in venues for rc in rows}
            first_post = min(by_key[(r["venue"], r["race_no"])]["post_time"] for r in official["races"])
            fh, fm = map(int, first_post.split(":"))
            if (datetime.datetime.combine(date, datetime.time(fh, fm), JST) - now).total_seconds() < 0 and not a.all:
                log["issues"].append(f"第1レース({first_post})の発走後のため、WIN5の組は保存しない")
            else:
                races, bad = [], []
                for orr in official["races"]:
                    rc = by_key.get((orr["venue"], orr["race_no"]))
                    rh = fetch_race(rc["cname"]) if rc else None
                    r = parse_race(rh) if rh else None
                    if not r or not r["odds_time"] or not r["horses"]:
                        bad.append(f"{orr['venue']}{orr['race_no']}R"); continue
                    rec = {"leg": orr["leg"], "venue": orr["venue"], "race_no": orr["race_no"], "post_time": rc["post_time"]}
                    rec.update(r)
                    races.append(rec)
                if bad:
                    log["issues"].append("オッズを取得できなかった対象レース：" + "、".join(bad)); log["exit_code"] = 2
                elif len(races) != 5 or len({(r["venue"], r["race_no"]) for r in races}) != 5:
                    log["issues"].append("組み立てた対象が5レースではない"); log["exit_code"] = 2
                else:
                    times = [r["odds_time"] for r in races]
                    prev = jsonl_read(out_set)
                    if prev and [r["odds_time"] for r in prev[-1]["races"]] == times:
                        log["issues"].append("前回の組とオッズ時刻がすべて同じため、保存しない")
                    else:
                        jsonl_append(out_set, {"fetched_at": log["run_at"], "date": str(date), "deadline": official["deadline"],
                                               "official_source": OFFICIAL_URL, "verified": True, "odds_times": times, "races": races})
                        log["saved"]["win5_set"] = True
    log["page_requests"] = getattr(net, "calls", None)
    jsonl_append(os.path.join(a.out, "logs", f"{date}.jsonl"), log)
    return log["exit_code"], log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD（既定：今日のJST）")
    ap.add_argument("--scope", choices=["all", "win5", "both"], default="both")
    ap.add_argument("--window-min", type=int, default=75, help="scope=all：今から何分以内に発走するレースを取るか")
    ap.add_argument("--all", action="store_true", help="時刻に関係なく取る（確認用）")
    ap.add_argument("--out", default=os.path.join("data", "odds"))
    ap.add_argument("--delay", type=float, default=0.4, help="リクエストの間隔（秒）")
    a = ap.parse_args(argv)
    code, log = run(a, Net(a.delay), datetime.datetime.now(JST))
    print(f"{log['date']} scope={a.scope}: 通常 {log['saved']['all']}件、WIN5の組 {'保存' if log['saved']['win5_set'] else '保存なし'}、"
          f"リクエスト {log.get('page_requests')}回、終了コード {code}")
    for i in log["issues"]:
        print("  注意：" + i)
    return code


if __name__ == "__main__":
    sys.exit(main())
