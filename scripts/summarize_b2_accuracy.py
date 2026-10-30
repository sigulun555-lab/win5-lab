#!/usr/bin/env python3
"""Plain-language accuracy summary for B, B2 and B2.1 on the retrospective test period. Read-only.

usage: summarize_b2_accuracy.py <v1_validation.json> <v2_validation.json> <prepared_v2.json>
Reports for the last split (2026-08-01..2026-10-24): hit rates (Top-1, Top-3, counts), the average probability
given to the actual winner, log-likelihood, Brier, and a head-to-head of the top picks of B vs B2.1.
Labels come from the prepared races. No model is fitted.
"""
import json, math, sys
from pathlib import Path

v1 = json.loads(Path(sys.argv[1]).read_text()); v2 = json.loads(Path(sys.argv[2]).read_text())
prep = json.loads(Path(sys.argv[3]).read_text())
win = {r["race_id"]: next(x["hid"] for x in r["rows"] if x["winner_share"] == 1.0) for r in prep}
fav = {r["race_id"]: min((x for x in r["rows"] if x["pop"] is not None), key=lambda x: x["pop"])["hid"] for r in prep}
r1, r2 = v1["folds"][-1], v2["folds"][-1]
n = r2["test_races"]
print(f"split {r2['split']}  races {n}")

def stats(preds):
    top1 = top3 = 0; ll = 0.0; br = 0.0; picks = {}
    for p in preds:
        w = str(win[p["race_id"]]); hs = sorted(p["horses"], key=lambda h: -h["probability"])
        order = [str(h["hid"]) for h in hs]
        top1 += order[0] == w; top3 += w in order[:3]
        pw = next(h["probability"] for h in hs if str(h["hid"]) == w)
        ll += math.log(max(pw, 1e-15))
        br += sum((h["probability"] - (1.0 if str(h["hid"]) == w else 0.0)) ** 2 for h in hs)
        picks[p["race_id"]] = order[0]
    k = len(preds)
    return dict(top1=top1, top3=top3, ll=ll / k, geo=math.exp(ll / k), brier=br / k, n=k, picks=picks)

models = {
    "B (現行・B0-original)": r1["candidates"]["B0-original"]["predictions"],
    "B0-refit (Bの温度だけ調整)": r1["candidates"]["B0-refit"]["predictions"],
    "B2 (重賞が付かない旧版)": r1["candidates"]["B2-full-b1-rating"]["predictions"],
    "B2.1 (重賞を直した版)": r2["candidates"]["B2-full-b1-rating"]["predictions"],
}
res = {k: stats(v) for k, v in models.items()}
po = r2["popularity_only"]; un = r2["uniform_all_horses_equal"]
print(f"{'モデル':26s} {'1着を当てた':>14s} {'3着以内に入れた':>16s} {'勝ち馬への平均確率':>18s} {'対数尤度':>9s} {'Brier':>7s}")
for k, s in res.items():
    print(f"{k:26s} {s['top1']:4d}/{s['n']} ({s['top1']/s['n']*100:4.1f}%) {s['top3']:4d}/{s['n']} ({s['top3']/s['n']*100:4.1f}%) {s['geo']*100:14.2f}%  {s['ll']:9.4f} {s['brier']:7.4f}")
t1 = round(po['top1_rate'] * n); t3 = round(po['top3_rate'] * n)
print(f"{'人気順位だけ(参考)':26s} {t1:4d}/{n} ({po['top1_rate']*100:4.1f}%) {t3:4d}/{n} ({po['top3_rate']*100:4.1f}%) {math.exp(po['mean_log_likelihood'])*100:14.2f}%  {po['mean_log_likelihood']:9.4f} {po['mean_brier']:7.4f}")
print(f"{'全頭同じ確率(参考)':26s} {'':>14s} {'':>16s} {math.exp(un['mean_log_likelihood'])*100:14.2f}%  {un['mean_log_likelihood']:9.4f} {un['mean_brier']:7.4f}")

a, b = res["B (現行・B0-original)"], res["B2.1 (重賞を直した版)"]
diff = [rid for rid in a["picks"] if a["picks"][rid] != b["picks"].get(rid)]
ah = sum(a["picks"][rid] == str(win[rid]) for rid in diff); bh = sum(b["picks"][rid] == str(win[rid]) for rid in diff)
print(f"\n本命(確率1位)が B と B2.1 で違ったレース: {len(diff)}/{n}。そのうち B が当てた {ah}、B2.1 が当てた {bh}、どちらも外れ {len(diff)-ah-bh}")
for name in ("B (現行・B0-original)", "B2.1 (重賞を直した版)"):
    s = res[name]
    same_fav = sum(s["picks"][rid] == str(fav[rid]) for rid in s["picks"])
    print(f"{name}: 本命が最終1番人気と同じレース {same_fav}/{n}")
# how often the winner was ranked k-th
for name in ("B (現行・B0-original)", "B2.1 (重賞を直した版)"):
    preds = models[name]; rank_hist = {}
    for p in preds:
        w = str(win[p["race_id"]]); order = [str(h["hid"]) for h in sorted(p["horses"], key=lambda h: -h["probability"])]
        k = order.index(w) + 1; k = k if k <= 5 else 6
        rank_hist[k] = rank_hist.get(k, 0) + 1
    print(name, "勝ち馬の予想順位の分布(6=6位以下):", dict(sorted(rank_hist.items())))
