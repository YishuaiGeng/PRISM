from __future__ import annotations

import json

from scripts.add_zebra_domains_to_puzzle_text import _with_domain_section


def test_with_domain_section_adds_backtick_candidate_values_before_clues():
    puzzle = "There are 2 houses.\n\nClues:\n1. Blue is in house 1."
    solution = {"color_Blue": "1", "color_Red": "2", "drink_Wine": "1"}

    enriched = _with_domain_section(puzzle, solution)

    assert "Candidate values:" in enriched
    assert "- color: `Blue`, `Red`" in enriched
    assert "- drink: `Wine`" in enriched
    assert enriched.index("Candidate values:") < enriched.index("Clues:")


def test_with_domain_section_is_idempotent():
    puzzle = "There are 2 houses.\n\nCandidate values:\n- color: `Blue`\n\nClues:"

    assert _with_domain_section(puzzle, {"color_Blue": "1"}) == puzzle
