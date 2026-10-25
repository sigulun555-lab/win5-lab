#!/usr/bin/env python3
"""Audit a collected horse-history JSON bundle before B2 fitting.

Usage:
  python3 scripts/audit_b2_history_bundle.py data/horse_history/2026-10-25.json
  python3 scripts/audit_b2_history_bundle.py path/to/collected-horse-history.json --out reports/b2-history-audit.json

This script only audits data availability and integrity. It does not fit B2 or claim
that the sample is sufficient for temporal validation. It never edits the input.
"""
from __future__ import annotations
import argparse
import collections
import datetime as dt
import hashlib
import json
from pathlib import Path

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def parse_date(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    for fmt in ('%Y年%m月%d日', '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d'):
        try:
            return dt.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=Path)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    path = args.input
    raw = path.read_bytes()
    doc = json.loads(raw)
    # Accept the collector's {horses: {hid: {runs: [...]}}} bundle or a direct map.
    horses = doc.get('horses') if isinstance(doc, dict) else None
    if not isinstance(horses, dict):
        horses = doc if isinstance(doc, dict) else {}
    horse_count = len(horses)
    run_count = 0
    missing_hid = 0
    missing_runs = 0
    invalid_run_rows = 0
    invalid_dates = 0
    future_or_unparseable = 0
    missing_fields = collections.Counter()
    venues = collections.Counter()
    dates = []
    duplicate_run_keys = 0
    administrative_event_rows = 0
    missing_field_examples = []
    for hid, horse in horses.items():
        if not str(hid).strip():
            missing_hid += 1
        if not isinstance(horse, dict) or not isinstance(horse.get('runs'), list):
            missing_runs += 1
            continue
        seen = set()
        for run in horse['runs']:
            if not isinstance(run, dict):
                invalid_run_rows += 1
                continue
            run_count += 1
            race_label = str(run.get('race', '')).strip()
            is_admin_event = race_label in {'JRAへ転入', 'JRAより転出', '地方へ転入', '地方より転出'}
            if is_admin_event:
                administrative_event_rows += 1
            required_fields = ('date',) if is_admin_event else ('date', 'venue', 'race', 'field', 'place')
            missing_here = [field for field in required_fields if not str(run.get(field, '')).strip()]
            for field in missing_here:
                missing_fields[field] += 1
            if missing_here and len(missing_field_examples) < 25:
                missing_field_examples.append({
                    'horse_id': str(hid),
                    'date': str(run.get('date', '')).strip() or None,
                    'venue': str(run.get('venue', '')).strip() or None,
                    'race': str(run.get('race', '')).strip() or None,
                    'missing_fields': missing_here,
                })
            date = parse_date(run.get('date'))
            if date is None:
                invalid_dates += 1
            else:
                dates.append(date)
            venues[str(run.get('venue', '')).strip() or '<EMPTY>'] += 1
            key = (date, str(run.get('venue', '')).strip(), str(run.get('race', '')).strip(), str(run.get('place', '')).strip())
            if key in seen:
                duplicate_run_keys += 1
            seen.add(key)
    report = {
        'input_path': str(path),
        'input_bytes': len(raw),
        'input_sha256': hashlib.sha256(raw).hexdigest(),
        'audit_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'schema_detected': 'collector_horses_map' if isinstance(doc, dict) and isinstance(doc.get('horses'), dict) else 'direct_map_or_unknown',
        'horse_records': horse_count,
        'run_records': run_count,
        'horses_without_run_list': missing_runs,
        'empty_horse_ids': missing_hid,
        'non_object_run_rows': invalid_run_rows,
        'administrative_event_rows_not_treated_as_races': administrative_event_rows,
        'unparseable_run_dates': invalid_dates,
        'duplicate_run_keys_within_horse': duplicate_run_keys,
        'missing_required_field_counts': dict(missing_fields),
        'missing_field_examples_first_25': missing_field_examples,
        'distinct_venue_labels': len(venues),
        'venue_label_counts': dict(venues.most_common()),
        'date_min': min(dates) if dates else None,
        'date_max': max(dates) if dates else None,
        'status': 'audit_only_not_b2_validation',
        'limitations': [
            'A history-page bundle is not by itself the race-level training dataset required by the B2 protocol.',
            'Run dates must be filtered to strictly before each target race date during feature construction.',
            'Class mapping, venue alias dictionary, race-level winner labels, time splits, and leakage tests are audited separately.',
            'This script does not infer missing values or determine whether coverage is sufficient.',
        ],
    }
    output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding='utf-8')
    print(output, end='')

if __name__ == '__main__':
    main()