"""B2 deterministic feature primitives; no fitting or performance claims."""
from __future__ import annotations
import datetime as dt
from typing import Any, Iterable

JRA_VENUES = {"札幌","函館","福島","新潟","東京","中山","中京","京都","阪神","小倉"}
LOCAL_VENUES = {"帯広","門別","盛岡","水沢","浦和","船橋","大井","川崎","金沢","笠松","名古屋","園田","姫路","高知","佐賀"}
CLASS_CATEGORIES = {"DEBUT","MAIDEN","1WIN","2WIN","3WIN","OP_L","GRADED","UNKNOWN_JRA","LOCAL","OVERSEAS","UNCLASSIFIABLE"}

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
    if label in {"サウ", "サウジ"}: return "OVERSEAS"
    overseas = ("海外","アメリカ","米国","英国","イギリス","フランス","香港","豪州","オーストラリア","ドバイ","サウジ","韓国","UAE","カナダ","ドイツ","イタリア","シンガポール","ニュージーランド")
    if any(t in label for t in overseas): return "OVERSEAS"
    return "UNCLASSIFIABLE"

def classify_race_class(value: Any, venue_type: str = "JRA", class_aliases: dict[str,str] | None = None) -> str:
    """Conservative exact/explicit mapping only; ambiguous race names stay unknown."""
    label = str(value or "").strip()
    if venue_type == "LOCAL": return "LOCAL"
    if venue_type == "OVERSEAS": return "OVERSEAS"
    if venue_type != "JRA": return "UNCLASSIFIABLE"
    if not label: return "UNKNOWN_JRA"
    if class_aliases and label in class_aliases:
        mapped = class_aliases[label]
        return mapped if mapped in CLASS_CATEGORIES else "UNKNOWN_JRA"
    exact = {
        "新馬":"DEBUT", "メイクデビュー":"DEBUT", "未勝利":"MAIDEN",
        "1勝クラス":"1WIN", "１勝クラス":"1WIN", "500万下":"1WIN",
        "2勝クラス":"2WIN", "２勝クラス":"2WIN", "1000万下":"2WIN",
        "3勝クラス":"3WIN", "３勝クラス":"3WIN", "1600万下":"3WIN",
        "オープン":"OP_L", "OP":"OP_L", "リステッド":"OP_L",
        "G1":"GRADED", "G2":"GRADED", "G3":"GRADED",
        "GI":"GRADED", "GII":"GRADED", "GIII":"GRADED",
        "JpnI":"GRADED", "JpnII":"GRADED", "JpnIII":"GRADED",
    }
    if label in exact: return exact[label]
    if any(token in label for token in ("GⅠ","GⅡ","GⅢ","ＧⅠ","ＧⅡ","ＧⅢ")): return "GRADED"
    # Age/sex qualifiers may surround the explicit class label; map only the registered tokens.
    if "新馬" in label or "メイクデビュー" in label: return "DEBUT"
    if "未勝利" in label: return "MAIDEN"
    if "1勝クラス" in label or "１勝クラス" in label or "500万下" in label: return "1WIN"
    if "2勝クラス" in label or "２勝クラス" in label or "1000万下" in label: return "2WIN"
    if "3勝クラス" in label or "３勝クラス" in label or "1600万下" in label: return "3WIN"
    if "リステッド" in label or "オープン" in label or label == "OP": return "OP_L"
    # Names such as 三宮S need a prior-only results join, never name guessing.
    return "UNKNOWN_JRA"

def valid_numeric_finish(run: dict[str,Any]) -> bool:
    try:
        place, field = int(str(run.get("place","")).strip()), int(str(run.get("field","")).strip())
        return 1 <= place <= field and field > 1
    except (TypeError,ValueError): return False

def eligible_prior_runs(runs: Iterable[dict[str,Any]], target_date, *, local_policy="downweight", max_runs=6, aliases=None):
    target = parse_date(target_date) if isinstance(target_date,str) else target_date
    if target is None: raise ValueError("target_date must be a parseable date")
    if local_policy not in {"downweight","exclude"}: raise ValueError("invalid local_policy")
    if max_runs < 0: raise ValueError("max_runs must be >= 0")
    eligible=[]
    for run in runs:
        if not isinstance(run,dict) or not valid_numeric_finish(run): continue
        d=parse_date(run.get("date"))
        if d is None or d >= target: continue
        venue_type=classify_venue(run.get("venue"),aliases)
        if local_policy=="exclude" and venue_type=="LOCAL": continue
        item=dict(run); item["_parsed_date"]=d.isoformat(); item["_venue_type"]=venue_type
        item["_class_category"]=classify_race_class(run.get("class"),venue_type,run.get("_class_aliases"))
        eligible.append(item)
    eligible.sort(key=lambda x:x["_parsed_date"],reverse=True)
    return eligible[:max_runs]

def percentile_score(run):
    if not valid_numeric_finish(run): raise ValueError("invalid finish/field")
    place,field=int(str(run["place"]).strip()),int(str(run["field"]).strip())
    return (field-place)/(field-1)

