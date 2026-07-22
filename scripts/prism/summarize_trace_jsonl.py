"""Summarize PRISM per-puzzle trace JSONL files."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize online trace JSONL files")
    p.add_argument("traces", nargs="+")
    p.add_argument("--output", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    rows = [_summarize(Path(path)) for path in args.traces]
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
    records = _load_jsonl(path)
    n = len(records)
    solved = sum(record.get("solved") is True for record in records)
    final_counts = Counter(record.get("final_z3_result", "") for record in records)
    rejection_reasons: Counter[str] = Counter()
    step_actions: Counter[str] = Counter()
    schema_replacements = 0
    error_guidance_steps = 0
    positive_guidance_steps = 0
    repair_sat_steps = 0
    repair_unsat_steps = 0
    exact_target_repair_steps = 0
    comparable_target_repair_steps = 0
    visible_key_counts: list[int] = []
    missing_visible_key_counts: list[int] = []
    dropped_invisible_constraint_counts: list[int] = []

    for record in records:
        for step in record.get("steps", []) or []:
            action = step.get("action", "")
            step_actions[action] += 1
            if step.get("error_guidance_triggered") is True:
                error_guidance_steps += 1
            if step.get("positive_guidance_triggered") is True:
                positive_guidance_steps += 1
            if action == "repair_rejected":
                rejection_reasons[step.get("repair_rejection_reason", "unknown")] += 1
            if action == "repair":
                if step.get("z3_result") == "SAT":
                    repair_sat_steps += 1
                if step.get("z3_result") == "UNSAT":
                    repair_unsat_steps += 1
                if _is_schema_constraint(step.get("old_constraint")):
                    schema_replacements += 1
                target = str(record.get("controlled_correct_constraint") or "")
                if target:
                    comparable_target_repair_steps += 1
                    if _canonical(step.get("repair_expression")) == _canonical(target):
                        exact_target_repair_steps += 1
            if "visible_schema_key_count" in step:
                visible_key_counts.append(int(step.get("visible_schema_key_count") or 0))
                missing_visible_key_counts.append(
                    len(step.get("missing_visible_schema_keys") or [])
                )
                dropped_invisible_constraint_counts.append(
                    len(step.get("dropped_invisible_schema_constraints") or [])
                )

    return {
        "file": str(path),
        "n": n,
        "accuracy": f"{solved}/{n}",
        "accuracy_pct": f"{(solved / n * 100) if n else 0:.1f}",
        "avg_llm_calls": f"{_mean(records, 'llm_calls'):.2f}",
        "avg_repair_rounds": f"{_mean(records, 'repair_rounds'):.2f}",
        "sat": final_counts.get("SAT", 0),
        "unsat": final_counts.get("UNSAT", 0),
        "invalid_model": final_counts.get("INVALID_MODEL", 0),
        "misaligned_model": final_counts.get("MISALIGNED_MODEL", 0),
        "key_mismatch": final_counts.get("KEY_MISMATCH", 0),
        "translation_failed": final_counts.get("TRANSLATION_FAILED", 0),
        "memory_eligible": sum(record.get("memory_eligible") is True for record in records),
        "repair_steps": step_actions.get("repair", 0),
        "repair_sat_steps": repair_sat_steps,
        "repair_unsat_steps": repair_unsat_steps,
        "exact_target_repair_steps": exact_target_repair_steps,
        "target_repair_steps": comparable_target_repair_steps,
        "exact_target_repair_pct": (
            f"{(exact_target_repair_steps / comparable_target_repair_steps * 100) if comparable_target_repair_steps else 0:.1f}"
        ),
        "repair_rejected_steps": step_actions.get("repair_rejected", 0),
        "repair_rejection_reasons": _format_counter(rejection_reasons),
        "schema_replacements": schema_replacements,
        "error_guidance_steps": error_guidance_steps,
        "positive_guidance_steps": positive_guidance_steps,
        "invalid_model_retranslate_steps": step_actions.get("invalid_model_retranslate", 0),
        "misaligned_model_retranslate_steps": step_actions.get("misaligned_model_retranslate", 0),
        "avg_visible_schema_keys": f"{_mean_values(visible_key_counts):.2f}",
        "avg_missing_visible_schema_keys": f"{_mean_values(missing_visible_key_counts):.2f}",
        "avg_dropped_invisible_constraints": f"{_mean_values(dropped_invisible_constraint_counts):.2f}",
    }


def _load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _mean(records: list[dict], key: str) -> float:
    values = []
    for record in records:
        try:
            values.append(float(record.get(key, 0) or 0))
        except (TypeError, ValueError):
            continue
    return sum(values) / len(values) if values else 0.0


def _mean_values(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _format_counter(counter: Counter[str]) -> str:
    return ";".join(f"{key}={value}" for key, value in sorted(counter.items()))


def _is_schema_constraint(constraint: str | None) -> bool:
    text = constraint or ""
    if "Distinct(" in text:
        return True
    return bool(
        text.startswith("And(")
        and ">=" in text
        and "<=" in text
        and len(set(re.findall(r"Int\('([^']+)'\)", text))) == 1
    )


def _canonical(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


if __name__ == "__main__":
    main()
