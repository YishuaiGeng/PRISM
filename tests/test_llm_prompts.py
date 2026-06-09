from __future__ import annotations

from prism.core.llm_client import (
    _build_translation_normalization_prompt_v2,
    _build_retranslation_prompt_v2,
    _build_translation_prompt_v2,
)


def test_translation_prompt_includes_semantic_schema_guidance():
    prompt = _build_translation_prompt_v2(
        "There are two houses.",
        "color_Blue, drink_Wine",
    )

    assert "Expected variable-key schema" in prompt
    assert "color_Blue" in prompt
    assert "drink_Wine" in prompt
    assert "Do not encode answers as house-slot variables" in prompt
    assert "house1_color" in prompt
    assert "answer values" in prompt
    assert "Use only these visible schema keys" in prompt
    assert "do not invent missing candidate values" in prompt


def test_retranslation_prompt_includes_semantic_schema_guidance():
    prompt = _build_retranslation_prompt_v2(
        "There are two houses.",
        ["Int('house1_color') == 1"],
        "schema mismatch",
        "color_Blue, drink_Wine",
    )

    assert "Expected variable-key schema" in prompt
    assert "color_Blue" in prompt
    assert "drink_Wine" in prompt
    assert "not house-slot variables" in prompt
    assert "house1_color" in prompt


def test_translation_normalization_prompt_includes_cleanup_rules():
    prompt = _build_translation_normalization_prompt_v2(
        "There are two houses.",
        ["Int('house1_color') == 1"],
        "color_Blue, color_Red",
        "schema cleanup",
    )

    assert "cleaning up a draft Z3 translation" in prompt
    assert "Draft constraints" in prompt
    assert "Int('house1_color') == 1" in prompt
    assert "Expected variable-key schema" in prompt
    assert "color_Blue" in prompt
    assert "Do not invent answer assignments" in prompt
    assert "Add domain bounds" in prompt
    assert "not a new translation" in prompt
    assert "do not reverse" in prompt
