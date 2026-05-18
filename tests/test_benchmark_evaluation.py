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
