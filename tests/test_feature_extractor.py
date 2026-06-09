"""Tests for FeatureExtractor — lexical constraint-type tag extraction."""

from __future__ import annotations

import pytest

from prism.core.types import SolverState
from prism.online.feature_extractor import FeatureExtractor


@pytest.fixture
def extractor():
    return FeatureExtractor()


def _make_state(constraints: list[str], unsat_core: list[str] | None = None) -> SolverState:
    return SolverState(
        puzzle_id="test",
        constraints=constraints,
        unsat_core=unsat_core,
        z3_result="UNSAT" if unsat_core else "SAT",
    )


# --------------------------------------------------------------------------- #
# extract() — full state                                                         #
# --------------------------------------------------------------------------- #

class TestExtract:

    def test_distinct_yields_all_different(self, extractor):
        state = _make_state(["Distinct(Int('x'), Int('y'), Int('z'))"])
        types = extractor.extract(state)
        assert "all_different" in types

    def test_adjacent_keyword(self, extractor):
        state = _make_state(["immediately left of house 3"])
        types = extractor.extract(state)
        assert "adjacent" in types

    def test_left_of_yields_relative_position(self, extractor):
        state = _make_state(["Int('brit') left of Int('swede')"])
        types = extractor.extract(state)
        assert "relative_position" in types

    def test_direct_position_number_assignment(self, extractor):
        state = _make_state(["Int('norwegian') == 1"])
        types = extractor.extract(state)
        assert "direct_position" in types

    def test_inequality_yields_exclusion(self, extractor):
        state = _make_state(["Int('x') != Int('y')"])
        types = extractor.extract(state)
        assert "exclusion" in types

    def test_ordering_less_than(self, extractor):
        state = _make_state(["Int('x') < Int('y')"])
        types = extractor.extract(state)
        assert "ordering" in types

    def test_ordering_greater_than(self, extractor):
        state = _make_state(["Int('x') > 3"])
        types = extractor.extract(state)
        assert "ordering" in types

    def test_and_yields_logical_implication(self, extractor):
        state = _make_state(["And(Int('x') > 0, Int('y') > 0)"])
        types = extractor.extract(state)
        assert "logical_implication" in types

    def test_unknown_fallback(self, extractor):
        state = _make_state(["some_unrecognized_constraint_string_xyz"])
        types = extractor.extract(state)
        assert types == ["unknown"]

    def test_empty_constraints_returns_unknown(self, extractor):
        state = _make_state([])
        types = extractor.extract(state)
        assert types == ["unknown"]

    def test_result_is_sorted(self, extractor):
        state = _make_state([
            "Distinct(Int('a'), Int('b'))",
            "Int('a') < Int('b')",
        ])
        types = extractor.extract(state)
        assert types == sorted(types)

    def test_result_is_deduplicated(self, extractor):
        state = _make_state([
            "Distinct(Int('a'), Int('b'))",
            "Distinct(Int('c'), Int('d'))",
        ])
        types = extractor.extract(state)
        assert len(types) == len(set(types))

    def test_uses_unsat_core_when_available(self, extractor):
        """When unsat_core is set, extraction focuses on core constraints only."""
        state = _make_state(
            constraints=["Distinct(Int('a'), Int('b'))", "Int('x') == 1"],
            unsat_core=["Int('x') == 1"],  # only direct_position in core
        )
        types = extractor.extract(state)
        assert "direct_position" in types

    def test_fallback_to_all_constraints_when_no_core(self, extractor):
        state = _make_state(
            constraints=["Distinct(Int('a'), Int('b'))"],
            unsat_core=None,
        )
        types = extractor.extract(state)
        assert "all_different" in types

    def test_relation_specific_tags_from_z3_expression(self, extractor):
        state = _make_state(["Int('color_Red') == Int('color_Blue') - 1"])
        types = extractor.extract(state)

        assert "directly_left" in types

    def test_unsat_core_adds_domain_candidate_mismatch(self, extractor):
        state = _make_state(
            constraints=[],
            unsat_core=[
                "And(Int('color_Green') >= 1, Int('color_Green') <= 3)",
                "Int('color_Green') == 4",
            ],
        )
        types = extractor.extract(state)

        assert "domain_candidate_mismatch" in types

    def test_unsat_core_adds_distinct_group_mismatch(self, extractor):
        state = _make_state(
            constraints=[],
            unsat_core=[
                "And(Int('color_A') >= 1, Int('color_A') <= 3)",
                "And(Int('color_B') >= 1, Int('color_B') <= 3)",
                "And(Int('color_C') >= 1, Int('color_C') <= 3)",
                "And(Int('color_D') >= 1, Int('color_D') <= 3)",
                "Distinct(Int('color_A'), Int('color_B'), Int('color_C'), Int('color_D'))",
            ],
        )
        types = extractor.extract(state)

        assert "distinct_group_mismatch" in types


# --------------------------------------------------------------------------- #
# classify_constraint_type() — single constraint                                 #
# --------------------------------------------------------------------------- #

class TestClassifySingle:

    def test_distinct_returns_all_different(self, extractor):
        assert extractor.classify_constraint_type("Distinct(Int('x'))") == "all_different"

    def test_immediately_returns_adjacent(self, extractor):
        assert extractor.classify_constraint_type("immediately right of") == "adjacent"

    def test_empty_string_returns_unknown(self, extractor):
        assert extractor.classify_constraint_type("") == "unknown"

    def test_unrecognized_returns_unknown(self, extractor):
        assert extractor.classify_constraint_type("some_mystery_expr") == "unknown"
