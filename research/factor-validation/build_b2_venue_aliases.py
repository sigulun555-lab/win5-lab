#!/usr/bin/env python3
"""Build the preregistered venue-alias dictionary from every observed race venue.

Unknown labels are deliberately UNCLASSIFIABLE; no fuzzy matching is performed.
The generated JSON is deterministic and its SHA256 is printed and saved beside it.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

JRA = {"札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉"}
LOCAL = {"帯広", "門別", "盛岡", "水沢", "浦和", "船橋", "大井", "川崎", "金沢",
         "笠松", "名古屋", "園田", "姫路", "高知", "佐賀"}
# Fixed, explicit shortened forms. Do not add mappings after inspecting model results.
ALIASES = {
    **{v: "JRA" for v in JRA},
    **{v: "LOCAL" for v in LOCAL},
    "名古": "LOCAL", "園田": "LOCAL", "帯広": "LOCAL", "門別": "LOCAL",
    "盛岡": "LOCAL", "水沢": "LOCAL", "浦和": "LOCAL", "船橋": "LOCAL",
    "大井": "LOCAL", "川崎": "LOCAL", "金沢": "LOCAL", "笠松": "LOCAL",
    "姫路": "LOCAL", "高知": "LOCAL", "佐賀": "LOCAL",
}
OVERSEAS_MARKERS = (
    "海外", "アメリカ", "米国", "英国", "イギリス", "フランス", "香港",
    "豪州", "オーストラリア", "ドバイ", "サウ", "サウジ", "韓国", "UAE",
    "カナダ", "ドイツ", "イタリア", "シンガポール", "ニュージーランド",
)

def classify(label: str) -> str:
    if label in ALIASES:
        return ALIASES[label]
    if any(marker in label for marker in OVERSEAS_MARKERS):
        return "OVERSEAS"
    return "UNCLASSIFIABLE"

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="parsed race JSON, e.g. research/factor-validation/races.json")
    ap.add_argument("--out", type=Path, default=Path("research/factor-validation/b2_venue_aliases.json"))
    args = ap.parse_args()
    races = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(races, list):
        raise ValueError("input must be a top-level race list")
    labels = sorted({str(r.get("venue") or "").strip() for r in races if isinstance(r, dict)})
    mapping = {label: classify(label) for label in labels}
    payload = (json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    sidecar = args.out.with_suffix(".sha256")
    sidecar.write_text(f"{digest}  {args.out.name}\n", encoding="ascii")
    counts = {k: sum(v == k for v in mapping.values()) for k in ("JRA", "LOCAL", "OVERSEAS", "UNCLASSIFIABLE")}
    print(json.dumps({
        "status": "dictionary_built_before_fitting",
        "input": str(args.input), "input_races": len(races),
        "distinct_venue_labels": len(labels), "classification_counts": counts,
        "blank_label_present": "" in mapping,
        "dictionary_path": str(args.out), "sha256": digest,
        "sha256_sidecar": str(sidecar),
        "unclassifiable_labels": [k for k, v in mapping.items() if v == "UNCLASSIFIABLE"],
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
