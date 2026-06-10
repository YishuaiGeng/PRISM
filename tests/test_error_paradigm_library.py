from __future__ import annotations

from datetime import datetime, timezone

import pytest

from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.schema import ErrorParadigm


def make_error_paradigm(
    *,
    pid: str = "E-001",
    scope: list[str] | None = None,
    confidence: float = 0.8,
    signature: str = "abc123",
) -> ErrorParadigm:
    return ErrorParadigm(
        id=pid,
        name="avoid_bad_bound",
        trigger={"constraint_types": scope or ["integer_bound"]},
        bad_operation="Int('x') > 5",
        unsat_signature=signature,
        avoid_instruction="Do not keep the contradictory lower bound.",
        repair_hint="Relax the lower bound or inspect the paired upper bound.",
        scope=scope or ["integer_bound"],
        confidence=confidence,
        support_count=2,
        source_cluster=0,
        created_at=datetime.now(tz=timezone.utc),
    )


def test_add_and_get_all():
    with ErrorParadigmLibrary(":memory:") as lib:
        p = make_error_paradigm()
        assert lib.add(p) is True
        loaded = lib.get_all()
        assert len(loaded) == 1
        assert loaded[0].id == p.id
        assert loaded[0].bad_operation == p.bad_operation


def test_retrieve_prefers_scope_and_signature_match():
    with ErrorParadigmLibrary(":memory:") as lib:
        weak = make_error_paradigm(pid="weak", scope=["adjacent"], confidence=0.9, signature="other")
        strong = make_error_paradigm(pid="strong", scope=["integer_bound"], confidence=0.6, signature="sig")
        lib.add(weak)
        lib.add(strong)

        results = lib.retrieve(["integer_bound"], unsat_signature="sig", top_k=1)
        assert results[0].id == "strong"


def test_retrieve_uses_relation_scope_inferred_from_bad_operation():
    with ErrorParadigmLibrary(":memory:") as lib:
        generic = make_error_paradigm(
            pid="generic",
            scope=["logical_implication"],
            confidence=1.0,
            signature="other",
        )
        specific = make_error_paradigm(
            pid="specific",
            scope=["logical_implication"],
            confidence=0.8,
            signature="other",
        ).model_copy(update={
            "bad_operation": "Int('color_Red') == Int('color_Blue') - 1",
        })
        lib.add(generic)
        lib.add(specific)

        results = lib.retrieve(["directly_left"], top_k=1)

        assert results[0].id == "specific"
        assert "directly_left" in results[0].scope


def test_retrieve_prefers_bad_operation_in_current_unsat_core():
    with ErrorParadigmLibrary(":memory:") as lib:
        first = make_error_paradigm(
            pid="first",
            scope=["direct_position"],
            confidence=1.0,
            signature="other",
        ).model_copy(update={
            "bad_operation": "Int('color_Green') == 1",
        })
        exact = make_error_paradigm(
            pid="exact",
            scope=["direct_position"],
            confidence=0.5,
            signature="other",
        ).model_copy(update={
            "bad_operation": "Int('pet_Rabbit') == 2",
        })
        lib.add(first)
        lib.add(exact)

        results = lib.retrieve(
            ["direct_position"],
            unsat_core=["Int('pet_Rabbit') == 2", "Distinct(Int('pet_Rabbit'), Int('pet_Bird'))"],
            top_k=1,
        )

        assert results[0].id == "exact"


def test_retrieve_filters_to_exact_replacement_policy_matches():
    with ErrorParadigmLibrary(":memory:") as lib:
        exact = make_error_paradigm(
            pid="exact",
            scope=["direct_position"],
            confidence=0.5,
        ).model_copy(update={
            "bad_operation": "Int('pet_Rabbit') == 2",
            "trigger": {
                "constraint_types": ["direct_position"],
                "replacement_policy": {"target_constraint": "Int('pet_Rabbit') == 1"},
            },
        })
        distractor = make_error_paradigm(
            pid="distractor",
            scope=["direct_position"],
            confidence=1.0,
        ).model_copy(update={
            "bad_operation": "Int('color_Green') == 1",
            "trigger": {
                "constraint_types": ["direct_position"],
                "replacement_policy": {"target_constraint": "Int('color_Green') == 3"},
            },
        })
        lib.add(distractor)
        lib.add(exact)

        results = lib.retrieve(
            ["direct_position"],
            unsat_core=["Int('pet_Rabbit') == 2"],
            top_k=2,
        )

        assert [p.id for p in results] == ["exact"]


def test_retrieve_filters_instance_specific_replacement_policy_by_puzzle_id():
    with ErrorParadigmLibrary(":memory:") as lib:
        wrong_puzzle = make_error_paradigm(
            pid="wrong-puzzle",
            scope=["direct_position"],
            confidence=1.0,
        ).model_copy(update={
            "bad_operation": "Int('color_White') == 3",
            "trigger": {
                "constraint_types": ["direct_position"],
                "replacement_policy": {
                    "target_constraint": "Int('color_White') == 2",
                    "puzzle_id": "other",
                },
            },
        })
        right_puzzle = make_error_paradigm(
            pid="right-puzzle",
            scope=["direct_position"],
            confidence=0.5,
        ).model_copy(update={
            "bad_operation": "Int('color_Red') == 3",
            "trigger": {
                "constraint_types": ["direct_position"],
                "replacement_policy": {
                    "target_constraint": "Int('color_Red') == 2",
                    "puzzle_id": "current",
                },
            },
        })
        lib.add(wrong_puzzle)
        lib.add(right_puzzle)

        results = lib.retrieve(
            ["direct_position"],
            unsat_core=["Int('color_White') == 3", "Int('color_Red') == 3"],
            puzzle_id="current",
            top_k=2,
        )

        assert [p.id for p in results] == ["right-puzzle"]


def test_stats_empty_and_populated():
    with ErrorParadigmLibrary(":memory:") as lib:
        assert lib.stats()["total"] == 0
        lib.add(make_error_paradigm(scope=["a", "b"], confidence=0.5))
        stats = lib.stats()
        assert stats["total"] == 1
        assert stats["avg_confidence"] == pytest.approx(0.5)
        assert stats["scope_distribution"] == {"a": 1, "b": 1}


def test_json_roundtrip(tmp_path):
    json_path = tmp_path / "errors.json"
    with ErrorParadigmLibrary(":memory:") as lib:
        lib.add(make_error_paradigm(pid="rt"))
        lib.save_json(str(json_path))

    with ErrorParadigmLibrary(":memory:") as fresh:
        assert fresh.load_json(str(json_path)) == 1
        loaded = fresh.get_all()
        assert len(loaded) == 1
        assert loaded[0].id == "rt"
