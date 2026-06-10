from __future__ import annotations

import csv

from scripts.summarize_online_csvs import _summarize


def test_summarize_online_csv_counts_diagnostics(tmp_path):
    path = tmp_path / "online.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "solved",
                "llm_calls",
                "repair_rounds",
                "initial_solver_result",
                "initial_z3_result",
                "final_z3_result",
                "memory_eligible",
                "repair_success",
                "validated_repair_success",
                "repair_rejected",
                "error_guidance_triggered",
                "positive_guidance_triggered",
                "invalid_model_retranslate",
                "misaligned_model_retranslate",
                "model_schema_aligned",
                "model_key_set_aligned",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "solved": "True",
            "llm_calls": "1",
            "repair_rounds": "0",
            "initial_solver_result": "SAT",
            "initial_z3_result": "SAT",
            "final_z3_result": "SAT",
            "memory_eligible": "False",
            "repair_success": "False",
            "validated_repair_success": "False",
            "repair_rejected": "False",
            "error_guidance_triggered": "False",
            "positive_guidance_triggered": "False",
            "invalid_model_retranslate": "False",
            "misaligned_model_retranslate": "True",
            "model_schema_aligned": "True",
            "model_key_set_aligned": "True",
        })
        writer.writerow({
            "solved": "False",
            "llm_calls": "3",
            "repair_rounds": "2",
            "initial_solver_result": "UNSAT",
            "initial_z3_result": "UNSAT",
            "final_z3_result": "KEY_MISMATCH",
            "memory_eligible": "True",
            "repair_success": "True",
            "validated_repair_success": "True",
            "repair_rejected": "True",
            "error_guidance_triggered": "True",
            "positive_guidance_triggered": "False",
            "invalid_model_retranslate": "False",
            "misaligned_model_retranslate": "False",
            "model_schema_aligned": "True",
            "model_key_set_aligned": "False",
        })

    summary = _summarize(path)

    assert summary["accuracy"] == "1/2"
    assert summary["sat"] == 1
    assert summary["initial_sat"] == 1
    assert summary["initial_unsat"] == 1
    assert summary["initial_solver_sat"] == 1
    assert summary["initial_solver_unsat"] == 1
    assert summary["key_mismatch"] == 1
    assert summary["avg_llm_calls"] == "2.00"
    assert summary["avg_repair_rounds"] == "1.00"
    assert summary["memory_eligible"] == 1
    assert summary["repair_success"] == 1
    assert summary["validated_repair_success"] == 1
    assert summary["repair_rejected"] == 1
    assert summary["error_guidance_triggered"] == 1
    assert summary["any_memory_guidance"] == 1
    assert summary["misaligned_model_retranslate"] == 1
