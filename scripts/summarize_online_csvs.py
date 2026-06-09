"""Summarize PRISM online per-puzzle CSV files."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize online evaluation CSVs")
    p.add_argument("csvs", nargs="+")
    p.add_argument("--output", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rows = [_summarize(Path(path)) for path in args.csvs]
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        for row in rows:
            print(row)


def _summarize(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    n = len(rows)
    final_counts = Counter(row.get("final_z3_result", "") for row in rows)
    initial_counts = Counter(row.get("initial_z3_result", "") for row in rows)
    initial_solver_counts = Counter(row.get("initial_solver_result", "") for row in rows)
    solved = sum(row.get("solved") == "True" for row in rows)
    return {
        "file": str(path),
        "n": n,
        "accuracy": f"{solved}/{n}",
        "accuracy_pct": f"{(solved / n * 100) if n else 0:.1f}",
        "avg_llm_calls": f"{_mean_float(rows, 'llm_calls'):.2f}",
        "avg_repair_rounds": f"{_mean_float(rows, 'repair_rounds'):.2f}",
        "sat": final_counts.get("SAT", 0),
        "unsat": final_counts.get("UNSAT", 0),
        "initial_sat": initial_counts.get("SAT", 0),
        "initial_unsat": initial_counts.get("UNSAT", 0),
        "initial_translation_failed": initial_counts.get("TRANSLATION_FAILED", 0),
        "initial_solver_sat": initial_solver_counts.get("SAT", 0),
        "initial_solver_unsat": initial_solver_counts.get("UNSAT", 0),
        "invalid_model": final_counts.get("INVALID_MODEL", 0),
        "misaligned_model": final_counts.get("MISALIGNED_MODEL", 0),
        "key_mismatch": final_counts.get("KEY_MISMATCH", 0),
        "translation_failed": final_counts.get("TRANSLATION_FAILED", 0),
        "memory_eligible": _count_true(rows, "memory_eligible"),
        "repair_success": _count_true(rows, "repair_success"),
        "validated_repair_success": _count_true(rows, "validated_repair_success"),
        "repair_rejected": _count_true(rows, "repair_rejected"),
        "error_guidance_triggered": _count_true(rows, "error_guidance_triggered"),
        "positive_guidance_triggered": _count_true(rows, "positive_guidance_triggered"),
        "invalid_model_retranslate": _count_true(rows, "invalid_model_retranslate"),
        "misaligned_model_retranslate": _count_true(rows, "misaligned_model_retranslate"),
        "any_memory_guidance": _count_true(rows, "error_guidance_triggered")
        + _count_true(rows, "positive_guidance_triggered"),
        "model_schema_aligned": _count_true(rows, "model_schema_aligned"),
        "model_key_set_aligned": _count_true(rows, "model_key_set_aligned"),
    }


def _count_true(rows: list[dict], key: str) -> int:
    return sum(row.get(key) == "True" for row in rows)


def _mean_float(rows: list[dict], key: str) -> float:
    values = []
    for row in rows:
        try:
            values.append(float(row.get(key, "") or 0))
        except ValueError:
            continue
    return sum(values) / len(values) if values else 0.0


if __name__ == "__main__":
    main()
