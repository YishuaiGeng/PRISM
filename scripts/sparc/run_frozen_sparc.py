"""Prepare and run prospectively paired SPARC gate experiments.

Historical arms called the LLM separately before reaching SPARC, so they do
not provide a clean component comparison.  This tool freezes the reconstructed
gate input from one no-gate run and reuses that exact constraint state across
all variants.

Preparing a cache and running ``sat_only`` or ``gate_only`` never calls an LLM.
Completion variants require the explicit ``--execute-paid`` acknowledgement.

Examples::

    python scripts/sparc/run_frozen_sparc.py prepare \
      --source-dir results/zebra_v2_s42 --source-system baseline \
      --output results/frozen_s42_baseline.jsonl

    python scripts/sparc/run_frozen_sparc.py run \
      --input results/frozen_s42_baseline.jsonl --variant gate_only \
      --output results/frozen_gate_only.jsonl

    python scripts/sparc/run_frozen_sparc.py run \
      --input results/frozen_s42_baseline.jsonl --variant sparc_k3 \
      --model GPT-4o-mini --seed 42 --execute-paid \
      --output results/frozen_sparc_k3.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance
from prism.evaluation.benchmarks.zebralogic import (
    _solution_to_str,
    answers_match,
    is_scorable,
    load_zebralogic,
)
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary
from scripts.sparc.audit_sparc_evidence import (
    constraints_sha256,
    load_records,
    reconstruct_constraints,
)


VARIANTS = {
    "sat_only": {"sparc": False, "budget": None, "blind": False, "no_invariant": False},
    "gate_only": {"sparc": True, "budget": 0, "blind": False, "no_invariant": False},
    "sparc_k1": {"sparc": True, "budget": 1, "blind": False, "no_invariant": False},
    "sparc_k2": {"sparc": True, "budget": 2, "blind": False, "no_invariant": False},
    "sparc_k3": {"sparc": True, "budget": 3, "blind": False, "no_invariant": False},
    "blind": {"sparc": True, "budget": 3, "blind": True, "no_invariant": False},
    "no_protection": {"sparc": True, "budget": 3, "blind": False, "no_invariant": True},
}
NO_COST_VARIANTS = {"sat_only", "gate_only"}


class _NoCallLLM:
    """Minimal gate-only client that fails loudly if an LLM path is reached."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def reset_call_count(self) -> None:
        self._call_count = 0

    def complete_constraint(self, *args, **kwargs):
        raise RuntimeError("Gate-only replay unexpectedly attempted an LLM call")

    def repair(self, *args, **kwargs):
        raise RuntimeError("Gate-only replay unexpectedly attempted an LLM call")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze and replay identical SPARC gate inputs"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create a frozen gate-input cache")
    prepare.add_argument("--source-dir", type=Path, required=True)
    prepare.add_argument(
        "--source-system", choices=("baseline", "nopar"), required=True
    )
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument(
        "--scorable-only",
        action="store_true",
        help="Keep only records with complete official answers",
    )

    run = subparsers.add_parser("run", help="Run one arm on a frozen cache")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--variant", choices=tuple(VARIANTS), required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--model", default="GPT-4o-mini")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--repair-budget", type=int, default=2)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--execute-paid", action="store_true")
    run.add_argument("--overwrite", action="store_true")
    run.add_argument("--data-dir", default="allenai/ZebraLogicBench")
    run.add_argument("--data-source", default="auto", choices=("auto", "hf", "local"))
    run.add_argument("--data-subset", default="grid_mode")
    return parser.parse_args(argv)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def freeze_rows(
    source_dir: Path, source_system: str, *, scorable_only: bool = False
) -> list[dict]:
    frozen: list[dict] = []
    for item in load_records([source_dir], source_system):
        record = item.record
        if scorable_only and not is_scorable(record.get("ground_truth")):
            continue
        constraints = reconstruct_constraints(record)
        frozen.append(
            {
                "schema_version": 1,
                "repetition": item.repetition,
                "group": item.group,
                "puzzle_id": item.puzzle_id,
                "domain": record.get("domain"),
                "source_system": source_system,
                "source_trace": item.source,
                "source_final_z3_result": record.get("final_z3_result"),
                "source_ground_truth": record.get("ground_truth"),
                "source_predicted": record.get("predicted"),
                "source_solved": bool(record.get("solved")),
                "constraints": constraints,
                "constraints_sha256": constraints_sha256(constraints),
            }
        )
    return frozen


def write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str))
            handle.write("\n")
            count += 1
    return count


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from exc
    return rows


def _build_gate_solver(
    llm,
    *,
    budget: int,
    repair_budget: int,
    blind: bool,
    no_invariant: bool,
) -> GuidedSolver:
    library = ParadigmLibrary(":memory:", Z3SolverWrapper())
    return GuidedSolver(
        llm_client=llm,
        library=library,
        layer2_enabled=False,
        enable_paradigm=False,
        enable_memory=False,
        enable_writeback=False,
        sparc=True,
        sparc_max_completions=budget,
        sparc_repair_budget=repair_budget,
        sparc_blind_completion=blind,
        sparc_no_invariant=no_invariant,
    )


def _rebuild_solver(constraints: Sequence[str]) -> tuple[Z3SolverWrapper, int]:
    solver = Z3SolverWrapper()
    parse_failures = 0
    for constraint in constraints:
        parse_failures += int(not solver.add_constraint(str(constraint)))
    return solver, parse_failures


