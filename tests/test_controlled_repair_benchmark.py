from __future__ import annotations

from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance
from scripts.prism.run_controlled_repair_benchmark import (
    ControlledRepairLLM,
    _add_controlled_target_memory,
    _add_controlled_template_memory,
    _build_controlled_puzzles,
    _direct_position_clues,
    _load_prepared_puzzles,
    _relation_clues,
    _save_prepared_puzzles,
    _solution_constraints,
)


def test_direct_position_clues_extracts_benchmark_style_keys():
    text = "1. The Purple color person lives in house 1.\n2. The Wine drink person lives in house 2."

    clues = _direct_position_clues(text)

    assert ("color_Purple", 1, "1. The Purple color person lives in house 1.") in clues
    assert ("drink_Wine", 2, "2. The Wine drink person lives in house 2.") in clues


def test_relation_clues_extracts_immediately_left_keys():
    text = "1. The Chef job is immediately left of the Pilot job."

    clues = _relation_clues(text)

    assert (
        "directly_left",
        "job_Chef",
        "job_Pilot",
        "1. The Chef job is immediately left of the Pilot job.",
    ) in clues


def test_solution_constraints_include_bounds_distinct_and_assignments():
    constraints = _solution_constraints(
        {"color_Blue": "1", "color_Red": "2", "drink_Water": "1"},
        2,
    )

    assert "And(Int('color_Blue') >= 1, Int('color_Blue') <= 2)" in constraints
    assert "Distinct(Int('color_Blue'), Int('color_Red'))" in constraints
    assert "Int('drink_Water') == 1" in constraints


def test_build_controlled_puzzle_injects_single_unsat_position_error():
    record = {
        "id": "p1",
        "size": "2x2",
        "puzzle": (
            "There are 2 houses.\n\n"
            "Candidate values:\n"
            "- color: `Blue`, `Red`\n"
            "- drink: `Water`, `Tea`\n\n"
            "Clues:\n"
            "1. The Blue color person lives in house 1.\n"
        ),
        "solution": {
            "color_Blue": "1",
            "color_Red": "2",
            "drink_Water": "1",
            "drink_Tea": "2",
        },
    }

    puzzles, metadata = _build_controlled_puzzles([record])
    puzzle = puzzles[0]
    constraints = puzzle.raw_data["controlled_constraints"]

    solver = Z3SolverWrapper()
    for constraint in constraints:
        assert solver.add_constraint(constraint)

    assert solver.check() == "UNSAT"
    assert metadata["p1"]["controlled_correct_constraint"] == "Int('color_Blue') == 1"
    assert metadata["p1"]["controlled_wrong_constraint"] == "Int('color_Blue') == 2"
    assert "Int('color_Blue') == 2" in solver.get_unsat_core()


def test_build_controlled_puzzle_injects_relation_direction_error():
    record = {
        "id": "p1",
        "size": "3x3",
        "puzzle": (
            "There are 3 houses.\n\n"
            "Candidate values:\n"
            "- job: `Artist`, `Chef`, `Pilot`\n\n"
            "Clues:\n"
            "1. The Chef job is immediately left of the Pilot job.\n"
        ),
        "solution": {
            "job_Artist": "1",
            "job_Chef": "2",
            "job_Pilot": "3",
        },
    }

    puzzles, metadata = _build_controlled_puzzles(
        [record],
        perturbation_type="directly_left",
    )
    constraints = puzzles[0].raw_data["controlled_constraints"]

    solver = Z3SolverWrapper()
    for constraint in constraints:
        assert solver.add_constraint(constraint)

    assert solver.check() == "UNSAT"
    assert metadata["p1"]["controlled_perturbation_type"] == "directly_left"
    assert metadata["p1"]["controlled_correct_constraint"] == (
        "Int('job_Chef') == Int('job_Pilot') - 1"
    )
    assert metadata["p1"]["controlled_wrong_constraint"] == (
        "Int('job_Chef') == Int('job_Pilot') + 1"
    )


def test_build_controlled_puzzle_can_use_validated_llm_base_constraints():
    class StubLLM:
        call_count = 0

        def translate(self, puzzle_nl, schema_hint=""):
            self.call_count += 1
            return """```python
And(Int('job_Artist') >= 1, Int('job_Artist') <= 3)
And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)
And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)
Distinct(Int('job_Artist'), Int('job_Chef'), Int('job_Pilot'))
Int('job_Artist') == 1
Int('job_Chef') == Int('job_Pilot') - 1
Int('job_Pilot') == 3
```"""

    record = {
        "id": "p1",
        "size": "3x3",
        "puzzle": (
            "There are 3 houses.\n\n"
            "Clues:\n"
            "1. The Chef job is immediately left of the Pilot job.\n"
        ),
        "solution": {
            "job_Artist": "1",
            "job_Chef": "2",
            "job_Pilot": "3",
        },
    }

    puzzles, metadata = _build_controlled_puzzles(
        [record],
        perturbation_type="directly_left",
        base_constraints="llm_validated",
        llm_client=StubLLM(),
    )

    constraints = puzzles[0].raw_data["controlled_constraints"]
    assert metadata["p1"]["controlled_base_constraints"] == "llm_validated"
    assert "Int('job_Chef') == Int('job_Pilot') - 1" not in constraints
    assert "Int('job_Chef') == Int('job_Pilot') + 1" in constraints

    solver = Z3SolverWrapper()
    for constraint in constraints:
        assert solver.add_constraint(constraint)
    assert solver.check() == "UNSAT"


