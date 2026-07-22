"""Tests for the SPARC structural-prior gate (no API).

Exercises the π-gate (uniqueness probe), diff-guided completion with the
progress guarantee, the conflict-repair path with the visibility invariant,
and the abstention semantics — all with stub LLMs and real Z3.
"""

from __future__ import annotations

import pytest

from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary

PUZZLE = PuzzleInstance(
    puzzle_id="sparc_toy",
    nl_description=(
        "Three houses. Clue 1: the red house is immediately left of the "
        "green house. Clue 2: the dog owner lives in the red house. "
        "Clue 3: the fish is in house 3. Clue 4: the green house is house 2."
    ),
    size="3x2",
    domain="zebralogic",
)

DOMAIN = [
    "And(Int('color_Red') >= 1, Int('color_Red') <= 3)",
    "And(Int('color_Green') >= 1, Int('color_Green') <= 3)",
    "And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)",
    "Distinct(Int('color_Red'), Int('color_Green'), Int('color_Blue'))",
    "And(Int('pet_Dog') >= 1, Int('pet_Dog') <= 3)",
    "And(Int('pet_Cat') >= 1, Int('pet_Cat') <= 3)",
    "And(Int('pet_Fish') >= 1, Int('pet_Fish') <= 3)",
    "Distinct(Int('pet_Dog'), Int('pet_Cat'), Int('pet_Fish'))",
]
CLUE1 = "Int('color_Red') == Int('color_Green') - 1"
CLUE2 = "Int('pet_Dog') == Int('color_Red')"
CLUE3 = "Int('pet_Fish') == 3"
CLUE4 = "Int('color_Green') == 2"

UNIQUE_SET = DOMAIN + [CLUE1, CLUE2, CLUE3, CLUE4]      # exactly one solution
UNDER_SET = DOMAIN + [CLUE1, CLUE3, CLUE4]              # clue 2 missing → 2 models


class _StubLLM:
    """Minimal LLM stub: canned completion responses, counts calls."""

    def __init__(self, completions=None, repairs=None):
        self.call_count = 0
        self._completions = list(completions or [])
        self._repairs = list(repairs or [])

    def reset_call_count(self):
        self.call_count = 0

    def complete_constraint(self, puzzle_nl, current_constraints, diff_summary):
        self.call_count += 1
        text = self._completions.pop(0) if self._completions else ""
        return f"```python\n{text}\n```" if text else "no idea"

    def repair(self, constraints, unsat_core, history_summary, **kwargs):
        self.call_count += 1
        text = self._repairs.pop(0) if self._repairs else ""
        return f"```python\n{text}\n```" if text else "no idea"


def _solver_for(constraints):
    s = Z3SolverWrapper()
    for c in constraints:
        s.add_constraint(c)
    assert s.check() == "SAT"
    return s


def _guided(llm, **kw):
    return GuidedSolver(
        llm_client=llm,
        library=ParadigmLibrary(":memory:", Z3SolverWrapper()),
        enable_paradigm=False,
        enable_memory=False,
        sparc=True,
        **kw,
    )


# --------------------------------------------------------------------------- #
# π-gate                                                                       #
# --------------------------------------------------------------------------- #

def test_gate_passes_unique_solution():
    gs = _guided(_StubLLM())
    steps = []
    result = gs._success(PUZZLE, _solver_for(UNIQUE_SET), steps, 0)
    assert result.solved is True
    assert result.final_z3_result == "SAT"
    assert any(s.get("action") == "pi_gate" and s.get("gate") == "unique" for s in steps)


def test_gate_abstains_when_completion_unavailable():
    gs = _guided(_StubLLM(completions=[]))
    steps = []
    result = gs._success(PUZZLE, _solver_for(UNDER_SET), steps, 0)
    assert result.solved is False
    assert result.final_z3_result == "SAT_NONUNIQUE"
    assert result.solution is None
    assert any(s.get("gate") == "non_unique" for s in steps)