def replay_row(
    row: dict,
    *,
    variant: str,
    gate_solver: GuidedSolver | None,
    puzzle: PuzzleInstance | None = None,
) -> dict:
    config = VARIANTS[variant]
    base = {
        "schema_version": 1,
        "variant": variant,
        "repetition": row.get("repetition"),
        "group": row.get("group"),
        "puzzle_id": row.get("puzzle_id"),
        "domain": row.get("domain"),
        "ground_truth": row.get("source_ground_truth"),
        "frozen_constraints_sha256": row.get("constraints_sha256"),
        "source_system": row.get("source_system"),
    }
    if variant == "sat_only" or row.get("source_final_z3_result") != "SAT":
        predicted = row.get("source_predicted")
        final = row.get("source_final_z3_result")
        return {
            **base,
            "final_z3_result": final,
            "predicted": predicted,
            "solved": answers_match(base["ground_truth"], predicted),
            "llm_calls": 0,
            "steps": [],
            "parse_failures": 0,
        }

    if gate_solver is None:
        raise ValueError(f"Variant {variant} requires a gate solver")
    if puzzle is None:
        puzzle = PuzzleInstance(puzzle_id=str(row["puzzle_id"]), nl_description="")

    constraints = [str(value) for value in row.get("constraints") or []]
    solver, parse_failures = _rebuild_solver(constraints)
    base_verdict = solver.check()
    if base_verdict != "SAT":
        return {
            **base,
            "final_z3_result": f"FROZEN_REPLAY_{base_verdict}",
            "predicted": None,
            "solved": False,
            "llm_calls": 0,
            "steps": [],
            "parse_failures": parse_failures,
        }

    gate_solver._llm.reset_call_count()
    steps: list[dict] = []
    verdict, final_solver = gate_solver._sparc_gate(puzzle, solver, steps)
    if verdict == "abstain":
        final = "SAT_NONUNIQUE"
        predicted = None
    else:
        final = "SAT"
        predicted = _solution_to_str(final_solver.get_model())
    return {
        **base,
        "final_z3_result": final,
        "predicted": predicted,
        "solved": answers_match(base["ground_truth"], predicted),
        "llm_calls": gate_solver._llm.call_count,
        "steps": steps,
        "parse_failures": parse_failures,
        "final_constraints": final_solver.get_constraints(),
    }


def prepare_command(args: argparse.Namespace) -> None:
    rows = freeze_rows(
        args.source_dir, args.source_system, scorable_only=args.scorable_only
    )
    count = write_jsonl(args.output, rows)
    manifest = {
        "schema_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "source_system": args.source_system,
        "scorable_only": args.scorable_only,
        "record_count": count,
        "output": str(args.output),
        "output_sha256": _sha256_file(args.output),
        "state_definition": (
            "final reconstructed no-gate constraints after replaying explicit "
            "snapshots and accepted repairs; this is the SPARC gate input"
        ),
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {count} frozen gate inputs to {args.output}")


def run_command(args: argparse.Namespace) -> None:
    paid = args.variant not in NO_COST_VARIANTS
    if paid and not args.execute_paid:
        raise SystemExit(
            f"Variant {args.variant} can call an LLM. Re-run with --execute-paid "
            "after reviewing the input count and API budget."
        )
    if args.output.exists() and not args.overwrite:
        raise SystemExit(f"Output exists: {args.output}; use --overwrite to replace it")

    rows = read_jsonl(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    config = VARIANTS[args.variant]
    llm = (
        LLMClient(args.model, temperature=0.0, seed=args.seed)
        if paid
        else _NoCallLLM()
    )
    gate_solver = None
    if config["sparc"]:
        gate_solver = _build_gate_solver(
            llm,
            budget=int(config["budget"]),
            repair_budget=args.repair_budget,
            blind=bool(config["blind"]),
            no_invariant=bool(config["no_invariant"]),
        )

    puzzle_map: dict[str, PuzzleInstance] = {}
    if paid:
        puzzles = load_zebralogic(
            args.data_dir, source=args.data_source, subset=args.data_subset
        )
        puzzle_map = {puzzle.puzzle_id: puzzle for puzzle in puzzles}
        missing = sorted(
            {
                str(row["puzzle_id"])
                for row in rows
                if row.get("source_final_z3_result") == "SAT"
                and str(row["puzzle_id"]) not in puzzle_map
            }
        )
        if missing:
            raise SystemExit(
                f"{len(missing)} SAT puzzle IDs are missing from --data-dir; "
                f"first missing ID: {missing[0]}"
            )

    started = datetime.now(timezone.utc)
    results = [
        replay_row(
            row,
            variant=args.variant,
            gate_solver=gate_solver,
            puzzle=puzzle_map.get(str(row["puzzle_id"])),
        )
        for row in rows
    ]
    count = write_jsonl(args.output, results)
    manifest = {
        "schema_version": 1,
        "status": "completed",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(args.input),
        "input_sha256": _sha256_file(args.input),
        "variant": args.variant,
        "variant_config": config,
        "model": args.model if paid else None,
        "seed": args.seed if paid else None,
        "paid_execution_acknowledged": bool(args.execute_paid),
        "record_count": count,
        "llm_call_count": sum(int(row["llm_calls"]) for row in results),
        "output": str(args.output),
        "output_sha256": _sha256_file(args.output),
    }
    args.output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Wrote {count} paired {args.variant} results to {args.output}; "
        f"LLM calls={manifest['llm_call_count']}"
    )


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.command == "prepare":
        prepare_command(args)
    else:
        run_command(args)


if __name__ == "__main__":
    main()
