"""Online inference entry point.

Loads a paradigm library and evaluates PRISM on the ZebraLogic benchmark.

Usage::

    python scripts/prism/run_online.py --config config/default.yaml

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
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRISM online inference on ZebraLogic")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--model", default=None)
    p.add_argument("--library", default="paradigm_store/prism.db")
    p.add_argument("--error-library", default=None)
    p.add_argument("--data-dir", default="allenai/ZebraLogicBench")
    p.add_argument("--data-source", default="auto", choices=["auto", "hf", "local"])
    p.add_argument("--data-subset", default="grid_mode")
    p.add_argument("--sizes", default=None, help="Comma-separated sizes, e.g. '4x5,5x5'")
    p.add_argument("--max-repair", type=int, default=5)
    p.add_argument("--output", default="results/prism/online_results.csv")
    p.add_argument(
        "--trace-output",
        default=None,
        help="Optional JSONL path for per-puzzle full step traces.",
    )
    p.add_argument(
        "--manifest-output",
        default=None,
        help="Run-provenance JSON path. Defaults to <output>.manifest.json.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-paradigm", action="store_true")
    p.add_argument("--no-memory", action="store_true")
    p.add_argument(
        "--sparc",
        action="store_true",
        help="Enable the SPARC structural-prior gate: accept a SAT model only "
        "if it is the unique solution; otherwise run diff-guided completion "
        "or abstain (final_z3_result=SAT_NONUNIQUE).",
    )
    p.add_argument(
        "--sparc-max-completions",
        type=int,
        default=3,
        help="Diff-completion budget per puzzle. 0 = gate-only ablation "
        "(detect under-constraint and abstain, no completion).",
    )
    p.add_argument(
        "--sparc-blind-completion",
        action="store_true",
        help="Ablation: completion without diff attribution (no model-diff "
        "summary in the prompt, no progress check).",
    )
    p.add_argument(
        "--sparc-no-invariant",
        action="store_true",
        help="Ablation: conflict repair without evidence protection or the "
        "no-weakening instruction.",
    )
    p.add_argument(
        "--sparc-va-mode",
        default="whitelist",
        choices=["whitelist", "all_int"],
        help="Answer-projection V_A for the uniqueness probe. 'whitelist' "
        "restricts blocking to answer variables derived from visible puzzle "
        "inputs (falls back to all integers when nothing matches); 'all_int' "
        "is the legacy all-non-tracked-integer approximation.",
    )
    p.add_argument(
        "--schema-hint-mode",
        default="puzzle",
        choices=["puzzle", "none", "solution_keys"],
        help=(
            "Variable schema guidance source. 'puzzle' uses only visible puzzle "
            "text/metadata; 'solution_keys' is an oracle upper-bound diagnostic."
        ),
    )
    p.add_argument(
        "--translation-normalize",
        default="none",
        choices=["none", "initial", "always"],
        help=(
            "Optional second-pass LLM cleanup of translated constraints before "
            "Z3 solving. 'initial' normalizes the first translation; 'always' "
            "also normalizes validation/retranslation output."
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

    llm = LLMClient(model_name=model_name, temperature=0.0, seed=args.seed)
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
        sparc=args.sparc,
        sparc_max_completions=args.sparc_max_completions,
        sparc_blind_completion=args.sparc_blind_completion,
        sparc_no_invariant=args.sparc_no_invariant,
        sparc_va_mode=args.sparc_va_mode,
    )

    output_path = Path(args.output)
    manifest_path = (
        Path(args.manifest_output)
        if args.manifest_output
        else output_path.with_suffix(".manifest.json")
    )
    started_at = datetime.now(timezone.utc)
    manifest = _build_run_manifest(
        args=args,
        llm=llm,
        puzzles=puzzles,
        started_at=started_at,
        output_path=output_path,
    )
    _write_manifest(manifest_path, manifest)

    # ── Evaluate ──────────────────────────────────────────────────────
    try:
        results = evaluate_zebralogic(guided_solver, puzzles)
    except BaseException as exc:
        manifest.update(
            {
                "status": "failed",
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        _write_manifest(manifest_path, manifest)
        raise

    # Final write-back flush: promote any staged candidates that did not
    # reach the auto-flush batch size during the run (paper §write-back).
    promoted = guided_solver.flush_candidate_pool()
    if promoted:
        logger.info("Write-back: %d candidate paradigms promoted at end of run.", promoted)

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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _save_csv(results, str(output_path))
    logger.info("Results saved to %s", output_path)
    if args.trace_output:
        trace_path = Path(args.trace_output)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        _save_trace_jsonl(results, str(trace_path))
        logger.info("Trace JSONL saved to %s", trace_path)

    manifest.update(
        {
            "status": "completed",
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "result_count": len(results),
            "llm_call_count": sum(int(row.get("llm_calls", 0)) for row in results),
            "artifacts": {
                "csv": _artifact_record(output_path),
                "trace": _artifact_record(Path(args.trace_output))
                if args.trace_output
                else None,
            },
        }
    )
    _write_manifest(manifest_path, manifest)
    logger.info("Run manifest saved to %s", manifest_path)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path) -> dict:
    return {
        "path": str(path),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": _sha256_file(path),
    }


def _build_run_manifest(
    *,
    args: argparse.Namespace,
    llm: LLMClient,
    puzzles: list,
    started_at: datetime,
    output_path: Path,
) -> dict:
    project_root = Path(__file__).resolve().parent.parent.parent
    tracked_inputs = (
        Path(args.config),
        project_root / "config/api/model_configs.json",
        project_root / "config/api/api_configs.json",
        project_root / "prism/core/llm_client.py",
        project_root / "prism/online/guided_solver.py",
        Path(__file__).resolve(),
    )
    puzzle_ids = [str(puzzle.puzzle_id) for puzzle in puzzles]
    arguments = {key: value for key, value in vars(args).items()}
    return {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": started_at.isoformat(),
        "requested_model_alias": llm.model_name,
        "configured_model_sources": llm.model_config.get("api_sources", []),
        "provider_override": os.environ.get("OPENZEBRA_API_PROVIDER") or None,
        "immutable_provider_revision": None,
        "immutable_provider_revision_note": (
            "The configured endpoint does not expose an immutable served-model "
            "revision; configured source identifiers are recorded instead."
        ),
        "temperature": 0.0,
        "requested_seed": args.seed,
        "seed_forwarded_on_requests": llm.seed == args.seed,
        "determinism_note": (
            "A forwarded seed improves request reproducibility only when the "
            "selected provider/model honors it; it is not a bitwise guarantee."
        ),
        "arguments": arguments,
        "command": [sys.executable, *sys.argv],
        "output_path": str(output_path),
        "puzzle_count": len(puzzles),
        "puzzle_ids_sha256": _sha256_bytes(
            json.dumps(puzzle_ids, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ),
        "input_hashes": {
            str(path): _sha256_file(path)
            for path in tracked_inputs
        },
    }


def _write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _save_csv(results: list[dict], path: str) -> None:
    if not results:
        return
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
        "translation_failed",
        "repair_success",
        "validated_repair_success",
        "repair_rejected",
        "invalid_model_retranslate",
        "misaligned_model_retranslate",
        "invalid_model",
        "model_schema_aligned",
        "model_key_set_aligned",
        "misaligned_model",
        "key_mismatch",
        "positive_guidance_triggered",
        "error_guidance_triggered",
        "ground_truth",
        "predicted",
    ]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def _save_trace_jsonl(results: list[dict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False, default=str))
            fh.write("\n")


if __name__ == "__main__":
    main()
