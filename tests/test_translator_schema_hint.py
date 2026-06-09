from __future__ import annotations

from prism.core.model_validation import (
    model_category_assignments_are_permutations,
    puzzle_schema_key_hint,
    visible_schema_keys,
)
from prism.core.translator import NLToZ3Translator
from prism.core.types import PuzzleInstance


class _SchemaRecordingLLM:
    def __init__(self) -> None:
        self.translate_schema_hint = ""
        self.retranslate_schema_hint = ""
        self.normalize_schema_hint = ""

    def translate(self, puzzle_nl: str, schema_hint: str = "") -> str:
        self.translate_schema_hint = schema_hint
        return "```python\nInt('color_Blue') == 1\n```"

    def retranslate(
        self,
        puzzle_nl: str,
        failed_constraints,
        error_ctx: str,
        schema_hint: str = "",
    ) -> str:
        self.retranslate_schema_hint = schema_hint
        return "```python\nInt('color_Blue') == 1\n```"

    def normalize_translation(
        self,
        puzzle_nl: str,
        draft_constraints,
        schema_hint: str = "",
        error_ctx: str = "",
    ) -> str:
        self.normalize_schema_hint = schema_hint
        self.normalize_draft_constraints = list(draft_constraints)
        return "```python\nInt('color_Blue') == 1\nDistinct(Int('color_Blue'), Int('color_Red'))\n```"


class _LegacyLLM:
    def translate(self, puzzle_nl: str) -> str:
        return "```python\nInt('x') == 1\n```"

    def retranslate(self, puzzle_nl: str, failed_constraints, error_ctx: str) -> str:
        return "```python\nInt('x') == 1\n```"


def test_translate_uses_visible_puzzle_schema_without_solution_values():
    llm = _SchemaRecordingLLM()
    translator = NLToZ3Translator(llm)
    puzzle = PuzzleInstance(
        nl_description=(
            "Each house has a unique attribute for each characteristic:\n"
            "- House colors: `blue`, `green`\n"
            "- Everyone drinks: `wine`, `water`"
        ),
        solution={"color_Red": "2", "drink_Beer": "1"},
    )

    constraints = translator.translate(puzzle)

    assert constraints == ["Int('color_Blue') == 1"]
    assert "color_Blue" in llm.translate_schema_hint
    assert "drink_Wine" in llm.translate_schema_hint
    assert "color_Red" not in llm.translate_schema_hint
    assert "drink_Beer" not in llm.translate_schema_hint
    assert "2" not in llm.translate_schema_hint
    assert "1" not in llm.translate_schema_hint


def test_visible_schema_keys_include_clue_values_without_oracle_values():
    puzzle = PuzzleInstance(
        nl_description=(
            "There are 3 houses.\n"
            "Clues:\n"
            "1. The Chef job is immediately left of the Pilot job.\n"
            "2. The Purple color person lives in house 1.\n"
            "3. The Wine drink person lives in house 2."
        ),
        solution={"color_Blue": "3", "job_Chef": "1"},
    )

    keys = visible_schema_keys(puzzle)
    hint = puzzle_schema_key_hint(puzzle)

    assert {"job_Chef", "job_Pilot", "color_Purple", "drink_Wine"} <= keys
    assert "color_Blue" not in hint
    assert "3" not in hint


def test_validate_model_rejects_duplicate_house_assignments_within_category():
    puzzle = PuzzleInstance(
        nl_description=(
            "Each house has a unique attribute for each characteristic:\n"
            "- Everyone drinks: `tea`, `water`, `wine`"
        ),
        size="3x3",
        solution={"drink_Tea": "1", "drink_Water": "2", "drink_Wine": "3"},
    )
    solution = {"drink_Tea": "1", "drink_Water": "1", "drink_Wine": "3"}

    assert model_category_assignments_are_permutations(puzzle, solution) is False


def test_validate_model_does_not_require_partial_visible_category_permutation():
    puzzle = PuzzleInstance(
        nl_description="There are 3 houses. The Tea drink person lives in house 1.",
        size="3x3",
        solution={"drink_Tea": "1", "drink_Water": "2", "drink_Wine": "3"},
    )
    solution = {"drink_Tea": "1", "drink_Water": "1", "drink_Wine": "3"}

    assert model_category_assignments_are_permutations(puzzle, solution) is True


