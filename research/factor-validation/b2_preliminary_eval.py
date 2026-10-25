#!/usr/bin/env python3
"""Preliminary chronological benchmark for the prepared history score.

This is NOT the full registered B2 model: class, local-transition, shrinkage,
rating and nested rolling-origin hyperparameter selection are not fitted here.
It is a diagnostic baseline only and must not be used for adoption.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json
from pathlib import Path
import numpy as np
from scipy.optimize import minimize

def load(path):
    doc=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc,list): raise ValueError("prepared dataset must be a list")
    return doc

def build(races, lo, hi):
    out=[]
    for r in races:
        date=dt.date.fromisoformat(r["date"])
        if not lo <= date <= hi: continue
        rows=r.get("rows",[])
        # Match preregistered formal eligibility: exactly one recorded winner.
        if int(r.get("winner_count",0)) != 1 or len(rows)<5: continue
        pop=np.array([min(max(int(x["pop"]),1),18) for x in rows],dtype=int)
        score=np.array([float(x.get("b2_score",0.0)) for x in rows],dtype=float)
        y=np.array([float(x.get("winner_share",0.0)) for x in rows],dtype=float)
        if not np.isfinite(score).all() or not np.isfinite(y).all() or abs(y.sum()-1)>1e-8: continue
        P=np.zeros((len(rows),18)); P[np.arange(len(rows)),pop-1]=1.0
        out.append({"date":date,"P":P,"b":score,"y":y,"race_id":r["race_id"]})
    return out

def softmax(z):
    z=z-np.max(z); e=np.exp(z); return e/e.sum()

def fit(races, use_b, l2=0.01):
    if not races: raise ValueError("empty training period")
    d=19 if use_b else 18
    def obj(theta):
        loss=0.0; grad=np.zeros(d)
        for r in races:
            X=np.column_stack([r["P"],r["b"]]) if use_b else r["P"]
            p=softmax(X@theta); loss-=float(r["y"]@np.log(np.clip(p,1e-15,1)))
            grad+=X.T@(p-r["y"])
        loss+=l2*float(theta@theta); grad+=2*l2*theta
        return loss,grad
    res=minimize(obj,np.zeros(d),jac=True,method="L-BFGS-B")
    if not res.success and not np.isfinite(res.fun): raise RuntimeError(res.message)
    return res.x

def per_race_ll(races, theta, use_b):
    out=[]
    for r in races:
        X=np.column_stack([r["P"],r["b"]]) if use_b else r["P"]
        p=softmax(X@theta); out.append(float(r["y"]@np.log(np.clip(p,1e-15,1))))
    return np.array(out)

def bootstrap_ci(delta, seed=7, B=4000):
    rng=np.random.default_rng(seed); n=len(delta)
    if n==0: return [None,None]
    ix=rng.integers(0,n,size=(B,n))
    means=delta[ix].mean(axis=1)
    return [float(x) for x in np.percentile(means,[2.5,97.5])]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("input",type=Path)
    ap.add_argument("--out",type=Path,required=True)
    ap.add_argument("--train-end",default="2026-07-31")
    ap.add_argument("--test-start",default="2026-08-01")
    args=ap.parse_args()
    races=load(args.input)
    train=build(races,dt.date(2025,10,1),dt.date.fromisoformat(args.train_end))
    test=build(races,dt.date.fromisoformat(args.test_start),dt.date(2026,10,24))
    if not train or not test: raise SystemExit(f"empty split: train={len(train)} test={len(test)}")
    th0=fit(train,False); th1=fit(train,True)
    ll0=per_race_ll(test,th0,False); ll1=per_race_ll(test,th1,True)
    delta=ll1-ll0
    payload={
      "status":"preliminary_diagnostic_not_full_b2_not_adoption",
      "warning":"Uses final popularity from result pages; this is a retrospective benchmark, not proof of pre-off operational performance.",
      "train":{"start":"2025-10-01","end":args.train_end,"races":len(train)},
      "test":{"start":args.test_start,"end":"2026-10-24","races":len(test)},
      "baseline_popularity_only_mean_log_likelihood":float(ll0.mean()),
      "history_score_plus_popularity_mean_log_likelihood":float(ll1.mean()),
      "delta_combined_minus_popularity":float(delta.mean()),
      "delta_bootstrap_95_ci":bootstrap_ci(delta),
      "test_races":len(test),
      "eligibility":"JRA flat turf/dirt; at least five rows; exactly one recorded winner; test ends 2026-10-24 per preregistration",
      "limitations":["No nested rolling-origin selection of L2/k/tau.","Class interaction, local-transition adjustment, JRA-run shrinkage, and rating candidates are not fitted.","Not a formal B2 adoption test; later forward validation remains required."],
      "input_sha256":hashlib.sha256(args.input.read_bytes()).hexdigest()
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
