"""PRISM online inference on the BBH LogicalDeduction benchmark.

Loads a paradigm library and evaluates PRISM on LogicalDeduction (pure
ordering CSPs, multiple-choice scoring).  Mirrors ``run_online.py``; results
are scored by option letter (see
:mod:`prism.evaluation.benchmarks.logical_deduction`).

Usage::

    python scripts/prism/run_logical_deduction.py \
        --model GPT-4o-mini \
        --library paradigm_store/prism_4x5x_v2.db \
        --error-library paradigm_store/error_4x5x_v2.db \
        --tasks logical_deduction_three_objects \
        --max-puzzles 50 \
        --output results/prism/logical_deduction_smoke.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.evaluation.benchmarks.logical_deduction import (
    DEFAULT_TASKS,
    evaluate_logical_deduction,
    load_logical_deduction,
)
from prism.evaluation.metrics import avg_llm_calls, avg_repair_rounds, solve_accuracy
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRISM online inference on LogicalDeduction")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--model", default=None)
    p.add_argument("--library", default="paradigm_store/prism.db")
    p.add_argument("--error-library", default=None)
    p.add_argument("--data-dir", default="data/hf/logical-deduction")
    p.add_argument(
        "--tasks",
        default=",".join(DEFAULT_TASKS),
        help="Comma-separated BBH task names (three/five/seven objects)",
    )
    p.add_argument("--max-puzzles", type=int, default=None)
    p.add_argument("--max-repair", type=int, default=5)
    p.add_argument("--output", default="results/prism/logical_deduction_results.csv")
    p.add_argument(
        "--trace-output",
        default=None,
        help="Optional JSONL path for per-puzzle full step traces.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-paradigm", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument(
        "--schema-hint-mode",
        default="puzzle",
        choices=["puzzle", "none"],
        help="Variable schema guidance source ('solution_keys' is unavailable: "
        "LogicalDeduction records carry no per-entity ground truth).",
    )
    p.add_argument(
        "--translation-normalize",
        default="none",
        choices=["none", "initial", "always"],
    )
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    model_name = args.model or config.get("model_name", "GPT-4o")
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    logger.info("Model: %s | tasks: %s", model_name, tasks)

    # ── Load benchmark ────────────────────────────────────────────────
    puzzles = load_logical_deduction(
        args.data_dir,
        tasks=tasks,
        max_puzzles=args.max_puzzles,
    )
    if not puzzles:
        logger.error("No puzzles loaded from %s. Check --data-dir.", args.data_dir)
        sys.exit(1)
    logger.info("Evaluating on %d puzzles.", len(puzzles))

    # ── Load library ─────────────────────────────────────────────────
    lib_path = ":memory:" if args.no_paradigm else args.library
    solver = Z3SolverWrapper()
    library = ParadigmLibrary(lib_path, solver)
    if not args.no_paradigm and Path(args.library).exists():
        logger.info("Library loaded from %s: %s", args.library, library.stats())
    elif not args.no_paradigm:
        logger.warning("Library file %s not found — using empty library.", args.library)

    error_library = None
    if args.error_library:
        if Path(args.error_library).exists():
            error_library = ErrorParadigmLibrary(args.error_library)
            logger.info(
                "Error library loaded from %s: %s",
                args.error_library,
                error_library.stats(),
            )
        else:
            logger.warning(
                "Error library file %s not found; negative guidance disabled.",
                args.error_library,
            )

    # ── Build solver ──────────────────────────────────────────────────
    llm = LLMClient(model_name=model_name, temperature=0.0)
    guided_solver = GuidedSolver(
        llm_client=llm,
        library=library,
        max_repair_rounds=args.max_repair,
        layer2_enabled=(not args.no_paradigm),
        enable_paradigm=(not args.no_paradigm),
        enable_memory=(not args.no_memory),
        error_library=error_library,
        schema_hint_mode=args.schema_hint_mode,
        translation_normalize=args.translation_normalize,
    )

    # ── Evaluate ──────────────────────────────────────────────────────
    results = evaluate_logical_deduction(guided_solver, puzzles)

    # Final write-back flush (paper §write-back): promote staged candidates
    # that did not reach the auto-flush batch size during the run.
    promoted = guided_solver.flush_candidate_pool()
    if promoted:
        logger.info("Write-back: %d candidate paradigms promoted at end of run.", promoted)

    # ── Report ───────────────────────────────────────────────────────
    acc = solve_accuracy(results)
    extracted = sum(1 for r in results if r.get("prediction_extracted")) / len(results)
    logger.info(
        "Results: Acc=%.1f%% | extracted=%.1f%% | LLM calls=%.2f | repair rounds=%.2f",
        acc * 100,
        extracted * 100,
        avg_llm_calls(results),
        avg_repair_rounds(results),
    )
    by_task: dict[str, list[dict]] = {}
    for row in results:
        by_task.setdefault(str(row.get("task")), []).append(row)
    for task, rows in sorted(by_task.items()):
        logger.info(
            "  %s: Acc=%.1f%% (n=%d)", task, solve_accuracy(rows) * 100, len(rows)
        )

    # ── Save CSV ──────────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _save_csv(results, str(output_path))
    logger.info("Results saved to %s", output_path)
    if args.trace_output:
        trace_path = Path(args.trace_output)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with open(trace_path, "w", encoding="utf-8") as fh:
            for row in results:
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        logger.info("Trace JSONL saved to %s", trace_path)


def _save_csv(results: list[dict], path: str) -> None:
    if not results:
        return
    keys = [
        "puzzle_id",
        "domain",
        "size",
        "task",
        "solved",
        "ground_truth",
        "predicted",
        "prediction_extracted",
        "llm_calls",
        "repair_rounds",
        "final_z3_result",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    main()
