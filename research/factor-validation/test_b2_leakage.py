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


from b2_class_lookup import build_prior_class_lookup, lookup_prior_class


class B2PriorClassLookupTests(unittest.TestCase):
    def setUp(self):
        self.races = [
            {"date": "2026-01-01", "venue": "東京", "cls": "G3",
             "rows": [{"hid": "winner", "place": 1}, {"hid": "other", "place": 2}]},
            {"date": "2026-01-02", "venue": "東京", "cls": "OP",
             "rows": [{"hid": "winner", "place": 1}, {"hid": "other", "place": 2}]},
            {"date": "2026-01-03", "venue": "阪神", "cls": "G2",
             "rows": [{"hid": "winner", "place": 1}, {"hid": "other", "place": 1}]},
        ]

    def test_only_strictly_prior_races_enter_lookup(self):
        lookup = build_prior_class_lookup(self.races, "2026-01-02")
        self.assertEqual(len(lookup), 1)
        self.assertEqual(lookup[("2026-01-01", "東京", "winner")], "G3")

    def test_future_run_cannot_be_looked_up_for_earlier_prediction(self):
        lookup = build_prior_class_lookup(self.races, "2026-01-04")
        self.assertEqual(lookup_prior_class(lookup, "2026-01-02", "東京", "winner", "2026-01-02"), "UNKNOWN_JRA")

    def test_ambiguous_winners_are_not_joined(self):
        lookup = build_prior_class_lookup(self.races, "2026-01-04")
        self.assertNotIn(("2026-01-03", "阪神", "winner"), lookup)

    def test_missing_match_stays_unknown_not_guessed(self):
        lookup = build_prior_class_lookup(self.races, "2026-01-04")
        self.assertEqual(lookup_prior_class(lookup, "2026-01-01", "京都", "winner", "2026-01-04"), "UNKNOWN_JRA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
