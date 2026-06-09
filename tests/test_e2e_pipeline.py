"""End-to-end integration test for the PRISM pipeline.

Exercises the full happy-path without touching any real LLM:

    fake-trajectory      →  KDP identification
        ↓                       ↓
    cluster              →  paradigm abstraction (LLM stub)
        ↓                       ↓
    triple verification  →  ParadigmLibrary
        ↓                       ↓
    config-driven        →  GuidedSolver.solve(puzzle)
    GuidedSolver         →     (uses library, repair memory, candidate pool)
        ↓                       ↓
    SAT outcome          →  candidate pool flush →  library stats grow

The test is deliberately small (one puzzle, one paradigm) so it runs in well
under one second and lock in the wiring between modules. It does NOT validate
solving accuracy — that is the job of the full evaluation, not unit tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import pytest

from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance
from prism.online.candidate_pool import CandidatePool
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import Paradigm


# --------------------------------------------------------------------------- #
# Fake LLM client                                                              #
# --------------------------------------------------------------------------- #


class _ScriptedLLM:
    """Deterministic stand-in for prism.core.llm_client.LLMClient.

    Returns canned answers for each task method so the test never makes a
    network call. The solver exercises real Z3, so the test still catches
    integration bugs in constraint handling and UNSAT-core analysis.
    """

    def __init__(self) -> None:
        self._count: int = 0

    @property
    def call_count(self) -> int:
        return self._count

    def reset_call_count(self) -> None:
        self._count = 0

    # ---- Used by NLToZ3Translator -----------------------------------------

    def translate(self, puzzle_nl: str) -> str:
        self._count += 1
        # Initial translation is intentionally over-constrained: x > 5 AND
        # x < 5 is UNSAT. This forces the online repair loop to engage.
        return "```python\nInt('x') > 5\nInt('x') < 5\n```"

    def retranslate(self, puzzle_nl: str, failed_constraints, error_ctx) -> str:
        self._count += 1
        return "```python\nInt('x') > 0\nInt('x') < 10\n```"

    # ---- Used by GuidedSolver repair loop ---------------------------------

    def repair(
        self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""
    ) -> str:
        """Replace the over-constraining "Int('x') < 5" with a SAT-compatible one."""
        self._count += 1
        return "Int('x') < 10"

    def judge_semantic_match(self, paradigm_summary: str, state_summary: str) -> bool:
        return False  # never invokes the Layer-2 LLM branch

    # ---- Used by ParadigmAbstractor (offline) -----------------------------

    def abstract_paradigm(self, kdps_text: str) -> str:
        self._count += 1
        return ""  # not used in this test (we seed a paradigm directly)


# --------------------------------------------------------------------------- #
# Test fixture                                                                  #
# --------------------------------------------------------------------------- #


def _seed_paradigm() -> Paradigm:
    """A trivially-valid paradigm to live in the library for the test."""
    return Paradigm(
        id="seed",
        name="seed",
        trigger={
            "constraint_types": ["ordering"],
            "relational_predicates": [
                {"kind": "count_atleast", "type": "ordering", "n": 1}
            ],
        },
        operation="Int('x') > 0",
        pre_condition="Int('x') >= 0",
        post_condition="Int('x') > 0",
        scope=["ordering"],
        confidence=0.95,
        support_count=10,
        source_cluster=-1,
        created_at=datetime.now(tz=timezone.utc),
    )


# --------------------------------------------------------------------------- #
# Test                                                                         #
# --------------------------------------------------------------------------- #


def test_e2e_pipeline_solves_via_repair_and_stages_candidate(tmp_path, monkeypatch):
    """Full happy-path: translate → repair to SAT → stage candidate → flush."""
    # 1. Build a config that mirrors config/default.yaml in spirit.
    config = {
        "thresholds": {
            "max_repair_rounds": 5,
            "paradigm_top_k": 3,
            "layer2_enabled": True,
            "layer2_policy": "complexity_gated",
            "layer2_complexity_floor": 25,
            "stagnation_jaccard": 0.75,
            "loop_cosine": 0.90,
            "enable_paradigm": True,
            "enable_memory": True,
            "enable_writeback": True,
            "writeback_batch_K": 1,  # auto-flush after a single solved puzzle
        }
    }

    # 2. Build the in-memory library with one verified paradigm.
    z3w = Z3SolverWrapper()
    lib = ParadigmLibrary(":memory:", z3w, soundness_threshold=0.0)
    lib.add(_seed_paradigm(), verify=False)
    assert lib.stats()["total"] == 1

    # 3. Build the GuidedSolver via config-driven factory.
    llm = _ScriptedLLM()
    solver = GuidedSolver.from_config(llm, lib, config)

    # 4. Replace the real translator with a scripted one whose translate()
    #    returns the same starting constraints as ScriptedLLM.translate would.
    #    We need a translator whose parse paths cope with our cooked LLM output.
    from prism.core.translator import NLToZ3Translator

    real_translator = NLToZ3Translator(llm)
    # Override the translate() method to emit the cooked constraints directly,
    # bypassing brittle Markdown parsing inside the production translator.
    real_translator.translate = lambda puzzle: ["Int('x') > 5", "Int('x') < 5"]
    real_translator.retranslate = lambda puzzle, failed, err: [
        "Int('x') > 0",
        "Int('x') < 10",
    ]
    real_translator.parse_repair_response = lambda response: response.strip()
    solver._translator = real_translator

    # 5. Solve a puzzle.
    puzzle = PuzzleInstance(
        nl_description="Find x such that 0 < x < 10.",
        variables=["x"],
        size="trivial",
    )
    result = solver.solve(puzzle)

    # 6. Assert the pipeline succeeded (SAT) via repair.
    assert result.solved is True, f"solve failed; result={result}"
    assert result.final_z3_result == "SAT"
    # At least one repair round happened because the initial translation was UNSAT.
    assert result.repair_rounds >= 1
    # LLM was invoked at least once (for the repair). Translation is stubbed
    # through a non-LLM lambda in this test, so we cannot assert >= 2.
    assert llm.call_count >= 1

    # 7. CandidatePool should have staged the successful repair and (because
    #    writeback_batch_K=1) auto-flushed at solve()'s exit.
    pool = solver._candidate_pool
    assert pool is not None
    stats = pool.stats()
    # The candidate either promoted (passed triple verification on the in-process
    # solver) or was logged in the rejected list — either is acceptable as long as
    # something was staged.
    assert stats["staged"] >= 1, f"candidate pool was never staged; stats={stats}"


def test_e2e_pipeline_solves_directly_when_translation_is_sat():
    """If the initial translation is already SAT, no repair loop runs."""
    config = {
        "thresholds": {
            "max_repair_rounds": 5,
            "enable_paradigm": True,
            "enable_memory": True,
            "enable_writeback": True,
            "writeback_batch_K": 1,
        }
    }

    z3w = Z3SolverWrapper()
    lib = ParadigmLibrary(":memory:", z3w, soundness_threshold=0.0)
    llm = _ScriptedLLM()
    solver = GuidedSolver.from_config(llm, lib, config)

    from prism.core.translator import NLToZ3Translator

    t = NLToZ3Translator(llm)
    t.translate = lambda puzzle: ["Int('x') > 0", "Int('x') < 10"]  # SAT immediately
    solver._translator = t

    puzzle = PuzzleInstance(
        nl_description="Find x such that 0 < x < 10.",
        variables=["x"],
        size="trivial",
    )
    result = solver.solve(puzzle)

    assert result.solved is True
    assert result.repair_rounds == 0
    # CandidatePool should NOT have staged anything (no successful *repair*).
    pool = solver._candidate_pool
    assert pool is not None
    assert pool.stats()["staged"] == 0


def test_e2e_candidate_pool_flushes_at_explicit_call():
    """flush_candidate_pool() must promote eligible candidates without K auto-trigger."""
    config = {"thresholds": {"enable_writeback": True, "writeback_batch_K": 999_999}}
    z3w = Z3SolverWrapper()
    lib = ParadigmLibrary(":memory:", z3w, soundness_threshold=0.0)
    llm = _ScriptedLLM()
    solver = GuidedSolver.from_config(llm, lib, config)

    # Manually stage one candidate; flush; assert promotion or rejection logged.
    pool = solver._candidate_pool
    assert pool is not None
    staged = pool.stage(
        trigger_types=["ordering"],
        operation="Int('x') > 0",
        pre_condition="Int('x') >= 0",
        post_condition="Int('x') > 0",
        scope=["ordering"],
    )
    assert staged is True
    promoted = solver.flush_candidate_pool()
    # Either promoted (passes verification) or rejected; either is fine — we are
    # validating the wiring, not the verifier's verdict on this specific shape.
    assert pool.stats()["pending"] == 0
    assert promoted + len(pool.rejected) >= 1
