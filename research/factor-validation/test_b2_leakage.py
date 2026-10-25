#!/usr/bin/env python3
"""Deterministic leakage tests for B2 feature construction.

These tests use synthetic histories only; they do not claim model performance.
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path

from b2_features import b_score, eligible_prior_runs, classify_venue


class B2LeakageTests(unittest.TestCase):
    def setUp(self):
        self.target = "2026-01-10"
        self.history = [
            {"date": "2026-01-09", "venue": "東京", "class": "1勝クラス", "place": "2", "field": "10"},
            {"date": "2026-01-10", "venue": "東京", "class": "1勝クラス", "place": "1", "field": "10"},
            {"date": "2026-01-11", "venue": "東京", "class": "G3", "place": "1", "field": "12"},
        ]

    def test_same_day_and_future_runs_are_excluded(self):
        selected = eligible_prior_runs(self.history, self.target)
        self.assertEqual([x["_parsed_date"] for x in selected], ["2026-01-09"])

    def test_adding_future_results_does_not_change_features(self):
        before = b_score(self.history[:1], self.target)["score"]
        after = b_score(self.history, self.target)["score"]
        self.assertEqual(before, after)

    def test_local_exclusion_happens_before_recent_six_selection(self):
        history = []
        for i in range(8):
            history.append({
                "date": f"2026-01-{9-i:02d}",
                "venue": "園田" if i < 4 else "東京",
                "class": "LOCAL" if i < 4 else "1勝クラス",
                "place": "1" if i % 2 == 0 else "4",
                "field": "10",
            })
        selected = eligible_prior_runs(history, self.target, local_policy="exclude", max_runs=6)
        self.assertEqual(len(selected), 4)
        self.assertTrue(all(x["_venue_type"] == "JRA" for x in selected))

    def test_alias_mapping_is_explicit_and_unknowns_stay_unclassifiable(self):
        aliases = {"名古": "LOCAL", "米": "UNCLASSIFIABLE"}
        self.assertEqual(classify_venue("名古", aliases), "LOCAL")
        self.assertEqual(classify_venue("米", aliases), "UNCLASSIFIABLE")
        self.assertEqual(classify_venue("不明競馬場", aliases), "UNCLASSIFIABLE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
