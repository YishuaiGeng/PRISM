"""Unit tests for the AR-LSAT well-definedness gate (SPARC pi-gate)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.types import PuzzleInstance
from prism.evaluation.benchmarks.arlsat import (
    OptionCheck,
    WellDefinednessGate,
    decide_option,
    recheck_options,
)

BACKGROUND = ["Int('x') >= 1", "Int('x') <= 3"]


def _puzzle(question_type: str = "could_be_true") -> PuzzleInstance:
    return PuzzleInstance(
        puzzle_id="gate-test",
        nl_description="x is between 1 and 3.",
        constraints_nl=["x is between 1 and 3."],
        solution=None,
        size="arlsat_3opt",
        domain="arlsat",
        raw_data={
            "passage": "x is between 1 and 3.",
            "question": "Which could be true?",
            "options": ["x is 1", "x is 2", "x is 5"],
            "answer": "B",
            "question_type": question_type,
            "is_except": False,
        },
    )


def _checks(formulas: dict[str, str | None]) -> dict[str, OptionCheck]:
    return recheck_options(
        BACKGROUND, {k: OptionCheck(formula=v) for k, v in formulas.items()}
    )


class _StubLLM:
    def __init__(self, completions: list[str]):
        self._completions = completions
        self.calls = 0

    def complete_arlsat_background(self, **_kwargs) -> str:
        self.calls += 1
        text = self._completions.pop(0) if self._completions else ""
        return f"```python\n{text}\n```" if text else "no idea"


class _StubOptionChecker:
    """Returns a fixed re-translation; counts as one LLM call."""

    def __init__(self, formulas: dict[str, str | None]):
        self._formulas = formulas
        self.last_llm_calls = 1

    def check_options(self, background, _puzzle):
        return recheck_options(
            background, {k: OptionCheck(formula=v) for k, v in self._formulas.items()}
        )


def test_tie_broken_by_completion():
    checks = _checks({"A": "Int('x') == 1", "B": "Int('x') == 2", "C": "Int('x') == 5"})
    decision = decide_option(checks, "could_be_true", False)
    assert decision.candidates == ["A", "B"]

    gate = WellDefinednessGate(_StubLLM(["Int('x') != 1"]), budget=2)
    decision, background, _, info = gate.run(
        _puzzle(), BACKGROUND, checks, _StubOptionChecker({}), decision
    )
    assert decision.predicted == "B"
    assert "Int('x') != 1" in background
    assert info["gate_completions"] == 1


def test_non_progress_completion_rejected_then_abstain():
    checks = _checks({"A": "Int('x') == 1", "B": "Int('x') == 2", "C": "Int('x') == 5"})
    decision = decide_option(checks, "could_be_true", False)

    # A tautology over the background eliminates nothing; an UNSAT-inducing
    # constraint must also be rejected (visibility preservation).
    gate = WellDefinednessGate(_StubLLM(["Int('x') >= 0", "Int('x') > 5"]), budget=2)
    decision, background, _, info = gate.run(
        _puzzle(), BACKGROUND, checks, _StubOptionChecker({}), decision
    )
    assert decision.predicted is None            # abstain, never guess
    assert background == BACKGROUND              # nothing committed
    assert info["gate_completions"] == 0
    assert info["gate_final_candidates"] == 2


def test_zero_candidates_routed_to_option_retranslation():
    checks = _checks({"A": None, "B": None, "C": None})  # option block unparseable
    decision = decide_option(checks, "could_be_true", False)
    assert decision.candidates == []

    retranslated = {"A": "Int('x') == 5", "B": "Int('x') == 2", "C": "Int('x') == 7"}
    gate = WellDefinednessGate(_StubLLM([]), budget=2)
    decision, _, _, info = gate.run(
        _puzzle(), BACKGROUND, checks, _StubOptionChecker(retranslated), decision
    )
    assert decision.predicted == "B"
    assert info["gate_option_retranslated"] is True
