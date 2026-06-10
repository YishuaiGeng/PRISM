from __future__ import annotations

from prism.core.types import StepType, Trajectory, TrajectoryStep
from prism.offline.error_paradigm_extractor import (
    ErrorParadigmExtractor,
    _repair_hint_for_operation,
    unsat_signature,
)


def _trajectory(step: TrajectoryStep) -> Trajectory:
    return Trajectory(
        puzzle_id="p1",
        puzzle_nl="test",
        temperature=0.0,
        seed=1,
        steps=[step],
        final_result="UNSAT",
        solved=False,
        total_llm_calls=1,
    )


def test_extracts_verified_error_paradigm_from_unsat_core():
    core = ["Int('x') > 5", "Int('x') < 3"]
    step = TrajectoryStep(
        iteration=1,
        action="repair",
        step_type=StepType.CONTRADICTION,
        constraint_added="Int('x') > 5",
        z3_result="UNSAT",
        unsat_core=core,
    )

    paradigms = ErrorParadigmExtractor().extract([_trajectory(step)])

    assert len(paradigms) == 1
    assert paradigms[0].unsat_signature == unsat_signature(core)
    assert paradigms[0].bad_operation == "Int('x') > 5"
    assert paradigms[0].support_count == 1


def test_rejects_non_unsat_core():
    step = TrajectoryStep(
        iteration=1,
        action="repair",
        step_type=StepType.CONTRADICTION,
        z3_result="UNSAT",
        unsat_core=["Int('x') > 5"],
    )

    assert ErrorParadigmExtractor().extract([_trajectory(step)]) == []


def test_min_support_filters_singletons():
    core = ["Int('x') > 5", "Int('x') < 3"]
    step = TrajectoryStep(
        iteration=1,
        action="repair",
        step_type=StepType.CONTRADICTION,
        z3_result="UNSAT",
        unsat_core=core,
    )

    assert ErrorParadigmExtractor(min_support=2).extract([_trajectory(step)]) == []


def test_repair_hint_for_or_relation_recommends_oriented_relation():
    hint = _repair_hint_for_operation(
        "Or(Int('house1_color') == Int('house2_color') - 1, "
        "Int('house1_color') == Int('house2_color') + 1)"
    )

    assert "Do not use a broad symmetric Or" in hint
    assert "directly-left/right" in hint


def test_repair_hint_for_plus_one_mentions_direction():
    hint = _repair_hint_for_operation("Int('house1_job') == Int('house2_job') + 1")

    assert "Verify the direction" in hint
    assert "directly left" in hint
    assert "directly right" in hint


def test_scope_includes_relation_specific_tags():
    core = [
        "Int('color_Red') == Int('color_Blue') + 1",
        "Int('color_Red') < Int('color_Blue')",
    ]
    step = TrajectoryStep(
        iteration=1,
        action="repair",
        step_type=StepType.CONTRADICTION,
        constraint_added="Int('color_Red') == Int('color_Blue') + 1",
        z3_result="UNSAT",
        unsat_core=core,
    )

    paradigms = ErrorParadigmExtractor().extract([_trajectory(step)])

    assert len(paradigms) == 1
    assert "directly_right" in paradigms[0].scope
    assert "somewhere_left" in paradigms[0].scope


def test_extracts_typed_direct_position_template_from_trace_record():
    record = {
        "puzzle_id": "p1",
        "puzzle": "Clues:\n1. The Blue color person lives in house 1.",
        "steps": [
            {
                "action": "repair",
                "z3_result": "SAT",
                "old_constraint": "Int('color_Blue') == 2",
                "repair_expression": "Int('color_Blue') == 1",
                "unsat_core": ["Int('color_Blue') == 2", "Int('color_Red') == 2"],
            }
        ],
    }

    paradigms = ErrorParadigmExtractor().extract_from_trace_records([record])

    assert len(paradigms) == 1
    policy = paradigms[0].trigger["replacement_policy"]
    assert policy["kind"] == "direct_position_from_source_clue"
    assert "source_clue" not in policy
    assert "puzzle_id" not in policy
    assert paradigms[0].bad_operation == "Int('color_Blue') == 2"


def test_extracts_typed_relation_template_from_trace_record():
    record = {
        "puzzle_id": "p1",
        "controlled_source_clue": "1. The Chef job is immediately left of the Pilot job.",
        "steps": [
            {
                "action": "repair",
                "z3_result": "SAT",
                "old_constraint": "Int('job_Chef') == Int('job_Pilot') + 1",
                "repair_expression": "Int('job_Chef') == Int('job_Pilot') - 1",
                "unsat_core": [
                    "Int('job_Chef') == Int('job_Pilot') + 1",
                    "And(Int('job_Chef') >= 1, Int('job_Chef') <= 3)",
                ],
            }
        ],
    }

    paradigms = ErrorParadigmExtractor().extract_from_trace_records([record])

    assert len(paradigms) == 1
    policy = paradigms[0].trigger["replacement_policy"]
    assert policy["kind"] == "directly_left_from_source_clue"
    assert "source_clue" not in policy
    assert "directly_right" in paradigms[0].scope
    assert "directly_left" in paradigms[0].scope


def test_trace_mining_can_keep_instance_specific_policy():
    record = {
        "puzzle_id": "p1",
        "controlled_source_clue": "1. The Chef job is immediately left of the Pilot job.",
        "steps": [
            {
                "action": "repair",
                "z3_result": "SAT",
                "old_constraint": "Int('job_Chef') == Int('job_Pilot') + 1",
                "repair_expression": "Int('job_Chef') == Int('job_Pilot') - 1",
            }
        ],
    }

    paradigms = ErrorParadigmExtractor().extract_from_trace_records(
        [record],
        instance_specific=True,
    )

    assert paradigms[0].trigger["replacement_policy"]["puzzle_id"] == "p1"
    assert paradigms[0].trigger["replacement_policy"]["source_clue"] == (
        "1. The Chef job is immediately left of the Pilot job."
    )
