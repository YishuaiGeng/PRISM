from __future__ import annotations

import json

from scripts.summarize_trace_jsonl import _summarize


def test_summarize_trace_jsonl_counts_repair_diagnostics(tmp_path):
    path = tmp_path / "trace.jsonl"
    records = [
        {
            "puzzle_id": "p1",
            "solved": False,
            "llm_calls": 3,
            "repair_rounds": 2,
            "final_z3_result": "UNSAT",
            "memory_eligible": True,
            "steps": [
                {"action": "invalid_model_retranslate"},
                {
                    "action": "repair_rejected",
                    "repair_rejection_reason": "schema_shrinking_distinct",
                    "error_guidance_triggered": True,
                    "positive_guidance_triggered": False,
                    "visible_schema_key_count": 7,
                    "missing_visible_schema_keys": ["color_Blue", "drink_Beer"],
                    "dropped_invisible_schema_constraints": ["Int('color_Blue') == 2"],
                },
            ],
        },
        {
            "puzzle_id": "p2",
            "solved": True,
            "llm_calls": 1,
            "repair_rounds": 1,
            "final_z3_result": "SAT",
            "memory_eligible": True,
            "steps": [
                {
                    "action": "repair",
                    "z3_result": "SAT",
                    "old_constraint": "Distinct(Int('a'), Int('b'))",
                    "new_constraint": "Int('a') == Int('b') - 1",
                    "error_guidance_triggered": True,
                    "positive_guidance_triggered": True,
                }
            ],
        },
    ]
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")

    summary = _summarize(path)

    assert summary["accuracy"] == "1/2"
    assert summary["avg_llm_calls"] == "2.00"
    assert summary["memory_eligible"] == 2
    assert summary["repair_steps"] == 1
    assert summary["repair_sat_steps"] == 1
    assert summary["repair_rejected_steps"] == 1
    assert summary["repair_rejection_reasons"] == "schema_shrinking_distinct=1"
    assert summary["schema_replacements"] == 1
    assert summary["error_guidance_steps"] == 2
    assert summary["positive_guidance_steps"] == 1
    assert summary["avg_visible_schema_keys"] == "7.00"
    assert summary["avg_missing_visible_schema_keys"] == "2.00"
    assert summary["avg_dropped_invisible_constraints"] == "1.00"
