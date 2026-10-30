import datetime, json, os, sys, tempfile, types, unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import odds_t10 as t  # noqa: E402

JST = t.JST
DATE = datetime.date(2026, 10, 31)


def dt(hhmm, sec=0, date=DATE):
    h, m = map(int, hhmm.split(":"))
    return datetime.datetime(date.year, date.month, date.day, h, m, sec, tzinfo=JST)


class FakeClock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep_until(self, when):
        if when > self.t:
            self.t = when


def horse(n, odds):
    return {"num": n, "name": f"馬{n}", "odds": odds, "pop": n, "status": ""}


class FakeSource:
    """時計に合わせて、オッズの更新時刻(HH:MM)を返すダミー。発走後は結果ページ(オッズなし)。"""
    def __init__(self, clock, races, lag_min=1, fail_after=None, post_time_override=None, fail_listing=None):
        self.clock, self.races, self.lag_min = clock, races, lag_min
        self.calls = 0
        self.fail_after = fail_after or {}
        self.post_time_override = post_time_override or {}
        self.fail_listing = fail_listing
        self.fetch_log = []

    def list_races(self, date):
        if self.fail_listing:
            raise t.SourceError(self.fail_listing)
        return self.races

    def fetch(self, race):
        self.calls += 1
        now = self.clock.now()
        self.fetch_log.append((race.key, now))
        if race.key in self.fail_after and now >= self.fail_after[race.key]:
            return None
        if now >= race.post_dt:
            return {"odds_time": None, "horses": [], "page_post_time": race.post_time}
        upd = (now - datetime.timedelta(minutes=self.lag_min)).replace(second=0, microsecond=0)
        return {"odds_time": upd.strftime("%H:%M"), "horses": [horse(1, 2.0), horse(2, 5.5)],
                "page_post_time": self.post_time_override.get(race.key, race.post_time),
                "surface": "芝", "going": "良", "dist": 1600, "cls": "オープン"}


def mk_races(spec):
    return [t.Race(DATE, v, code, no, pt, f"R{no}", f"cn{code}{no}") for v, code, no, pt in spec]


def opts(**kw):
    d = dict(date=str(DATE), session="all", split="12:30", poll_interval_min=3.0, poll_window_min=24.0, final_margin_s=30.0,
             max_run_min=340.0, dry_run=True)
    d.update(kw)
    return types.SimpleNamespace(**d)


def read(path):
    return [json.loads(l) for l in open(path, encoding="utf-8")] if os.path.exists(path) else []


class Times(unittest.TestCase):
    def test_cutoff_is_ten_minutes_before_post_in_jst(self):
        r = mk_races([("東京", "05", 11, "15:45")])[0]
        self.assertEqual(r.cutoff, dt("15:35"))
        self.assertEqual(r.cutoff.utcoffset(), datetime.timedelta(hours=9))
        self.assertEqual(r.cutoff.astimezone(datetime.timezone.utc).strftime("%H:%M"), "06:35")

    def test_poll_times_end_before_cutoff(self):
        r = mk_races([("東京", "05", 1, "10:00")])[0]
        ts = t.poll_times(r, 3.0, 24.0, 30.0)
        self.assertEqual(ts[0], dt("09:26"))          # cutoff 09:50 の24分前
        self.assertTrue(all(x < r.cutoff for x in ts))
        self.assertEqual(ts[-1], r.cutoff - datetime.timedelta(seconds=30))
        self.assertEqual(len(ts), 9)

    def test_single_digit_minutes_are_normalised(self):
        r = t.Race(DATE, "東京", "05", 1, "9:5", "x", "c")
        self.assertEqual(r.post_time, "09:05")
        self.assertEqual(r.cutoff, dt("08:55"))

    def test_session_boundary(self):
        am, pm = mk_races([("東京", "05", 1, "12:29"), ("東京", "05", 2, "12:30")])
        self.assertEqual(t.session_of(am, "12:30"), "am")
        self.assertEqual(t.session_of(pm, "12:30"), "pm")


