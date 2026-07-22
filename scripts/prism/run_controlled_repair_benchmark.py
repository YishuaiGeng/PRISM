"""Run a controlled repair-loop benchmark on ZebraLogic records.

This benchmark isolates the repair stage: it builds a complete, domain-explicit
Z3 formalization from each record's solution, injects one wrong constraint, then
asks the online repair loop to recover it. The setup is intentionally controlled
and should be reported separately from the full NL->Z3 pipeline.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.constraint_tags import classify_constraint_tags
from prism.core.model_validation import validate_model
from prism.core.solver import Z3SolverWrapper
from prism.core.translator import NLToZ3Translator
from prism.core.types import PuzzleInstance
from prism.evaluation.benchmarks.zebralogic import evaluate_zebralogic
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import ErrorParadigm


@dataclass(frozen=True)
class Perturbation:
    key: str
    correct_value: int
    wrong_value: int
    correct_constraint: str
    wrong_constraint: str
    source_clue: str
    kind: str = "direct_position"
    left_key: str = ""
    right_key: str = ""


class ControlledTranslator:
    """Translator stub that returns prebuilt controlled constraints."""

    def __init__(self) -> None:
        self.last_diagnostics: dict = {}

    def translate(self, puzzle: PuzzleInstance) -> list[str]:
        raw = puzzle.raw_data or {}
        self.last_diagnostics = dict(raw.get("controlled_diagnostics") or {})
        return list(raw.get("controlled_constraints") or [])

    def retranslate(
        self,
        puzzle: PuzzleInstance,
        failed_constraints: list[str],
        error_ctx: str,
    ) -> list[str]:
        return self.translate(puzzle)

    def parse_repair_response(self, response: str) -> Optional[str]:
        return LLMClient.parse_repair(response)

    def build_state_summary(
        self,
        puzzle_nl: str,
        constraints: list[str],
        unsat_core: list[str],
    ) -> str:
        core = "\n".join(f"  {item}" for item in unsat_core)
        return (
            f"Puzzle: {puzzle_nl[:400]}\n"
            f"Constraint count: {len(constraints)}\n"
            f"UNSAT core:\n{core}"
        )


class ControlledRepairLLM:
    """Wrap an LLM client and inject controlled clue context into repairs."""

    def __init__(self, inner: LLMClient, inject_target: bool = True) -> None:
        self._inner = inner
        self._inject_target = inject_target
        self.current_puzzle: PuzzleInstance | None = None

    @property
    def call_count(self) -> int:
        return self._inner.call_count

    def reset_call_count(self) -> None:
        self._inner.reset_call_count()

    def repair(
        self,
        constraints,
        unsat_core,
        history_summary,
        paradigm_hint="",
        switch_prompt="",
    ) -> str:
        hint = paradigm_hint
        if self._inject_target and self.current_puzzle is not None:
            raw = self.current_puzzle.raw_data or {}
            diag = raw.get("controlled_diagnostics") or {}
            controlled_hint = (
                "\n\nControlled repair target:\n"
                f"- Source clue: {diag.get('controlled_source_clue', '')}\n"
                f"- Replace the wrong assertion with exactly: "
                f"{diag.get('controlled_correct_constraint', '')}\n"
                "- Do not return a weaker inequality such as != wrong_house.\n"
            )
            hint = "\n".join(part for part in [hint, controlled_hint] if part)
        return self._inner.repair(
            constraints,
            unsat_core,
            history_summary,
            hint,
            switch_prompt,
        )

    def judge_semantic_match(self, paradigm_summary, state_summary) -> bool:
        return self._inner.judge_semantic_match(paradigm_summary, state_summary)

    def translate(self, puzzle_nl: str, schema_hint: str = "") -> str:
        return self._inner.translate(puzzle_nl, schema_hint=schema_hint)

    def retranslate(
        self,
        puzzle_nl: str,
        failed_constraints,
        error_ctx: str,
        schema_hint: str = "",
    ) -> str:
        return self._inner.retranslate(
            puzzle_nl,
            failed_constraints,
            error_ctx,
            schema_hint=schema_hint,
        )


class ControlledGuidedSolver:
    """Set per-puzzle context on the wrapped LLM before solving."""

    def __init__(self, solver: GuidedSolver, llm: ControlledRepairLLM) -> None:
        self._solver = solver
        self._llm = llm

    def solve(self, puzzle: PuzzleInstance):
        self._llm.current_puzzle = puzzle
        try:
            return self._solver.solve(puzzle)
        finally:
            self._llm.current_puzzle = None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Controlled ZebraLogic repair benchmark")
    p.add_argument("--data", required=True, help="Input ZebraLogic JSONL file")
    p.add_argument("--model", default="GPT-4o-mini")
    p.add_argument("--sizes", default=None, help="Comma-separated size filter")
    p.add_argument("--max-records", type=int, default=None)
    p.add_argument("--max-repair", type=int, default=1)
    p.add_argument("--output", default="results/prism/controlled_repair.csv")
    p.add_argument("--trace-output", default=None)
    p.add_argument("--error-library", default=None)
    p.add_argument(
        "--prepared-output",
        default=None,
        help=(
            "Optional JSONL path to save the prepared controlled puzzles before "
            "running repair. Useful for reusing the exact same LLM-derived base "
            "constraints across ablations."
        ),
    )
    p.add_argument(
        "--prepared-input",
        default=None,
        help="Optional JSONL path of previously prepared controlled puzzles.",
    )
    p.add_argument(
        "--base-constraints",
        default="solution",
        choices=["solution", "llm_validated", "llm_schema_completed"],
        help=(
            "How to build the controlled constraint base. 'solution' uses the "
            "benchmark solution as before; 'llm_validated' first translates the "
            "puzzle with the selected LLM and keeps only SAT translations whose "
            "model exactly matches the benchmark solution; 'llm_schema_completed' "
            "uses LLM-translated clue constraints plus deterministic domain bounds "
            "and Distinct schema constraints before validation."
        ),
    )
    p.add_argument(
        "--controlled-error-memory",
        action="store_true",
        help="Add a generic direct-position repair error paradigm.",
    )
    p.add_argument(
        "--memory-targets",
        action="store_true",
        help="Encode exact repair targets as per-puzzle structured error memory.",
    )
    p.add_argument(
        "--template-memory",
        action="store_true",
        help="Encode clue-derived typed replacement templates instead of exact targets.",
    )
    p.add_argument(
        "--no-wrapper-target",
        action="store_true",
        help="Do not inject exact target from the benchmark wrapper.",
    )
    p.add_argument(
        "--perturbation-type",
        default="direct_position",
        choices=[
            "direct_position",
            "directly_left",
            "directly_right",
            "somewhere_left",
            "somewhere_right",
            "adjacent",
        ],
        help="Controlled formalization error to inject.",
    )
    p.add_argument(
        "--relation-hard-mode",
        action="store_true",
        help=(
            "For relation perturbations, avoid exposing both relation endpoint "
            "assignments in the repair prompt by creating a boundary-triggered "
            "UNSAT core."
        ),
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.prepared_input:
        puzzles, metadata = _load_prepared_puzzles(Path(args.prepared_input))
    else:
        sizes = set(args.sizes.split(",")) if args.sizes else None
        records = _load_records(Path(args.data), sizes=sizes, max_records=args.max_records)
        base_llm = (
            LLMClient(model_name=args.model, temperature=0.0)
            if args.base_constraints in {"llm_validated", "llm_schema_completed"}
            else None
        )
        puzzles, metadata = _build_controlled_puzzles(
            records,
            perturbation_type=args.perturbation_type,
            relation_hard_mode=args.relation_hard_mode,
            base_constraints=args.base_constraints,
            llm_client=base_llm,
        )
        if args.prepared_output:
            _save_prepared_puzzles(puzzles, Path(args.prepared_output))
    if not puzzles:
        raise SystemExit("No controlled puzzles could be built.")

    solver = Z3SolverWrapper()
    with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as library:
        error_library = _load_error_library(args.error_library)
        if args.controlled_error_memory:
            error_library = _add_controlled_error_memory(error_library)
        if args.memory_targets:
            error_library = _add_controlled_target_memory(error_library, metadata)
        if args.template_memory:
            error_library = _add_controlled_template_memory(error_library, metadata)

        llm = ControlledRepairLLM(
            LLMClient(model_name=args.model, temperature=0.0),
            inject_target=not args.no_wrapper_target,
        )
        guided = GuidedSolver(
            llm_client=llm,
            library=library,
            max_repair_rounds=args.max_repair,
            layer2_enabled=False,
            enable_paradigm=False,
            error_library=error_library,
            schema_hint_mode="puzzle",
        )
        guided._translator = ControlledTranslator()
        results = evaluate_zebralogic(ControlledGuidedSolver(guided, llm), puzzles)

    for row in results:
        row.update(metadata.get(row["puzzle_id"], {}))

    _save_csv(results, Path(args.output))
    if args.trace_output:
        _save_trace_jsonl(results, Path(args.trace_output))

    solved = sum(row.get("solved") is True for row in results)
    memory_eligible = sum(row.get("memory_eligible") is True for row in results)
    repair_success = sum(row.get("repair_success") is True for row in results)
    print(f"Puzzles: {len(results)}")
    print(f"Accuracy: {solved}/{len(results)}")
    print(f"Memory eligible: {memory_eligible}")
    print(f"Repair success: {repair_success}")
    print(f"CSV: {args.output}")
    if args.trace_output:
        print(f"Trace: {args.trace_output}")


def _load_records(
    path: Path,
    *,
    sizes: set[str] | None,
    max_records: int | None,
) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            size = str(record.get("size", "")).replace("*", "x")
            if sizes and size not in sizes:
                continue
            records.append(record)
            if max_records and len(records) >= max_records:
                break
    return records


def _save_prepared_puzzles(puzzles: list[PuzzleInstance], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for puzzle in puzzles:
            fh.write(json.dumps(puzzle.model_dump(mode="json"), ensure_ascii=False))
            fh.write("\n")


def _load_prepared_puzzles(path: Path) -> tuple[list[PuzzleInstance], dict[str, dict]]:
    puzzles: list[PuzzleInstance] = []
    metadata: dict[str, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            puzzle = PuzzleInstance.model_validate(json.loads(line))
            puzzles.append(puzzle)
            raw = puzzle.raw_data or {}
            metadata[puzzle.puzzle_id] = dict(raw.get("controlled_diagnostics") or {})
    return puzzles, metadata


def _build_controlled_puzzles(
    records: list[dict],
    perturbation_type: str = "direct_position",
    relation_hard_mode: bool = False,
    base_constraints: str = "solution",
    llm_client: LLMClient | None = None,
) -> tuple[list[PuzzleInstance], dict[str, dict]]:
    puzzles: list[PuzzleInstance] = []
    metadata: dict[str, dict] = {}
    for record in records:
        solution = _normalise_solution(record.get("solution") or {})
        if not solution:
            continue
        size = str(record.get("size", "")).replace("*", "x")
        try:
            n_houses = int(size.split("x", 1)[0])
        except (ValueError, IndexError):
            continue
        perturbation = _choose_perturbation(
            record,
            solution,
            n_houses,
            perturbation_type=perturbation_type,
            relation_hard_mode=relation_hard_mode,
        )
        if perturbation is None:
            continue
        puzzle_id = str(record.get("id") or "")
        puzzle_text = str(record.get("puzzle") or record.get("nl_description") or "")
        puzzle = PuzzleInstance(
            puzzle_id=puzzle_id,
            nl_description=puzzle_text,
            constraints_nl=_extract_clues(puzzle_text),
            solution={key: str(value) for key, value in solution.items()},
            size=size,
            domain="zebralogic_controlled_repair",
            raw_data=dict(record),
        )
        if base_constraints in {"llm_validated", "llm_schema_completed"}:
            if llm_client is None:
                raise ValueError("llm_client is required for LLM-derived base constraints")
            base = _validated_llm_base_constraints(
                puzzle,
                llm_client,
                complete_schema=base_constraints == "llm_schema_completed",
                n_houses=n_houses,
            )
            if base is None:
                continue
            constraints = _perturb_existing_constraints(base, perturbation)
            if constraints is None:
                continue
            base_source = base_constraints
        else:
            constraints = _controlled_constraints(
                solution,
                n_houses,
                perturbation,
                relation_hard_mode=relation_hard_mode,
            )
            base_source = "solution"
        diagnostics = {
            "controlled_perturbed_key": perturbation.key,
            "controlled_perturbation_type": perturbation.kind,
            "controlled_relation_hard_mode": bool(
                relation_hard_mode and perturbation.kind != "direct_position"
            ),
            "controlled_base_constraints": base_source,
            "controlled_correct_constraint": perturbation.correct_constraint,
            "controlled_wrong_constraint": perturbation.wrong_constraint,
            "controlled_source_clue": perturbation.source_clue,
        }
        puzzle.raw_data = {
            **dict(record),
            "controlled_constraints": constraints,
            "controlled_diagnostics": diagnostics,
        }
        puzzles.append(puzzle)
        metadata[puzzle_id] = diagnostics
    return puzzles, metadata


def _normalise_solution(raw: dict) -> dict[str, str]:
    solution: dict[str, str] = {}
    for key, value in raw.items():
        text = str(value)
        match = re.fullmatch(r"house(\d+)", text, flags=re.I)
        solution[str(key)] = match.group(1) if match else text
    return solution


def _solution_constraints(
    solution: dict[str, str],
    n_houses: int,
    omit_assignments: Optional[set[str]] = None,
) -> list[str]:
    omitted = omit_assignments or set()
    constraints: list[str] = []
    keys = sorted(solution)
    for key in keys:
        constraints.append(f"And(Int('{key}') >= 1, Int('{key}') <= {n_houses})")
    by_category: dict[str, list[str]] = {}
    for key in keys:
        category = key.split("_", 1)[0]
        by_category.setdefault(category, []).append(key)
    for group in by_category.values():
        if len(group) > 1:
            args = ", ".join(f"Int('{key}')" for key in sorted(group))
            constraints.append(f"Distinct({args})")
    for key in keys:
        if key not in omitted:
            constraints.append(f"Int('{key}') == {int(solution[key])}")
    return constraints


def _validated_llm_base_constraints(
    puzzle: PuzzleInstance,
    llm_client: LLMClient,
    *,
    complete_schema: bool = False,
    n_houses: int | None = None,
) -> Optional[list[str]]:
    translator = NLToZ3Translator(llm_client, schema_hint_mode="solution_keys")
    constraints = translator.translate(puzzle)
    if not constraints:
        return None
    if complete_schema:
        if n_houses is None:
            return None
        constraints = _complete_schema_constraints(
            constraints,
            puzzle.solution or {},
            n_houses,
        )
    solver = Z3SolverWrapper()
    for constraint in constraints:
        if not solver.add_constraint(constraint):
            return None
    if solver.check() != "SAT":
        return None
    if not validate_model(puzzle, solver.get_model()).ok:
        return None
    if _model_to_int_str(solver.get_model()) != _model_to_int_str(puzzle.solution or {}):
        return None
    return constraints


def _complete_schema_constraints(
    constraints: list[str],
    solution: dict[str, str],
    n_houses: int,
) -> list[str]:
    semantic_constraints = [
        constraint for constraint in constraints
        if not _is_schema_constraint(constraint)
    ]
    schema = [
        constraint for constraint in _solution_constraints(solution, n_houses)
        if _is_schema_constraint(constraint)
    ]
    return schema + semantic_constraints


def _is_schema_constraint(constraint: str) -> bool:
    text = constraint or ""
    if "Distinct(" in text:
        return True
    return bool(
        text.startswith("And(")
        and ">=" in text
        and "<=" in text
        and len(set(re.findall(r"Int\('([^']+)'\)", text))) == 1
    )


def _model_to_int_str(model: dict[str, str]) -> dict[str, str]:
    return {str(key): str(int(str(value))) for key, value in model.items()}


def _perturb_existing_constraints(
    constraints: list[str],
    perturbation: Perturbation,
) -> Optional[list[str]]:
    perturbed: list[str] = []
    replaced = False
    for constraint in constraints:
        if (
            not replaced
            and _constraints_equivalent(constraint, perturbation.correct_constraint)
        ):
            perturbed.append(perturbation.wrong_constraint)
            replaced = True
        else:
            perturbed.append(constraint)
    if not replaced:
        return None

    solver = Z3SolverWrapper()
    for constraint in perturbed:
        solver.add_constraint(constraint)
    if solver.check() != "UNSAT":
        return None
    return perturbed


def _constraints_equivalent(left: str, right: str) -> bool:
    canonical_left = re.sub(r"\s+", "", left or "")
    canonical_right = re.sub(r"\s+", "", right or "")
    if canonical_left == canonical_right:
        return True
    try:
        import z3  # noqa: PLC0415
        from prism.core.solver import _Z3_NS  # type: ignore  # noqa: PLC0415

        left_expr = eval(left, _Z3_NS)  # noqa: S307
        right_expr = eval(right, _Z3_NS)  # noqa: S307
        solver = z3.Solver()
        solver.add(left_expr != right_expr)
        return solver.check() == z3.unsat
    except Exception:
        return False


def _controlled_constraints(
    solution: dict[str, str],
    n_houses: int,
    perturbation: Perturbation,
    *,
    relation_hard_mode: bool = False,
) -> list[str]:
    if perturbation.kind == "direct_position":
        constraints = _solution_constraints(solution, n_houses)
        return [
            perturbation.wrong_constraint
            if item == perturbation.correct_constraint
            else item
            for item in constraints
        ]

    omitted: set[str] = set()
    anchor: Optional[tuple[str, int]] = None
    if relation_hard_mode:
        omitted = {perturbation.left_key, perturbation.right_key}
        anchor = _relation_boundary_anchor(
            perturbation.kind,
            perturbation.left_key,
            perturbation.right_key,
            solution,
            n_houses,
        )
    constraints = _solution_constraints(solution, n_houses, omit_assignments=omitted)
    if anchor:
        constraints.append(f"Int('{anchor[0]}') == {anchor[1]}")
    constraints.append(perturbation.wrong_constraint)
    return constraints


def _choose_perturbation(
    record: dict,
    solution: dict[str, str],
    n_houses: int,
    perturbation_type: str = "direct_position",
    relation_hard_mode: bool = False,
) -> Optional[Perturbation]:
    if perturbation_type != "direct_position":
        relation_clues = _relation_clues(str(record.get("puzzle") or ""))
        for relation_kind, left_key, right_key, clue in relation_clues:
            if relation_kind != perturbation_type:
                continue
            if left_key in solution and right_key in solution:
                perturbation = _relation_perturbation(
                    relation_kind,
                    left_key,
                    right_key,
                    clue,
                )
                if not relation_hard_mode or _relation_boundary_anchor(
                    relation_kind,
                    left_key,
                    right_key,
                    solution,
                    n_houses,
                ):
                    return perturbation
        return None

    direct_clues = _direct_position_clues(str(record.get("puzzle") or ""))
    for key, house, clue in direct_clues:
        if key in solution and int(solution[key]) == house:
            return _perturb(key, house, n_houses, clue)
    key = sorted(solution)[0]
    return _perturb(key, int(solution[key]), n_houses, "")


def _perturb(key: str, correct_value: int, n_houses: int, source_clue: str) -> Perturbation:
    wrong_value = (correct_value % n_houses) + 1
    return Perturbation(
        key=key,
        correct_value=correct_value,
        wrong_value=wrong_value,
        correct_constraint=f"Int('{key}') == {correct_value}",
        wrong_constraint=f"Int('{key}') == {wrong_value}",
        source_clue=source_clue,
    )


def _relation_perturbation(
    relation_kind: str,
    left_key: str,
    right_key: str,
    source_clue: str,
) -> Perturbation:
    correct = _relation_constraint(relation_kind, left_key, right_key)
    wrong = _wrong_relation_constraint(relation_kind, left_key, right_key)
    return Perturbation(
        key=f"{left_key}__{relation_kind}__{right_key}",
        correct_value=0,
        wrong_value=0,
        correct_constraint=correct,
        wrong_constraint=wrong,
        source_clue=source_clue,
        kind=relation_kind,
        left_key=left_key,
        right_key=right_key,
    )


def _relation_boundary_anchor(
    relation_kind: str,
    left_key: str,
    right_key: str,
    solution: dict[str, str],
    n_houses: int,
) -> Optional[tuple[str, int]]:
    try:
        left_value = int(solution[left_key])
        right_value = int(solution[right_key])
    except (KeyError, TypeError, ValueError):
        return None

    if relation_kind in {"directly_left", "somewhere_left"}:
        if left_value == 1:
            return left_key, left_value
        if right_value == n_houses:
            return right_key, right_value
    if relation_kind in {"directly_right", "somewhere_right"}:
        if left_value == n_houses:
            return left_key, left_value
        if right_value == 1:
            return right_key, right_value
    if relation_kind == "adjacent":
        return None
    return None


def _relation_constraint(relation_kind: str, left_key: str, right_key: str) -> str:
    if relation_kind == "directly_left":
        return f"Int('{left_key}') == Int('{right_key}') - 1"
    if relation_kind == "directly_right":
        return f"Int('{left_key}') == Int('{right_key}') + 1"
    if relation_kind == "somewhere_left":
        return f"Int('{left_key}') < Int('{right_key}')"
    if relation_kind == "somewhere_right":
        return f"Int('{left_key}') > Int('{right_key}')"
    if relation_kind == "adjacent":
        return f"Abs(Int('{left_key}') - Int('{right_key}')) == 1"
    raise ValueError(f"Unsupported relation kind: {relation_kind}")


def _wrong_relation_constraint(relation_kind: str, left_key: str, right_key: str) -> str:
    if relation_kind == "directly_left":
        return f"Int('{left_key}') == Int('{right_key}') + 1"
    if relation_kind == "directly_right":
        return f"Int('{left_key}') == Int('{right_key}') - 1"
    if relation_kind == "somewhere_left":
        return f"Int('{left_key}') > Int('{right_key}')"
    if relation_kind == "somewhere_right":
        return f"Int('{left_key}') < Int('{right_key}')"
    if relation_kind == "adjacent":
        return f"Int('{left_key}') == Int('{right_key}')"
    raise ValueError(f"Unsupported relation kind: {relation_kind}")


def _direct_position_clues(puzzle_text: str) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    pattern = re.compile(
        r"^\s*\d+\.\s+The\s+(?P<value>[A-Za-z0-9][A-Za-z0-9 ]*?)\s+"
        r"(?P<category>[A-Za-z][A-Za-z0-9 ]*?)(?:\s+person)?\s+"
        r"lives\s+in\s+house\s+(?P<house>\d+)\.?\s*$",
        re.I,
    )
    for line in puzzle_text.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        key = _make_key(match.group("category"), match.group("value"))
        found.append((key, int(match.group("house")), line.strip()))
    return found


def _relation_clues(puzzle_text: str) -> list[tuple[str, str, str, str]]:
    found: list[tuple[str, str, str, str]] = []
    patterns = [
        (
            re.compile(
                r"^\s*\d+\.\s+(?P<left>.+?)\s+is\s+"
                r"(?:immediately|directly)\s+left\s+of\s+(?P<right>.+?)\.?\s*$",
                re.I,
            ),
            "directly_left",
        ),
        (
            re.compile(
                r"^\s*\d+\.\s+(?P<left>.+?)\s+is\s+"
                r"(?:immediately|directly)\s+right\s+of\s+(?P<right>.+?)\.?\s*$",
                re.I,
            ),
            "directly_right",
        ),
        (
            re.compile(
                r"^\s*\d+\.\s+(?P<left>.+?)\s+is\s+"
                r"(?:somewhere\s+)?to\s+the\s+left\s+of\s+(?P<right>.+?)\.?\s*$",
                re.I,
            ),
            "somewhere_left",
        ),
        (
            re.compile(
                r"^\s*\d+\.\s+(?P<left>.+?)\s+is\s+"
                r"(?:somewhere\s+)?to\s+the\s+right\s+of\s+(?P<right>.+?)\.?\s*$",
                re.I,
            ),
            "somewhere_right",
        ),
        (
            re.compile(
                r"^\s*\d+\.\s+(?P<left>.+?)\s+and\s+(?P<right>.+?)\s+"
                r"are\s+next\s+to\s+each\s+other\.?\s*$",
                re.I,
            ),
            "adjacent",
        ),
    ]
    for line in puzzle_text.splitlines():
        for pattern, relation_kind in patterns:
            match = pattern.match(line)
            if not match:
                continue
            left_key = _relation_entity_key(match.group("left"))
            right_key = _relation_entity_key(match.group("right"))
            if left_key and right_key:
                found.append((relation_kind, left_key, right_key, line.strip()))
            break
    return found


def _relation_entity_key(entity: str) -> Optional[str]:
    text = re.sub(r"^\s*the\s+", "", entity or "", flags=re.I).strip()
    text = re.sub(r"\s+person\s*$", "", text, flags=re.I).strip()
    parts = [part for part in re.split(r"\s+", text) if part]
    if len(parts) < 2:
        return None
    return _make_key(parts[-1], " ".join(parts[:-1]))


def _make_key(category: str, value: str) -> str:
    category_slug = re.sub(r"[^A-Za-z0-9]+", "_", category.strip()).strip("_")
    category_slug = category_slug[:1].lower() + category_slug[1:]
    value_parts = [part for part in re.split(r"[^A-Za-z0-9]+", value.strip()) if part]
    value_slug = "_".join(part[:1].upper() + part[1:] for part in value_parts)
    return f"{category_slug}_{value_slug}"


def _extract_clues(puzzle_text: str) -> list[str]:
    return [
        line.strip()
        for line in puzzle_text.splitlines()
        if re.match(r"^\d+\.\s+", line.strip())
    ]


def _load_error_library(path: str | None) -> ErrorParadigmLibrary | None:
    if not path:
        return None
    if not Path(path).exists():
        return None
    return ErrorParadigmLibrary(path)


def _add_controlled_error_memory(
    library: ErrorParadigmLibrary | None,
) -> ErrorParadigmLibrary:
    lib = library or ErrorParadigmLibrary(":memory:")
    lib.add(
        ErrorParadigm(
            id="controlled-direct-position-mismatch",
            name="avoid_wrong_direct_position",
            trigger={
                "constraint_types": [
                    "direct_position",
                    "all_different",
                    "distinct_group_mismatch",
                ],
                "z3_result": "UNSAT",
            },
            bad_operation="Int('attribute_Value') == wrong_house",
            unsat_signature="controlled_direct_position",
            avoid_instruction=(
                "Avoid keeping a direct-position assignment that conflicts with "
                "the all-different group."
            ),
            repair_hint=(
                "If the UNSAT core contains a wrong direct house assignment, "
                "use the Controlled repair target when provided and return the "
                "exact equality stated there. Do not weaken the assertion to "
                "!= wrong_house or shrink a Distinct(...) schema constraint."
            ),
            scope=["direct_position", "all_different", "distinct_group_mismatch"],
            confidence=1.0,
            support_count=1,
            source_cluster=-1,
            created_at=datetime.now(tz=timezone.utc),
        )
    )
    return lib


def _add_controlled_target_memory(
    library: ErrorParadigmLibrary | None,
    metadata: dict[str, dict],
) -> ErrorParadigmLibrary:
    lib = library or ErrorParadigmLibrary(":memory:")
    for idx, (puzzle_id, item) in enumerate(sorted(metadata.items()), start=1):
        wrong = str(item.get("controlled_wrong_constraint") or "")
        target = str(item.get("controlled_correct_constraint") or "")
        perturbation_type = str(item.get("controlled_perturbation_type") or "direct_position")
        scope = _memory_scope_for(wrong, perturbation_type)
        if not wrong or not target:
            continue
        lib.add(
            ErrorParadigm(
                id=f"controlled-target-{idx:03d}",
                name=f"replace_{item.get('controlled_perturbed_key', 'direct_position')}",
                trigger={
                    "constraint_types": scope,
                    "bad_constraint": wrong,
                    "replacement_policy": {
                        "target_constraint": target,
                        "source_clue": str(item.get("controlled_source_clue") or ""),
                        "puzzle_id": puzzle_id,
                    },
                    "z3_result": "UNSAT",
                },
                bad_operation=wrong,
                unsat_signature=f"controlled_target_{idx:03d}",
                avoid_instruction=(
                    "This exact controlled assertion conflicts with the "
                    "controlled source clue and should be replaced."
                ),
                repair_hint=(
                    f"Return exactly this replacement expression: {target}. "
                    "Do not weaken it to an inequality or less specific relation."
                ),
                scope=scope,
                confidence=1.0,
                support_count=1,
                source_cluster=-1,
                created_at=datetime.now(tz=timezone.utc),
            )
        )
    return lib


def _add_controlled_template_memory(
    library: ErrorParadigmLibrary | None,
    metadata: dict[str, dict],
) -> ErrorParadigmLibrary:
    lib = library or ErrorParadigmLibrary(":memory:")
    for idx, (puzzle_id, item) in enumerate(sorted(metadata.items()), start=1):
        wrong = str(item.get("controlled_wrong_constraint") or "")
        clue = str(item.get("controlled_source_clue") or "")
        key = str(item.get("controlled_perturbed_key") or "direct_position")
        perturbation_type = str(item.get("controlled_perturbation_type") or "direct_position")
        scope = _memory_scope_for(wrong, perturbation_type)
        if not wrong or not clue:
            continue
        policy_kind = (
            "direct_position_from_source_clue"
            if perturbation_type == "direct_position"
            else f"{perturbation_type}_from_source_clue"
        )
        lib.add(
            ErrorParadigm(
                id=f"controlled-template-{idx:03d}",
                name=f"template_{key}",
                trigger={
                    "constraint_types": scope,
                    "bad_constraint": wrong,
                    "replacement_policy": {
                        "kind": policy_kind,
                        "source_clue": clue,
                        "puzzle_id": puzzle_id,
                    },
                    "z3_result": "UNSAT",
                },
                bad_operation=wrong,
                unsat_signature=f"controlled_template_{idx:03d}",
                avoid_instruction=(
                    "This controlled assertion conflicts with the source clue."
                ),
                repair_hint=(
                    "Parse the source clue and return the corresponding typed "
                    "replacement constraint exactly. Do not weaken it to an "
                    "inequality or less specific relation."
                ),
                scope=scope,
                confidence=1.0,
                support_count=1,
                source_cluster=-1,
                created_at=datetime.now(tz=timezone.utc),
            )
        )
    return lib


def _memory_scope_for(wrong_constraint: str, perturbation_type: str) -> list[str]:
    tags = set(classify_constraint_tags(wrong_constraint))
    tags.discard("unknown")
    tags.add(perturbation_type)
    if perturbation_type == "direct_position":
        tags.update({"direct_position", "all_different", "distinct_group_mismatch"})
    return sorted(tags)


def _save_csv(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = [
        "puzzle_id",
        "domain",
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
        "positive_guidance_triggered",
        "error_guidance_triggered",
        "controlled_perturbed_key",
        "controlled_perturbation_type",
        "controlled_relation_hard_mode",
        "controlled_base_constraints",
        "controlled_correct_constraint",
        "controlled_wrong_constraint",
        "controlled_source_clue",
        "ground_truth",
        "predicted",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def _save_trace_jsonl(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False, default=str))
            fh.write("\n")


if __name__ == "__main__":
    main()