def test_gate_completion_recovers_missing_clue():
    # LLM supplies exactly the missing clue 2 → solution becomes unique.
    gs = _guided(_StubLLM(completions=[CLUE2]))
    steps = []
    result = gs._success(PUZZLE, _solver_for(UNDER_SET), steps, 0)
    assert result.solved is True
    assert result.final_z3_result == "SAT"
    # correct unique assignment recovered
    assert result.solution["color_Red"] == "1"
    assert result.solution["pet_Dog"] == "1"
    actions = [s.get("action") for s in steps]
    assert "diff_completion" in actions
    assert actions[-1] == "pi_gate"  # final pass through the gate


def test_progress_guarantee_rejects_non_discriminating_candidate():
    # First candidate holds under BOTH models (no progress) → rejected;
    # second candidate is the real missing clue → accepted.
    tautology = "Int('pet_Fish') == 3"  # already true in every model
    gs = _guided(_StubLLM(completions=[tautology, CLUE2]))
    steps = []
    result = gs._success(PUZZLE, _solver_for(UNDER_SET), steps, 0)
    assert result.solved is True
    assert any(
        s.get("action") == "diff_completion_rejected"
        and s.get("reason") == "does_not_discriminate"
        for s in steps
    )


def test_gate_off_keeps_legacy_behaviour():
    gs = GuidedSolver(
        llm_client=_StubLLM(),
        library=ParadigmLibrary(":memory:", Z3SolverWrapper()),
        enable_paradigm=False,
        enable_memory=False,
        sparc=False,
    )
    result = gs._success(PUZZLE, _solver_for(UNDER_SET), [], 0)
    assert result.solved is True  # legacy: SBW-prone acceptance


# --------------------------------------------------------------------------- #
# Conflict repair path (visibility restored)                                   #
# --------------------------------------------------------------------------- #

def test_completion_exposing_conflict_gets_repaired():
    # Start from a WEAKENED, flipped set: clue 1 flipped (red right of green),
    # clue 2 deleted. Completion re-adds clue 2 → conflict with the flip
    # (red=3, dog=3, fish=3) → conflict repair must fix the flipped clue 1.
    flipped = "Int('color_Red') == Int('color_Green') + 1"
    weakened = DOMAIN + [flipped, CLUE3, CLUE4]
    gs = _guided(_StubLLM(completions=[CLUE2], repairs=[CLUE1]))
    steps = []
    result = gs._success(PUZZLE, _solver_for(weakened), steps, 0)
    assert result.solved is True
    assert result.solution["color_Red"] == "1"  # flip corrected
    actions = [s.get("action") for s in steps]
    assert "sparc_conflict_repair" in actions


def test_conflict_repair_protects_completion_constraint():
    # Repair budget exhausted without a fix → abstain, and the completion
    # constraint must never be selected as the repair target.
    flipped = "Int('color_Red') == Int('color_Green') + 1"
    weakened = DOMAIN + [flipped, CLUE3, CLUE4]
    gs = _guided(
        _StubLLM(completions=[CLUE2], repairs=["Int('color_Blue') == 1"]),
        sparc_repair_budget=1,
    )
    steps = []
    result = gs._success(PUZZLE, _solver_for(weakened), steps, 0)
    assert result.solved is False
    assert result.final_z3_result == "SAT_NONUNIQUE"
    for s in steps:
        if s.get("action") == "sparc_conflict_repair":
            assert s.get("old_constraint") != CLUE2


# --------------------------------------------------------------------------- #
# Ablation switches                                                            #
# --------------------------------------------------------------------------- #

def test_gate_only_ablation_abstains_without_completion():
    # sparc_max_completions=0: detect under-constraint → abstain immediately,
    # never call the LLM for completion.
    llm = _StubLLM(completions=[CLUE2])
    gs = _guided(llm, sparc_max_completions=0)
    steps = []
    result = gs._success(PUZZLE, _solver_for(UNDER_SET), steps, 0)
    assert result.solved is False
    assert result.final_z3_result == "SAT_NONUNIQUE"
    assert llm.call_count == 0
    assert not any(s.get("action") == "diff_completion" for s in steps)


