from __future__ import annotations

from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.benchmarks.knights_knaves import evaluate_knights_knaves
from prism.evaluation.benchmarks.zebralogic import evaluate_zebralogic


class _StaticSolver:
    def __init__(self, result: SolveResult) -> None:
        self._result = result

    def solve(self, puzzle: PuzzleInstance) -> SolveResult:
        return self._result


def test_zebralogic_evaluation_requires_exact_match_when_ground_truth_exists():
    puzzle = PuzzleInstance(
        puzzle_id="z1",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z1",
            solved=True,
            solution={"color_blue": "house2"},
            final_z3_result="SAT",
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["solved"] is False
    assert results[0]["ground_truth"] == "color_blue=house1"
    assert results[0]["predicted"] == "color_blue=house2"


def test_zebralogic_evaluation_accepts_exact_match_when_ground_truth_exists():
    puzzle = PuzzleInstance(
        puzzle_id="z2",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z2",
            solved=True,
            solution={"color_blue": "house1"},
            final_z3_result="SAT",
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["solved"] is True


def test_zebralogic_evaluation_surfaces_memory_eligibility_diagnostics():
    puzzle = PuzzleInstance(
        puzzle_id="z-memory",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z-memory",
            solved=False,
            solution={"color_blue": "house2"},
            final_z3_result="UNSAT",
            steps=[
                {"iteration": 0, "action": "translate", "z3_result": "UNSAT"},
                {"iteration": 1, "action": "repair", "z3_result": "UNSAT"},
            ],
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["initial_z3_result"] == "UNSAT"
    assert results[0]["initial_solver_result"] == "UNSAT"
    assert results[0]["memory_eligible"] is True
    assert results[0]["repair_success"] is False
    assert results[0]["validated_repair_success"] is False
    assert results[0]["repair_rejected"] is False


def test_zebralogic_evaluation_preserves_raw_initial_solver_result():
    puzzle = PuzzleInstance(
        puzzle_id="z-raw",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z-raw",
            solved=False,
            solution={"color_blue": "house2"},
            final_z3_result="INVALID_MODEL",
            steps=[
                {
                    "iteration": 0,
                    "action": "translate",
                    "raw_z3_result": "SAT",
                    "z3_result": "INVALID_MODEL",
                },
            ],
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["initial_solver_result"] == "SAT"
    assert results[0]["initial_z3_result"] == "INVALID_MODEL"


def test_zebralogic_evaluation_validated_repair_success_requires_correct_solution():
    puzzle = PuzzleInstance(
        puzzle_id="z-valid-repair",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z-valid-repair",
            solved=True,
            solution={"color_blue": "house1"},
            final_z3_result="SAT",
            steps=[
                {"iteration": 0, "action": "translate", "z3_result": "UNSAT"},
                {"iteration": 1, "action": "repair", "z3_result": "SAT"},
            ],
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["repair_success"] is True
    assert results[0]["validated_repair_success"] is True


def test_zebralogic_evaluation_surfaces_repair_rejected():
    puzzle = PuzzleInstance(
        puzzle_id="z-reject",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z-reject",
            solved=False,
            solution=None,
            final_z3_result="UNSAT",
            steps=[
                {"iteration": 0, "action": "translate", "z3_result": "UNSAT"},
                {"iteration": 1, "action": "repair_rejected", "z3_result": "UNSAT"},
            ],
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["memory_eligible"] is True
    assert results[0]["repair_rejected"] is True


def test_zebralogic_evaluation_surfaces_misaligned_model_diagnostics():
    puzzle = PuzzleInstance(
        puzzle_id="z3",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z3",
            solved=False,
            solution={"house1_color": "1"},
            final_z3_result="MISALIGNED_MODEL",
            steps=[
                {
                    "action": "validate_model",
                    "z3_result": "MISALIGNED_MODEL",
                    "model_schema_aligned": False,
                }
            ],
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["model_schema_aligned"] is False
    assert results[0]["model_key_set_aligned"] is True
    assert results[0]["misaligned_model"] is True
    assert results[0]["key_mismatch"] is False
    assert results[0]["invalid_model"] is False


def test_zebralogic_evaluation_surfaces_key_mismatch_diagnostics():
    puzzle = PuzzleInstance(
        puzzle_id="z4",
        nl_description="test",
        size="2x4",
        domain="zebralogic",
        solution={"color_blue": "house1", "color_green": "house2"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="z4",
            solved=False,
            solution={"color_blue": "house1", "color_red": "house2"},
            final_z3_result="KEY_MISMATCH",
            steps=[
                {
                    "action": "validate_model",
                    "z3_result": "KEY_MISMATCH",
                    "model_schema_aligned": True,
                    "model_key_set_aligned": False,
                }
            ],
        )
    )

    results = evaluate_zebralogic(solver, [puzzle])

    assert results[0]["model_schema_aligned"] is True
    assert results[0]["model_key_set_aligned"] is False
    assert results[0]["key_mismatch"] is True
    assert results[0]["misaligned_model"] is False


def test_knk_evaluation_requires_exact_match_when_ground_truth_exists():
    puzzle = PuzzleInstance(
        puzzle_id="k1",
        nl_description="test",
        size="knk_2",
        domain="knights_knaves",
        solution={"A": "knight", "B": "knave"},
    )
    solver = _StaticSolver(
        SolveResult(
            puzzle_id="k1",
            solved=True,
            solution={"A": "knave", "B": "knave"},
            final_z3_result="SAT",
        )
    )

    results = evaluate_knights_knaves(solver, [puzzle])

    assert results[0]["solved"] is False
    assert results[0]["ground_truth"] == "A=knight|B=knave"
    assert results[0]["predicted"] == "A=knave|B=knave"
