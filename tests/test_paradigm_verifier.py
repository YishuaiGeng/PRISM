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

    def test_score_is_float_in_unit_interval(self, verifier, solver):
        paradigm = make_paradigm()
        score = verifier.verify_soundness(paradigm, solver)
        assert 0.0 <= score <= 1.0


# --------------------------------------------------------------------------- #
# verify_effect()                                                                #
# --------------------------------------------------------------------------- #

class TestVerifyEffect:

    def test_sat_operation_returns_true(self, verifier):
        paradigm = make_paradigm(operation="Int('x') >= 0")
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

    def test_tautology_like_operation_returns_true(self, verifier):
        """Even simple always-true expressions are SAT and pass the effect check."""
        paradigm = make_paradigm(operation="Int('x') >= 0")
        assert verifier.verify_effect(paradigm) is True


# --------------------------------------------------------------------------- #
# verify_trigger_precision()                                                     #
# --------------------------------------------------------------------------- #

class TestVerifyTriggerPrecision:

    def test_specific_trigger_type_has_high_precision(self, verifier):
        """Trigger type 'adjacent' never appears in the random pool → precision ≈ 1.0."""
        paradigm = make_paradigm(trigger_types=["adjacent_position_keyword_xyz"])
        precision = verifier.verify_trigger_precision(paradigm)
        assert precision >= 0.80

    def test_empty_trigger_types_returns_one(self, verifier):
        """No trigger types → nothing fires → perfect precision."""
        paradigm = make_paradigm(trigger_types=[])
        paradigm = paradigm.model_copy(update={"trigger": {"constraint_types": []}})
        precision = verifier.verify_trigger_precision(paradigm)
        assert precision == 1.0

    def test_precision_is_float_in_unit_interval(self, verifier):
        paradigm = make_paradigm(trigger_types=["direct_position"])
        precision = verifier.verify_trigger_precision(paradigm)
        assert 0.0 <= precision <= 1.0


# --------------------------------------------------------------------------- #
# verify() — combined gate                                                       #
# --------------------------------------------------------------------------- #

class TestVerifyGate:

    def test_good_paradigm_accepted(self, verifier, solver):
        """Compatible operation + SAT effect + specific trigger → accepted."""
        paradigm = make_paradigm(
            operation="Int('x') >= 0",
            pre_condition="Int('x') > 0",
            trigger_types=["nonexistent_type_xyz"],
        )
        score = verifier.verify(paradigm, solver)
        # Should pass all checks and return a positive soundness score
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
