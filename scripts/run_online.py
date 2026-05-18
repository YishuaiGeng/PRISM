"""Online inference entry point.

Loads a paradigm library and evaluates PRISM on the ZebraLogic benchmark.

Usage::

    python scripts/run_online.py --config config/default.yaml

Key flags::

    --config      Path to YAML configuration file
    --model       LLM model name (overrides config)
    --library     Path to paradigm library (.db file)
    --data-dir    Path to ZebraLogic benchmark data
    --sizes       Puzzle sizes to evaluate (e.g. "4x5,5x5,6x6")
    --max-repair  Maximum repair rounds per puzzle (default: 5)
    --output      Output CSV path for per-puzzle results
    --seed        Random seed for reproducibility
    --no-paradigm Disable paradigm library (ablation)
    --no-memory   Disable repair memory (ablation)
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.evaluation.benchmarks.zebralogic import evaluate_zebralogic, load_zebralogic
from prism.evaluation.metrics import (
    avg_llm_calls,
    avg_repair_rounds,
    generate_report,
    paradigm_hit_rate,
    paradigm_trigger_rate,
    solve_accuracy,
)
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRISM online inference on ZebraLogic")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--model", default=None)
    p.add_argument("--library", default="paradigm_store/prism.db")
    p.add_argument("--data-dir", default="allenai/ZebraLogicBench")
    p.add_argument("--data-source", default="auto", choices=["auto", "hf", "local"])
    p.add_argument("--data-subset", default="grid_mode")
    p.add_argument("--sizes", default=None, help="Comma-separated sizes, e.g. '4x5,5x5'")
    p.add_argument("--max-repair", type=int, default=5)
    p.add_argument("--output", default="results/online_results.csv")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-paradigm", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    model_name = args.model or config.get("model_name", "GPT-4o")
    sizes = args.sizes.split(",") if args.sizes else None
    logger.info("Model: %s | sizes: %s", model_name, sizes or "all")

    # ── Load benchmark ────────────────────────────────────────────────
    puzzles = load_zebralogic(
        args.data_dir,
        sizes=sizes,
        source=args.data_source,
        subset=args.data_subset,
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

    # ── Build solver ──────────────────────────────────────────────────
    llm = LLMClient(model_name=model_name, temperature=0.0)
    guided_solver = GuidedSolver(
        llm_client=llm,
        library=library,
        max_repair_rounds=args.max_repair,
        layer2_enabled=(not args.no_paradigm),
        enable_paradigm=(not args.no_paradigm),
        enable_memory=(not args.no_memory),
    )

    # ── Evaluate ──────────────────────────────────────────────────────
    results = evaluate_zebralogic(guided_solver, puzzles)

    # ── Report ───────────────────────────────────────────────────────
    acc = solve_accuracy(results)
    calls = avg_llm_calls(results)
    rounds = avg_repair_rounds(results)
    trig = paradigm_trigger_rate(results)
    hit = paradigm_hit_rate(results)
    logger.info(
        "Results: Acc=%.1f%% | LLM calls=%.2f | Repair rounds=%.2f | "
        "Paradigm trigger=%.1f%% | Hit=%.1f%%",
        acc * 100, calls, rounds, trig * 100, hit * 100,
    )

    report = generate_report(results, library.stats(), title="PRISM Online Evaluation")
    print(report)

    # ── Save CSV ──────────────────────────────────────────────────────
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _save_csv(results, str(output_path))
    logger.info("Results saved to %s", output_path)


def _save_csv(results: list[dict], path: str) -> None:
    if not results:
        return
    keys = ["puzzle_id", "domain", "solved", "llm_calls", "repair_rounds"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    main()
