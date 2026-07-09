"""Tests for ParadigmAbstractor trigger-type selection.

No API calls: exercises the pure ``_dominant_types`` helper that anchors a
paradigm's trigger in the cluster's KDP tag namespace. Taking the raw union
of all cluster constraint types makes triggers fire everywhere on
heterogeneous states (AR-LSAT), so only majority types survive, capped at
the most frequent few.
"""

from __future__ import annotations

from prism.core.types import KDP, StepType, TrajectoryStep
from prism.offline.paradigm_abstractor import (
    _MAX_TRIGGER_TYPES,
    ParadigmAbstractor,
)


def _kdp(types):
    return KDP(
        trajectory_id="t",
        puzzle_id="p",
        step=TrajectoryStep(
            iteration=0, action="repair", step_type=StepType.BASIC, z3_result="SAT",
        ),
        constraint_types=types,
        feature_vector=[0.0],
        kdp_type="repair",
    )


def test_dominant_types_keeps_majority_drops_rare():
    kdps = [
        _kdp(["exclusion", "ordering", "adjacent"]),
        _kdp(["exclusion", "ordering", "binding"]),
        _kdp(["exclusion", "ordering", "inclusion", "domain_bound"]),
        _kdp(["exclusion", "direct_position"]),
    ]
    # 'exclusion' 4/4 and 'ordering' 3/4 clear the majority threshold;
    # the five singleton types must be dropped.
    assert ParadigmAbstractor._dominant_types(kdps) == ["exclusion", "ordering"]


def test_dominant_types_caps_at_max():
    shared = ["a", "b", "c", "d", "e", "f"]
    kdps = [_kdp(list(shared)) for _ in range(3)]
    result = ParadigmAbstractor._dominant_types(kdps)
    assert len(result) == _MAX_TRIGGER_TYPES


def test_dominant_types_falls_back_when_no_majority():
    # Five disjoint singletons: nothing clears 50%, but the trigger must not
    # end up empty — fall back to the most frequent types, capped.
    kdps = [_kdp([t]) for t in ["a", "b", "c", "d", "e"]]
    result = ParadigmAbstractor._dominant_types(kdps)
    assert 0 < len(result) <= _MAX_TRIGGER_TYPES


def test_dominant_types_ignores_unknown_and_duplicates():
    # 'unknown' never counts; duplicate tags within one KDP count once.
    kdps = [
        _kdp(["exclusion", "exclusion", "unknown"]),
        _kdp(["exclusion", "unknown"]),
    ]
    assert ParadigmAbstractor._dominant_types(kdps) == ["exclusion"]


def test_dominant_types_empty_cluster():
    assert ParadigmAbstractor._dominant_types([]) == []
