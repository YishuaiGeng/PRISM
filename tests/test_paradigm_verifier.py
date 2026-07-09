"""Tests for ParadigmVerifier — three-check Z3 soundness gating."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from prism.core.solver import Z3SolverWrapper
from prism.offline.paradigm_verifier import ParadigmVerifier, _DEFAULT_SOUNDNESS_THRESHOLD
from prism.paradigm_library.schema import Paradigm


# --------------------------------------------------------------------------- #
# Factory                                                                       #
# --------------------------------------------------------------------------- #

def make_paradigm(
    *,
    operation: str = "Int('x') >= 0",
    pre_condition: str = "Int('x') > 0",
    trigger_types: list[str] | None = None,
) -> Paradigm:
    return Paradigm(
        id=str(uuid.uuid4()),
        name="test-paradigm",
        trigger={"constraint_types": trigger_types or ["direct_position"]},
        operation=operation,
        pre_condition=pre_condition,
        post_condition="domain reduced",
        scope=["direct_position"],
        confidence=0.0,
        support_count=5,
        source_cluster=0,
        created_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def verifier():
    # Use small n_samples for test speed
    return ParadigmVerifier(n_samples=10, soundness_threshold=0.80)


@pytest.fixture
def solver():
    return Z3SolverWrapper()


# --------------------------------------------------------------------------- #
# verify_soundness()                                                             #
# --------------------------------------------------------------------------- #

class TestVerifySoundness:

    def test_compatible_operation_has_high_soundness(self, verifier, solver):
        """x >= 0 is compatible with pre-condition x > 0 — should score near 1.0."""
        paradigm = make_paradigm(
            operation="Int('x') >= 0",
            pre_condition="Int('x') > 0",
        )
        score = verifier.verify_soundness(paradigm, solver)
        assert score >= 0.70

    def test_contradictory_operation_has_low_soundness(self, verifier, solver):
        """x < 0 contradicts pre-condition x > 0 — should score near 0.0."""
        paradigm = make_paradigm(
            operation="Int('x') < 0",
            pre_condition="Int('x') > 0",
        )
        score = verifier.verify_soundness(paradigm, solver)
        assert score < 0.30

    def test_empty_operation_returns_zero(self, verifier, solver):
        paradigm = make_paradigm(operation="", pre_condition="Int('x') > 0")
        assert verifier.verify_soundness(paradigm, solver) == 0.0

    def test_empty_precondition_sat_operation_has_full_soundness(self, verifier, solver):
        paradigm = make_paradigm(
            operation="And(Int('x') >= 1, Int('x') <= 3)",
            pre_condition="",
        )
        assert verifier.verify_soundness(paradigm, solver) == 1.0

    def test_empty_precondition_unsat_operation_has_zero_soundness(self, verifier, solver):
        paradigm = make_paradigm(
            operation="And(Int('x') > 5, Int('x') < 3)",
            pre_condition="",
        )
        assert verifier.verify_soundness(paradigm, solver) == 0.0

    def test_score_is_float_in_unit_interval(self, verifier, solver):
        paradigm = make_paradigm()
        score = verifier.verify_soundness(paradigm, solver)
        assert 0.0 <= score <= 1.0


class TestSchemaInvariantFilter:

    def test_domain_bounds_are_schema_invariants_not_paradigms(self, verifier):
        paradigm = make_paradigm(
            operation="And(Int('x') >= 1, Int('x') <= 3)",
            pre_condition="",
        )
        assert verifier.is_schema_invariant(paradigm) is True

    def test_non_bound_operation_is_not_schema_invariant(self, verifier):
        paradigm = make_paradigm(
            operation="Int('x') == Int('y') + 1",
            pre_condition="",
        )
        assert verifier.is_schema_invariant(paradigm) is False

    def test_schema_invariant_rejected_by_combined_gate(self, verifier, solver):
        paradigm = make_paradigm(
            operation="And(Int('x') >= 1, Int('x') <= 3)",
            pre_condition="",
            trigger_types=["nonexistent_type_xyz"],
        )
        assert verifier.verify(paradigm, solver) == 0.0


# --------------------------------------------------------------------------- #
# verify_effect()                                                                #
# --------------------------------------------------------------------------- #

class TestVerifyEffect:

    def test_sat_operation_returns_true(self, verifier):
        # P0 update: ``verify_effect`` now also enforces non-vacuousness via
        # ``pre ∧ ¬op`` SAT. The operation must be informative under its
        # pre-condition — ``Int('x') >= 0`` is entailed by ``Int('x') > 0``
        # and would now be rejected. We use a genuinely informative op.
        paradigm = make_paradigm(
            operation="Int('x') >= 5",
            pre_condition="Int('x') > 0",
        )
        assert verifier.verify_effect(paradigm) is True

    def test_unsat_operation_returns_false(self, verifier):
        paradigm = make_paradigm(operation="And(Int('x') > 5, Int('x') < 3)")
        assert verifier.verify_effect(paradigm) is False

    def test_empty_operation_returns_false(self, verifier):
        paradigm = make_paradigm(operation="")
        assert verifier.verify_effect(paradigm) is False

    def test_whitespace_only_returns_false(self, verifier):
        paradigm = make_paradigm(operation="   ")
        assert verifier.verify_effect(paradigm) is False

    def test_vacuous_operation_is_now_rejected(self, verifier):
        """P0 change: pre ∧ ¬op UNSAT → operation is entailed by pre → vacuous.

        Previously verify_effect accepted any SAT operation; the non-vacuousness
        sub-check (Section 3.3.4 in the paper) now correctly rejects paradigms
        whose operation adds no information beyond the pre-condition.
        """
        paradigm = make_paradigm(
            operation="Int('x') >= 0",        # entailed by pre below
            pre_condition="Int('x') > 0",
        )
        assert verifier.verify_effect(paradigm) is False


# --------------------------------------------------------------------------- #
# verify_trigger_precision()                                                     #
# --------------------------------------------------------------------------- #

class TestVerifyTriggerPrecision:

    def test_specific_trigger_type_has_high_precision(self, verifier):
        """Trigger type 'adjacent' never appears in the random pool → precision ≈ 1.0."""
        paradigm = make_paradigm(trigger_types=["adjacent_position_keyword_xyz"])
        precision = verifier.verify_trigger_precision(paradigm)
        assert precision >= 0.80

    def test_empty_trigger_types_returns_zero(self, verifier):
        """P0 change: a paradigm with no trigger types is treated as over-broad.

        Previously empty trigger types reported precision = 1.0 (vacuously
        "never fires"). The corrected interpretation is that empty trigger
        types fire on *everything*, so precision is 0.0 and the paradigm is
        rejected by the gate.
        """
        paradigm = make_paradigm(trigger_types=[])
        paradigm = paradigm.model_copy(update={"trigger": {"constraint_types": []}})
        precision = verifier.verify_trigger_precision(paradigm)
        assert precision == 0.0

    def test_precision_is_float_in_unit_interval(self, verifier):
        paradigm = make_paradigm(trigger_types=["direct_position"])
        precision = verifier.verify_trigger_precision(paradigm)
        assert 0.0 <= precision <= 1.0


# --------------------------------------------------------------------------- #
# verify() — combined gate                                                       #
# --------------------------------------------------------------------------- #

class TestVerifyGate:

    def test_good_paradigm_accepted(self, verifier, solver):
        """Compatible operation + SAT effect + specific trigger → accepted.

        P0 update: operation must be informative (non-vacuous) under its
        pre-condition, and — since soundness became a sampled estimate over
        random domain-bound states — it must also hold on ≥ the soundness
        threshold of states satisfying the pre-condition. ``Int('x') <= 8``
        is not entailed by ``Int('x') > 0`` (informative) yet consistent with
        every sampled bound configuration (sound); ``Int('x') >= 5`` would
        fail sampled soundness because it contradicts narrow low-range states.
        """
        paradigm = make_paradigm(
            operation="Int('x') <= 8",
            pre_condition="Int('x') > 0",
            trigger_types=["nonexistent_type_xyz"],
        )
        score = verifier.verify(paradigm, solver)
        assert score > 0.0

    def test_unsat_operation_rejected(self, verifier, solver):
        """Contradictory operation fails effect check → verify() returns 0.0."""
        paradigm = make_paradigm(
            operation="And(Int('x') > 5, Int('x') < 3)",
            pre_condition="Int('x') > 0",
        )
        score = verifier.verify(paradigm, solver)
        assert score == 0.0

    def test_low_soundness_rejected(self):
        """Verifier with high threshold rejects otherwise-valid paradigm."""
        strict_verifier = ParadigmVerifier(
            n_samples=20,
            soundness_threshold=0.99,  # near-impossible to satisfy
        )
        solver = Z3SolverWrapper()
        paradigm = make_paradigm(
            operation="Int('x') < 0",
            pre_condition="Int('x') > 0",
        )
        assert strict_verifier.verify(paradigm, solver) == 0.0