def test_translate_filters_invisible_semantic_variables_when_schema_is_visible():
    llm = _SchemaRecordingLLM()
    llm.translate = lambda puzzle_nl, schema_hint="": (  # type: ignore[method-assign]
        "```python\n"
        "Int('color_Purple') == 1\n"
        "Int('color_Blue') == 2\n"
        "Int('house1_color') == 1\n"
        "```"
    )
    translator = NLToZ3Translator(llm)
    puzzle = PuzzleInstance(
        nl_description="The Purple color person lives in house 1.",
        solution={"color_Purple": "1", "color_Blue": "2"},
    )

    constraints = translator.translate(puzzle)

    assert "Int('color_Purple') == 1" in constraints
    assert "Int('house1_color') == 1" in constraints
    assert "Int('color_Blue') == 2" not in constraints
    assert translator.last_diagnostics["visible_schema_key_count"] == 1
    assert translator.last_diagnostics["missing_visible_schema_keys"] == ["color_Blue"]
    assert translator.last_diagnostics["dropped_invisible_schema_constraints"] == [
        "Int('color_Blue') == 2"
    ]


def test_retranslate_uses_visible_puzzle_schema_without_solution_values():
    llm = _SchemaRecordingLLM()
    translator = NLToZ3Translator(llm)
    puzzle = PuzzleInstance(
        nl_description=(
            "Each house has a unique attribute for each characteristic:\n"
            "- House colors: `blue`, `green`\n"
            "- Everyone drinks: `wine`, `water`"
        ),
        solution={"color_Red": "2", "drink_Beer": "1"},
    )

    constraints = translator.retranslate(puzzle, ["Int('bad') == 0"], "bad schema")

    assert constraints == ["Int('color_Blue') == 1"]
    assert "color_Blue" in llm.retranslate_schema_hint
    assert "drink_Wine" in llm.retranslate_schema_hint
    assert "color_Red" not in llm.retranslate_schema_hint
    assert "drink_Beer" not in llm.retranslate_schema_hint
    assert "2" not in llm.retranslate_schema_hint
    assert "1" not in llm.retranslate_schema_hint


def test_solution_key_schema_hint_is_explicit_oracle_mode():
    llm = _SchemaRecordingLLM()
    translator = NLToZ3Translator(llm, schema_hint_mode="solution_keys")
    puzzle = PuzzleInstance(
        nl_description="There are two houses.",
        solution={"color_Blue": "2", "drink_Wine": "1"},
    )

    translator.translate(puzzle)

    assert "color_Blue" in llm.translate_schema_hint
    assert "drink_Wine" in llm.translate_schema_hint
    assert "2" not in llm.translate_schema_hint
    assert "1" not in llm.translate_schema_hint


def test_schema_hint_can_be_disabled():
    llm = _SchemaRecordingLLM()
    translator = NLToZ3Translator(llm, schema_hint_mode="none")
    puzzle = PuzzleInstance(
        nl_description="- House colors: `blue`, `green`",
        solution={"color_Blue": "2"},
    )

    translator.translate(puzzle)

    assert llm.translate_schema_hint == ""


def test_translator_remains_compatible_with_legacy_llm_stubs():
    translator = NLToZ3Translator(_LegacyLLM())
    puzzle = PuzzleInstance(
        nl_description="There is one variable.",
        solution={"x": "1"},
    )

    assert translator.translate(puzzle) == ["Int('x') == 1"]
    assert translator.retranslate(puzzle, [], "retry") == ["Int('x') == 1"]


def test_translate_can_normalize_initial_constraints():
    llm = _SchemaRecordingLLM()
    translator = NLToZ3Translator(llm, schema_hint_mode="solution_keys", normalize_mode="initial")
    puzzle = PuzzleInstance(
        nl_description="There are two houses.",
        solution={"color_Blue": "1", "color_Red": "2"},
    )

    constraints = translator.translate(puzzle)

    assert "Int('color_Blue') == 1" in constraints
    assert "Distinct(Int('color_Blue'), Int('color_Red'))" in constraints
    assert llm.normalize_draft_constraints == ["Int('color_Blue') == 1"]
    assert "color_Red" in llm.normalize_schema_hint


def test_normalize_keeps_original_when_original_scores_better():
    class LLM(_SchemaRecordingLLM):
        def translate(self, puzzle_nl: str, schema_hint: str = "") -> str:
            return (
                "```python\n"
                "Int('color_Blue') == 1\n"
                "Int('color_Red') == 2\n"
                "```"
            )

        def normalize_translation(
            self,
            puzzle_nl: str,
            draft_constraints,
            schema_hint: str = "",
            error_ctx: str = "",
        ) -> str:
            return "```python\nInt('color_Blue') == 2\n```"

    translator = NLToZ3Translator(LLM(), schema_hint_mode="solution_keys", normalize_mode="initial")
    puzzle = PuzzleInstance(
        nl_description="There are two houses.",
        size="2x2",
        solution={"color_Blue": "1", "color_Red": "2"},
    )

    assert translator.translate(puzzle) == [
        "Int('color_Blue') == 1",
        "Int('color_Red') == 2",
    ]


