"""Leakage-safe class lookup for historical horse runs.

A class is attached only when exactly one prior result race matches the
historical run's date, normalized venue, and recorded winner horse ID.
Ambiguous/missing matches stay UNKNOWN_JRA; this module never guesses from names.
"""
from __future__ import annotations
import datetime as dt
from collections import defaultdict


def _date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _venue(value):
    return str(value or "").strip()


def build_prior_class_lookup(result_races, prediction_date):
    """Return (run_date, venue, winner_hid) -> class for unique strictly prior races."""
    cutoff = _date(prediction_date)
    if cutoff is None:
        raise ValueError("prediction_date must be a parseable date")
    matches = defaultdict(list)
    for race in result_races if isinstance(result_races, list) else []:
        if not isinstance(race, dict):
            continue
        race_date = _date(race.get("date"))
        if race_date is None or race_date >= cutoff:
            continue
        venue = _venue(race.get("venue"))
        cls = str(race.get("cls") or race.get("class") or "").strip()
        if not venue or not cls:
            continue
        rows = race.get("rows", [])
        winners = [r for r in rows if isinstance(r, dict) and str(r.get("place", "")).strip() == "1" and r.get("hid")]
        if len(winners) != 1:
            continue
        key = (race_date.isoformat(), venue, str(winners[0]["hid"]))
        matches[key].append(cls)
    # Ambiguous duplicate matches are deliberately not resolved by file order.
    return {key: values[0] for key, values in matches.items() if len(values) == 1}


def lookup_prior_class(lookup, run_date, venue, winner_hid, prediction_date):
    """Look up a class only for a run strictly before the prediction date."""
    run_day, cutoff = _date(run_date), _date(prediction_date)
    if run_day is None or cutoff is None or run_day >= cutoff:
        return "UNKNOWN_JRA"
    return lookup.get((run_day.isoformat(), _venue(venue), str(winner_hid)), "UNKNOWN_JRA")
