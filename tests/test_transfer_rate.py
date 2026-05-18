"""Tests for prism.evaluation.transfer_rate — L1/L2 transfer metrics."""

from __future__ import annotations

import pytest

from prism.evaluation.transfer_rate import (
    l1_cross_scale_summary,
    l2_cross_domain_summary,
    paradigm_transfer_rate,
    solve_accuracy,
)


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _result(solved: bool, domain: str = "4x5", triggered: bool = False, correct: bool = False) -> dict:
    return {
        "puzzle_id": "p1",
        "domain": domain,
        "solved": solved,
        "llm_calls": 3,
        "repair_rounds": 1,
        "steps": [{"paradigm_triggered": triggered, "paradigm_correct": correct, "stagnated": False}],
    }


# --------------------------------------------------------------------------- #
# solve_accuracy (internal helper exposed as alias)                             #
# --------------------------------------------------------------------------- #

class TestSolveAccuracy:

    def test_all_solved(self):
        results = [_result(True), _result(True)]
        assert solve_accuracy(results) == 1.0

    def test_none_solved(self):
        results = [_result(False), _result(False)]
        assert solve_accuracy(results) == 0.0

    def test_half_solved(self):
        results = [_result(True), _result(False)]
        assert solve_accuracy(results) == pytest.approx(0.5)

    def test_empty_list_returns_zero(self):
        assert solve_accuracy([]) == 0.0


# --------------------------------------------------------------------------- #
# paradigm_transfer_rate()                                                      #
# --------------------------------------------------------------------------- #

class TestParadigmTransferRate:

    def test_empty_returns_zeros(self):
        result = paradigm_transfer_rate([], [])
        assert result == {"trigger_rate": 0.0, "hit_rate": 0.0, "delta_accuracy": 0.0}

    def test_trigger_rate_computed_from_target(self):
        source = [_result(True)]
        target = [
            _result(True,  triggered=True),
            _result(False, triggered=False),
        ]
        r = paradigm_transfer_rate(source, target)
        # 1 step triggered out of 2 total steps
        assert r["trigger_rate"] == pytest.approx(0.5)

    def test_hit_rate_correct_fraction(self):
        source = [_result(True)]
        target = [
            _result(True, triggered=True, correct=True),
            _result(True, triggered=True, correct=False),
        ]
        r = paradigm_transfer_rate(source, target)
        # 2 triggered, 1 correct → 0.5
        assert r["hit_rate"] == pytest.approx(0.5)

    def test_hit_rate_zero_when_no_triggered(self):
        source = [_result(True)]
        target = [_result(False, triggered=False)]
        r = paradigm_transfer_rate(source, target)
        assert r["hit_rate"] == 0.0

    def test_positive_delta_accuracy(self):
        source = [_result(False), _result(False)]   # 0% accuracy
        target = [_result(True), _result(True)]      # 100% accuracy
        r = paradigm_transfer_rate(source, target)
        assert r["delta_accuracy"] == pytest.approx(1.0)

    def test_negative_delta_accuracy(self):
        source = [_result(True), _result(True)]   # 100%
        target = [_result(False), _result(False)] # 0%
        r = paradigm_transfer_rate(source, target)
        assert r["delta_accuracy"] == pytest.approx(-1.0)

    def test_zero_delta_accuracy_same_performance(self):
        results = [_result(True), _result(False)]  # 50% each
        r = paradigm_transfer_rate(results, list(results))
        assert r["delta_accuracy"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# l1_cross_scale_summary()                                                      #
# --------------------------------------------------------------------------- #

class TestL1CrossScaleSummary:

    def test_returns_one_row_per_config(self):
        configs = {
            "Config-A": [_result(True, domain="4x5")],
            "Config-B": [_result(False, domain="4x5")],
        }
        rows = l1_cross_scale_summary(configs, ["4x5"])
        assert len(rows) == 2

    def test_accuracy_per_size_correct(self):
        configs = {
            "Config-A": [_result(True, domain="4x5"), _result(False, domain="5x5")],
        }
        rows = l1_cross_scale_summary(configs, ["4x5", "5x5"])
        row = rows[0]
        assert row["4x5"] == pytest.approx(1.0)
        assert row["5x5"] == pytest.approx(0.0)

    def test_missing_size_returns_none(self):
        configs = {"Config-A": [_result(True, domain="4x5")]}
        rows = l1_cross_scale_summary(configs, ["4x5", "6x6"])
        row = rows[0]
        assert row["6x6"] is None

    def test_config_label_in_row(self):
        configs = {"My Config": [_result(True, domain="4x5")]}
        rows = l1_cross_scale_summary(configs, ["4x5"])
        assert rows[0]["config"] == "My Config"


# --------------------------------------------------------------------------- #
# l2_cross_domain_summary()                                                     #
# --------------------------------------------------------------------------- #

class TestL2CrossDomainSummary:

    def test_returns_expected_keys(self):
        zebra = [_result(True)]
        knk = [_result(False)]
        summary = l2_cross_domain_summary(zebra, knk)
        expected_keys = {
            "zebra_accuracy", "knk_accuracy",
            "knk_trigger_rate", "knk_hit_rate", "delta_accuracy",
        }
        assert expected_keys == set(summary.keys())

    def test_accuracy_values_correct(self):
        zebra = [_result(True), _result(True)]    # 100%
        knk = [_result(False), _result(False)]    # 0%
        summary = l2_cross_domain_summary(zebra, knk)
        assert summary["zebra_accuracy"] == pytest.approx(1.0)
        assert summary["knk_accuracy"] == pytest.approx(0.0)

    def test_delta_accuracy_computed(self):
        zebra = [_result(True)]   # 100%
        knk = [_result(False)]    # 0%
        summary = l2_cross_domain_summary(zebra, knk)
        assert summary["delta_accuracy"] == pytest.approx(-1.0)
