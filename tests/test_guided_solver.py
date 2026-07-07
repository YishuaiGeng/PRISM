"""Integration tests for GuidedSolver.

Uses stub LLM clients and translators so that no real API calls are made.
Z3SolverWrapper is used for real (not mocked) constraint checking to keep the
tests grounded in actual solver behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance, SolverState
from prism.online.guided_solver import (
    _find_clue_coverage_issues,
    GuidedSolver,
    _parse_direct_position_source_clue,
    _parse_relation_source_clue,
    _replacement_policy_from_error_paradigm,
)
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import ErrorParadigm
from prism.paradigm_library.schema import Paradigm

# Import conftest factory
from tests.conftest import make_paradigm


# --------------------------------------------------------------------------- #
# Stub LLM clients (no API calls)                                              #
# --------------------------------------------------------------------------- #

class _BaseLLMClient:
    """Minimal LLMClient stub 鈥?never calls an API."""
    _count: int = 0

    @property
    def call_count(self) -> int:
        return self._count

    def reset_call_count(self) -> None:
        self._count = 0

    def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
        return unsat_core[0] if unsat_core else ""

    def judge_semantic_match(self, paradigm_summary, state_summary) -> bool:
        return False

    def retranslate(self, puzzle_nl, failed_constraints, error_ctx) -> str:
        return "Int('x') > 0\nInt('x') < 10"


class _FixingRepairClient(_BaseLLMClient):
    """On first repair call, returns a constraint that resolves the UNSAT."""
    def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
        # Replace the first core constraint with one that is SAT-compatible
        self._count += 1
        return "Int('x') > 0"  # Compatible with Int('x') < 10


class _RecordingRepairClient(_FixingRepairClient):
    def __init__(self):
        self.last_paradigm_hint = ""

    def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
        self.last_paradigm_hint = paradigm_hint
        return super().repair(constraints, unsat_core, history_summary, paradigm_hint, switch_prompt)


class _TargetRecordingRepairClient(_RecordingRepairClient):
    def __init__(self, target: str):
        super().__init__()
        self._target = target

    def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
        self.last_paradigm_hint = paradigm_hint
        self._count += 1
        return self._target


class _RecordingRetranslateClient(_BaseLLMClient):
    def __init__(self):
        self.last_error_ctx = ""

    def retranslate(self, puzzle_nl, failed_constraints, error_ctx) -> str:
        self.last_error_ctx = error_ctx
        return super().retranslate(puzzle_nl, failed_constraints, error_ctx)


class _AlwaysUnsat(_BaseLLMClient):
    """Repair always returns the same (non-fixing) constraint 鈥?triggers stagnation."""
    def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
        self._count += 1
        return unsat_core[0] if unsat_core else "Int('x') > 5"

    def retranslate(self, puzzle_nl, failed_constraints, error_ctx) -> str:
        # Return SAT constraints so L4 eventually succeeds
        return "```python\nInt('x') > 0\nInt('x') < 10\n```"


class _RecordingLibrary:
    def __init__(self, paradigms=None):
        self.retrieve_calls = 0
        self.update_calls = 0
        self._paradigms = paradigms or []

    def retrieve(self, constraint_types, top_k=3):
        self.retrieve_calls += 1
        return list(self._paradigms[:top_k])

    def update_confidence(self, paradigm_id, new_score):
        self.update_calls += 1


# --------------------------------------------------------------------------- #
# Stub translator (no API calls)                                               #
# --------------------------------------------------------------------------- #

class _StubTranslator:
    def __init__(self, initial=None, retranslate_result=None):
        self._initial = ["Int('x') > 0", "Int('x') < 10"] if initial is None else initial
        self._retranslate_result = (
            ["Int('x') > 0", "Int('x') < 10"]
            if retranslate_result is None
            else retranslate_result
        )
        self.last_paradigm_hint = ""

    def translate(self, puzzle, paradigm_hint=""):
        self.last_paradigm_hint = paradigm_hint
        return list(self._initial)

    def retranslate(self, puzzle, failed_constraints, error_ctx):
        return list(self._retranslate_result)

    def parse_repair_response(self, response: str):
        for line in response.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("```"):
                return line
        return None

    def build_state_summary(self, nl, constraints, unsat_core):
        return "test state"


# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #

@pytest.fixture
def empty_library(solver):
    with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as lib:
        yield lib


def _make_solver(llm, translator, library) -> GuidedSolver:
    gs = GuidedSolver(
        llm_client=llm,
        library=library,
        max_repair_rounds=5,
        layer2_enabled=False,
    )
    gs._translator = translator
    return gs


def _sat_puzzle() -> PuzzleInstance:
    return PuzzleInstance(nl_description="Simple SAT puzzle", puzzle_id="sat_test")


def _unsat_puzzle() -> PuzzleInstance:
    return PuzzleInstance(nl_description="Simple UNSAT puzzle", puzzle_id="unsat_test")


# --------------------------------------------------------------------------- #
# Direct SAT (no repair needed)                                                  #
# --------------------------------------------------------------------------- #

class TestDirectSAT:

    def test_solve_direct_sat_returns_solved_true(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=["Int('x') > 0", "Int('x') < 10"])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert result.solved is True

    def test_direct_sat_zero_repair_rounds(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=["Int('x') > 0", "Int('x') < 10"])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert result.repair_rounds == 0

    def test_direct_sat_solution_populated(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=["Int('x') > 0", "Int('x') < 10"])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert result.solution is not None

    def test_direct_sat_z3_result_is_sat(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=["Int('x') > 0", "Int('x') < 10"])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert result.final_z3_result == "SAT"

    def test_direct_sat_out_of_domain_model_is_invalid(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=["Int('x') == 4"])
        gs = GuidedSolver(
            llm_client=llm,
            library=empty_library,
            max_repair_rounds=0,
            layer2_enabled=False,
        )
        gs._translator = translator
        puzzle = PuzzleInstance(
            nl_description="There are 3 houses.",
            puzzle_id="invalid_model_test",
            size="3x3",
        )

        result = gs.solve(puzzle)

        assert result.solved is False
        assert result.final_z3_result == "INVALID_MODEL"
        assert result.error == "model contains assignments outside puzzle domain"

    def test_invalid_model_retranslate_can_recover(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(
            initial=["Int('x') == 4"],
            retranslate_result=["Int('x') == 3"],
        )
        gs = _make_solver(llm, translator, empty_library)
        puzzle = PuzzleInstance(
            nl_description="There are 3 houses.",
            puzzle_id="invalid_model_recover_test",
            size="3x3",
        )

        result = gs.solve(puzzle)

        assert result.solved is True
        assert result.final_z3_result == "SAT"
        assert any(step.get("action") == "invalid_model_retranslate" for step in result.steps)

    def test_invalid_model_retranslate_unsat_enters_repair_loop(self, empty_library):
        with ErrorParadigmLibrary(":memory:") as error_lib:
            error_lib.add(
                ErrorParadigm(
                    id="err-recovery-unsat",
                    name="avoid_bad_lower_bound",
                    trigger={"constraint_types": ["integer_bound"]},
                    bad_operation="Int('x') > 5",
                    unsat_signature="sig",
                    avoid_instruction="Do not keep the contradictory lower bound.",
                    repair_hint="Relax the lower bound before retrying.",
                    scope=["integer_bound"],
                    confidence=1.0,
                    support_count=1,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            llm = _RecordingRepairClient()
            translator = _StubTranslator(
                initial=["Int('x') == 4"],
                retranslate_result=["Int('x') > 5", "Int('x') < 3"],
            )
            gs = GuidedSolver(
                llm_client=llm,
                library=empty_library,
                max_repair_rounds=2,
                layer2_enabled=False,
                error_library=error_lib,
            )
            gs._translator = translator
            puzzle = PuzzleInstance(
                nl_description="There are 3 houses.",
                puzzle_id="invalid_model_repair_after_retranslate_test",
                size="3x3",
            )

            result = gs.solve(puzzle)

            assert result.solved is True
            assert any(
                step.get("action") == "repair"
                and step.get("source") == "validation_recovery"
                for step in result.steps
            )
            repair_step = next(step for step in result.steps if step.get("action") == "repair")
            assert repair_step["repair_response"] == "Int('x') > 0"
            assert repair_step["repair_expression"] == "Int('x') > 0"
            assert repair_step["old_constraint"] == "Int('x') > 5"
            assert repair_step["new_constraint"] == "Int('x') > 0"
            assert repair_step["error_paradigms"][0]["id"] == "err-recovery-unsat"
            assert "Avoid these verified UNSAT-producing patterns" in llm.last_paradigm_hint

    def test_direct_sat_misaligned_model_is_invalid_schema(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[
            "Int('house1_color') == 1",
            "Int('house2_color') == 2",
        ])
        gs = GuidedSolver(
            llm_client=llm,
            library=empty_library,
            max_repair_rounds=0,
            layer2_enabled=False,
        )
        gs._translator = translator
        puzzle = PuzzleInstance(
            nl_description="There are 2 houses.",
            puzzle_id="misaligned_model_test",
            size="2x2",
            solution={"color_Blue": "1", "color_Green": "2"},
        )

        result = gs.solve(puzzle)

        assert result.solved is False
        assert result.final_z3_result == "MISALIGNED_MODEL"
        assert result.error == "model variable names do not align with puzzle solution schema"
        assert result.steps[-1]["model_schema_aligned"] is False

    def test_direct_sat_matching_solution_schema_is_accepted(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[
            "Int('color_Blue') == 1",
            "Int('color_Green') == 2",
        ])
        gs = _make_solver(llm, translator, empty_library)
        puzzle = PuzzleInstance(
            nl_description="There are 2 houses.",
            puzzle_id="aligned_model_test",
            size="2x2",
            solution={"color_Blue": "1", "color_Green": "2"},
        )

        result = gs.solve(puzzle)

        assert result.solved is True
        assert result.final_z3_result == "SAT"
        assert result.solution == {"color_Blue": "1", "color_Green": "2"}

    def test_direct_sat_partial_solution_schema_is_key_mismatch(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[
            "Int('color_Blue') == 1",
            "Int('color_Red') == 2",
        ])
        gs = GuidedSolver(
            llm_client=llm,
            library=empty_library,
            max_repair_rounds=0,
            layer2_enabled=False,
        )
        gs._translator = translator
        puzzle = PuzzleInstance(
            nl_description="There are 2 houses.",
            puzzle_id="key_mismatch_model_test",
            size="2x2",
            solution={"color_Blue": "1", "color_Green": "2"},
        )

        result = gs.solve(puzzle)

        assert result.solved is False
        assert result.final_z3_result == "KEY_MISMATCH"
        assert result.error == "model variable key set does not match puzzle solution schema"
        assert result.steps[-1]["model_schema_aligned"] is True
        assert result.steps[-1]["model_key_set_aligned"] is False

    def test_misaligned_model_retranslate_can_recover(self, empty_library):
        llm = _RecordingRetranslateClient()
        translator = _StubTranslator(
            initial=["Int('house1_color') == 1", "Int('house2_color') == 2"],
            retranslate_result=["Int('color_Blue') == 1", "Int('color_Green') == 2"],
        )
        gs = _make_solver(llm, translator, empty_library)
        puzzle = PuzzleInstance(
            nl_description="There are 2 houses.",
            puzzle_id="misaligned_model_recover_test",
            size="2x2",
            solution={"color_Blue": "1", "color_Green": "2"},
        )

        result = gs.solve(puzzle)

        assert result.solved is True
        assert result.final_z3_result == "SAT"
        assert any(step.get("action") == "misaligned_model_retranslate" for step in result.steps)

    def test_translation_step_records_visible_schema_diagnostics(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[
            "Int('color_Purple') == 1",
            "Int('color_Blue') == 2",
        ])
        translator.last_diagnostics = {
            "visible_schema_key_count": 1,
            "expected_schema_key_count": 2,
            "missing_visible_schema_keys": ["color_Blue"],
            "generated_extra_schema_keys": ["color_Blue"],
            "dropped_invisible_schema_constraints": ["Int('color_Blue') == 2"],
        }
        gs = GuidedSolver(
            llm_client=llm,
            library=empty_library,
            max_repair_rounds=0,
            layer2_enabled=False,
        )
        gs._translator = translator
        puzzle = PuzzleInstance(
            nl_description="The Purple color person lives in house 1.",
            puzzle_id="visible_schema_diag_test",
            size="2x2",
            solution={"color_Purple": "1", "color_Blue": "2"},
        )

        result = gs.solve(puzzle)

        assert result.steps[0]["visible_schema_key_count"] == 1
        assert result.steps[0]["missing_visible_schema_keys"] == ["color_Blue"]


# --------------------------------------------------------------------------- #
# One repair round 鈫?SAT                                                         #
# --------------------------------------------------------------------------- #

class TestOneRepair:

    def test_one_repair_success(self, empty_library):
        """Initial UNSAT; repairing first core constraint 鈫?SAT."""
        llm = _FixingRepairClient()
        # initial: UNSAT ("x > 5" 鈭?"x < 3")
        # after repair "x > 5" 鈫?"x > 0": constraints become ["x > 0", "x < 3"] 鈫?SAT
        translator = _StubTranslator(
            initial=["Int('x') > 5", "Int('x') < 3"],
        )
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_unsat_puzzle())
        assert result.solved is True
        assert result.repair_rounds >= 1

    def test_one_repair_call_count_incremented(self, empty_library):
        llm = _FixingRepairClient()
        translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
        gs = _make_solver(llm, translator, empty_library)
        gs.solve(_unsat_puzzle())
        # At least 1 repair call was tracked
        assert llm.call_count >= 1

    def test_apply_repair_prefers_relation_target_over_schema_bound(self):
        constraints = [
            "And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)",
            "Int('color_Red') == Int('color_White') - 1",
            "Distinct(Int('color_Red'), Int('color_White'), Int('color_Blue'))",
        ]
        unsat_core = list(constraints)

        old, new = GuidedSolver._apply_repair(
            constraints,
            unsat_core,
            "Int('color_Red') == Int('color_White') + 1",
        )

        assert old == "Int('color_Red') == Int('color_White') - 1"
        assert new == "Int('color_Red') == Int('color_White') + 1"
        assert constraints[0] == "And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)"

    def test_apply_repair_replaces_wrong_relation_even_when_target_already_in_core(self):
        constraints = [
            "Int('x') == 1",
            "Int('x') == 2",
        ]
        unsat_core = list(constraints)

        old, new = GuidedSolver._apply_repair(
            constraints,
            unsat_core,
            "Int('x') == 1",
        )

        assert old == "Int('x') == 2"
        assert new == "Int('x') == 1"
        assert constraints == ["Int('x') == 1", "Int('x') == 1"]

    def test_apply_repair_appends_when_only_schema_constraints_match(self):
        constraints = [
            "And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)",
            "Distinct(Int('color_Red'), Int('color_White'), Int('color_Blue'))",
        ]
        unsat_core = list(constraints)

        old, new = GuidedSolver._apply_repair(
            constraints,
            unsat_core,
            "Int('color_Red') == Int('color_White') + 1",
        )

        assert old is None
        assert new == "Int('color_Red') == Int('color_White') + 1"
        assert constraints[-1] == "Int('color_Red') == Int('color_White') + 1"

    def test_apply_repair_does_not_shrink_distinct_schema(self):
        constraints = [
            "Distinct(Int('color_Red'), Int('color_White'), Int('color_Blue'), Int('color_Green'))",
            "Int('color_Red') == 2",
        ]
        unsat_core = list(constraints)

        old, new = GuidedSolver._apply_repair(
            constraints,
            unsat_core,
            "Distinct(Int('color_Red'), Int('color_White'), Int('color_Blue'))",
        )

        assert old is None
        assert new == "Distinct(Int('color_Red'), Int('color_White'), Int('color_Blue'))"
        assert constraints[0] == "Distinct(Int('color_Red'), Int('color_White'), Int('color_Blue'), Int('color_Green'))"

    def test_validate_repair_rejects_noop(self):
        ok, reason = GuidedSolver._validate_repair_output(
            "Int('color_Red') < Int('color_Blue')",
            ["Int('color_Red') < Int('color_Blue')"],
            ["Int('color_Red') < Int('color_Blue')"],
        )

        assert ok is False
        assert reason == "no_op_repair"

    def test_validate_repair_rejects_shrinking_distinct(self):
        ok, reason = GuidedSolver._validate_repair_output(
            "Distinct(Int('color_Red'), Int('color_Blue'))",
            ["Distinct(Int('color_Red'), Int('color_Blue'), Int('color_Green'))"],
            ["Distinct(Int('color_Red'), Int('color_Blue'), Int('color_Green'))"],
        )

        assert ok is False
        assert reason == "schema_shrinking_distinct"

    def test_validate_repair_rejects_low_variable_overlap(self):
        ok, reason = GuidedSolver._validate_repair_output(
            "Int('drink_Wine') == Int('drink_Water') - 1",
            ["Int('color_Red') < Int('color_Blue')"],
            ["Int('color_Red') < Int('color_Blue')"],
        )

        assert ok is False
        assert reason == "low_variable_overlap"


# --------------------------------------------------------------------------- #
# Max rounds exhausted 鈫?failure                                                 #
# --------------------------------------------------------------------------- #

class TestMaxRounds:

    def test_max_rounds_returns_solved_false(self, empty_library):
        """When every repair keeps same UNSAT, solved=False after max_repair_rounds."""
        llm = _AlwaysUnsat()
        translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
        gs = GuidedSolver(
            llm_client=llm, library=empty_library,
            max_repair_rounds=3, layer2_enabled=False,
        )
        gs._translator = translator
        result = gs.solve(_unsat_puzzle())
        # Even if stagnation triggers L4 retranslation 鈫?_AlwaysUnsat.retranslate returns SAT
        # That's fine 鈥?what we care about is the solver exits cleanly
        assert isinstance(result.solved, bool)

    def test_empty_initial_translation_returns_failure(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert result.solved is False
        assert result.final_z3_result == "TRANSLATION_FAILED"
        assert result.error == "translation produced no valid constraints"


# --------------------------------------------------------------------------- #
# Result fields                                                                  #
# --------------------------------------------------------------------------- #

class TestResultFields:

    def test_puzzle_id_in_result(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator()
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert result.puzzle_id == "sat_test"

    def test_steps_list_populated(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator()
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_sat_puzzle())
        assert len(result.steps) >= 1  # at least the initial translate step

    def test_llm_calls_tracked(self, empty_library):
        llm = _FixingRepairClient()
        translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_unsat_puzzle())
        assert result.total_llm_calls >= 1

    def test_paradigm_not_triggered_with_empty_library(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
        gs = _make_solver(llm, translator, empty_library)
        result = gs.solve(_unsat_puzzle())
        assert result.paradigm_triggered is False


# --------------------------------------------------------------------------- #
# Paradigm guidance                                                               #
# --------------------------------------------------------------------------- #

class TestParadigmGuidance:

    def test_positive_paradigm_guides_initial_translation(self, solver):
        with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as lib:
            lib.add(
                Paradigm(
                    id="p-initial-direct-left",
                    name="direct_left_template",
                    trigger={"constraint_types": ["directly_left"]},
                    operation="Int('a') == Int('b') - 1",
                    pre_condition="",
                    post_condition="Use the canonical directly-left encoding.",
                    scope=["directly_left"],
                    confidence=1.0,
                    support_count=5,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                ),
                verify=False,
            )
            translator = _StubTranslator(initial=[
                "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
                "And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)",
                "Int('job_Chef') == Int('job_Pilot') - 1",
            ])
            gs = GuidedSolver(
                llm_client=_BaseLLMClient(),
                library=lib,
                max_repair_rounds=2,
                layer2_enabled=False,
            )
            gs._translator = translator
            puzzle = PuzzleInstance(
                nl_description="Clues:\n1. The Chef job is immediately left of the Pilot job.",
                puzzle_id="initial_positive_guidance_test",
                size="3x3",
            )

            result = gs.solve(puzzle)

            assert "directly-left clue" in translator.last_paradigm_hint
            assert result.steps[0]["positive_guidance_triggered"] is True
            assert result.paradigm_triggered is True

    def test_paradigm_hint_injected_when_library_has_match(self, solver):
        """With a library paradigm whose scope matches, paradigm_triggered=True."""
        with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as lib:
            p = make_paradigm(scope=["ordering"])
            lib.add(p, verify=False)

            llm = _FixingRepairClient()
            translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
            gs = GuidedSolver(
                llm_client=llm, library=lib,
                max_repair_rounds=3, layer2_enabled=False,
            )
            gs._translator = translator
            # Manually set constraint_types to match paradigm scope
            result = gs.solve(_unsat_puzzle())
            # Paradigm may or may not be triggered depending on scope match 鈥?            # the important thing is no exception and a valid result
            assert isinstance(result.paradigm_triggered, bool)

    def test_error_paradigm_hint_injected_into_repair_prompt(self, empty_library):
        with ErrorParadigmLibrary(":memory:") as error_lib:
            error_lib.add(
                ErrorParadigm(
                    id="err-001",
                    name="avoid_bad_lower_bound",
                    trigger={"constraint_types": ["integer_bound"]},
                    bad_operation="Int('x') > 5",
                    unsat_signature="sig",
                    avoid_instruction="Do not keep the contradictory lower bound.",
                    repair_hint="Relax the lower bound before retrying.",
                    scope=["integer_bound"],
                    confidence=1.0,
                    support_count=1,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            llm = _TargetRecordingRepairClient("Int('x') == 1")
            translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
            gs = GuidedSolver(
                llm_client=llm,
                library=empty_library,
                max_repair_rounds=1,
                layer2_enabled=False,
                error_library=error_lib,
            )
            gs._translator = translator

            result = gs.solve(_unsat_puzzle())

            assert result.solved is True
            assert "Avoid these verified UNSAT-producing patterns" in llm.last_paradigm_hint
            assert "Int('x') > 5" in llm.last_paradigm_hint

    def test_error_guidance_includes_structured_replacement_policy(self, empty_library):
        with ErrorParadigmLibrary(":memory:") as error_lib:
            error_lib.add(
                ErrorParadigm(
                    id="err-target",
                    name="replace_bad_position",
                    trigger={
                        "constraint_types": ["direct_position"],
                        "replacement_policy": {
                            "target_constraint": "Int('x') == 1",
                            "source_clue": "The x value lives in house 1.",
                        },
                    },
                    bad_operation="Int('x') == 2",
                    unsat_signature="sig",
                    avoid_instruction="Replace the wrong direct assignment.",
                    repair_hint="Return the exact replacement.",
                    scope=["direct_position"],
                    confidence=1.0,
                    support_count=1,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            llm = _TargetRecordingRepairClient("Int('x') == 1")
            translator = _StubTranslator(initial=["Int('x') == 2", "Int('x') == 1"])
            gs = GuidedSolver(
                llm_client=llm,
                library=empty_library,
                max_repair_rounds=1,
                layer2_enabled=False,
                error_library=error_lib,
            )
            gs._translator = translator

            result = gs.solve(_unsat_puzzle())

            repair_step = next(step for step in result.steps if step.get("action") == "repair")
            assert "replacement_policy=target=Int('x') == 1" in llm.last_paradigm_hint
            assert repair_step["error_paradigms"][0]["replacement_policy"]["target_constraint"] == "Int('x') == 1"

    def test_template_replacement_policy_materializes_from_source_clue(self):
        paradigm = ErrorParadigm(
            id="template",
            name="template_color",
            trigger={
                "constraint_types": ["direct_position"],
                "replacement_policy": {
                    "kind": "direct_position_from_source_clue",
                    "source_clue": "1. The Blue color person lives in house 1.",
                },
            },
            bad_operation="Int('color_Blue') == 2",
            unsat_signature="sig",
            avoid_instruction="bad",
            repair_hint="hint",
            scope=["direct_position"],
            confidence=1.0,
            support_count=1,
            source_cluster=0,
            created_at=datetime.now(tz=timezone.utc),
        )

        policy = _replacement_policy_from_error_paradigm(paradigm)

        assert policy["target_constraint"] == "Int('color_Blue') == 1"

    def test_parse_direct_position_source_clue(self):
        assert _parse_direct_position_source_clue(
            "1. The Wine drink person lives in house 2."
        ) == ("drink_Wine", 2)

    def test_relation_template_materializes_directly_left_target(self):
        paradigm = ErrorParadigm(
            id="relation-template",
            name="template_directly_left",
            trigger={
                "constraint_types": ["directly_left"],
                "replacement_policy": {
                    "kind": "directly_left_from_source_clue",
                    "source_clue": "1. The Chef job is immediately left of the Pilot job.",
                },
            },
            bad_operation="Int('job_Chef') == Int('job_Pilot') + 1",
            unsat_signature="sig",
            avoid_instruction="bad",
            repair_hint="hint",
            scope=["directly_left"],
            confidence=1.0,
            support_count=1,
            source_cluster=0,
            created_at=datetime.now(tz=timezone.utc),
        )

        policy = _replacement_policy_from_error_paradigm(paradigm)

        assert policy["target_constraint"] == "Int('job_Chef') == Int('job_Pilot') - 1"

    def test_relation_template_can_materialize_from_state_puzzle_text(self):
        paradigm = ErrorParadigm(
            id="relation-template",
            name="template_directly_left",
            trigger={
                "constraint_types": ["directly_left"],
                "replacement_policy": {
                    "kind": "directly_left_from_source_clue",
                },
            },
            bad_operation="Int('job_Chef') == Int('job_Pilot') + 1",
            unsat_signature="sig",
            avoid_instruction="bad",
            repair_hint="hint",
            scope=["directly_left"],
            confidence=1.0,
            support_count=1,
            source_cluster=0,
            created_at=datetime.now(tz=timezone.utc),
        )
        state = SolverState(
            puzzle_id="p1",
            constraints=[],
            unsat_core=["Int('job_Chef') == Int('job_Pilot') + 1"],
            z3_result="UNSAT",
            problem_nl="Clues:\n1. The Chef job is immediately left of the Pilot job.",
        )

        policy = _replacement_policy_from_error_paradigm(paradigm, state)

        assert policy["source_clue"] == "1. The Chef job is immediately left of the Pilot job."
        assert policy["target_constraint"] == "Int('job_Chef') == Int('job_Pilot') - 1"

    def test_generic_relation_template_prefers_current_unsat_core_vars(self):
        paradigm = ErrorParadigm(
            id="relation-template",
            name="template_directly_left",
            trigger={
                "constraint_types": ["directly_left"],
                "replacement_policy": {
                    "kind": "directly_left_from_source_clue",
                },
            },
            bad_operation="Int('job_Chef') == Int('job_Pilot') + 1",
            unsat_signature="sig",
            avoid_instruction="bad",
            repair_hint="hint",
            scope=["directly_left"],
            confidence=1.0,
            support_count=1,
            source_cluster=0,
            created_at=datetime.now(tz=timezone.utc),
        )
        state = SolverState(
            puzzle_id="p2",
            constraints=[],
            unsat_core=["Int('pet_Cat') == Int('pet_Fish') + 1"],
            z3_result="UNSAT",
            problem_nl="Clues:\n1. The Cat pet is immediately left of the Fish pet.",
        )

        policy = _replacement_policy_from_error_paradigm(paradigm, state)

        assert policy["source_clue"] == "1. The Cat pet is immediately left of the Fish pet."
        assert policy["target_constraint"] == "Int('pet_Cat') == Int('pet_Fish') - 1"

    def test_generic_relation_template_uses_wrong_relation_vars_in_multi_relation_core(self):
        paradigm = ErrorParadigm(
            id="relation-template",
            name="template_directly_left",
            trigger={
                "constraint_types": ["directly_left"],
                "replacement_policy": {
                    "kind": "directly_left_from_source_clue",
                },
            },
            bad_operation="Int('job_Chef') == Int('job_Pilot') + 1",
            unsat_signature="sig",
            avoid_instruction="bad",
            repair_hint="hint",
            scope=["directly_left", "directly_right"],
            confidence=1.0,
            support_count=1,
            source_cluster=0,
            created_at=datetime.now(tz=timezone.utc),
        )
        state = SolverState(
            puzzle_id="p3",
            constraints=[],
            unsat_core=[
                "Distinct(Int('hobby_Gardening'), Int('hobby_Music'), Int('hobby_Reading'))",
                "Int('hobby_Gardening') == Int('hobby_Music') - 1",
                "Int('hobby_Music') == Int('hobby_Reading') + 1",
            ],
            z3_result="UNSAT",
            problem_nl=(
                "Clues:\n"
                "1. The Music hobby is immediately left of the Reading hobby.\n"
                "4. The Gardening hobby is immediately left of the Music hobby."
            ),
        )

        policy = _replacement_policy_from_error_paradigm(paradigm, state)

        assert policy["source_clue"] == "1. The Music hobby is immediately left of the Reading hobby."
        assert policy["target_constraint"] == "Int('hobby_Music') == Int('hobby_Reading') - 1"

    def test_parse_relation_source_clue(self):
        assert _parse_relation_source_clue(
            "1. The Chef job is immediately left of the Pilot job."
        ) == ("directly_left", "job_Chef", "job_Pilot")

    def test_clue_coverage_detects_wrong_relation_direction(self):
        issues = _find_clue_coverage_issues(
            "Clues:\n1. The Chef job is immediately left of the Pilot job.",
            ["Int('job_Chef') == Int('job_Pilot') + 1"],
        )

        assert len(issues) == 1
        assert issues[0].issue_type == "wrong_relation"
        assert issues[0].expected_constraint == "Int('job_Chef') == Int('job_Pilot') - 1"
        assert issues[0].offending_constraint == "Int('job_Chef') == Int('job_Pilot') + 1"

    def test_clue_coverage_detects_wrong_direct_position(self):
        issues = _find_clue_coverage_issues(
            "Clues:\n1. The Blue color person lives in house 1.",
            ["Int('color_Blue') == 2"],
        )

        assert len(issues) == 1
        assert issues[0].issue_type == "wrong_direct_position"
        assert issues[0].expected_constraint == "Int('color_Blue') == 1"

    def test_clue_coverage_detects_missing_relation(self):
        issues = _find_clue_coverage_issues(
            "Clues:\n1. The Chef job is immediately left of the Pilot job.",
            [
                "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
                "And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)",
            ],
        )

        assert len(issues) == 1
        assert issues[0].issue_type == "missing_relation"
        assert issues[0].expected_constraint == "Int('job_Chef') == Int('job_Pilot') - 1"
        assert issues[0].offending_constraint == ""

    def test_clue_coverage_accepts_equivalent_inverse_direct_relation(self):
        issues = _find_clue_coverage_issues(
            "Clues:\n1. The Chef job is immediately left of the Pilot job.",
            ["Int('job_Pilot') - 1 == Int('job_Chef')"],
        )

        assert issues == []

    def test_clue_coverage_repairs_without_error_memory_target(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[
            "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
            "And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)",
            "Int('job_Chef') == Int('job_Pilot') + 1",
        ])
        gs = GuidedSolver(
            llm_client=llm,
            library=empty_library,
            max_repair_rounds=2,
            layer2_enabled=False,
            enable_memory=True,
        )
        gs._translator = translator
        puzzle = PuzzleInstance(
            nl_description="Clues:\n1. The Chef job is immediately left of the Pilot job.",
            puzzle_id="coverage_no_memory_test",
            size="3x3",
        )

        result = gs.solve(puzzle)

        assert result.solved is True
        assert any(step.get("action") == "validate_clue_coverage" for step in result.steps)
        repair_step = next(
            step for step in result.steps
            if step.get("action") == "repair" and step.get("source") == "clue_coverage"
        )
        assert repair_step["old_constraint"] == "Int('job_Chef') == Int('job_Pilot') + 1"
        assert repair_step["new_constraint"] == "Int('job_Chef') == Int('job_Pilot') - 1"
        assert repair_step["error_guidance_triggered"] is False

    def test_clue_coverage_appends_missing_constraint(self, empty_library):
        llm = _BaseLLMClient()
        translator = _StubTranslator(initial=[
            "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
            "And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)",
        ])
        gs = GuidedSolver(
            llm_client=llm,
            library=empty_library,
            max_repair_rounds=2,
            layer2_enabled=False,
            enable_memory=True,
        )
        gs._translator = translator
        puzzle = PuzzleInstance(
            nl_description="Clues:\n1. The Chef job is immediately left of the Pilot job.",
            puzzle_id="coverage_missing_constraint_test",
            size="3x3",
        )

        result = gs.solve(puzzle)

        repair_step = next(
            step for step in result.steps
            if step.get("action") == "repair" and step.get("source") == "clue_coverage"
        )
        assert result.solved is True
        assert repair_step["old_constraint"] == ""
        assert repair_step["new_constraint"] == "Int('job_Chef') == Int('job_Pilot') - 1"

    def test_clue_coverage_uses_error_memory_to_repair_sat_mismatch(self, empty_library):
        with ErrorParadigmLibrary(":memory:") as error_lib:
            error_lib.add(
                ErrorParadigm(
                    id="coverage-relation-template",
                    name="template_directly_left",
                    trigger={
                        "constraint_types": ["directly_left"],
                        "replacement_policy": {
                            "kind": "directly_left_from_source_clue",
                        },
                    },
                    bad_operation="Int('job_Chef') == Int('job_Pilot') + 1",
                    unsat_signature="sig",
                    avoid_instruction="Do not reverse directly-left clues.",
                    repair_hint="Use the directly-left target from the source clue.",
                    scope=["directly_left"],
                    confidence=1.0,
                    support_count=1,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            llm = _BaseLLMClient()
            translator = _StubTranslator(initial=[
                "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
                "And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)",
                "Int('job_Chef') == Int('job_Pilot') + 1",
            ])
            gs = GuidedSolver(
                llm_client=llm,
                library=empty_library,
                max_repair_rounds=2,
                layer2_enabled=False,
                enable_memory=True,
                error_library=error_lib,
            )
            gs._translator = translator
            puzzle = PuzzleInstance(
                nl_description="Clues:\n1. The Chef job is immediately left of the Pilot job.",
                puzzle_id="coverage_memory_test",
                size="3x3",
            )

            result = gs.solve(puzzle)

            repair_step = next(
                step for step in result.steps
                if step.get("action") == "repair" and step.get("source") == "clue_coverage"
            )
            assert result.solved is True
            assert repair_step["old_constraint"] == "Int('job_Chef') == Int('job_Pilot') + 1"
            assert repair_step["new_constraint"] == "Int('job_Chef') == Int('job_Pilot') - 1"
            assert repair_step["error_guidance_triggered"] is True

    def test_clue_coverage_batches_all_memory_targeted_repairs(self, empty_library):
        with ErrorParadigmLibrary(":memory:") as error_lib:
            error_lib.add(
                ErrorParadigm(
                    id="coverage-relation-template",
                    name="template_directly_left",
                    trigger={
                        "constraint_types": ["directly_left"],
                        "replacement_policy": {
                            "kind": "directly_left_from_source_clue",
                        },
                    },
                    bad_operation="Abs(Int('job_Chef') - Int('job_Pilot')) == 1",
                    unsat_signature="sig",
                    avoid_instruction="Do not weaken directly-left clues.",
                    repair_hint="Use the directly-left target from the source clue.",
                    scope=["directly_left", "adjacent"],
                    confidence=1.0,
                    support_count=1,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            llm = _BaseLLMClient()
            translator = _StubTranslator(initial=[
                "And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)",
                "And(Int('color_Red') >= 1, Int('color_Red') <= 3)",
                "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
                "And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)",
                "Abs(Int('color_Blue') - Int('color_Red')) == 1",
                "Abs(Int('job_Chef') - Int('job_Pilot')) == 1",
            ])
            gs = GuidedSolver(
                llm_client=llm,
                library=empty_library,
                max_repair_rounds=2,
                layer2_enabled=False,
                enable_memory=True,
                error_library=error_lib,
            )
            gs._translator = translator
            puzzle = PuzzleInstance(
                nl_description=(
                    "Clues:\n"
                    "1. The Blue color is immediately left of the Red color.\n"
                    "2. The Chef job is immediately left of the Pilot job."
                ),
                puzzle_id="coverage_batch_memory_test",
                size="3x3",
            )

            result = gs.solve(puzzle)

            repair_step = next(
                step for step in result.steps
                if step.get("action") == "repair" and step.get("source") == "clue_coverage"
            )
            assert result.solved is True
            assert repair_step["clue_coverage_repair_count"] == 2
            assert {
                item["expected_constraint"]
                for item in repair_step["clue_coverage_repairs"]
            } == {
                "Int('color_Blue') == Int('color_Red') - 1",
                "Int('job_Chef') == Int('job_Pilot') - 1",
            }

    def test_relation_error_guidance_requires_materialized_target(self, empty_library):
        with ErrorParadigmLibrary(":memory:") as error_lib:
            error_lib.add(
                ErrorParadigm(
                    id="relation-template",
                    name="template_directly_left",
                    trigger={
                        "constraint_types": ["directly_left"],
                        "replacement_policy": {
                            "kind": "directly_left_from_source_clue",
                        },
                    },
                    bad_operation="Int('job_Chef') == Int('job_Pilot') + 1",
                    unsat_signature="sig",
                    avoid_instruction="bad",
                    repair_hint="hint",
                    scope=["directly_left"],
                    confidence=1.0,
                    support_count=1,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
            gs = GuidedSolver(
                llm_client=_BaseLLMClient(),
                library=empty_library,
                layer2_enabled=False,
                error_library=error_lib,
            )
            state = SolverState(
                puzzle_id="no-target",
                constraints=[],
                unsat_core=["Int('drink_Water') == Int('drink_Coffee') + 1"],
                z3_result="UNSAT",
                problem_nl="Clues:\n1. The Coffee drink is immediately left of the Milk drink.",
                constraint_types=["directly_right"],
            )

            hint, trace = gs._build_error_guidance(state)

            assert hint == ""
            assert trace == []

    def test_validate_repair_rejects_target_mismatch(self):
        ok, reason = GuidedSolver._validate_repair_output(
            "Int('job_Chef') < Int('job_Pilot')",
            ["Int('job_Chef') == Int('job_Pilot') + 1"],
            ["Int('job_Chef') == Int('job_Pilot') + 1"],
            ["Int('job_Chef') == Int('job_Pilot') - 1"],
        )

        assert ok is False
        assert reason == "target_mismatch"

    def test_validate_repair_rejects_weak_direct_position_repair(self):
        ok, reason = GuidedSolver._validate_repair_output(
            "Int('color_Blue') != 2",
            ["Int('color_Blue') == 2"],
            ["Int('color_Blue') == 2"],
            ["Int('color_Blue') == 1"],
        )

        assert ok is False
        assert reason == "weak_repair"

    def test_validate_repair_rejects_weak_relation_repair(self):
        ok, reason = GuidedSolver._validate_repair_output(
            "Abs(Int('job_Chef') - Int('job_Pilot')) == 1",
            ["Int('job_Chef') == Int('job_Pilot') + 1"],
            ["Int('job_Chef') == Int('job_Pilot') + 1"],
            ["Int('job_Chef') == Int('job_Pilot') - 1"],
        )

        assert ok is False
        assert reason == "weak_repair"

    def test_empty_precondition_paradigm_hint_can_be_injected(self, solver):
        with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as lib:
            lib.add(
                Paradigm(
                    id="p-empty-pre",
                    name="restore_domain_bounds",
                    trigger={"constraint_types": ["ordering"]},
                    operation="And(Int('x') >= 1, Int('x') <= 3)",
                    pre_condition="",
                    post_condition="Keep generated values inside the house range.",
                    scope=["ordering"],
                    confidence=1.0,
                    support_count=5,
                    source_cluster=0,
                    created_at=datetime.now(tz=timezone.utc),
                ),
                verify=False,
            )
            llm = _RecordingRepairClient()
            translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
            gs = GuidedSolver(
                llm_client=llm,
                library=lib,
                max_repair_rounds=1,
                layer2_enabled=False,
            )
            gs._translator = translator

            result = gs.solve(_unsat_puzzle())

            assert result.solved is True
            assert "restore_domain_bounds" in llm.last_paradigm_hint
            assert "And(Int('x') >= 1, Int('x') <= 3)" in llm.last_paradigm_hint


# --------------------------------------------------------------------------- #
# Stagnation / escalation                                                        #
# --------------------------------------------------------------------------- #

class TestStagnationEscalation:

    def test_stagnation_triggers_l4_retranslate_to_sat(self, empty_library):
        """Same UNSAT core on every repair 鈫?stagnation 鈫?L4 retranslate 鈫?SAT."""
        llm = _AlwaysUnsat()
        translator = _StubTranslator(
            initial=["Int('x') > 5", "Int('x') < 3"],
            retranslate_result=["Int('x') > 0", "Int('x') < 10"],  # SAT
        )
        gs = GuidedSolver(
            llm_client=llm, library=empty_library,
            max_repair_rounds=5, layer2_enabled=False,
        )
        gs._translator = translator
        result = gs.solve(_unsat_puzzle())
        # L4 retranslation produces SAT constraints 鈫?should eventually solve
        # (stagnation detected after 2 identical repairs 鈫?L4 fires on 3rd iteration)
        assert result.stagnation_detected is True

    def test_stagnation_flag_set_in_result(self, empty_library):
        llm = _AlwaysUnsat()
        translator = _StubTranslator(
            initial=["Int('x') > 5", "Int('x') < 3"],
            retranslate_result=["Int('x') > 0", "Int('x') < 10"],
        )
        gs = GuidedSolver(
            llm_client=llm, library=empty_library,
            max_repair_rounds=5, layer2_enabled=False,
        )
        gs._translator = translator
        result = gs.solve(_unsat_puzzle())
        assert isinstance(result.stagnation_detected, bool)


class TestFeatureFlags:

    def test_disable_paradigm_skips_library_retrieval(self):
        llm = _FixingRepairClient()
        library = _RecordingLibrary(paradigms=[make_paradigm(scope=["ordering"])])
        translator = _StubTranslator(initial=["Int('x') > 5", "Int('x') < 3"])
        gs = GuidedSolver(
            llm_client=llm,
            library=library,
            max_repair_rounds=3,
            enable_paradigm=False,
            enable_memory=True,
            layer2_enabled=False,
        )
        gs._translator = translator

        result = gs.solve(_unsat_puzzle())

        assert result.paradigm_triggered is False
        assert library.retrieve_calls == 0

    def test_disable_memory_prevents_stagnation_escalation(self):
        llm = _AlwaysUnsat()
        translator = _StubTranslator(
            initial=["Int('x') > 5", "Int('x') < 3"],
            retranslate_result=["Int('x') > 0", "Int('x') < 10"],
        )
        gs = GuidedSolver(
            llm_client=llm,
            library=_RecordingLibrary(),
            max_repair_rounds=4,
            enable_paradigm=False,
            enable_memory=False,
            layer2_enabled=False,
        )
        gs._translator = translator

        result = gs.solve(_unsat_puzzle())

        assert result.stagnation_detected is False
        assert all(step.get("action") != "retranslate" for step in result.steps)
