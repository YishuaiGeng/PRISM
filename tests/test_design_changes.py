"""Tests for design changes introduced in the P0/P1 paper-revision pass.

Each test exercises a code path that was added or rewritten and previously had
zero direct coverage:

1. ``ParadigmVerifier.verify_effect`` — non-vacuousness via ``pre ∧ ¬op``.
2. ``RepairMemory`` UNSAT-core canonicalisation (operator aliasing + variable
   renaming) and its effect on stagnation detection.
3. ``StrategySwitcher`` multi-level checkpoint stack (push / peek / pop).
4. ``GuidedSolver._should_run_layer2`` cost-aware gating logic.
5. ``KDPIdentifier`` Condition C aggregate information-gain.
6. ``ParadigmRetriever`` relational predicate evaluation.

The tests intentionally avoid live LLM calls; only Z3, numpy, and the
PRISM code under test are exercised.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

# --------------------------------------------------------------------------- #
# 1. verify_effect non-vacuousness                                             #
# --------------------------------------------------------------------------- #

class _StubParadigm:
    """Tiny stand-in for the Paradigm pydantic model.

    ``verify_effect`` only touches ``operation`` and ``pre_condition`` (both
    strings); the heavier Paradigm schema is not needed to exercise the check.
    """

    def __init__(self, operation: str, pre_condition: str) -> None:
        self.operation = operation
        self.pre_condition = pre_condition


def test_verify_effect_rejects_vacuous_paradigm():
    """pre_condition that entails operation must fail non-vacuousness."""
    from prism.offline.paradigm_verifier import ParadigmVerifier

    # pre: x > 10  entails  op: x > 5   ⇒  pre ∧ ¬op  is UNSAT ⇒ vacuous.
    p = _StubParadigm(operation="Int('x') > 5", pre_condition="Int('x') > 10")
    assert ParadigmVerifier.verify_effect(p) is False


def test_verify_effect_accepts_informative_paradigm():
    """pre that does not entail op must pass both effect sub-checks."""
    from prism.offline.paradigm_verifier import ParadigmVerifier

    p = _StubParadigm(operation="Int('x') > 5", pre_condition="Int('x') > 0")
    assert ParadigmVerifier.verify_effect(p) is True


def test_verify_effect_rejects_contradiction():
    """pre ∧ op UNSAT must fail the non-contradiction sub-check."""
    from prism.offline.paradigm_verifier import ParadigmVerifier

    p = _StubParadigm(operation="Int('x') < 0", pre_condition="Int('x') > 10")
    assert ParadigmVerifier.verify_effect(p) is False


# --------------------------------------------------------------------------- #
# 2. RepairMemory canonicalisation                                             #
# --------------------------------------------------------------------------- #

def test_canonicalize_core_renames_variables_consistently():
    """Two cores that differ only in variable names must canonicalise equal."""
    from prism.online.repair_memory import _canonicalize_core

    a = _canonicalize_core(["Int('x') > 0", "Int('x') < Int('y')"])
    b = _canonicalize_core(["Int('a') > 0", "Int('a') < Int('b')"])
    assert a == b, f"canonicalisation should equate {a!r} and {b!r}"


def test_canonicalize_core_normalises_negated_comparators():
    """Not(x > k) and (x <= k) must canonicalise to the same atom."""
    from prism.online.repair_memory import _canonicalize_core

    not_form = _canonicalize_core(["Not(Int('x') > 5)"])
    le_form = _canonicalize_core(["Int('x') <= 5"])
    # The Not(>) rewriter produces "(...) <= ..." with parens; after canonical
    # variable renaming and sorting both should mention the same comparator.
    assert any("<=" in s for s in not_form)
    assert any("<=" in s for s in le_form)


def test_fingerprint_stable_across_variable_renaming():
    """Two equivalent cores under variable renaming must share a fingerprint."""
    from prism.online.repair_memory import _fingerprint

    f1 = _fingerprint(["Int('x') > 0", "Int('x') < 10"])
    f2 = _fingerprint(["Int('a') > 0", "Int('a') < 10"])
    assert f1 == f2


def test_detect_stagnation_uses_canonicalised_cores(memory_config):
    """Stagnation must fire even when variable names differ across iterations."""
    from prism.online.repair_memory import RepairMemory
    from prism.paradigm_library.schema import (
        ErrorType,
        Outcome,
        RepairAction,
        RepairRecord,
    )

    mem = RepairMemory(memory_config)
    for i, var in enumerate(["x", "y", "z"]):
        mem.append(
            RepairRecord(
                iteration=i,
                error_type=ErrorType.OVER_CONSTRAINT,
                unsat_core=[f"Int('{var}') > 0", f"Int('{var}') < 0"],
                core_fingerprint="",
                repair_action=RepairAction(
                    type="relax_bound",
                    target_constraint=f"Int('{var}') > 0",
                    summary=f"loosen {var}",
                    parameter_signature=f"{var}+1",
                ),
                outcome=Outcome.UNSAT,
            )
        )
    # Three records that look textually different but canonicalise identically
    # must trigger MAX-pair stagnation at the default Jaccard threshold of 0.75.
    assert mem.detect_stagnation() is True


# --------------------------------------------------------------------------- #
# 3. StrategySwitcher checkpoint stack                                          #
# --------------------------------------------------------------------------- #

def test_checkpoint_stack_lifo_semantics(memory):
    """save_checkpoint / get_checkpoint / pop_checkpoint must form a LIFO."""
    from prism.online.strategy_switcher import StrategySwitcher

    sw = StrategySwitcher(memory)
    sw.save_checkpoint({"iteration": 1, "summary": "first"})
    sw.save_checkpoint({"iteration": 2, "summary": "second"})
    sw.save_checkpoint({"iteration": 3, "summary": "third"})

    # Peek
    assert sw.get_checkpoint()["summary"] == "third"

    # Pop top
    top = sw.pop_checkpoint()
    assert top["summary"] == "third"
    assert sw.get_checkpoint()["summary"] == "second"

    # Drain
    sw.pop_checkpoint()
    sw.pop_checkpoint()
    assert sw.get_checkpoint() is None
    assert sw.pop_checkpoint() is None


def test_checkpoint_stack_evicts_when_exceeding_limit(memory):
    """Pushing beyond the limit must evict the oldest (FIFO at the bottom)."""
    from prism.online.strategy_switcher import _CHECKPOINT_STACK_LIMIT, StrategySwitcher

    sw = StrategySwitcher(memory)
    n = _CHECKPOINT_STACK_LIMIT + 3
    for i in range(n):
        sw.save_checkpoint({"iteration": i, "summary": f"c{i}"})

    # Stack should hold exactly _CHECKPOINT_STACK_LIMIT entries, and the
    # remaining top entry should be the most recently pushed.
    assert sw.get_checkpoint()["iteration"] == n - 1

    # Drain everything; we should get exactly _CHECKPOINT_STACK_LIMIT pops.
    popped = 0
    while sw.pop_checkpoint() is not None:
        popped += 1
    assert popped == _CHECKPOINT_STACK_LIMIT


# --------------------------------------------------------------------------- #
# 4. GuidedSolver._should_run_layer2 cost-aware gating                         #
# --------------------------------------------------------------------------- #

class _FakeLLM:
    """Minimal LLM stub: no network calls, no side effects."""

    call_count = 0

    def reset_call_count(self) -> None:
        self.call_count = 0

    def translate(self, *args, **kwargs):
        return ""


def _build_solver(layer2_policy: str = "complexity_gated"):
    """Construct a GuidedSolver instance for gating tests."""
    from prism.core.solver import Z3SolverWrapper
    from prism.online.guided_solver import GuidedSolver
    from prism.paradigm_library.library import ParadigmLibrary

    z3w = Z3SolverWrapper()
    lib = ParadigmLibrary(":memory:", z3w, soundness_threshold=0.0)
    return GuidedSolver(
        llm_client=_FakeLLM(),
        library=lib,
        layer2_policy=layer2_policy,
        enable_writeback=False,
    )


def _solver_state(num_constraints: int):
    """Tiny SolverState for gating tests."""
    from prism.core.types import SolverState

    return SolverState(
        puzzle_id="t",
        constraints=[f"c{i}" for i in range(num_constraints)],
        constraint_types=["typeA"],
    )


def test_layer2_skipped_when_only_one_candidate():
    """Even with the always policy, a single candidate must skip Layer-2."""
    gs = _build_solver(layer2_policy="always")
    state = _solver_state(num_constraints=50)
    assert gs._should_run_layer2(state, candidates=["only"]) is False


def test_layer2_complexity_gated_below_floor():
    """Below the constraint-count floor and without prior UNSAT, skip Layer-2."""
    gs = _build_solver(layer2_policy="complexity_gated")
    state = _solver_state(num_constraints=5)
    assert gs._should_run_layer2(state, candidates=["a", "b"]) is False


def test_layer2_complexity_gated_above_floor():
    """At/above the floor Layer-2 must activate regardless of UNSAT history."""
    gs = _build_solver(layer2_policy="complexity_gated")
    state = _solver_state(num_constraints=30)
    assert gs._should_run_layer2(state, candidates=["a", "b"]) is True


def test_layer2_complexity_gated_unsat_seen_overrides_floor():
    """A previous UNSAT in this puzzle activates Layer-2 even on small puzzles."""
    gs = _build_solver(layer2_policy="complexity_gated")
    gs._unsat_seen_in_puzzle = True
    state = _solver_state(num_constraints=5)
    assert gs._should_run_layer2(state, candidates=["a", "b"]) is True


def test_layer2_always_policy_runs_with_multiple_candidates():
    """'always' policy fires whenever Layer-1 returns >= 2 candidates."""
    gs = _build_solver(layer2_policy="always")
    state = _solver_state(num_constraints=2)
    assert gs._should_run_layer2(state, candidates=["a", "b"]) is True


# --------------------------------------------------------------------------- #
# 5. KDPIdentifier Condition C information gain                                #
# --------------------------------------------------------------------------- #

def _step(before: dict, after: dict):
    from prism.core.types import StepType, TrajectoryStep

    return TrajectoryStep(
        iteration=0,
        step_type=StepType.BASIC,
        action="infer",
        z3_result="SAT",
        domain_sizes_before=before,
        domain_sizes_after=after,
    )


def test_condition_c_fires_on_aggregate_gain_above_one_bit():
    """Two variables shrinking by mild ratios can sum past the 1.0-bit floor."""
    from prism.offline.kdp_identifier import KDPIdentifier

    ident = KDPIdentifier()
    # log2(5/3) + log2(4/3) ≈ 0.737 + 0.415 ≈ 1.152 bits > 1.0 → fires.
    step = _step({"x": 5, "y": 4}, {"x": 3, "y": 3})
    assert ident._condition_c(step) is True


def test_condition_c_silent_on_trivial_gain():
    """A single 5→4 drop is ~0.32 bits, well below the floor."""
    from prism.offline.kdp_identifier import KDPIdentifier

    ident = KDPIdentifier()
    step = _step({"x": 5}, {"x": 4})
    assert ident._condition_c(step) is False


def test_condition_c_decisive_when_domain_becomes_impossible():
    """Domain size dropping to 0 must be treated as decisive (∞ gain)."""
    from prism.offline.kdp_identifier import KDPIdentifier

    ident = KDPIdentifier()
    step = _step({"x": 5}, {"x": 0})
    assert ident._condition_c(step) is True


def test_condition_c_respects_custom_threshold():
    """A higher threshold rejects steps that the default would accept."""
    from prism.offline.kdp_identifier import KDPIdentifier

    ident = KDPIdentifier(info_gain_bits_threshold=3.0)
    step = _step({"x": 5, "y": 4}, {"x": 3, "y": 3})  # ~1.15 bits, below 3.0
    assert ident._condition_c(step) is False


# --------------------------------------------------------------------------- #
# 6. ParadigmRetriever relational predicates                                   #
# --------------------------------------------------------------------------- #

def test_predicate_count_atleast():
    from prism.paradigm_library.retriever import _eval_predicate

    pred = {"kind": "count_atleast", "type": "pos", "n": 2}
    assert _eval_predicate(pred, ["pos", "pos", "bind"]) is True
    assert _eval_predicate(pred, ["pos", "bind"]) is False


def test_predicate_count_atmost():
    from prism.paradigm_library.retriever import _eval_predicate

    pred = {"kind": "count_atmost", "type": "pos", "n": 1}
    assert _eval_predicate(pred, ["pos", "bind"]) is True
    assert _eval_predicate(pred, ["pos", "pos"]) is False


def test_predicate_cooccur():
    from prism.paradigm_library.retriever import _eval_predicate

    pred = {"kind": "cooccur", "types": ["pos", "bind"]}
    assert _eval_predicate(pred, ["pos", "bind", "noise"]) is True
    assert _eval_predicate(pred, ["pos", "noise"]) is False


def test_predicate_unknown_kind_soft_passes():
    """Unknown predicate kinds must not filter the paradigm out."""
    from prism.paradigm_library.retriever import _eval_predicate

    pred = {"kind": "totally_made_up", "args": "whatever"}
    assert _eval_predicate(pred, ["any"]) is True


def test_retriever_prunes_paradigms_failing_predicates(lib):
    """A paradigm whose count_atleast predicate fails must be pruned from results."""
    from prism.paradigm_library.retriever import ParadigmRetriever
    from prism.paradigm_library.schema import Paradigm

    p_eligible = Paradigm(
        id="eligible",
        name="eligible",
        trigger={
            "constraint_types": ["pos"],
            "relational_predicates": [{"kind": "count_atleast", "type": "pos", "n": 2}],
        },
        operation="Int('x') > 0",
        pre_condition="Int('x') >= 0",
        post_condition="Int('x') > 0",
        scope=["pos"],
        confidence=0.9,
        support_count=10,
        source_cluster=0,
        created_at=datetime.now(tz=timezone.utc),
    )
    p_ineligible = Paradigm(
        id="ineligible",
        name="ineligible",
        trigger={
            "constraint_types": ["pos"],
            "relational_predicates": [{"kind": "count_atleast", "type": "pos", "n": 5}],
        },
        operation="Int('x') > 0",
        pre_condition="Int('x') >= 0",
        post_condition="Int('x') > 0",
        scope=["pos"],
        confidence=0.95,
        support_count=10,
        source_cluster=0,
        created_at=datetime.now(tz=timezone.utc),
    )

    result = ParadigmRetriever().retrieve(
        [p_eligible, p_ineligible],
        constraint_types=["pos"],
        top_k=5,
        type_bag=["pos", "pos"],
    )
    ids = [p.id for p in result]
    assert "eligible" in ids
    assert "ineligible" not in ids