def test_normalize_replaces_original_when_normalized_scores_better():
    class LLM(_SchemaRecordingLLM):
        def translate(self, puzzle_nl: str, schema_hint: str = "") -> str:
            return "```python\nInt('color_Blue') == 1\n```"

        def normalize_translation(
            self,
            puzzle_nl: str,
            draft_constraints,
            schema_hint: str = "",
            error_ctx: str = "",
        ) -> str:
            return (
                "```python\n"
                "Int('color_Blue') == 1\n"
                "Int('color_Red') == 2\n"
                "```"
            )

    translator = NLToZ3Translator(LLM(), schema_hint_mode="solution_keys", normalize_mode="initial")
    puzzle = PuzzleInstance(
        nl_description="There are two houses.",
        size="2x2",
        solution={"color_Blue": "1", "color_Red": "2"},
    )

    assert translator.translate(puzzle) == [
        "Int('color_Blue') == 1",
        "Int('color_Red') == 2",
    ]


def test_normalize_rejects_semantic_relation_rewrite_even_if_score_improves():
    class LLM(_SchemaRecordingLLM):
        def translate(self, puzzle_nl: str, schema_hint: str = "") -> str:
            return "```python\nInt('pet_Cat') == Int('pet_Dog') - 1\n```"

        def normalize_translation(
            self,
            puzzle_nl: str,
            draft_constraints,
            schema_hint: str = "",
            error_ctx: str = "",
        ) -> str:
            return (
                "```python\n"
                "And(Int('pet_Cat') >= 1, Int('pet_Cat') <= 2)\n"
                "And(Int('pet_Dog') >= 1, Int('pet_Dog') <= 2)\n"
                "Distinct(Int('pet_Cat'), Int('pet_Dog'))\n"
                "Int('pet_Dog') == Int('pet_Cat') - 1\n"
                "```"
            )

    translator = NLToZ3Translator(LLM(), normalize_mode="initial")
    puzzle = PuzzleInstance(
        nl_description=(
            "There are 2 houses.\n"
            "1. The Cat pet is immediately left of the Dog pet."
        ),
        size="2x2",
        solution={"pet_Cat": "1", "pet_Dog": "2"},
    )

    assert translator.translate(puzzle) == ["Int('pet_Cat') == Int('pet_Dog') - 1"]
    assert translator.last_diagnostics["translation_normalization_attempted"] is True
    assert translator.last_diagnostics["translation_normalization_selected"] is False
    assert (
        translator.last_diagnostics["translation_normalization_reject_reason"]
        == "changed_original_semantic_constraints"
    )


def test_normalize_treats_single_argument_and_as_same_semantic_relation():
    class LLM(_SchemaRecordingLLM):
        def translate(self, puzzle_nl: str, schema_hint: str = "") -> str:
            return "```python\nAnd(Int('drink_Tea') == 1)\n```"

        def normalize_translation(
            self,
            puzzle_nl: str,
            draft_constraints,
            schema_hint: str = "",
            error_ctx: str = "",
        ) -> str:
            return (
                "```python\n"
                "And(Int('drink_Tea') >= 1, Int('drink_Tea') <= 2)\n"
                "And(Int('drink_Water') >= 1, Int('drink_Water') <= 2)\n"
                "Distinct(Int('drink_Tea'), Int('drink_Water'))\n"
                "Int('drink_Tea') == 1\n"
                "Int('drink_Water') == 2\n"
                "```"
            )

    translator = NLToZ3Translator(LLM(), schema_hint_mode="solution_keys", normalize_mode="initial")
    puzzle = PuzzleInstance(
        nl_description="There are 2 houses. The Tea drink person lives in house 1.",
        size="2x2",
        solution={"drink_Tea": "1", "drink_Water": "2"},
    )

    constraints = translator.translate(puzzle)

    assert "Int('drink_Tea') == 1" in constraints
    assert translator.last_diagnostics["translation_normalization_selected"] is True


def test_normalize_initial_does_not_normalize_retranslation():
    llm = _SchemaRecordingLLM()
    translator = NLToZ3Translator(llm, schema_hint_mode="solution_keys", normalize_mode="initial")
    puzzle = PuzzleInstance(
        nl_description="There are two houses.",
        solution={"color_Blue": "1", "color_Red": "2"},
    )

    translator.retranslate(puzzle, ["Int('bad') == 0"], "retry")

    assert llm.normalize_schema_hint == ""
