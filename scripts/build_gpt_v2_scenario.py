#!/usr/bin/env python3
"""Create an auditable V2 probability scenario by updating V1 with market movement.

Formula: V2_i ∝ V1_i * (old_odds_i / latest_odds_i) ** alpha.
alpha=0 preserves V1; alpha=1 applies the full relative odds movement.
This is a market-informed scenario, NOT a newly trained independent GPT model.
"""
from __future__ import annotations
import argparse, csv, math
from collections import defaultdict
from pathlib import Path

RACE="race"
OLD_ODDS="win_odds"
NEW_ODDS="latest_observed_win_odds"
V1="gpt_estimated_win_probability_pct"
V2="gpt_v2_market_adjusted_probability_pct"

def build(input_path: Path, output_path: Path, alpha: float=1.0) -> dict[str,float]:
    if not math.isfinite(alpha) or alpha < 0:
        raise ValueError("alpha must be finite and >= 0")
    with input_path.open(newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if not reader.fieldnames: raise ValueError("CSV header missing")
        fields=list(reader.fieldnames); rows=list(reader)
    required={RACE,OLD_ODDS,NEW_ODDS,V1}
    missing=sorted(required-set(fields))
    if missing: raise ValueError("Required columns missing: "+", ".join(missing))
    if V2 not in fields: fields.append(V2)
    groups=defaultdict(list)
    for row in rows:
        race=(row.get(RACE) or "").strip()
        try: old,new,p=float(row[OLD_ODDS]),float(row[NEW_ODDS]),float(row[V1])
        except (TypeError,ValueError): raise ValueError(f"Missing/invalid value: {race}/{row.get('horse_name','')}")
        if not race or not all(math.isfinite(x) for x in (old,new,p)) or old<=1 or new<=1 or p<=0:
            raise ValueError(f"Invalid race/odds/probability: {race}/{row.get('horse_name','')}")
        groups[race].append((row, p*((old/new)**alpha)))
    sums={}
    for race,items in groups.items():
        total=sum(weight for _,weight in items)
        if total<=0 or not math.isfinite(total): raise ValueError(f"Invalid total weight for {race}")
        exact=[weight/total*100 for _,weight in items]
        cents=[math.floor(p*100) for p in exact]
        remain=10000-sum(cents)
        order=sorted(range(len(cents)),key=lambda i: exact[i]*100-cents[i],reverse=True)
        for i in order[:remain]: cents[i]+=1
        for (row,_),value in zip(items,cents): row[V2]=f"{value/100:.2f}"
        sums[race]=sum(float(row[V2]) for row,_ in items)
    output_path.parent.mkdir(parents=True,exist_ok=True)
    with output_path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
    return sums

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--alpha",type=float,default=1.0,help="market movement strength; default 1.0")
    a=p.parse_args()
    sums=build(a.input,a.output,a.alpha)
    for race,total in sums.items(): print(f"{race}: {total:.2f}%")
    if any(abs(v-100)>1e-9 for v in sums.values()): raise SystemExit("V2 probability sum validation failed")
    print(f"Wrote: {a.output}")
    print("NOTE: V2 is a market-informed scenario, not an independently generated GPT model.")

if __name__=="__main__": main()
