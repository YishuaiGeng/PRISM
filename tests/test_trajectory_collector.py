from __future__ import annotations

from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance
from prism.offline.trajectory_collector import (
    TrajectoryCollector,
    _compute_domain_sizes,
    _infer_value_range,
)


def test_model_within_puzzle_domain_rejects_out_of_range_assignment():
    puzzle = PuzzleInstance(
        nl_description="There are 3 houses.",
        size="3x4",
    )
    assert TrajectoryCollector._model_within_puzzle_domain(
        puzzle,
        {"house2_pet": "4", "_prism_track_1": "True"},
    ) is False


def test_model_within_puzzle_domain_accepts_in_range_assignment():
    puzzle = PuzzleInstance(
        nl_description="There are 3 houses.",
        size="3x4",
    )
    assert TrajectoryCollector._model_within_puzzle_domain(
        puzzle,
        {"house2_pet": "3", "house1_color": "1"},
    ) is True


def test_domain_sizes_populated_after_repair(mock_llm_client):
    """domain_sizes_before and domain_sizes_after should be non-empty dicts."""
    puzzle = PuzzleInstance(
        puzzle_id="test-001",
        nl_description=(
            "There are 3 houses numbered 1 to 3. Each house has 2 attributes.\n"
            "1. The Red color person lives in house 1.\n"
            "2. The Blue color person is immediately left of the Green color person.\n"
            "Candidate values:\n- color: Red, Blue, Green\n- pet: Cat, Dog, Fish"
        ),
        constraints_nl=[
            "The Red color person lives in house 1.",
            "The Blue color person is immediately left of the Green color person.",
        ],
        solution={"color_Red": "1", "color_Blue": "2", "color_Green": "3",
                  "pet_Cat": "1", "pet_Dog": "2", "pet_Fish": "3"},
        size="3x2",
        domain="zebralogic",
        raw_data={},
    )

    collector = TrajectoryCollector(llm_client=mock_llm_client, max_repair_rounds=2)
    trajectories = collector.collect([puzzle], n_runs=1, temperature=0.0)

    assert len(trajectories) == 1
    traj = trajectories[0]
    # Every non-translate step that enters the repair loop should have domain sizes
    repair_steps = [s for s in traj.steps if s.action == "repair"]
    if repair_steps:
        for step in repair_steps:
            assert isinstance(step.domain_sizes_before, dict), "domain_sizes_before must be a dict"
            assert isinstance(step.domain_sizes_after, dict), "domain_sizes_after must be a dict"
            # Sizes must be positive integers
            for var, size in step.domain_sizes_before.items():
                assert isinstance(size, int) and size >= 1, f"Bad size for {var}: {size}"
            for var, size in step.domain_sizes_after.items():
                assert isinstance(size, int) and size >= 1, f"Bad size for {var}: {size}"


def test_domain_sizes_decrease_after_constraint(mock_llm_client):
    """After adding a direct-position constraint, that variable's domain should be size 1."""
    solver = Z3SolverWrapper()
    # Add domain bounds for a 3-house puzzle with variable color_Red
    solver.add_constraint("And(Int('color_Red') >= 1, Int('color_Red') <= 3)")
    solver.add_constraint("And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)")
    solver.add_constraint("And(Int('color_Green') >= 1, Int('color_Green') <= 3)")
    solver.add_constraint("Distinct(Int('color_Red'), Int('color_Blue'), Int('color_Green'))")
    sizes_before = _compute_domain_sizes(solver, n_houses=3)
    # Each variable has domain [1,2,3] = 3 candidates
    assert sizes_before.get("color_Red") == 3
    assert sizes_before.get("color_Blue") == 3

    solver.add_constraint("Int('color_Red') == 1")
    solver.check()
    sizes_after = _compute_domain_sizes(solver, n_houses=3)
    # color_Red is now pinned to 1
    assert sizes_after.get("color_Red") == 1


def test_compute_domain_sizes_with_explicit_value_range():
    """value_range overrides n_houses; 0/1 selection flags are trackable."""
    solver = Z3SolverWrapper()
    solver.add_constraint("And(Int('sel_A') >= 0, Int('sel_A') <= 1)")
    solver.add_constraint("And(Int('sel_B') >= 0, Int('sel_B') <= 1)")
    sizes = _compute_domain_sizes(solver, value_range=(0, 1))
    assert sizes.get("sel_A") == 2

    solver.add_constraint("Int('sel_A') == 1")
    solver.check()
    sizes = _compute_domain_sizes(solver, value_range=(0, 1))
    assert sizes.get("sel_A") == 1


def test_compute_domain_sizes_no_range_returns_empty():
    solver = Z3SolverWrapper()
    solver.add_constraint("Int('x') >= 1")
    assert _compute_domain_sizes(solver) == {}
    assert _compute_domain_sizes(solver, value_range=(3, 1)) == {}


def test_infer_value_range_from_ordering_constraints():
    constraints = [
        "And(Int('slot_Ann') >= 1, Int('slot_Ann') <= 6)",
        "Distinct(Int('slot_Ann'), Int('slot_Bob'))",
        "Int('slot_Ann') < Int('slot_Bob')",
    ]
    assert _infer_value_range(constraints) == (1, 6)


def test_infer_value_range_ignores_quoted_names_and_negatives():
    # The 1 in 'O1' is inside quotes and must not count as a literal;
    # the -1 offset must not drag the lower bound below zero.
    constraints = [
        "Int('O1') == Int('O2') - 1",
        "And(Int('O2') >= 0, Int('O2') <= 5)",
    ]
    assert _infer_value_range(constraints) == (0, 5)


def test_infer_value_range_caps_outlier_span():
    constraints = ["And(Int('year_X') >= 1, Int('year_X') <= 1991)"]
    lo, hi = _infer_value_range(constraints)
    assert lo == 1
    assert hi - lo + 1 == 12  # capped at _MAX_INFERRED_RANGE_WIDTH


def test_infer_value_range_none_when_no_usable_literals():
    assert _infer_value_range(["Int('a') == Int('b')"]) is None
    assert _infer_value_range([]) is None
    # A single distinct literal gives no span to probe.
    assert _infer_value_range(["Int('a') == 3", "Int('b') == 3"]) is None