def test_llm_validated_base_skips_incorrect_translation():
    class StubLLM:
        call_count = 0

        def translate(self, puzzle_nl, schema_hint=""):
            self.call_count += 1
            return """```python
And(Int('job_Artist') >= 1, Int('job_Artist') <= 3)
And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)
And(Int('job_Pilot') >= 1, Int('job_Pilot') <= 3)
Distinct(Int('job_Artist'), Int('job_Chef'), Int('job_Pilot'))
Int('job_Artist') == 2
Int('job_Chef') == Int('job_Pilot') - 1
Int('job_Pilot') == 3
```"""

    record = {
        "id": "p1",
        "size": "3x3",
        "puzzle": (
            "There are 3 houses.\n\n"
            "Clues:\n"
            "1. The Chef job is immediately left of the Pilot job.\n"
        ),
        "solution": {
            "job_Artist": "1",
            "job_Chef": "2",
            "job_Pilot": "3",
        },
    }

    puzzles, metadata = _build_controlled_puzzles(
        [record],
        perturbation_type="directly_left",
        base_constraints="llm_validated",
        llm_client=StubLLM(),
    )

    assert puzzles == []
    assert metadata == {}


def test_llm_schema_completed_base_adds_bounds_before_validation():
    class StubLLM:
        call_count = 0

        def translate(self, puzzle_nl, schema_hint=""):
            self.call_count += 1
            return """```python
Int('job_Artist') == 1
Int('job_Chef') == Int('job_Pilot') - 1
Int('job_Pilot') == 3
```"""

    record = {
        "id": "p1",
        "size": "3x3",
        "puzzle": (
            "There are 3 houses.\n\n"
            "Clues:\n"
            "1. The Chef job is immediately left of the Pilot job.\n"
        ),
        "solution": {
            "job_Artist": "1",
            "job_Chef": "2",
            "job_Pilot": "3",
        },
    }

    puzzles, metadata = _build_controlled_puzzles(
        [record],
        perturbation_type="directly_left",
        base_constraints="llm_schema_completed",
        llm_client=StubLLM(),
    )

    constraints = puzzles[0].raw_data["controlled_constraints"]
    assert metadata["p1"]["controlled_base_constraints"] == "llm_schema_completed"
    assert "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)" in constraints
    assert "Distinct(Int('job_Artist'), Int('job_Chef'), Int('job_Pilot'))" in constraints
    assert "Int('job_Chef') == Int('job_Pilot') + 1" in constraints


def test_prepared_controlled_puzzles_roundtrip(tmp_path):
    record = {
        "id": "p1",
        "size": "2x2",
        "puzzle": (
            "There are 2 houses.\n\n"
            "Candidate values:\n"
            "- color: `Blue`, `Red`\n\n"
            "Clues:\n"
            "1. The Blue color person lives in house 1.\n"
        ),
        "solution": {
            "color_Blue": "1",
            "color_Red": "2",
        },
    }
    puzzles, metadata = _build_controlled_puzzles([record])
    path = tmp_path / "prepared.jsonl"

    _save_prepared_puzzles(puzzles, path)
    loaded, loaded_metadata = _load_prepared_puzzles(path)

    assert loaded[0].puzzle_id == "p1"
    assert loaded[0].raw_data["controlled_constraints"] == puzzles[0].raw_data["controlled_constraints"]
    assert loaded_metadata == metadata


def test_relation_hard_mode_omits_endpoint_assignments_from_core():
    record = {
        "id": "p1",
        "size": "3x3",
        "puzzle": (
            "There are 3 houses.\n\n"
            "Candidate values:\n"
            "- job: `Artist`, `Chef`, `Pilot`\n\n"
            "Clues:\n"
            "1. The Chef job is immediately left of the Pilot job.\n"
        ),
        "solution": {
            "job_Artist": "1",
            "job_Chef": "2",
            "job_Pilot": "3",
        },
    }

    puzzles, metadata = _build_controlled_puzzles(
        [record],
        perturbation_type="directly_left",
        relation_hard_mode=True,
    )
    constraints = puzzles[0].raw_data["controlled_constraints"]

    solver = Z3SolverWrapper()
    for constraint in constraints:
        assert solver.add_constraint(constraint)
    core = solver.get_unsat_core()

    assert solver.check() == "UNSAT"
    assert metadata["p1"]["controlled_relation_hard_mode"] is True
    assert "Int('job_Pilot') == 3" in core
    assert "Int('job_Chef') == 2" not in core
    assert "Int('job_Chef') == Int('job_Pilot') + 1" in core