class Selection(unittest.TestCase):
    def cand(self, race, odds_hhmm, fetched, post=None):
        return {"odds_time": odds_hhmm, "odds_dt": t.odds_dt(DATE, odds_hhmm), "fetched_at": fetched,
                "page_post_time": post or race.post_time, "horses": [horse(1, 2.0)]}

    def setUp(self):
        self.r = mk_races([("東京", "05", 11, "15:45")])[0]   # cutoff 15:35

    def test_odds_time_equal_to_cutoff_is_accepted(self):
        c = self.cand(self.r, "15:35", dt("15:35", 20))
        c["fetched_at"] = dt("15:35", 0)
        self.assertIsNone(t.eligible(c, self.r))

    def test_odds_time_one_minute_after_cutoff_is_rejected(self):
        self.assertEqual(t.eligible(self.cand(self.r, "15:36", dt("15:35", 0)), self.r), "odds_time_after_cutoff")

    def test_fetched_one_second_after_cutoff_is_rejected_even_if_odds_time_is_before(self):
        self.assertEqual(t.eligible(self.cand(self.r, "15:34", dt("15:35", 1)), self.r), "fetched_after_cutoff")

    def test_page_post_time_mismatch_is_rejected(self):
        self.assertEqual(t.eligible(self.cand(self.r, "15:30", dt("15:31"), post="15:40"), self.r), "page_post_time_differs")

    def test_latest_odds_time_wins_then_latest_fetch(self):
        a = self.cand(self.r, "15:30", dt("15:31"))
        b = self.cand(self.r, "15:33", dt("15:34"))
        c = self.cand(self.r, "15:33", dt("15:34", 30))
        d = self.cand(self.r, "15:36", dt("15:34", 50))   # 不適格（odds_time が cutoff より後）
        self.assertIs(t.choose([a, b, c, d], self.r), c)

    def test_no_candidates_is_none(self):
        self.assertIsNone(t.choose([], self.r))

    def test_verify_rejects_a_bad_record(self):
        c = self.cand(self.r, "15:30", dt("15:31"))
        rec = t.build_record(self.r, c, [c], {})
        t.verify_selected(rec)
        bad = dict(rec, odds_time_at=dt("15:36").isoformat())
        with self.assertRaises(AssertionError):
            t.verify_selected(bad)
        bad2 = dict(rec, staleness_seconds=1)
        with self.assertRaises(AssertionError):
            t.verify_selected(bad2)


