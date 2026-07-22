from __future__ import annotations

import json

from scripts.run_frozen_sparc import (
    _NoCallLLM,
    _build_gate_solver,
    freeze_rows,
    replay_row,
)


def test_freeze_rows_reconstructs_final_gate_input(tmp_path):
    trace = tmp_path / "baseline_gA.trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "puzzle_id": "p1",
                "domain": "2x2",
                "ground_truth": "x=1",
                "predicted": "x=1",
                "final_z3_result": "SAT",
                "steps": [
                    {"action": "translate", "constraints": ["Int('x') >= 0"]},
                    {
                        "action": "repair",
                        "constraints_before": ["Int('x') >= 0"],
                        "old_constraint": "Int('x') >= 0",
                        "new_constraint": "Int('x') == 1",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rows = freeze_rows(tmp_path, "baseline")

    assert len(rows) == 1
    assert rows[0]["constraints"] == ["Int('x') == 1"]
    assert len(rows[0]["constraints_sha256"]) == 64


def test_gate_only_replay_uses_frozen_state_without_llm():
    gate_solver = _build_gate_solver(
        _NoCallLLM(),
        budget=0,
        repair_budget=2,
        blind=False,
        no_invariant=False,
    )
    unique = {
        "puzzle_id": "p1",
        "source_system": "baseline",
        "source_final_z3_result": "SAT",
        "source_ground_truth": "x=1",
        "source_predicted": "x=1",
        "constraints": ["Int('x') == 1"],
        "constraints_sha256": "unique",
    }
    non_unique = {
        **unique,
        "puzzle_id": "p2",
        "constraints": ["And(Int('x') >= 1, Int('x') <= 2)"],
        "constraints_sha256": "nonunique",
    }

    unique_result = replay_row(
        unique, variant="gate_only", gate_solver=gate_solver
    )
    non_unique_result = replay_row(
        non_unique, variant="gate_only", gate_solver=gate_solver
    )

    assert unique_result["final_z3_result"] == "SAT"
    assert unique_result["llm_calls"] == 0
    assert non_unique_result["final_z3_result"] == "SAT_NONUNIQUE"
    assert non_unique_result["llm_calls"] == 0