def test_controlled_repair_llm_injects_exact_target_into_hint():
    class Inner:
        call_count = 0

        def reset_call_count(self):
            pass

        def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
            self.last_hint = paradigm_hint
            return "Int('color_Blue') == 1"

    inner = Inner()
    wrapper = ControlledRepairLLM(inner)
    wrapper.current_puzzle = PuzzleInstance(
        nl_description="test",
        raw_data={
            "controlled_diagnostics": {
                "controlled_source_clue": "1. The Blue color person lives in house 1.",
                "controlled_correct_constraint": "Int('color_Blue') == 1",
            }
        },
    )

    response = wrapper.repair([], [], "history", "existing guidance")

    assert response == "Int('color_Blue') == 1"
    assert "existing guidance" in inner.last_hint
    assert "Controlled repair target" in inner.last_hint
    assert "Int('color_Blue') == 1" in inner.last_hint


def test_controlled_repair_llm_can_disable_wrapper_target_injection():
    class Inner:
        call_count = 0

        def reset_call_count(self):
            pass

        def repair(self, constraints, unsat_core, history_summary, paradigm_hint="", switch_prompt=""):
            self.last_hint = paradigm_hint
            return "Int('color_Blue') == 1"

    inner = Inner()
    wrapper = ControlledRepairLLM(inner, inject_target=False)
    wrapper.current_puzzle = PuzzleInstance(
        nl_description="test",
        raw_data={
            "controlled_diagnostics": {
                "controlled_correct_constraint": "Int('color_Blue') == 1",
            }
        },
    )

    wrapper.repair([], [], "history", "existing guidance")

    assert inner.last_hint == "existing guidance"


def test_add_controlled_target_memory_stores_replacement_policy():
    metadata = {
        "p1": {
            "controlled_perturbed_key": "color_Blue",
            "controlled_wrong_constraint": "Int('color_Blue') == 2",
            "controlled_correct_constraint": "Int('color_Blue') == 1",
            "controlled_source_clue": "1. The Blue color person lives in house 1.",
        }
    }

    lib = _add_controlled_target_memory(None, metadata)
    paradigms = lib.retrieve(["direct_position"], top_k=1)

    assert paradigms[0].bad_operation == "Int('color_Blue') == 2"
    assert paradigms[0].trigger["replacement_policy"]["target_constraint"] == "Int('color_Blue') == 1"


def test_add_controlled_template_memory_stores_clue_template_policy():
    metadata = {
        "p1": {
            "controlled_perturbed_key": "color_Blue",
            "controlled_wrong_constraint": "Int('color_Blue') == 2",
            "controlled_correct_constraint": "Int('color_Blue') == 1",
            "controlled_source_clue": "1. The Blue color person lives in house 1.",
        }
    }

    lib = _add_controlled_template_memory(None, metadata)
    paradigms = lib.retrieve(
        ["direct_position"],
        unsat_core=["Int('color_Blue') == 2"],
        puzzle_id="p1",
        top_k=1,
    )

    policy = paradigms[0].trigger["replacement_policy"]
    assert policy["kind"] == "direct_position_from_source_clue"
    assert policy["source_clue"] == "1. The Blue color person lives in house 1."
    assert "target_constraint" not in policy


def test_add_controlled_template_memory_stores_relation_policy_kind():
    metadata = {
        "p1": {
            "controlled_perturbed_key": "job_Chef__directly_left__job_Pilot",
            "controlled_perturbation_type": "directly_left",
            "controlled_wrong_constraint": "Int('job_Chef') == Int('job_Pilot') + 1",
            "controlled_correct_constraint": "Int('job_Chef') == Int('job_Pilot') - 1",
            "controlled_source_clue": (
                "1. The Chef job is immediately left of the Pilot job."
            ),
        }
    }

    lib = _add_controlled_template_memory(None, metadata)
    paradigms = lib.retrieve(
        ["directly_left"],
        unsat_core=["Int('job_Chef') == Int('job_Pilot') + 1"],
        puzzle_id="p1",
        top_k=1,
    )

    policy = paradigms[0].trigger["replacement_policy"]
    assert policy["kind"] == "directly_left_from_source_clue"
    assert "directly_left" in paradigms[0].scope
