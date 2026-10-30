#!/usr/bin/env python3
"""全レースの「発走10分前以前の最新」単勝オッズを、開催日ごとに保存する（標準ライブラリのみ）。お金を賭けない、記録上の検証用。

  python3 collector/odds_t10.py --session am --out data           # 午前のレース（発走 12:30 より前）
  python3 collector/odds_t10.py --session pm --out data           # 午後のレース（12:30 以降）
  python3 collector/odds_t10.py --session all --dry-run --out out # 保存先を odds-data にせず、手元に書くだけ

仕組み（既存の odds_snapshot とは別。jra_odds_snapshot.py は読み込むだけで、変更しない）
  - 開催日の出馬表から全レース（会場・レース番号・発走時刻）を取り、レースごとに cutoff = 発走時刻 - 10分 を決める。
  - cutoff より前の一定間隔（既定3分、最終は cutoff の30秒前）で、そのレースの出馬表ページを取得する。
    取得したオッズ（「HH時MM分現在」）は、すべて候補として候補ファイルに追記する。
  - cutoff の5秒後に、候補の中から次の条件をすべて満たす「最新」を1つ選び、レースごとに1行を選択ファイルに追記する。
      odds_time <= cutoff   かつ   取得時刻 <= cutoff   かつ   ページの発走時刻が予定と同じ
    最新 = odds_time が最大（同じなら取得が後のもの）。条件を満たす候補がなければ status="missing" と理由を書く。補間はしない。
  - 発走後のページは結果ページでオッズがないため、候補にならない。最終人気は使わない。
  - 保存先は <out>/odds_t10/ の新しいファイルだけ。追記のみで、既存ファイルは書き換えない。
      selected/<日付>.jsonl   レースごとに1行（採用したスナップショット、または欠測）
      candidates/<日付>.jsonl 取得したすべての候補（会場・レース・odds_time ごとに1行）
      logs/<日付>.jsonl       セッションの開始・終了の記録
  - 再実行しても、選択済みのレースは取り直さず、二重に追記しない。

終了コード
  0 : 割り当てた全レースを選択ファイルに記録した（欠測なし）
  2 : 全レースを記録したが、欠測が1つ以上ある
  1 : 開催のレース一覧を取得できない／一覧が空／時間切れで未記録のレースがある／保存（push）に失敗した
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jra_odds_snapshot as base  # noqa: E402  読み込みだけ。変更しない。

JST = base.JST
SCHEMA = "odds_t10/v1"
CUTOFF_MIN = 10
FINALIZE_GRACE_S = 5


# ---------------------------------------------------------------- 時刻とレース
def hhmm_to_dt(date, hhmm):
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime.combine(date, datetime.time(h, m), JST)


class Race:
    def __init__(self, date, venue, venue_code, race_no, post_time, name, cname):
        self.date, self.venue, self.venue_code, self.race_no = date, venue, venue_code, race_no
        self.name, self.cname = name, cname
        self.post_dt = hhmm_to_dt(date, post_time)
        self.post_time = f"{self.post_dt.hour:02d}:{self.post_dt.minute:02d}"   # 桁をそろえる（"9:5" と "09:05" を同じにする）
        self.cutoff = self.post_dt - datetime.timedelta(minutes=CUTOFF_MIN)

    @property
    def key(self):
        return (self.venue_code, self.race_no)

    def label(self):
        return f"{self.venue}{self.race_no}R"


def session_of(race, split):
    return "am" if race.post_time < split else "pm"


def poll_times(race, interval_min, window_min, final_margin_s):
    """cutoff より前の取得時刻。最後は cutoff の final_margin_s 秒前。"""
    out = []
    k = window_min
    while k >= interval_min:
        out.append(race.cutoff - datetime.timedelta(minutes=k))
        k -= interval_min
    out.append(race.cutoff - datetime.timedelta(seconds=final_margin_s))
    return sorted(set(out))


# ---------------------------------------------------------------- 取得元
class SourceError(Exception):
    pass


def page_post_time(html):
    m = re.search(r"発走時刻：\s*(\d+)時(\d+)分", base.text(html))
    return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}" if m else None


class RealSource:
    """JRA公式の出馬表。テストでは、同じ形のダミーに差し替える。"""

    def __init__(self, net):
        self.net = net

    @property
    def calls(self):
        return getattr(self.net, "calls", 0)

    def list_races(self, date):
        date8 = date.strftime("%Y%m%d")
        idx = self.net.post("/JRADB/accessD.html", "pw01dli00/F3")
        if not idx:
            raise SourceError("出馬表トップを取得できない")
        out = []
        for vc in base.venue_pages(idx, date8):
            vh = self.net.post("/JRADB/accessD.html", vc)
            if not vh:
                raise SourceError(f"開催ページを取得できない：{vc}")
            vname = base.venue_name(vh) or vc[8:10]
            vcode = vc[len("pw01drl00"):len("pw01drl00") + 2]
            for r in base.races_on_venue(vh):
                if r["race_no"] is None:
                    raise SourceError(f"レース番号を読み取れない行がある：{vname}")
                out.append(Race(date, vname, vcode, r["race_no"], r["post_time"], r["name"], r["cname"]))
        return out

    def fetch(self, race):
        """1回ぶんの取得。(html を取れたか, 解析結果) を返す。オッズがないページ（発走後など）は odds_time=None。"""
        html = self.net.post("/JRADB/accessD.html", race.cname)
        if not html:
            return None
        r = base.parse_race(html)
        r["page_post_time"] = page_post_time(html)
        return r


# ---------------------------------------------------------------- 保存
def jsonl_read(path):
    return base.jsonl_read(path)


def jsonl_append(path, rec):
    base.jsonl_append(path, rec)


class Store:
    def __init__(self, out, date):
        root = os.path.join(out, "odds_t10")
        self.selected = os.path.join(root, "selected", f"{date}.jsonl")
        self.candidates = os.path.join(root, "candidates", f"{date}.jsonl")
        self.logs = os.path.join(root, "logs", f"{date}.jsonl")
        self.root = root
        self._sel_keys = {(d["venue_code"], d["race_no"]) for d in jsonl_read(self.selected)}
        self._cand_keys = {(d["venue_code"], d["race_no"], d["odds_time"]) for d in jsonl_read(self.candidates)}

    def has_selected(self, key):
        return key in self._sel_keys

    def add_selected(self, rec):
        key = (rec["venue_code"], rec["race_no"])
        if key in self._sel_keys:
            return False
        jsonl_append(self.selected, rec)
        self._sel_keys.add(key)
        return True

    def add_candidate(self, rec):
        key = (rec["venue_code"], rec["race_no"], rec["odds_time"])
        if key in self._cand_keys:
            return False
        jsonl_append(self.candidates, rec)
        self._cand_keys.add(key)
        return True

    def log(self, rec):
        jsonl_append(self.logs, rec)


class GitSink:
    """odds-data の作業ディレクトリへ、新しいファイルだけをコミットして push する。"""

    def __init__(self, git_dir, paths=("odds_t10",)):
        self.git_dir, self.paths = git_dir, paths
        self.failed = False

    def flush(self, message):
        def git(*a, check=True):
            return subprocess.run(["git", "-C", self.git_dir, *a], capture_output=True, text=True, check=check)
        try:
            git("add", *self.paths)
            if git("diff", "--cached", "--quiet", check=False).returncode == 0:
                return True
            git("-c", "user.name=odds-t10", "-c", "user.email=odds-t10@users.noreply.github.com", "commit", "-q", "-m", message)
            for i in range(1, 5):
                if git("push", "origin", "odds-data", check=False).returncode == 0:
                    return True
                git("pull", "--rebase", "origin", "odds-data", check=False)
                time.sleep(3 * i)
        except Exception as e:  # noqa: BLE001
            print(f"  push失敗: {e}", file=sys.stderr)
        self.failed = True
        return False


class NullSink:
    failed = False

    def flush(self, message):
        return True


# ---------------------------------------------------------------- 時計
class RealClock:
    def now(self):
        return datetime.datetime.now(JST)

    def sleep_until(self, dt):
        while True:
            left = (dt - self.now()).total_seconds()
            if left <= 0:
                return
            time.sleep(min(left, 30))


# ---------------------------------------------------------------- 選択
def odds_dt(date, odds_time):
    return hhmm_to_dt(date, odds_time) if odds_time else None


def eligible(c, race):
    """候補が cutoff 以前のオッズか（機械検証と同じ条件）。理由があれば文字列を返す。"""
    if c["odds_dt"] is None:
        return "no_odds"
    if c["odds_dt"] > race.cutoff:
        return "odds_time_after_cutoff"
    if c["fetched_at"] > race.cutoff:
        return "fetched_after_cutoff"
    if c["page_post_time"] is not None and c["page_post_time"] != race.post_time:
        return "page_post_time_differs"
    return None


def choose(cands, race):
    ok = [c for c in cands if eligible(c, race) is None]
    if not ok:
        return None
    return max(ok, key=lambda c: (c["odds_dt"], c["fetched_at"]))


def verify_selected(rec):
    """採用したスナップショットが条件を満たすことを、保存する直前に機械検証する。"""
    if rec["status"] != "ok":
        return
    cutoff = datetime.datetime.fromisoformat(rec["cutoff_at"])
    odds = datetime.datetime.fromisoformat(rec["odds_time_at"])
    fetched = datetime.datetime.fromisoformat(rec["selected_snapshot_fetched_at"])
    post = datetime.datetime.fromisoformat(rec["scheduled_post_time"])
    assert odds <= cutoff, "odds_time が cutoff より後"
    assert fetched <= cutoff, "取得時刻が cutoff より後"
    assert cutoff == post - datetime.timedelta(minutes=CUTOFF_MIN), "cutoff が発走10分前ではない"
    assert rec["staleness_seconds"] == int((cutoff - odds).total_seconds()) and rec["staleness_seconds"] >= 0, "staleness が不整合"
    assert rec["horses"], "馬別オッズがない"


def build_record(race, chosen, cands, run_ctx, reason=None):
    rec = {
        "schema": SCHEMA, "date": str(race.date), "venue": race.venue, "venue_code": race.venue_code,
        "race_no": race.race_no, "race_name": race.name,
        "scheduled_post_time": race.post_dt.isoformat(timespec="seconds"),
        "cutoff_at": race.cutoff.isoformat(timespec="seconds"),
        "source": "JRA公式 出馬表 POST https://www.jra.go.jp/JRADB/accessD.html cname=" + race.cname,
        "github_run_id": run_ctx.get("github_run_id"), "session": run_ctx.get("session"),
        "n_candidates": len(cands),
        "candidate_odds_times": sorted({c["odds_time"] for c in cands if c["odds_time"]}),
    }
    if chosen is None:
        rec.update({"status": "missing", "missing_reason": reason or "no_eligible_snapshot",
                    "selected_snapshot_fetched_at": None, "odds_time": None, "odds_time_at": None,
                    "staleness_seconds": None, "horses": []})
        return rec
    rec.update({
        "status": "ok",
        "selected_snapshot_fetched_at": chosen["fetched_at"].isoformat(timespec="seconds"),
        "odds_time": chosen["odds_time"], "odds_time_at": chosen["odds_dt"].isoformat(timespec="seconds"),
        "staleness_seconds": int((race.cutoff - chosen["odds_dt"]).total_seconds()),
        "page_post_time": chosen["page_post_time"],
        "surface": chosen.get("surface"), "going": chosen.get("going"), "dist": chosen.get("dist"), "cls": chosen.get("cls"),
        "horses": [{"num": h["num"], "name": h["name"], "odds": h["odds"], "pop": h["pop"], "status": h["status"]} for h in chosen["horses"]],
    })
    return rec


# ---------------------------------------------------------------- 本体
def plan_events(races, opts, store, now):
    """(時刻, 種類, レース) の予定。選択済みのレースは含めない。cutoff を過ぎたレースは、すぐ欠測として確定する。"""
    events, late = [], []
    for r in races:
        if store.has_selected(r.key):
            continue
        if r.cutoff <= now:
            late.append(r)
            continue
        for t in poll_times(r, opts.poll_interval_min, opts.poll_window_min, opts.final_margin_s):
            if t > now:
                events.append((t, 0, r))
        events.append((r.cutoff + datetime.timedelta(seconds=FINALIZE_GRACE_S), 1, r))
    events.sort(key=lambda e: (e[0], e[1], e[2].key))
    return events, late


def run_session(opts, source, store, sink, clock):
    now = clock.now()
    date = datetime.date.fromisoformat(opts.date) if opts.date else now.date()
    ctx = {"github_run_id": os.environ.get("GITHUB_RUN_ID"), "session": opts.session}
    log = {"event": "session", "schema": SCHEMA, "started_at": now.isoformat(timespec="seconds"), "date": str(date),
           "session": opts.session, "split": opts.split, "github_run_id": ctx["github_run_id"], "dry_run": bool(getattr(opts, "dry_run", False)),
           "issues": [], "planned": 0, "already_selected": 0, "polls": 0, "polls_failed": 0, "polls_no_odds": 0,
           "candidates_saved": 0, "selected_ok": 0, "selected_missing": 0, "unfinalized": [], "exit_code": 0}
    try:
        all_races = source.list_races(date)
    except SourceError as e:
        log["issues"].append(f"レース一覧を取得できない：{e}")
        log["exit_code"] = 1
        log["requests"] = getattr(source, "calls", None)
        log["ended_at"] = clock.now().isoformat(timespec="seconds")
        store.log(log)
        return 1, log
    if not all_races:
        log["issues"].append("対象日のレースが見つからない（開催なし、または出馬表が未掲載）。成功扱いにしない")
        log["exit_code"] = 1
        log["requests"] = getattr(source, "calls", None)
        log["ended_at"] = clock.now().isoformat(timespec="seconds")
        store.log(log)
        return 1, log
    keys = [r.key for r in all_races]
    if len(set(keys)) != len(keys):
        log["issues"].append("会場・レース番号が重複している")
        log["exit_code"] = 1
        store.log(log)
        return 1, log
    per_venue = {}
    for r in all_races:
        per_venue[r.venue] = per_venue.get(r.venue, 0) + 1
    for v, n in per_venue.items():
        if n != 12:
            log["issues"].append(f"{v}のレース数が12ではない：{n}")
    races = [r for r in all_races if opts.session == "all" or session_of(r, opts.split) == opts.session]
    log["planned"] = len(races)
    log["races_listed_total"] = len(all_races)
    log["already_selected"] = sum(store.has_selected(r.key) for r in races)
    events, late = plan_events(races, opts, store, now)
    cands = {r.key: [] for r in races}
    deadline = now + datetime.timedelta(minutes=opts.max_run_min)
    finalized = set(r.key for r in races if store.has_selected(r.key))

    def finalize(race, reason=None):
        chosen = choose(cands[race.key], race)
        rr = reason
        if chosen is None and rr is None:
            reasons = sorted({eligible(c, race) for c in cands[race.key] if eligible(c, race)})
            rr = "no_eligible_snapshot" + (":" + ",".join(reasons) if reasons else ":no_candidates")
        rec = build_record(race, chosen, cands[race.key], ctx, rr)
        verify_selected(rec)
        store.add_selected(rec)
        finalized.add(race.key)
        log["selected_ok" if rec["status"] == "ok" else "selected_missing"] += 1

    for r in late:
        finalize(r, "session_started_after_cutoff")
    last_flush = clock.now()
    for due, kind, race in events:
        if due > deadline:
            log["issues"].append("実行時間の上限に達した")
            break
        clock.sleep_until(due)
        if kind == 0:
            t = clock.now()
            if t >= race.cutoff:
                continue   # 遅れて cutoff を過ぎた取得は、候補にならないので行わない
            snap = source.fetch(race)
            log["polls"] += 1
            if snap is None:
                log["polls_failed"] += 1
                continue
            c = {"fetched_at": clock.now(), "odds_time": snap.get("odds_time"), "odds_dt": odds_dt(date, snap.get("odds_time")),
                 "page_post_time": snap.get("page_post_time"), "horses": snap.get("horses") or [],
                 "surface": snap.get("surface"), "going": snap.get("going"), "dist": snap.get("dist"), "cls": snap.get("cls")}
            if c["odds_dt"] is None or not c["horses"]:
                log["polls_no_odds"] += 1
                continue
            cands[race.key].append(c)
            rec = {"schema": SCHEMA, "date": str(date), "venue": race.venue, "venue_code": race.venue_code, "race_no": race.race_no,
                   "scheduled_post_time": race.post_dt.isoformat(timespec="seconds"), "cutoff_at": race.cutoff.isoformat(timespec="seconds"),
                   "fetched_at": c["fetched_at"].isoformat(timespec="seconds"), "odds_time": c["odds_time"],
                   "page_post_time": c["page_post_time"], "github_run_id": ctx["github_run_id"],
                   "horses": [{"num": h["num"], "odds": h["odds"], "pop": h["pop"], "status": h["status"]} for h in c["horses"]]}
            if store.add_candidate(rec):
                log["candidates_saved"] += 1
        else:
            finalize(race)
            if (clock.now() - last_flush).total_seconds() >= 20 * 60:
                sink.flush(f"odds t10 {date} {opts.session}")
                last_flush = clock.now()
    log["unfinalized"] = [r.label() for r in races if r.key not in finalized]
    log["requests"] = getattr(source, "calls", None)
    if log["unfinalized"]:
        log["issues"].append("未記録のレースがある：" + "、".join(log["unfinalized"]))
        log["exit_code"] = 1
    elif log["selected_missing"]:
        log["exit_code"] = 2
    log["ended_at"] = clock.now().isoformat(timespec="seconds")
    store.log(log)
    if not sink.flush(f"odds t10 {date} {opts.session} done"):
        log["issues"].append("odds-data への保存（push）に失敗した")
        log["exit_code"] = 1
    return log["exit_code"], log


def list_only(a, src, date, now):
    try:
        races = src.list_races(date)
    except SourceError as e:
        print(f"レース一覧を取得できない：{e}")
        return 1
    if not races:
        print(f"{date}: レースが見つからない（開催なし、または出馬表が未掲載）")
        return 1
    by = {}
    for r in races:
        by.setdefault(r.venue, []).append(r)
    for v, rs in by.items():
        print(f"{v}: {len(rs)}レース  " + " ".join(f"{r.race_no}R={r.post_time}" for r in sorted(rs, key=lambda x: x.race_no)))
    for sess in ("am", "pm"):
        rs = [r for r in races if session_of(r, a.split) == sess]
        if rs:
            n = sum(len(poll_times(r, a.poll_interval_min, a.poll_window_min, a.final_margin_s)) for r in rs)
            print(f"{sess}: {len(rs)}レース、最初の cutoff {min(r.cutoff for r in rs):%H:%M}、最後の cutoff {max(r.cutoff for r in rs):%H:%M}、取得予定 {n}回")
    print(f"合計 {len(races)}レース、リクエスト {src.calls}回（一覧の取得）")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="YYYY-MM-DD（既定：今日のJST）")
    ap.add_argument("--session", choices=["am", "pm", "all"], required=True)
    ap.add_argument("--split", default="12:30", help="午前/午後の境（発走時刻がこれより前なら午前）")
    ap.add_argument("--out", default="data")
    ap.add_argument("--git-dir", help="odds-data の作業ディレクトリ。指定すると、定期的にコミットして push する")
    ap.add_argument("--list-only", action="store_true", help="レース一覧と取得予定だけを表示する（取得も保存もしない）。出馬表が出ている日の確認用")
    ap.add_argument("--dry-run", action="store_true", help="push しない（保存は --out にだけ書く）")
    ap.add_argument("--poll-interval-min", type=float, default=3.0)
    ap.add_argument("--poll-window-min", type=float, default=24.0)
    ap.add_argument("--final-margin-s", type=float, default=30.0)
    ap.add_argument("--max-run-min", type=float, default=340.0)
    ap.add_argument("--delay", type=float, default=0.5, help="リクエストの間隔（秒）")
    a = ap.parse_args(argv)
    clock = RealClock()
    date = datetime.date.fromisoformat(a.date) if a.date else clock.now().date()
    a.date = str(date)
    src = RealSource(base.Net(a.delay))
    if a.list_only:
        return list_only(a, src, date, clock.now())
    sink = GitSink(a.git_dir) if a.git_dir and not a.dry_run else NullSink()
    code, log = run_session(a, src, Store(a.out, date), sink, clock)
    print(f"{log['date']} session={a.session}: 対象 {log['planned']}レース、記録 ok={log['selected_ok']} 欠測={log['selected_missing']}、"
          f"取得 {log['polls']}回（失敗 {log['polls_failed']}、オッズなし {log['polls_no_odds']}）、リクエスト {log.get('requests')}回、終了コード {code}")
    for i in log["issues"]:
        print("  注意：" + i)
    return code


if __name__ == "__main__":
    sys.exit(main())
