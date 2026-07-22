from __future__ import annotations

import json

from scripts.prism.run_clue_coverage_replay import _iter_replay_rows


def test_clue_coverage_replay_reports_improved_fixed_state(tmp_path):
    trace = tmp_path / "trace.jsonl"
    record = {
        "puzzle_id": "p1",
        "domain": "2x2",
        "ground_truth": "color_Blue=1|color_Red=2",
        "steps": [
            {
                "action": "repair",
                "source": "clue_coverage",
                "constraints_before": [
                    "And(Int('color_Blue') >= 1, Int('color_Blue') <= 2)",
                    "And(Int('color_Red') >= 1, Int('color_Red') <= 2)",
                    "Distinct(Int('color_Blue'), Int('color_Red'))",
                    "Int('color_Blue') == Int('color_Red') + 1",
                ],
                "clue_coverage_repairs": [
                    {
                        "offending_constraint": "Int('color_Blue') == Int('color_Red') + 1",
                        "expected_constraint": "Int('color_Blue') == Int('color_Red') - 1",
                    }
                ],
            }
        ],
    }
    trace.write_text(json.dumps(record) + "\n", encoding="utf-8")

    rows = list(_iter_replay_rows(trace))

    assert len(rows) == 1
    assert rows[0]["before_correct"] is False
    assert rows[0]["after_correct"] is True
    assert rows[0]["improved"] is True
    assert rows[0]["regressed"] is False


def test_clue_coverage_replay_extracts_sat_step_with_puzzle_text(tmp_path):
    trace = tmp_path / "trace.jsonl"
    record = {
        "puzzle_id": "p1",
        "domain": "2x2",
        "ground_truth": "color_Blue=1|color_Red=2",
        "steps": [
            {
                "action": "translate",
                "z3_result": "SAT",
                "constraints": [
                    "And(Int('color_Blue') >= 1, Int('color_Blue') <= 2)",
                    "And(Int('color_Red') >= 1, Int('color_Red') <= 2)",
                    "Distinct(Int('color_Blue'), Int('color_Red'))",
                    "Int('color_Blue') == Int('color_Red') + 1",
                ],
            }
        ],
    }
    trace.write_text(json.dumps(record) + "\n", encoding="utf-8")
    puzzle_text = {
        "p1": "Clues:\n1. The Blue color is immediately left of the Red color."
    }

    rows = list(_iter_replay_rows(trace, puzzle_text))

    assert len(rows) == 1
    assert rows[0]["before_correct"] is False
    assert rows[0]["after_correct"] is True
    assert rows[0]["repair_count"] == 1
