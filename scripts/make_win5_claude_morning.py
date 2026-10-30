#!/usr/bin/env python3
"""Claudeの「朝の予想」/「直前の確認」CSVを、公式オッズのWIN5セット(odds/win5/<日付>.jsonl の最後の1組)から作る。

  python scripts/make_win5_claude_morning.py --win5-jsonl <odds/win5/日付.jsonl> --version 朝の予想 \
      --output data/win5_joint/2026-10-31/win5_claude_morning.csv

- 市場確率 = 各レース内で 1/単勝オッズ を合計100%に正規化（取消・除外・オッズなしの馬は除く）。補正はしない。
- モデル確率 = 市場確率を0.1%単位に丸め、各レースの合計が100.0になるよう最大剰余法で調整。独立モデルではない。
- 確信度は、市場確率の水準による機械的な区分（A≥35 / B 20-35 / C 10-20 / D<10）。補正前＝補正後（判断による補正なし）。
- 既存の出力ファイルは上書きしない（--force が必要）。取得できなかったことは推測で埋めない。
"""
import argparse
import csv
import datetime
import json
import sys
from pathlib import Path

JST = datetime.timezone(datetime.timedelta(hours=9))
FIELDS = ["version", "date", "win5_order", "venue_race", "race_name", "horse_no", "horse_name", "jockey", "weight_kg", "win_odds",
          "odds_time_jst", "fetched_at_jst", "market_prob_pct", "model_prob_pct", "rank", "confidence", "market_favorite",
          "model_honmei", "prediction_created_jst", "source", "method", "notes", "rule_version"]
RULE_VERSION = "WIN5-JOINT-v1.6"
METHOD = ("公式単勝オッズの逆数を各レース内で合計100%に正規化（市場確率）。補正なし＝モデル確率は市場確率を0.1%単位に丸めて"
          "合計100.0に調整。独立モデルではない")


def grade(p):
    return "A" if p >= 35 else "B" if p >= 20 else "C" if p >= 10 else "D"


def round_to_tenth_sum_100(probs):
    """最大剰余法。probs(合計≈100)を0.1単位にして合計をちょうど100.0にする。"""
    units = [p * 10 for p in probs]
    base = [int(u) for u in units]
    need = 1000 - sum(base)
    order = sorted(range(len(probs)), key=lambda i: (-(units[i] - base[i]), i))
    for i in order[:need]:
        base[i] += 1
    return [b / 10 for b in base]


def build(rec, version, now, source_note=""):
    date = rec["date"]
    fetched = datetime.datetime.fromisoformat(rec["fetched_at"]).astimezone(JST)
    rows = []
    for race in rec["races"]:
        hs = [h for h in race["horses"] if h.get("odds") and not h.get("status")]
        excluded = [h for h in race["horses"] if not (h.get("odds") and not h.get("status"))]
        inv = [1.0 / h["odds"] for h in hs]
        tot = sum(inv)
        mk = [100.0 * v / tot for v in inv]
        md = round_to_tenth_sum_100(mk)
        order = sorted(range(len(hs)), key=lambda i: (-md[i], hs[i]["num"]))
        rank = {i: r + 1 for r, i in enumerate(order)}
        mk_fav = min(range(len(hs)), key=lambda i: (hs[i]["odds"], hs[i]["num"]))
        for i, h in enumerate(hs):
            note = (f"取消・除外の表示なし。" if not excluded else "除外: " + "、".join(f"{x['num']}番{x.get('status') or 'オッズなし'}" for x in excluded) + "。") + "馬体重・馬場変化は未取得"
            if source_note:
                note += "。" + source_note
            g = grade(mk[i])
            rows.append({
                "version": version, "date": date, "win5_order": race["leg"], "venue_race": f"{race['venue']}{race['race_no']}R",
                "race_name": race["race_name"], "horse_no": h["num"], "horse_name": h["name"], "jockey": h["jockey"],
                "weight_kg": h["wt"], "win_odds": h["odds"], "odds_time_jst": f"{date} {race['odds_time']} JST",
                "fetched_at_jst": fetched.isoformat(timespec="seconds").replace("T", " ") + " JST",
                "market_prob_pct": round(mk[i], 2), "model_prob_pct": md[i], "rank": rank[i],
                "confidence": f"{g}→{g}（推定の信頼性：中）", "market_favorite": "Yes" if i == mk_fav else "No",
                "model_honmei": "Yes" if rank[i] == 1 else "No",
                "prediction_created_jst": now.strftime("%Y-%m-%d %H:%M JST"), "source": "JRA公式 出馬表",
                "method": METHOD, "notes": note, "rule_version": RULE_VERSION})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--win5-jsonl", type=Path, required=True)
    ap.add_argument("--version", required=True, help="朝の予想 / 直前の確認 など")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--note", default="")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in a.win5_jsonl.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not recs:
        raise SystemExit("WIN5の組がありません")
    rec = recs[-1]
    if not rec.get("verified") or len(rec["races"]) != 5:
        raise SystemExit("公式照合済みの5レースではありません。作成しません")
    if a.output.exists() and not a.force:
        raise SystemExit(f"{a.output} は既にあります。上書きしません")
    rows = build(rec, a.version, datetime.datetime.now(JST), a.note)
    for leg in range(1, 6):
        s = sum(r["model_prob_pct"] for r in rows if r["win5_order"] == leg)
        if abs(s - 100.0) > 1e-6:
            raise SystemExit(f"leg {leg} の合計が100.0ではありません: {s}")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)}頭、5レース、各レース合計100.0 → {a.output}")


if __name__ == "__main__":
    sys.exit(main())
