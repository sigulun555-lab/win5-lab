"""B2 deterministic feature primitives; no fitting or performance claims."""
from __future__ import annotations
import datetime as dt
from typing import Any, Iterable
JRA_VENUES = {"札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉"}
LOCAL_VENUES = {"帯広","門別","盛岡","水沢","浦和","船橋","大井","川崎","金沢","笠松","名古屋","園田","姫路","高知","佐賀"}
def parse_date(value: Any):
    if not isinstance(value, str): return None
    for fmt in ("%Y年%m月%d日","%Y-%m-%d","%Y/%m/%d","%Y.%m.%d"):
        try: return dt.datetime.strptime(value.strip(), fmt).date()
        except ValueError: pass
    return None
def classify_venue(value: Any, aliases: dict[str,str] | None = None) -> str:
    label = str(value or "").strip()
    if not label: return "UNCLASSIFIABLE"
    if aliases and label in aliases:
        return aliases[label] if aliases[label] in {"JRA","LOCAL","OVERSEAS","UNCLASSIFIABLE"} else "UNCLASSIFIABLE"
    if label in JRA_VENUES: return "JRA"
    if label in LOCAL_VENUES: return "LOCAL"
    overseas = ("海外","アメリカ","英国","イギリス","フランス","香港","豪州","オーストラリア","ドバイ","サウジ","韓国","UAE")
    if any(t in label for t in overseas): return "OVERSEAS"
    return "UNCLASSIFIABLE"
def valid_numeric_finish(run: dict[str,Any]) -> bool:
    try: return int(str(run.get("place","")).strip()) >= 1 and int(str(run.get("field","")).strip()) > 1
    except (TypeError,ValueError): return False
def eligible_prior_runs(runs: Iterable[dict[str,Any]], target_date, *, local_policy="downweight", max_runs=6, aliases=None):
    target = parse_date(target_date) if isinstance(target_date,str) else target_date
    if target is None: raise ValueError("target_date must be a parseable date")
    if local_policy not in {"downweight","exclude"}: raise ValueError("invalid local_policy")
    eligible=[]
    for run in runs:
        if not isinstance(run,dict) or not valid_numeric_finish(run): continue
        d=parse_date(run.get("date"))
        if d is None or d >= target: continue
        venue_type=classify_venue(run.get("venue"),aliases)
        if local_policy=="exclude" and venue_type=="LOCAL": continue
        item=dict(run); item["_parsed_date"]=d.isoformat(); item["_venue_type"]=venue_type; eligible.append(item)
    eligible.sort(key=lambda x:x["_parsed_date"],reverse=True)
    return eligible[:max_runs]
def percentile_score(run):
    if not valid_numeric_finish(run): raise ValueError("invalid finish/field")
    place,field=int(str(run["place"]).strip()),int(str(run["field"]).strip())
    return (field-place)/(field-1)
def b_score(runs: Iterable[dict[str,Any]], target_date, *, local_policy="downweight", local_eta=0.0, shrink_k=0.0, aliases=None):
    """Base score with frozen weights. Class gamma/rating and calibration are separate steps."""
    if not -1.0 <= local_eta <= 0.0: raise ValueError("local_eta must be in [-1,0]")
    if shrink_k < 0: raise ValueError("shrink_k must be >= 0")
    selected=eligible_prior_runs(runs,target_date,local_policy=local_policy,aliases=aliases)
    numerator=denominator=0.0; jra_count=0; details=[]
    for i,run in enumerate(selected):
        base_w=0.78**i; local=run["_venue_type"]=="LOCAL"
        weight=base_w*(1.0+local_eta if local and local_policy=="downweight" else 1.0)
        p=percentile_score(run); x=2.1*(p-0.5)
        numerator += weight*x; denominator += base_w
        if run["_venue_type"]=="JRA": jra_count+=1
        details.append({"date":run["_parsed_date"],"venue_type":run["_venue_type"],"place":int(str(run["place"]).strip()),"field":int(str(run["field"]).strip()),"percentile":p,"base_weight":base_w,"effective_weight":weight})
    base=numerator/denominator if denominator else 0.0
    shrink=jra_count/(jra_count+shrink_k) if jra_count+shrink_k else 0.0
    return {"score":base*shrink,"base_score":base,"shrink_factor":shrink,"selected_runs":len(selected),"jra_runs_selected":jra_count,"local_policy":local_policy,"local_eta":local_eta,"shrink_k":shrink_k,"details":details}
def history_runs_for_horse(bundle: dict[str,Any], hid: str):
    horses=bundle.get("horses",{}) if isinstance(bundle,dict) else {}
    horse=horses.get(hid,{}) if isinstance(horses,dict) else {}
    runs=horse.get("runs",[]) if isinstance(horse,dict) else []
    return runs if isinstance(runs,list) else []