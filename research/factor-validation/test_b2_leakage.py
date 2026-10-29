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
from b2_dataset_prep import _history_seed, prepare
from fit_b2_candidates import candidate_design, fit_theta


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


class B2DatasetClassJoinTests(unittest.TestCase):
    def test_history_class_join_is_prior_only_and_uses_runner_id(self):
        bundle = {"horses": {"runner": {"runs": [
            {"date": "2026-01-01", "venue": "東京", "place": "2", "field": "10"},
            {"date": "2026-01-03", "venue": "東京", "place": "1", "field": "10"},
        ]}}}
        races = [
            {"date": "2026-01-01", "venue": "東京", "cls": "G3", "rows": [{"hid": "winner", "place": 1}, {"hid": "runner", "place": 2}]},
            {"date": "2026-01-02", "venue": "東京", "cls": "OP", "rows": [{"hid": "winner2", "place": 1}, {"hid": "runner", "place": 3}]},
            {"date": "2026-01-04", "venue": "東京", "cls": "G2", "rows": [{"hid": "winner3", "place": 1}, {"hid": "runner", "place": 2}]},
        ]
        seeded = _history_seed(bundle, __import__("datetime").date(2026, 1, 5), races)
        self.assertEqual([r["class"] for r in seeded["runner"]], ["G3", ""])

    def test_direct_horse_pages_bundle_is_supported(self):
        bundle = {"runner": {"profile": {}, "runs": [
            {"date": "2026-01-01", "venue": "東京", "place": "2", "field": "10"}
        ]}}
        seeded = _history_seed(bundle, __import__("datetime").date(2026, 1, 5), self.races)
        self.assertEqual(seeded["runner"][0]["place"], 2)

    def test_ambiguous_duplicate_race_match_stays_unknown(self):
        bundle = {"horses": {"runner": {"runs": [{"date": "2026-01-01", "venue": "東京", "place": "2", "field": "10"}]}}}
        races = [
            {"date": "2026-01-01", "venue": "東京", "cls": "G3", "rows": [{"hid": "winner", "place": 1}, {"hid": "runner", "place": 2}]},
            {"date": "2026-01-01", "venue": "東京", "cls": "G1", "rows": [{"hid": "winner2", "place": 1}, {"hid": "runner", "place": 2}]},
        ]
        seeded = _history_seed(bundle, __import__("datetime").date(2026, 1, 5), races)
        self.assertEqual(seeded["runner"][0]["class"], "")



class B2RaceEligibilityTests(unittest.TestCase):
    def test_multi_winner_flat_race_is_excluded_not_fractional_labelled(self):
        race = {
            "date": "2026-01-01", "venue": "東京", "rn": 8,
            "surface": "芝", "dist": 1800, "cls": "1勝クラス",
            "rows": [
                {"hid": f"h{i}", "num": i, "pop": i, "place": 1 if i in (1, 2) else i}
                for i in range(1, 7)
            ],
        }
        self.assertEqual(prepare([race]), [])

    def test_single_winner_flat_race_is_kept_with_one_full_winner_label(self):
        race = {
            "date": "2026-01-01", "venue": "東京", "rn": 8,
            "surface": "芝", "dist": 1800, "cls": "1勝クラス",
            "rows": [
                {"hid": f"h{i}", "num": i, "pop": i, "place": 1 if i == 1 else i}
                for i in range(1, 7)
            ],
        }
        prepared = prepare([race])
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["winner_count"], 1)
        self.assertEqual(sum(x["winner_share"] for x in prepared[0]["rows"]), 1.0)



class B2CandidateFitSmokeTests(unittest.TestCase):
    def test_design_applies_shrink_to_base_and_class_but_not_rating(self):
        row = {"candidate_features": {"all": {
            "base_score": 2.0, "class_features": {"MAIDEN": 0.2},
            "local_feature": 0.1, "jra_runs_selected": 2, "rating_delta": 4.0
        }}}
        spec = {"policy": "all", "class": True, "shrink": True, "local": False, "rating": True}
        base, columns = candidate_design(row, spec, 2)
        self.assertAlmostEqual(base, 1.0)
        self.assertAlmostEqual(columns[0], 0.1)
        self.assertAlmostEqual(columns[-1], 4.0)

    def test_candidate_fit_returns_finite_coefficients(self):
        spec = {"policy": "all", "class": True, "shrink": False, "local": False, "rating": False}
        races = []
        for r in range(6):
            rows = []
            for h in range(5):
                rows.append({
                    "winner_share": 1.0 if h == (r % 5) else 0.0,
                    "candidate_features": {"all": {
                        "base_score": (4-h)*0.1,
                        "class_features": {"MAIDEN": (h-2)*0.1, "UNKNOWN_JRA": 0.0},
                        "local_feature": 0.0, "jra_runs_selected": 3, "rating_delta": 0.0
                    }}
                })
            races.append({"rows": rows})
        theta = fit_theta(races, spec, 0.01, 0, 0.75)
        self.assertEqual(len(theta), 7)
        self.assertTrue(all(__import__("math").isfinite(float(x)) for x in theta))
\n\nif __name__ == "__main__":
    unittest.main(verbosity=2)
