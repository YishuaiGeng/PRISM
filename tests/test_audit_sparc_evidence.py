from __future__ import annotations

from collections import Counter

from scripts.audit_sparc_evidence import (
    TraceRecord,
    cluster_bootstrap_ci,
    pairing_audit,
    reconstruct_constraints,
    uniqueness_probe,
    variable_premise_audit,
)


def _trace(record: dict, system: str = "baseline") -> TraceRecord:
    return TraceRecord(
        repetition="rep1",
        group="gA",
        system=system,
        source="synthetic.jsonl",
        record=record,
    )


def test_reconstruct_constraints_replays_resets_repairs_and_completions():
    record = {
        "steps": [
            {"action": "translate", "constraints": ["Int('x') >= 0"]},
            {
                "action": "repair",
                "constraints_before": ["Int('x') >= 0"],
                "old_constraint": "Int('x') >= 0",
                "new_constraint": "Int('x') == 1",
            },
            {"action": "pi_gate", "gate": "non_unique"},
            {
                "action": "diff_completion",
                "new_constraint": "Int('y') == 2",
            },
        ]
    }

    assert reconstruct_constraints(record, stop_before_gate=True) == ["Int('x') == 1"]
    assert reconstruct_constraints(record) == ["Int('x') == 1", "Int('y') == 2"]


def test_uniqueness_probe_distinguishes_unique_and_non_unique_states():
    unique = uniqueness_probe(["Int('x') == 1"])
    non_unique = uniqueness_probe(["And(Int('x') >= 1, Int('x') <= 2)"])

    assert unique["gate"] == "unique"
    assert non_unique["gate"] == "non_unique"


def test_pairing_ignores_constraint_order_but_replays_final_repair():
    common = {
        "puzzle_id": "p1",
        "ground_truth": "x=1",
        "predicted": "x=1",
        "final_z3_result": "SAT",
    }
    no_gate = _trace(
        {
            **common,
            "steps": [
                {"action": "translate", "constraints": ["Int('x') >= 0", "Int('x') <= 1"]},
                {
                    "action": "repair",
                    "constraints_before": ["Int('x') >= 0", "Int('x') <= 1"],
                    "old_constraint": "Int('x') >= 0",
                    "new_constraint": "Int('x') == 1",
                },
            ],
        }
    )
    sparc = _trace(
        {
            **common,
            "steps": [
                {"action": "translate", "constraints": ["Int('x') <= 1", "Int('x') == 1"]},
                {"action": "pi_gate", "gate": "unique"},
            ],
        },
        system="basesparc",
    )

    result = pairing_audit([no_gate], [sparc])

    assert result["exact_pre_gate_pairs"] == 1
    assert result["snapshot_only_pairs"] == 0


def test_variable_premise_audit_flags_new_completion_variable():
    record = _trace(
        {
            "puzzle_id": "p1",
            "ground_truth": "x=1",
            "steps": [
                {"action": "translate", "constraints": ["Int('x') == 1"]},
                {
                    "action": "diff_completion",
                    "new_constraint": "Int('aux') == 2",
                },
            ],
        },
        system="basesparc",
    )

    result = variable_premise_audit([record])

    assert result["accepted_completion_constraints"] == 1
    assert result["events_with_previously_unseen_variables"] == 1
    assert result["scorable_events_with_previously_unseen_variables"] == 1


def test_cluster_bootstrap_keeps_repetitions_with_their_puzzle():
    rows = [
        {"puzzle_id": "p1", "counts": {"hit": 1, "total": 1}},
        {"puzzle_id": "p1", "counts": {"hit": 1, "total": 1}},
        {"puzzle_id": "p2", "counts": {"total": 1}},
    ]

    result = cluster_bootstrap_ci(
        rows,
        lambda counts: counts["hit"] / counts["total"] if counts["total"] else None,
        replicates=100,
        seed=7,
    )

    assert result["cluster_count"] == 2
    assert result["estimate"] == 2 / 3
    assert result["valid_replicates"] == 100