class Session(unittest.TestCase):
    def run_session(self, races, start, out, sink=None, **kw):
        clock = FakeClock(start)
        src = kw.pop("source", None) or FakeSource(clock, races, **kw.pop("src_kw", {}))
        if src.clock is not clock:
            src.clock = clock
        o = opts(**kw)
        store = t.Store(out, DATE)
        code, log = t.run_session(o, src, store, sink or t.NullSink(), clock)
        return code, log, store, src

    def test_normal_run_records_every_race_with_latest_snapshot(self):
        races = mk_races([("東京", "05", 1, "10:00"), ("京都", "08", 1, "10:00"), ("東京", "05", 2, "10:25")])
        with tempfile.TemporaryDirectory() as out:
            code, log, store, src = self.run_session(races, dt("09:00"), out)
            sel = read(store.selected)
            self.assertEqual(len(sel), 3)
            for s in sel:
                self.assertEqual(s["status"], "ok")
                self.assertLessEqual(s["staleness_seconds"], 120)    # 最終取得は cutoff の30秒前、更新遅れ1分
                self.assertGreaterEqual(s["staleness_seconds"], 0)
                self.assertLessEqual(s["odds_time_at"], s["cutoff_at"])
                self.assertLessEqual(s["selected_snapshot_fetched_at"], s["cutoff_at"])
                self.assertEqual(s["schema"], t.SCHEMA)
                self.assertTrue(s["horses"])
            self.assertEqual(code, 0)
            self.assertEqual(log["selected_missing"], 0)
            self.assertGreater(len(read(store.candidates)), 3)

    def test_no_fetch_after_cutoff(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            _c, _l, _s, src = self.run_session(races, dt("09:00"), out)
            self.assertTrue(all(when < races[0].cutoff for _k, when in src.fetch_log))

    def test_post_race_page_never_becomes_a_candidate(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            code, log, store, _src = self.run_session(races, dt("09:49", 40), out)   # すでに cutoff(09:50) の直前
            self.assertEqual(log["polls_no_odds"], 0)   # cutoff 後の取得自体を行わない

    def test_missing_when_every_fetch_fails_and_not_interpolated(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            code, log, store, _src = self.run_session(races, dt("09:00"), out, src_kw={"fail_after": {("05", 1): dt("00:00")}})
            sel = read(store.selected)
            self.assertEqual(sel[0]["status"], "missing")
            self.assertIsNone(sel[0]["odds_time"])
            self.assertEqual(sel[0]["horses"], [])
            self.assertIn("no_candidates", sel[0]["missing_reason"])
            self.assertEqual(code, 2)

    def test_late_start_marks_missing_without_fetching(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            code, log, store, src = self.run_session(races, dt("09:55"), out)     # cutoff 09:50 を過ぎている
            sel = read(store.selected)
            self.assertEqual(sel[0]["missing_reason"], "session_started_after_cutoff")
            self.assertEqual(src.calls, 0)
            self.assertEqual(code, 2)

    def test_session_split_only_handles_its_races(self):
        races = mk_races([("東京", "05", 1, "12:29"), ("東京", "05", 2, "12:30")])
        with tempfile.TemporaryDirectory() as out:
            _c, log, store, _s = self.run_session(races, dt("11:30"), out, session="am")
            self.assertEqual([s["race_no"] for s in read(store.selected)], [1])
            _c, log, store2, _s = self.run_session(races, dt("12:00"), out, session="pm")
            self.assertEqual(sorted(s["race_no"] for s in read(store2.selected)), [1, 2])

    def test_rerun_does_not_duplicate_or_refetch_finished_races(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            self.run_session(races, dt("09:00"), out)
            n_sel, n_cand = len(read(os.path.join(out, "odds_t10", "selected", f"{DATE}.jsonl"))), len(read(os.path.join(out, "odds_t10", "candidates", f"{DATE}.jsonl")))
            code, log, store, src = self.run_session(races, dt("09:10"), out)
            self.assertEqual(len(read(store.selected)), n_sel)
            self.assertEqual(len(read(store.candidates)), n_cand)
            self.assertEqual(src.calls, 0)
            self.assertEqual(log["already_selected"], 1)

    def test_rerun_after_midway_failure_continues_without_duplicates(self):
        races = mk_races([("東京", "05", 1, "10:00"), ("東京", "05", 2, "10:30")])
        with tempfile.TemporaryDirectory() as out:
            # 1回目: 10:10 で打ち切り（レース1だけ確定）
            clock = FakeClock(dt("09:00"))
            src = FakeSource(clock, races)
            store = t.Store(out, DATE)
            o = opts(max_run_min=70.0)     # 09:00 + 70分 = 10:10 を超える予定は実行しない
            code, log = t.run_session(o, src, store, t.NullSink(), clock)
            self.assertEqual(code, 1)
            self.assertEqual(log["unfinalized"], ["東京2R"])
            self.assertEqual([s["race_no"] for s in read(store.selected)], [1])
            # 2回目
            code2, log2, store2, _s = self.run_session(races, dt("10:12"), out)
            sel = read(store2.selected)
            self.assertEqual(sorted(s["race_no"] for s in sel), [1, 2])
            self.assertEqual(len({(s["venue_code"], s["race_no"]) for s in sel}), 2)

    def test_empty_listing_is_not_success(self):
        with tempfile.TemporaryDirectory() as out:
            code, log, store, _s = self.run_session([], dt("09:00"), out)
            self.assertEqual(code, 1)
            self.assertTrue(any("見つからない" in i for i in log["issues"]))
            self.assertEqual(read(store.selected), [])

    def test_listing_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as out:
            code, log, store, _s = self.run_session([], dt("09:00"), out, src_kw={"fail_listing": "出馬表トップを取得できない"})
            self.assertEqual(code, 1)
            self.assertEqual(read(store.selected), [])

    def test_page_post_time_change_is_missing_not_accepted(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            code, log, store, _s = self.run_session(races, dt("09:00"), out, src_kw={"post_time_override": {("05", 1): "10:05"}})
            sel = read(store.selected)
            self.assertEqual(sel[0]["status"], "missing")
            self.assertIn("page_post_time_differs", sel[0]["missing_reason"])

    def test_writes_only_under_odds_t10(self):
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            self.run_session(races, dt("09:00"), out)
            top = sorted(os.listdir(out))
            self.assertEqual(top, ["odds_t10"])
            self.assertEqual(sorted(os.listdir(os.path.join(out, "odds_t10"))), ["candidates", "logs", "selected"])

    def test_gap_in_updates_shows_up_as_staleness_not_hidden(self):
        # 更新が止まったことを想定: 取得は常に 5分前のオッズを返す
        races = mk_races([("東京", "05", 1, "10:00")])
        with tempfile.TemporaryDirectory() as out:
            _c, _l, store, _s = self.run_session(races, dt("09:00"), out, src_kw={"lag_min": 5})
            s = read(store.selected)[0]
            self.assertGreaterEqual(s["staleness_seconds"], 5 * 60)


class Real(unittest.TestCase):
    """実ページの解析に使う部分（既存 jra_odds_snapshot の関数）との結線。"""
    def test_page_post_time(self):
        self.assertEqual(t.page_post_time("<html>発走時刻：<strong>9時5分</strong>天候</html>"), "09:05")
        self.assertIsNone(t.page_post_time("<html>結果</html>"))

    def test_real_source_lists_races_and_fetches(self):
        sys.path.insert(0, os.path.dirname(__file__))
        import test_collector as tc
        net = tc.FakeNet()
        net.calls = 0
        src = t.RealSource(net)
        races = src.list_races(tc.DATE)
        self.assertEqual(len(races), 7)
        k = next(r for r in races if r.venue == "京都" and r.race_no == 10)
        self.assertEqual(k.post_time, "14:50")
        self.assertEqual(k.cutoff, tc.DATE and datetime.datetime(2026, 10, 24, 14, 40, tzinfo=JST))
        snap = src.fetch(k)
        self.assertEqual(snap["odds_time"], "14:20")
        self.assertEqual(len(snap["horses"]), 3)
        self.assertEqual(snap["page_post_time"], "15:00")   # ダミーの出馬表ページの発走時刻
        self.assertGreater(src.calls, 0)


if __name__ == "__main__":
    unittest.main()
