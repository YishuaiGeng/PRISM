"""PRISM online inference on the AR-LSAT benchmark.

Loads a paradigm library and evaluates PRISM on AR-LSAT (LSAT analytical
reasoning, five-option multiple choice).  Mirrors ``run_online.py``; the
passage is formalised by the guided solver, options are checked per the
SatLM-style protocol (see :mod:`prism.evaluation.benchmarks.arlsat`).

Usage::

    python scripts/prism/run_arlsat.py \
        --model GPT-4o-mini \
        --library paradigm_store/arlsat_train.db \
        --split test \
        --max-puzzles 20 \
        --output results/prism/arlsat_smoke.csv
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
from prism.evaluation.benchmarks.arlsat import (
    ARLSATOptionChecker,
    WellDefinednessGate,
    evaluate_arlsat,
    load_arlsat,
)
from prism.evaluation.metrics import avg_llm_calls, avg_repair_rounds, solve_accuracy
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRISM online inference on AR-LSAT")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--model", default=None)
    p.add_argument("--library", default="paradigm_store/prism.db")
    p.add_argument("--error-library", default=None)
    p.add_argument("--data-dir", default="data/hf/ar-lsat")
    p.add_argument(
        "--split",
        default="test",
        choices=["train", "dev", "test"],
        help="Report on test (230 q, Logic-LM comparable); tune on dev (231 q).",
    )
    p.add_argument("--max-puzzles", type=int, default=None)
    p.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N questions (for sharding across parallel workers).",
    )
    p.add_argument("--max-repair", type=int, default=5)
    p.add_argument("--output", default="results/prism/arlsat_results.csv")
    p.add_argument(
        "--trace-output",
        default=None,
        help="Optional JSONL path for per-question full step traces.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--fallback",
        default="random",
        choices=["random", "none"],
        help="Backup protocol for questions with no solver-derived candidate: "
        "'random' = seeded guess (Logic-LM protocol, default), 'none' = "
        "leave unanswered (scored wrong).",
    )
    p.add_argument("--no-paradigm", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument(
        "--pi-gate",
        action="store_true",
        help="Enable the well-definedness gate (SPARC pi-gate, AR-LSAT "
        "instantiation): candidate count != 1 routes to gate repair; "
        "unresolved questions are abstained, never guessed.",
    )
    p.add_argument("--gate-budget", type=int, default=2)
    p.add_argument(
        "--schema-hint-mode",
        default="none",
        choices=["puzzle", "none"],
        help="AR-LSAT carries no fixed variable schema; default 'none'.",
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
    logger.info("Model: %s | split: %s", model_name, args.split)

    # ── Load benchmark ────────────────────────────────────────────────
    puzzles = load_arlsat(
        args.data_dir,
        split=args.split,
        max_puzzles=args.max_puzzles,
        offset=args.offset,
    )
    if not puzzles:
        logger.error("No questions loaded from %s. Check --data-dir.", args.data_dir)
        sys.exit(1)
    logger.info("Evaluating on %d questions.", len(puzzles))

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
    option_checker = ARLSATOptionChecker(llm)
    gate = WellDefinednessGate(llm, budget=args.gate_budget) if args.pi_gate else None
    if gate:
        logger.info("Well-definedness gate ON (budget=%d); fallback disabled.", args.gate_budget)

    # ── Evaluate ──────────────────────────────────────────────────────
    results = evaluate_arlsat(
        guided_solver,
        puzzles,
        option_checker,
        fallback=args.fallback,
        seed=args.seed,
        gate=gate,
    )

    # Final write-back flush (paper §write-back): promote staged candidates
    # that did not reach the auto-flush batch size during the run.
    promoted = guided_solver.flush_candidate_pool()
    if promoted:
        logger.info("Write-back: %d candidate paradigms promoted at end of run.", promoted)

    # ── Report ───────────────────────────────────────────────────────
    acc = solve_accuracy(results)
    extracted = sum(1 for r in results if r.get("prediction_extracted")) / len(results)
    ambiguous = sum(1 for r in results if r.get("ambiguous")) / len(results)
    fallback_used = sum(1 for r in results if r.get("fallback_used")) / len(results)
    logger.info(
        "Results: Acc=%.1f%% | extracted=%.1f%% | fallback=%.1f%% | "
        "ambiguous=%.1f%% | LLM calls=%.2f | repair rounds=%.2f",
        acc * 100,
        extracted * 100,
        fallback_used * 100,
        ambiguous * 100,
        avg_llm_calls(results),
        avg_repair_rounds(results),
    )
    # Three-value ledger (answered right / answered wrong / abstained).
    answered = [r for r in results if r.get("predicted")]
    abstained = len(results) - len(answered)
    wrong = sum(1 for r in answered if not r.get("solved"))
    logger.info(
        "Ledger: answered=%d (right=%d, wrong=%d, risk=%.0f%%) | abstained=%d",
        len(answered), len(answered) - wrong, wrong,
        (wrong / len(answered) * 100) if answered else 0.0, abstained,
    )
    by_type: dict[str, list[dict]] = {}
    for row in results:
        by_type.setdefault(str(row.get("question_type")), []).append(row)
    for qtype, rows in sorted(by_type.items()):
        logger.info(
            "  %s: Acc=%.1f%% (n=%d)", qtype, solve_accuracy(rows) * 100, len(rows)
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
        "split",
        "passage_id",
        "question_type",
        "is_except",
        "solved",
        "ground_truth",
        "predicted",
        "prediction_extracted",
        "fallback_used",
        "ambiguous",
        "gate_abstain",
        "gate_initial_candidates",
        "gate_final_candidates",
        "gate_rounds",
        "gate_completions",
        "gate_option_retranslated",
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
