"""Ablation and generalization experiment runner.

Executes the experiment suite defined in config/experiments/*.yaml.

Usage::

    python scripts/prism/run_experiments.py --experiment ablation
    python scripts/prism/run_experiments.py --experiment generalization

Experiment types::

    ablation        -- Exp-4: remove each PRISM component one at a time
    generalization  -- Exp-5: L1 cross-scale and L2 cross-domain transfer
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.evaluation.benchmarks.knights_knaves import (
    evaluate_knights_knaves,
    load_knights_knaves,
)
from prism.evaluation.benchmarks.zebralogic import evaluate_zebralogic, load_zebralogic
from prism.evaluation.metrics import generate_report, solve_accuracy
from prism.evaluation.transfer_rate import l1_cross_scale_summary, l2_cross_domain_summary
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRISM experiment runner")
    p.add_argument("--experiment", choices=["ablation", "generalization"], default="ablation")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--exp-config", default=None, help="Override experiment config path")
    p.add_argument("--output-dir", default="results/prism/experiments")
    p.add_argument("--model", default=None)
    p.add_argument("--library", default="paradigm_store/prism.db")
    p.add_argument("--data-dir", default="allenai/ZebraLogicBench")
    p.add_argument("--data-source", default="auto", choices=["auto", "hf", "local"])
    p.add_argument("--data-subset", default="grid_mode")
    p.add_argument("--knk-data-dir", default="K-and-K/knights-and-knaves")
    p.add_argument("--knk-data-source", default="auto", choices=["auto", "hf", "local"])
    p.add_argument("--knk-subset", default="test")
    p.add_argument(
        "--schema-hint-mode",
        default="puzzle",
        choices=["puzzle", "none", "solution_keys"],
        help=(
            "Variable schema guidance source. 'solution_keys' is an oracle "
            "upper-bound diagnostic, not a main benchmark setting."
        ),
    )
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    model_name = args.model or config.get("model_name", "GPT-4o")

    exp_config_path = args.exp_config or f"config/experiments/{args.experiment}.yaml"
    exp_config = load_config(exp_config_path)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.experiment == "ablation":
        run_ablation(args, config, exp_config, model_name, output_dir)
    else:
        run_generalization(args, config, exp_config, model_name, output_dir)


# --------------------------------------------------------------------------- #
# Ablation                                                                      #
# --------------------------------------------------------------------------- #

def run_ablation(args, config, exp_config, model_name, output_dir):
    """Exp-4: remove each PRISM component and measure the accuracy delta."""
    sizes = exp_config.get("sizes", ["4x5", "5x5", "6x6"])
    puzzles = load_zebralogic(
        args.data_dir,
        sizes=sizes,
        source=args.data_source,
        subset=args.data_subset,
    )
    if not puzzles:
        logger.error("No ablation puzzles loaded.")
        return

    variants = exp_config.get("variants", {})
    all_results: Dict[str, list] = {}

    for variant_name, variant_cfg in variants.items():
        logger.info("Running ablation variant: %s", variant_name)
        solver = _build_solver(
            model_name=model_name,
            library_path=args.library,
            no_paradigm=variant_cfg.get("no_paradigm", False),
            no_memory=variant_cfg.get("no_memory", False),
            max_repair=variant_cfg.get("max_repair", 5),
            schema_hint_mode=getattr(args, "schema_hint_mode", "puzzle"),
        )
        results = evaluate_zebralogic(solver, puzzles)
        all_results[variant_name] = results

        acc = solve_accuracy(results)
        logger.info("  Variant %s: Acc=%.1f%%", variant_name, acc * 100)

    _save_ablation_csv(all_results, sizes, output_dir / "ablation.csv")
    logger.info("Ablation results saved.")


# --------------------------------------------------------------------------- #
# Generalization                                                                 #
# --------------------------------------------------------------------------- #

def run_generalization(args, config, exp_config, model_name, output_dir):
    """Exp-5: L1 cross-scale and L2 cross-domain transfer experiments."""
    l1_configs = exp_config.get("l1_configs", {})
    l2_enabled = exp_config.get("l2_enabled", False)
    test_sizes = exp_config.get("test_sizes", ["3x5", "4x5", "5x5", "5x6", "6x6"])

    # ── L1: cross-scale ──────────────────────────────────────────────
    l1_config_results: Dict[str, list] = {}
    for config_label, cfg in l1_configs.items():
        logger.info("L1 config: %s", config_label)
        train_sizes = cfg.get("train_sizes", [])
        lib_path = cfg.get("library_path", args.library)

        puzzles = load_zebralogic(
            args.data_dir,
            sizes=test_sizes,
            source=args.data_source,
            subset=args.data_subset,
        )
        solver = _build_solver(
            model_name=model_name,
            library_path=lib_path,
            schema_hint_mode=getattr(args, "schema_hint_mode", "puzzle"),
        )
        results = evaluate_zebralogic(solver, puzzles)
        for r in results:
            r["config"] = config_label
        l1_config_results[config_label] = results

    rows = l1_cross_scale_summary(l1_config_results, test_sizes)
    _save_l1_csv(rows, output_dir / "l1_transfer.csv")
    logger.info("L1 transfer results saved.")

    # ── L2: cross-domain ─────────────────────────────────────────────
    if l2_enabled:
        logger.info("Running L2 KnK transfer...")
        knk_puzzles = load_knights_knaves(
            args.knk_data_dir,
            max_puzzles=200,
            source=args.knk_data_source,
            subset=args.knk_subset,
        )
        solver = _build_solver(
            model_name=model_name,
            library_path=args.library,
            schema_hint_mode=getattr(args, "schema_hint_mode", "puzzle"),
        )
        zebra_results = load_zebralogic(
            args.data_dir,
            sizes=["4x5"],
            source=args.data_source,
            subset=args.data_subset,
        )
        zebra_eval = evaluate_zebralogic(solver, zebra_results[:50] if zebra_results else [])
        knk_results = evaluate_knights_knaves(solver, knk_puzzles)

        summary = l2_cross_domain_summary(zebra_eval, knk_results)
        logger.info("L2 summary: %s", summary)

        with open(output_dir / "l2_transfer.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(summary.keys()))
            writer.writeheader()
            writer.writerow(summary)
        logger.info("L2 transfer results saved.")


# --------------------------------------------------------------------------- #
# Helpers                                                                        #
# --------------------------------------------------------------------------- #

def _build_solver(
    model_name: str,
    library_path: str,
    no_paradigm: bool = False,
    no_memory: bool = False,
    max_repair: int = 5,
    schema_hint_mode: str = "puzzle",
) -> GuidedSolver:
    llm = LLMClient(model_name=model_name, temperature=0.0)
    lib_path = ":memory:" if no_paradigm else library_path
    solver_z3 = Z3SolverWrapper()
    library = ParadigmLibrary(lib_path, solver_z3)
    if not no_paradigm and Path(library_path).exists():
        library.load_json(library_path.replace(".db", ".json"))
    return GuidedSolver(
        llm_client=llm,
        library=library,
        max_repair_rounds=max_repair,
        layer2_enabled=not no_paradigm,
        enable_paradigm=not no_paradigm,
        enable_memory=not no_memory,
        schema_hint_mode=schema_hint_mode,
    )


def _save_ablation_csv(all_results: Dict[str, list], sizes: List[str], path: Path) -> None:
    rows = []
    for variant, results in all_results.items():
        by_size: Dict[str, list] = {}
        for r in results:
            by_size.setdefault(r.get("domain", ""), []).append(r)
        row: Dict[str, object] = {"variant": variant}
        for size in sizes:
            row[size] = f"{solve_accuracy(by_size.get(size, [])) * 100:.1f}%"
        row["avg"] = f"{solve_accuracy(results) * 100:.1f}%"
        rows.append(row)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        if rows:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


def _save_l1_csv(rows: List[Dict], path: Path) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
