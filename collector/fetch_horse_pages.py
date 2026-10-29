#!/usr/bin/env python3
"""馬ごとのJRA公式競走馬情報ページを一括取得する（標準ライブラリのみ。B2の検証用の入力）。

  python3 collector/fetch_horse_pages.py --cnames research/factor-validation/data/horse_cnames.json.gz \
      --out-dir out --workers 5

- 入力：馬ID→cnameの後ろ2桁（JRA結果ページのリンクから抽出したもの）。
- 出力：<out-dir>/horses.json.gz（馬IDごとの profile と runs、各馬の fetched_at）、<out-dir>/manifest.json（件数・欠損・時刻・SHA256）。
- 取得に失敗した馬は、最大 --passes 回まで再試行する。それでも取れなかった馬は missing_horses に記録し、推測で補わない。
- JRAのページは取得時点の現行ページ。過去の予測に使うときは、対象レース日より前の走だけに切り詰めること（B2仕様書）。
"""
import argparse
import concurrent.futures as cf
import datetime
import gzip
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jra_odds_snapshot as c  # noqa: E402
import horse_history as hh  # noqa: E402


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fetch_one(args):
    hid, suffix = args
    t = c.Net(delay=0.25).post("/JRADB/accessU.html", f"{hid}/{suffix}")
    if not t:
        return hid, None
    d = hh.parse_horse(t)
    d["fetched_at"] = datetime.datetime.now(c.JST).isoformat(timespec="seconds")
    return hid, d


def run(cnames_path, out_dir, workers=5, passes=3, limit=None):
    raw = gzip.open(cnames_path, "rb").read()
    cn = json.loads(raw)
    items = sorted(cn.items())[:limit] if limit else sorted(cn.items())
    started = datetime.datetime.now(c.JST).isoformat(timespec="seconds")
    got = {}
    pending = items
    for p in range(1, passes + 1):
        if not pending:
            break
        print(f"pass {p}: {len(pending)} horses", flush=True)
        n = 0
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            for hid, d in ex.map(fetch_one, pending):
                if d is not None:
                    got[hid] = d
                n += 1
                if n % 500 == 0:
                    print(f"  {n}/{len(pending)} (ok {len(got)})", flush=True)
        pending = [(h, s) for h, s in items if h not in got]
        if pending:
            time.sleep(30)
    finished = datetime.datetime.now(c.JST).isoformat(timespec="seconds")
    os.makedirs(out_dir, exist_ok=True)
    blob = json.dumps(got, ensure_ascii=False, separators=(",", ":")).encode()
    path = os.path.join(out_dir, "horses.json.gz")
    with open(path, "wb") as f:
        f.write(gzip.compress(blob, 9))
    runs = [len(v["runs"]) for v in got.values()]
    manifest = {
        "source": "JRA公式 競走馬情報（https://www.jra.go.jp/JRADB/accessU.html）", "started_at_jst": started, "finished_at_jst": finished,
        "requested": len(items), "succeeded": len(got), "missing": len(items) - len(got),
        "missing_horses": [h for h, _ in items if h not in got], "passes": passes, "workers": workers,
        "horses_with_zero_runs": sum(1 for x in runs if x == 0), "total_runs": sum(runs),
        "cnames_file": cnames_path, "cnames_sha256": sha256_bytes(raw),
        "horses_json_sha256": sha256_bytes(blob), "horses_json_gz_sha256": sha256_bytes(open(path, "rb").read()),
        "script_sha256": sha256_bytes(open(__file__, "rb").read()),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in manifest.items() if k != "missing_horses"}, ensure_ascii=False, indent=2))
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cnames", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    run(a.cnames, a.out_dir, a.workers, a.passes, a.limit)


if __name__ == "__main__":
    main()
