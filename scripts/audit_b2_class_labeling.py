#!/usr/bin/env python3
"""Read-only audit of class labeling v1 (class text as-is) vs v2 (explicit G1/G2/G3 icon) on real data.

Prints: raw class text and grade-icon cross-tab, sample race names per icon, and the per-category
counts of selected JRA history runs in the prepared datasets (train period and test period).
No model is fitted. Race names are shown for review only and are never used for classification.
"""
import argparse, collections, importlib.util, json, sys
from pathlib import Path

FV = Path(__file__).resolve().parents[1] / "research" / "factor-validation"
sys.path.insert(0, str(FV))
spec = importlib.util.spec_from_file_location("b2_dataset_prep", FV / "b2_dataset_prep.py")
PREP = importlib.util.module_from_spec(spec); spec.loader.exec_module(PREP)

ap = argparse.ArgumentParser()
ap.add_argument("races", type=Path)
ap.add_argument("--aliases", type=Path, required=True)
ap.add_argument("--horse-history", type=Path, required=True)
ap.add_argument("--prepared-v1", type=Path, default=None, help="write v1 prepared races here")
ap.add_argument("--prepared-v2", type=Path, default=None, help="write v2 prepared races here")
a = ap.parse_args()

races = json.loads(a.races.read_text(encoding="utf-8"))
print(f"races {len(races)}  with grade field: {sum('grade_icon' in r for r in races)}")
print("== cls x grade_icon (races)")
ct = collections.Counter((r.get("cls", ""), r.get("grade_icon", ""), r.get("grade", "")) for r in races)
for k, v in sorted(ct.items(), key=lambda kv: -kv[1]):
    print(f"  cls={k[0]!r:12} icon={k[1]!r:6} mapped={k[2]!r:4} races={v}")
print("== grade_alt values by icon")
alts = collections.defaultdict(collections.Counter)
for r in races:
    if r.get("grade_icon"): alts[r["grade_icon"]][r.get("grade_alt", "")] += 1
for icon, c in sorted(alts.items()): print(f"  {icon}: {dict(c)}")
print("== sample race names per icon (review only)")
names = collections.defaultdict(collections.Counter)
for r in races:
    if r.get("grade_icon"): names[r["grade_icon"]][r.get("name", "")] += 1
for icon, c in sorted(names.items()): print(f"  {icon} ({sum(c.values())} races): {[n for n, _ in c.most_common(12)]}")
print("== open-class races without any recognised grade (cls=オープン and grade empty), by icon")
nog = collections.Counter(r.get("grade_icon", "") or "(none)" for r in races if r.get("cls") == "オープン" and not r.get("grade"))
print("  ", dict(nog))
print("== obstacle races (cat startswith 障害) in the input:", sum(str(r.get("cat", "")).startswith("障害") for r in races))

aliases = json.loads(a.aliases.read_text(encoding="utf-8"))
history = json.loads(a.horse_history.read_text(encoding="utf-8"))
res = {}
for lab, out in (("v1", a.prepared_v1), ("v2", a.prepared_v2)):
    prepared = PREP.prepare(races, aliases, history, lab)
    res[lab] = prepared
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def counts(prepared, lo, hi, policy="all"):
    c = collections.Counter(); rows = 0; nz = collections.Counter(); prior0 = 0
    for race in prepared:
        if not (lo <= race["date"] <= hi): continue
        for row in race["rows"]:
            cf = row["candidate_features"][policy]
            rows += 1
            if not cf.get("selected"): prior0 += 1
            for run in cf.get("selected", []):
                if run.get("venue_type") == "JRA": c[run["class_category"]] += 1
            for k, v in (cf.get("class_features") or {}).items():
                if v: nz[k] += 1
    return rows, c, nz

for label, (lo, hi) in (("train 2025-10-01..2026-07-31", ("2025-10-01", "2026-07-31")), ("test 2026-08-01..2026-10-24", ("2026-08-01", "2026-10-24"))):
    print(f"== selected JRA history runs by class_category, {label}, policy=all")
    for lab in ("v1", "v2"):
        rows, c, nz = counts(res[lab], lo, hi)
        tot = sum(c.values())
        unk = c.get("UNKNOWN_JRA", 0)
        print(f"  {lab}: runner_rows={rows} selected_jra_runs={tot} unknown={unk} ({unk / tot:.4f}) graded={c.get('GRADED', 0)}")
        print(f"      {dict(sorted(c.items()))}")
        print(f"      runner rows with nonzero class_features: {dict(sorted(nz.items()))}")
print("== prepared race counts:", {lab: len(p) for lab, p in res.items()})
