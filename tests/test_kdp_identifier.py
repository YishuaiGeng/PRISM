"""Tests for KDPIdentifier — Key Decision Point extraction from trajectories."""

from __future__ import annotations

import uuid

import pytest

from prism.core.types import KDP, StepType, Trajectory, TrajectoryStep
from prism.offline.kdp_identifier import (
    KDPIdentifier,
    _ALL_TYPES,
    _DOMAIN_DROP_THRESHOLD,
)


# --------------------------------------------------------------------------- #
# Factories                                                                     #
# --------------------------------------------------------------------------- #

def make_step(
    *,
    step_type: StepType = StepType.BASIC,
    domain_sizes_before: dict | None = None,
    domain_sizes_after: dict | None = None,
    constraint_added: str | None = None,
    z3_result: str = "SAT",
    iteration: int = 0,
) -> TrajectoryStep:
    return TrajectoryStep(
        iteration=iteration,
        action="infer",
        step_type=step_type,
        constraint_added=constraint_added,
        z3_result=z3_result,
        domain_sizes_before=domain_sizes_before or {},
        domain_sizes_after=domain_sizes_after or {},
    )


def make_trajectory(steps: list[TrajectoryStep]) -> Trajectory:
    return Trajectory(
        trajectory_id=str(uuid.uuid4()),
        puzzle_id="test_puzzle",
        puzzle_nl="test puzzle",
        temperature=0.7,
        seed=42,
        steps=steps,
    )


def make_solved_trajectory(steps: list[TrajectoryStep]) -> Trajectory:
    traj = make_trajectory(steps)
    return traj.model_copy(update={"solved": True, "final_result": "SAT"})


@pytest.fixture
def identifier():
    return KDPIdentifier()


# --------------------------------------------------------------------------- #
# Condition A: domain drop ≥ threshold                                          #
# --------------------------------------------------------------------------- #

class TestConditionA:

    def test_exactly_at_threshold_is_kdp(self, identifier):
        step = make_step(
            domain_sizes_before={"var1": 5},
            domain_sizes_after={"var1": 5 - _DOMAIN_DROP_THRESHOLD},
        )
        assert identifier._condition_a(step) is True

    def test_above_threshold_is_kdp(self, identifier):
        step = make_step(
            domain_sizes_before={"var1": 5},
            domain_sizes_after={"var1": 1},
        )
        assert identifier._condition_a(step) is True

    def test_below_threshold_is_not_kdp(self, identifier):
        step = make_step(
            domain_sizes_before={"var1": 5},
            domain_sizes_after={"var1": 5 - _DOMAIN_DROP_THRESHOLD + 1},
        )
        assert identifier._condition_a(step) is False

    def test_any_variable_exceeds_threshold(self, identifier):
        """Even if one variable does not drop, another exceeding threshold → KDP."""
        step = make_step(
            domain_sizes_before={"var1": 5, "var2": 3},
            domain_sizes_after={"var1": 3, "var2": 3},  # var1 drops 2, var2 unchanged
        )
        assert identifier._condition_a(step) is True

    def test_no_sizes_returns_false(self, identifier):
        step = make_step()
        assert identifier._condition_a(step) is False

    def test_missing_after_key_treated_as_no_drop(self, identifier):
        step = make_step(
            domain_sizes_before={"var1": 5},
            domain_sizes_after={},  # var1 missing from after → treated as no change
        )
        assert identifier._condition_a(step) is False


# --------------------------------------------------------------------------- #
# Condition B: step type                                                         #
# --------------------------------------------------------------------------- #

class TestConditionB:

    def test_chain_step_is_kdp(self, identifier):
        step = make_step(step_type=StepType.CHAIN)
        assert identifier._condition_b(step) is True

    def test_contradiction_step_is_kdp(self, identifier):
        step = make_step(step_type=StepType.CONTRADICTION)
        assert identifier._condition_b(step) is True

    def test_basic_step_is_not_kdp(self, identifier):
        step = make_step(step_type=StepType.BASIC)
        assert identifier._condition_b(step) is False


# --------------------------------------------------------------------------- #
# is_kdp() — combined condition                                                  #
# --------------------------------------------------------------------------- #

class TestIsKDP:

    def test_condition_a_alone_is_kdp(self, identifier):
        step = make_step(
            step_type=StepType.BASIC,
            domain_sizes_before={"x": 5},
            domain_sizes_after={"x": 1},
        )
        assert identifier._is_kdp(step) is True

    def test_condition_b_alone_is_kdp(self, identifier):
        step = make_step(step_type=StepType.CHAIN)
        assert identifier._is_kdp(step) is True

    def test_neither_condition_not_kdp(self, identifier):
        step = make_step(step_type=StepType.BASIC)
        assert identifier._is_kdp(step) is False


# --------------------------------------------------------------------------- #
# Feature extraction                                                             #
# --------------------------------------------------------------------------- #