def b_score(runs: Iterable[dict[str,Any]], target_date, *, local_policy="downweight", local_eta=0.0, shrink_k=0.0, class_gamma=None, aliases=None):
    """Deterministic B2 score primitive. Coefficients must be fitted on training folds."""
    if not -1.0 <= local_eta <= 0.0: raise ValueError("local_eta must be in [-1,0]")
    if local_policy=="exclude" and local_eta != 0.0: raise ValueError("local_eta must be zero for exclude policy")
    if shrink_k < 0: raise ValueError("shrink_k must be >= 0")
    gamma = dict(class_gamma or {})
    if any(k not in CLASS_CATEGORIES for k in gamma): raise ValueError("unknown class_gamma category")
    if gamma.get("DEBUT",0.0) != 0.0: raise ValueError("DEBUT is the fixed reference category (gamma=0)")
    selected=eligible_prior_runs(runs,target_date,local_policy=local_policy,aliases=aliases)
    numerator=denominator=0.0; jra_count=0; details=[]
    for i,run in enumerate(selected):
        base_w=0.78**i; local=run["_venue_type"]=="LOCAL"
        effective_w=base_w*(1.0+local_eta if local and local_policy=="downweight" else 1.0)
        p=percentile_score(run); x=2.1*(p-0.5)
        category=run["_class_category"]
        class_term=gamma.get(category,0.0)*(p-0.5)
        local_term=local_eta*x if local and local_policy=="downweight" else 0.0
        numerator += base_w*(x+class_term+local_term)
        denominator += base_w
        if run["_venue_type"]=="JRA": jra_count+=1
        details.append({"date":run["_parsed_date"],"venue_type":run["_venue_type"],"class_category":category,"place":int(str(run["place"]).strip()),"field":int(str(run["field"]).strip()),"percentile":p,"base_weight":base_w,"effective_weight":effective_w,"class_term":class_term,"local_term":local_term})
    base=numerator/denominator if denominator else 0.0
    shrink=jra_count/(jra_count+shrink_k) if jra_count+shrink_k else 0.0
    return {"score":base*shrink,"base_score":base,"shrink_factor":shrink,"selected_runs":len(selected),"jra_runs_selected":jra_count,"local_policy":local_policy,"local_eta":local_eta,"shrink_k":shrink_k,"details":details}

def candidate_feature_summary(runs: Iterable[dict[str,Any]], target_date, *, aliases=None, local_policy="downweight", max_runs=6):
    """Return fixed sufficient statistics for the preregistered conditional-logit candidates."""
    selected = eligible_prior_runs(runs, target_date, local_policy=local_policy, max_runs=max_runs, aliases=aliases)
    denominator = sum(0.78 ** i for i in range(len(selected)))
    if denominator <= 0:
        return {"base_score": 0.0, "class_features": {}, "local_feature": 0.0,
                "jra_runs_selected": 0, "rating_delta": 0.0, "rating_runs": 0,
                "selected_runs": 0, "selected": []}
    base_sum = 0.0
    class_sums = {}
    local_sum = 0.0
    jra_count = 0
    rating_sum = 0.0
    rating_weight = 0.0
    rating_runs = 0
    details = []
    for i, run in enumerate(selected):
        weight = 0.78 ** i
        p = percentile_score(run)
        centered = p - 0.5
        x = 2.1 * centered
        venue_type = run["_venue_type"]
        category = run["_class_category"]
        base_sum += weight * x
        if category != "DEBUT" and category in CLASS_CATEGORIES and category not in {"LOCAL", "OVERSEAS", "UNCLASSIFIABLE"}:
            class_sums[category] = class_sums.get(category, 0.0) + weight * centered
        if venue_type == "LOCAL" and local_policy == "downweight":
            local_sum += weight * x
        rating_value = None
        if venue_type == "JRA":
            jra_count += 1
            raw_rating = str(run.get("rt", run.get("rating", "")) or "").strip()
            import re
            match = re.search(r"[-+]?\d+(?:\.\d+)?", raw_rating)
            if match:
                rating_value = float(match.group(0))
                rating_sum += weight * rating_value
                rating_weight += weight
                rating_runs += 1
        details.append({"date": run["_parsed_date"], "venue": str(run.get("venue") or ""),
                        "venue_type": venue_type, "class_category": category,
                        "place": int(str(run["place"]).strip()), "field": int(str(run["field"]).strip()),
                        "weight": weight, "percentile": p, "rating": rating_value})
    return {
        "base_score": base_sum / denominator,
        "class_features": {k: v / denominator for k, v in class_sums.items()},
        "local_feature": local_sum / denominator,
        "jra_runs_selected": jra_count,
        "rating_delta": (rating_sum / rating_weight - 90.0) if rating_weight else 0.0,
        "rating_runs": rating_runs,
        "selected_runs": len(selected),
        "selected": details,
    }


def history_runs_for_horse(bundle: dict[str,Any], hid: str):
    horses=bundle.get("horses",{}) if isinstance(bundle,dict) else {}
    horse=horses.get(hid,{}) if isinstance(horses,dict) else {}
    runs=horse.get("runs",[]) if isinstance(horse,dict) else []
    return runs if isinstance(runs,list) else []
