"""Replay fixed SAT clue-coverage repair states without LLM calls."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.solver import Z3SolverWrapper
from prism.core.types import SolverState
from prism.online.guided_solver import (
    _find_clue_coverage_issues,
    _replacement_policy_from_error_paradigm,
    GuidedSolver,
)
from prism.paradigm_library.error_library import ErrorParadigmLibrary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replay clue-coverage memory repairs")
    p.add_argument("--trace", required=True, help="Input online trace JSONL")
    p.add_argument(
        "--data",
        default=None,
        help=(
            "Optional ZebraLogic JSONL used to recover puzzle text. When set, "
            "SAT steps with recorded constraints are scanned for clue-coverage "
            "mismatches even if the online run did not execute coverage repair."
        ),
    )
    p.add_argument(
        "--error-library",
        default=None,
        help="Optional error paradigm DB; keeps only repairs materialized by memory.",
    )
    p.add_argument("--output", default="results/clue_coverage_replay.csv")
    p.add_argument("--trace-output", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    puzzle_text = _load_puzzle_text(Path(args.data)) if args.data else {}
    error_library = (
        ErrorParadigmLibrary(args.error_library)
        if args.error_library
        else None
    )
    try:
        rows = list(_iter_replay_rows(Path(args.trace), puzzle_text, error_library))
    finally:
        if error_library is not None:
            error_library.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "puzzle_id",
            "domain",
            "repair_count",
            "before_z3_result",
            "after_z3_result",
            "before_correct",
            "after_correct",
            "improved",
            "regressed",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    if args.trace_output:
        trace_path = Path(args.trace_output)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str))
                fh.write("\n")
    _print_summary(rows)


def _iter_replay_rows(
    path: Path,
    puzzle_text: dict[str, str] | None = None,
    error_library: ErrorParadigmLibrary | None = None,
):
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            yielded_from_record = False
            for step in record.get("steps", []):
                if step.get("action") != "repair" or step.get("source") != "clue_coverage":
                    continue
                before_constraints = list(step.get("constraints_before") or [])
                repairs = list(step.get("clue_coverage_repairs") or [])
                if not before_constraints or not repairs:
                    continue
                yielded_from_record = True
                yield _build_replay_row(record, before_constraints, repairs)
            if yielded_from_record:
                continue
            text = (puzzle_text or {}).get(str(record.get("puzzle_id")), "")
            if not text:
                continue
            for step in record.get("steps", []):
                if step.get("z3_result") != "SAT":
                    continue
                constraints = list(step.get("constraints") or [])
                if not constraints:
                    continue
                issues = _find_clue_coverage_issues(text, constraints)
                repairs = _issues_to_repairs(
                    issues,
                    puzzle_id=str(record.get("puzzle_id")),
                    constraints=constraints,
                    puzzle_text=text,
                    error_library=error_library,
                )
                if repairs:
                    yield _build_replay_row(record, constraints, repairs)


def _build_replay_row(record: dict, before_constraints: list[str], repairs: list[dict]) -> dict:
    after_constraints = _apply_repairs(before_constraints, repairs)
    before_result, before_model = _solve(before_constraints)
    after_result, after_model = _solve(after_constraints)
    ground_truth = record.get("ground_truth")
    before_pred = _solution_to_str(before_model)
    after_pred = _solution_to_str(after_model)
    before_correct = before_pred == ground_truth
    after_correct = after_pred == ground_truth
    return {
        "puzzle_id": record.get("puzzle_id"),
        "domain": record.get("domain"),
        "repair_count": len(repairs),
        "before_z3_result": before_result,
        "after_z3_result": after_result,
        "before_correct": before_correct,
        "after_correct": after_correct,
        "improved": (not before_correct) and after_correct,
        "regressed": before_correct and (not after_correct),
        "ground_truth": ground_truth,
        "before_predicted": before_pred,
        "after_predicted": after_pred,
        "repairs": repairs,
    }


def _issues_to_repairs(
    issues,
    *,
    puzzle_id: str,
    constraints: list[str],
    puzzle_text: str,
    error_library: ErrorParadigmLibrary | None,
) -> list[dict]:
    repairs = []
    for issue in issues:
        repair = {
            "issue_type": issue.issue_type,
            "clue_relation": issue.clue_relation,
            "generated_relation": issue.generated_relation,
            "offending_constraint": issue.offending_constraint,
            "expected_constraint": issue.expected_constraint,
            "source_clue": issue.source_clue,
        }
        if error_library is not None and not _memory_materializes_issue(
            issue,
            puzzle_id=puzzle_id,
            constraints=constraints,
            puzzle_text=puzzle_text,
            error_library=error_library,
        ):
            continue
        repairs.append(repair)
    return repairs


def _memory_materializes_issue(
    issue,
    *,
    puzzle_id: str,
    constraints: list[str],
    puzzle_text: str,
    error_library: ErrorParadigmLibrary,
) -> bool:
    state = SolverState(
        puzzle_id=puzzle_id,
        constraints=constraints,
        unsat_core=[issue.offending_constraint],
        z3_result="CLUE_MISMATCH",
        iteration=0,
        constraint_types=[issue.clue_relation, issue.issue_type, "clue_coverage_mismatch"],
        problem_nl=puzzle_text,
    )
    candidates = error_library.retrieve(
        state.constraint_types,
        unsat_core=state.unsat_core or [],
        puzzle_id=state.puzzle_id,
        top_k=2,
    )
    targets = []
    for paradigm in candidates:
        replacement = _replacement_policy_from_error_paradigm(paradigm, state)
        if isinstance(replacement, dict):
            target = str(replacement.get("target_constraint") or "").strip()
            if target:
                targets.append(target)
    return GuidedSolver._matches_any_target(issue.expected_constraint, targets)


def _apply_repairs(constraints: list[str], repairs: list[dict]) -> list[str]:
    updated = list(constraints)
    for repair in repairs:
        old = str(repair.get("offending_constraint") or "")
        new = str(repair.get("expected_constraint") or "")
        if not new:
            continue
        if not old:
            if new not in updated:
                updated.append(new)
            continue
        try:
            index = updated.index(old)
        except ValueError:
            continue
        updated[index] = new
    return updated


def _solve(constraints: list[str]) -> tuple[str, Optional[dict]]:
    solver = Z3SolverWrapper()
    for constraint in constraints:
        if not solver.add_constraint(constraint):
            return "PARSE_FAILED", None
    result = solver.check()
    if result != "SAT":
        return result, None
    return result, solver.get_model()


def _solution_to_str(solution: Optional[dict]) -> Optional[str]:
    if solution is None:
        return None
    return "|".join(
        f"{key}={value}"
        for key, value in sorted(solution.items())
        if not str(key).startswith("_prism_track_")
    )


def _print_summary(rows: list[dict]) -> None:
    n = len(rows)
    before = sum(row["before_correct"] for row in rows)
    after = sum(row["after_correct"] for row in rows)
    improved = sum(row["improved"] for row in rows)
    regressed = sum(row["regressed"] for row in rows)
    print(
        json.dumps(
            {
                "n": n,
                "before_correct": f"{before}/{n}",
                "after_correct": f"{after}/{n}",
                "improved": improved,
                "regressed": regressed,
            },
            ensure_ascii=False,
        )
    )


def _load_puzzle_text(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            puzzle_id = str(record.get("id") or record.get("puzzle_id") or "")
            text = str(record.get("puzzle") or record.get("nl_description") or "")
            if puzzle_id and text:
                result[puzzle_id] = text
    return result


if __name__ == "__main__":
    main()