def test_blind_completion_skips_diff_and_progress_check():
    # Blind ablation: no model-diff in the prompt, no discrimination check —
    # a non-discriminating candidate is accepted (and wastes a completion).
    captured = []

    class _Recorder(_StubLLM):
        def complete_constraint(self, puzzle_nl, current_constraints, diff_summary):
            captured.append(diff_summary)
            return super().complete_constraint(
                puzzle_nl, current_constraints, diff_summary
            )

    tautology = "Int('pet_Fish') == 3"  # holds in every model: no progress
    gs = _guided(
        _Recorder(completions=[tautology, CLUE2]), sparc_blind_completion=True
    )
    steps = []
    result = gs._success(PUZZLE, _solver_for(UNDER_SET), steps, 0)
    assert result.solved is True  # second candidate still fixes it
    assert all("no model diff" in s for s in captured)
    assert not any(
        s.get("action") == "diff_completion_rejected" for s in steps
    )


def test_no_invariant_ablation_exposes_completion_to_repair():
    # Without the invariant the repair may target the completion constraint
    # itself (the stub replaces it with a tautology → SAT restored, but the
    # flipped clue stays hidden → wrong unique-looking state never reached;
    # here the loop re-detects non-unique and abstains on budget).
    flipped = "Int('color_Red') == Int('color_Green') + 1"
    weakened = DOMAIN + [flipped, CLUE3, CLUE4]
    seen_cores = []

    class _Recorder(_StubLLM):
        def repair(self, constraints, unsat_core, history_summary, **kwargs):
            seen_cores.append(list(unsat_core))
            assert "do not delete or weaken" not in history_summary
            return super().repair(
                constraints, unsat_core, history_summary, **kwargs
            )

    gs = _guided(
        _Recorder(completions=[CLUE2], repairs=["Int('color_Blue') == 1"]),
        sparc_repair_budget=1,
        sparc_no_invariant=True,
    )
    steps = []
    gs._success(PUZZLE, _solver_for(weakened), steps, 0)
    # evidence protection is off: the completion constraint is a legal target
    assert any(CLUE2 in core for core in seen_cores)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def test_blocking_clause_skips_tracking_vars():
    clause = GuidedSolver._blocking_clause(
        {"a": "1", "_prism_track_0": "True", "b": "2"}
    )
    assert "a" in clause and "b" in clause and "_prism_track_" not in clause


def test_blocking_clause_none_for_empty_model():
    assert GuidedSolver._blocking_clause({}) is None
    assert GuidedSolver._blocking_clause(None) is None


def test_blocking_clause_whitelist_restricts_to_answer_vars():
    # normalise_schema_key("color_Blue") == "colorblue"
    clause = GuidedSolver._blocking_clause(
        {"color_Blue": "1", "aux_counter": "3"},
        frozenset({"colorblue"}),
    )
    assert "color_Blue" in clause and "aux_counter" not in clause


def test_blocking_clause_whitelist_falls_back_when_nothing_matches():
    clause = GuidedSolver._blocking_clause(
        {"a": "1", "b": "2"},
        frozenset({"petdog"}),
    )
    assert "a" in clause and "b" in clause


def test_answer_projection_vars_reports_mode():
    model = {"color_Blue": "1", "aux": "3", "_prism_track_0": "True"}
    pairs, mode = GuidedSolver._answer_projection_vars(
        model, frozenset({"colorblue"})
    )
    assert pairs == [("color_Blue", "1")] and mode == "whitelist"
    pairs, mode = GuidedSolver._answer_projection_vars(model, frozenset())
    assert mode == "all_int" and ("aux", "3") in pairs


def test_holds_under_decides_and_rejects_unknown_vars():
    model = {"x": "1", "y": "2"}
    assert GuidedSolver._holds_under("Int('x') < Int('y')", model) is True
    assert GuidedSolver._holds_under("Int('x') > Int('y')", model) is False
    assert GuidedSolver._holds_under("garbage((", model) is None