class TestFeatureExtraction:

    def test_distinct_maps_to_all_different(self, identifier):
        step = make_step(constraint_added="Distinct(Int('x'), Int('y'))")
        types = identifier._extract_constraint_types(step)
        assert "all_different" in types

    def test_immediately_maps_to_adjacent(self, identifier):
        step = make_step(constraint_added="immediately left of")
        types = identifier._extract_constraint_types(step)
        assert "adjacent" in types

    def test_inequality_maps_to_exclusion(self, identifier):
        step = make_step(constraint_added="Int('x') != Int('y')")
        types = identifier._extract_constraint_types(step)
        assert "exclusion" in types

    def test_empty_constraint_returns_unknown(self, identifier):
        step = make_step()
        types = identifier._extract_constraint_types(step)
        assert types == ["unknown"]

    def test_feature_vector_correct_length(self, identifier):
        # h_ct + b_dom(4) + e_tau(3) + n_var + n_con
        step = make_step(constraint_added="Distinct(Int('x'))")
        types = identifier._extract_constraint_types(step)
        vec = identifier._compute_feature_vector(types, step)
        assert len(vec) == len(_ALL_TYPES) + 4 + 3 + 2

    def test_feature_vector_histogram_is_l1_normalised(self, identifier):
        step = make_step(constraint_added="Distinct(Int('x'))")
        types = identifier._extract_constraint_types(step)
        vec = identifier._compute_feature_vector(types, step)
        h_ct = vec[: len(_ALL_TYPES)]
        assert abs(sum(h_ct) - 1.0) < 1e-9
        assert all(v >= 0.0 for v in h_ct)

    def test_feature_vector_all_zeros_for_unknown(self, identifier):
        vec = identifier._compute_feature_vector(["unknown"])
        # "unknown" is not in _ALL_TYPES, so the histogram is all zeros
        assert all(v == 0.0 for v in vec[: len(_ALL_TYPES)])

    def test_feature_vector_encodes_domain_bins_and_step_type(self, identifier):
        step = make_step(
            constraint_added="Distinct(Int('x'))",
            domain_sizes_after={"a": 1, "b": 2, "c": 4, "d": 6},
        )
        types = identifier._extract_constraint_types(step)
        vec = identifier._compute_feature_vector(types, step, n_constraints=15)
        b_dom = vec[len(_ALL_TYPES): len(_ALL_TYPES) + 4]
        assert b_dom == [0.25, 0.25, 0.25, 0.25]
        n_var, n_con = vec[-2], vec[-1]
        assert n_var == pytest.approx(4 / 36.0)
        assert n_con == pytest.approx(15 / 30.0)


# --------------------------------------------------------------------------- #
# identify() — full trajectory                                                   #
# --------------------------------------------------------------------------- #

class TestIdentify:

    def test_empty_trajectory_returns_empty(self, identifier):
        traj = make_trajectory([])
        kdps = identifier.identify(traj)
        assert kdps == []

    def test_non_kdp_steps_filtered_out(self, identifier):
        steps = [
            make_step(step_type=StepType.BASIC, iteration=i)
            for i in range(5)
        ]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        assert kdps == []

    def test_kdp_steps_extracted(self, identifier):
        steps = [
            make_step(step_type=StepType.BASIC, iteration=0),
            make_step(step_type=StepType.CHAIN, iteration=1),       # KDP
            make_step(step_type=StepType.BASIC, iteration=2),
            make_step(step_type=StepType.CONTRADICTION, iteration=3),  # KDP
        ]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        assert len(kdps) == 2

    def test_kdp_ids_are_unique(self, identifier):
        steps = [make_step(step_type=StepType.CHAIN, iteration=i) for i in range(5)]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        ids = [k.kdp_id for k in kdps]
        assert len(ids) == len(set(ids))

    def test_kdp_references_correct_trajectory(self, identifier):
        steps = [make_step(step_type=StepType.CHAIN)]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        assert kdps[0].trajectory_id == traj.trajectory_id
        assert kdps[0].puzzle_id == traj.puzzle_id

    def test_kdp_type_chain(self, identifier):
        steps = [make_step(step_type=StepType.CHAIN)]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        assert kdps[0].kdp_type == "CHAIN"

    def test_kdp_type_contradiction(self, identifier):
        steps = [make_step(step_type=StepType.CONTRADICTION)]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        assert kdps[0].kdp_type == "CONTRADICTION"

    def test_kdp_type_domain_reduction(self, identifier):
        steps = [make_step(
            step_type=StepType.BASIC,
            domain_sizes_before={"x": 5},
            domain_sizes_after={"x": 1},
        )]
        traj = make_trajectory(steps)
        kdps = identifier.identify(traj)
        assert kdps[0].kdp_type == "DOMAIN_REDUCTION"

    def test_successful_repair_step_is_positive_kdp(self, identifier):
        steps = [
            make_step(step_type=StepType.BASIC, z3_result="UNSAT", iteration=0),
            make_step(
                step_type=StepType.CONTRADICTION,
                constraint_added="Int('a') == Int('b') + 1",
                z3_result="SAT",
                iteration=1,
            ).model_copy(update={"action": "repair"}),
        ]
        traj = make_solved_trajectory(steps)
        kdps = identifier.identify(traj)
        assert kdps[-1].kdp_type == "SUCCESSFUL_REPAIR"

    def test_unsolved_repair_step_is_not_successful_repair_kdp(self, identifier):
        step = make_step(
            step_type=StepType.CONTRADICTION,
            constraint_added="Int('a') == Int('b') + 1",
            z3_result="SAT",
            iteration=1,
        ).model_copy(update={"action": "repair"})
        traj = make_trajectory([step])
        kdps = identifier.identify(traj)
        assert all(k.kdp_type != "SUCCESSFUL_REPAIR" for k in kdps)
