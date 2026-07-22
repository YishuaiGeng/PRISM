from __future__ import annotations

from prism.core.types import PuzzleInstance
from scripts.shared.generate_zebra_jsonl import _parse_specs, _puzzle_to_record


def test_parse_specs_accepts_comma_separated_sizes():
    specs = _parse_specs("2:3x3:medium,4:3*4:easy")

    assert specs == [(2, 3, 3, "medium"), (4, 3, 4, "easy")]


def test_puzzle_to_record_can_insert_domain_section():
    puzzle = PuzzleInstance(
        puzzle_id="p1",
        nl_description="There are 2 houses.\n\nClues:\n1. The Blue color person lives in house 1.",
        solution={"color_Blue": "1", "color_Red": "2"},
        size="2x2",
        difficulty="easy",
        raw_data={"conflict_count": 3},
    )

    record = _puzzle_to_record(puzzle, domain_explicit=True)

    assert record["id"] == "p1"
    assert record["size"] == "2x2"
    assert record["solution"] == {"color_Blue": "1", "color_Red": "2"}
    assert "Candidate values:" in record["puzzle"]
    assert "- color: `Blue`, `Red`" in record["puzzle"]
    assert record["difficulty"] == "easy"
    assert record["conflict_count"] == 3
