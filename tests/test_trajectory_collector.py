from __future__ import annotations

from prism.core.types import PuzzleInstance
from prism.offline.trajectory_collector import TrajectoryCollector


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
