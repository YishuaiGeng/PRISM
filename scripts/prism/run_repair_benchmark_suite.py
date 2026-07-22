"""Run controlled repair benchmark across all perturbation types and datasets.

Orchestrates multiple runs of ``run_controlled_repair_benchmark.py`` with
consistent settings, collecting no-memory vs template-memory results for
each perturbation type and writing a unified summary CSV.

Usage::

    # Full suite on 3x3/3x4 (150 records)
    python scripts/prism/run_repair_benchmark_suite.py \
        --data data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl \
        --output-dir results/prism/repair_suite_3x

    # Full suite on 5x5/6x5
    python scripts/prism/run_repair_benchmark_suite.py \
        --data data/hf/zebralogic/generated_5x5_6x5_eval_domain_explicit_100.jsonl \
        --output-dir results/prism/repair_suite_5x

    # Smoke test (5 records, single perturbation type)
    python scripts/prism/run_repair_benchmark_suite.py \
        --data data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl \
        --output-dir results/prism/repair_suite_smoke \
        --perturbation-types directly_right \
        --max-records 5
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ALL_PERTURBATION_TYPES = [
    "direct_position",
    "directly_left",
    "directly_right",
    "somewhere_left",
    "somewhere_right",
    "adjacent",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run controlled repair benchmark suite across perturbation types"
    )
    p.add_argument("--data", required=True, help="Input ZebraLogic JSONL file")
    p.add_argument("--model", default="GPT-4o-mini")
    p.add_argument("--output-dir", required=True, help="Output directory for results")
    p.add_argument(
        "--perturbation-types",
        default=None,
        help=(
            "Comma-separated perturbation types to run. "
            f"Default: all ({','.join(_ALL_PERTURBATION_TYPES)})"
        ),
    )
    p.add_argument("--max-records", type=int, default=None, help="Limit input records")
    p.add_argument("--max-repair", type=int, default=1, help="Max repair rounds")
    p.add_argument(
        "--base-constraints",
        default="llm_schema_completed",
        choices=["solution", "llm_validated", "llm_schema_completed"],
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip runs whose output CSV already exists.",
    )
    p.add_argument(
        "--skip-prepare",
        action="store_true",
        help="Skip the prepare step and expect prepared JSONL to exist.",
    )
    return p.parse_args(argv)


def _run_benchmark(
    *,
    data: str,
    model: str,
    perturbation_type: str,
    output_csv: str,
    trace_jsonl: str | None = None,
    max_records: int | None = None,
    max_repair: int = 1,
    base_constraints: str = "llm_schema_completed",
    prepared_output: str | None = None,
    prepared_input: str | None = None,
    template_memory: bool = False,
    no_wrapper_target: bool = True,
) -> int:
    """Run a single controlled repair benchmark instance.

    Returns the process exit code.
    """
    cmd = [
        sys.executable,
        "scripts/run_controlled_repair_benchmark.py",
        "--output", output_csv,
        "--model", model,
        "--perturbation-type", perturbation_type,
        "--max-repair", str(max_repair),
    ]
    # --data is always required by run_controlled_repair_benchmark.py
    cmd.extend(["--data", data])
    if prepared_input:
        cmd.extend(["--prepared-input", prepared_input])
    else:
        cmd.extend(["--base-constraints", base_constraints])
        if max_records:
            cmd.extend(["--max-records", str(max_records)])
    if prepared_output:
        cmd.extend(["--prepared-output", prepared_output])
    if trace_jsonl:
        cmd.extend(["--trace-output", trace_jsonl])
    if template_memory:
        cmd.append("--template-memory")
    if no_wrapper_target:
        cmd.append("--no-wrapper-target")

    # Run from the project root (parent of scripts/)
    project_root = Path(__file__).resolve().parent.parent.parent
    print(f"  CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=False, cwd=str(project_root))
    return result.returncode


def _read_summary(csv_path: str) -> dict:
    """Read a result CSV and compute summary statistics."""
    rows = []
    path = Path(csv_path)
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
    if not rows:
        return {}

    n = len(rows)
    solved = sum(1 for r in rows if r.get("solved", "").lower() == "true")
    memory_eligible = sum(1 for r in rows if r.get("memory_eligible", "").lower() == "true")
    repair_success = sum(1 for r in rows if r.get("repair_success", "").lower() == "true")
    validated_repair = sum(
        1 for r in rows if r.get("validated_repair_success", "").lower() == "true"
    )
    error_guidance = sum(
        1 for r in rows if r.get("error_guidance_triggered", "").lower() == "true"
    )

    return {
        "n": n,
        "solved": solved,
        "accuracy_pct": round(solved / n * 100, 1) if n else 0,
        "memory_eligible": memory_eligible,
        "repair_success": repair_success,
        "validated_repair_success": validated_repair,
        "error_guidance_triggered": error_guidance,
    }


def _run_suite(args: argparse.Namespace) -> None:
    perturbation_types = (
        args.perturbation_types.split(",")
        if args.perturbation_types
        else _ALL_PERTURBATION_TYPES
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Metadata for provenance
    meta = {
        "data": args.data,
        "model": args.model,
        "base_constraints": args.base_constraints,
        "max_records": args.max_records,
        "max_repair": args.max_repair,
        "perturbation_types": perturbation_types,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
    meta_path = output_dir / "suite_metadata.json"
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)

    all_summaries: list[dict] = []

    for pt in perturbation_types:
        print(f"\n{'='*60}")
        print(f"Perturbation type: {pt}")
        print(f"{'='*60}")

        prepared_path = output_dir / f"prepared_{pt}.jsonl"
        nomem_csv = output_dir / f"{pt}_nomemory.csv"
        nomem_trace = output_dir / f"{pt}_nomemory.jsonl"
        memory_csv = output_dir / f"{pt}_template_memory.csv"
        memory_trace = output_dir / f"{pt}_template_memory.jsonl"

        # Step 1: Prepare controlled puzzles (shared between conditions)
        if not args.skip_prepare and not prepared_path.exists():
            print(f"\n--- Preparing {pt} puzzles ---")
            rc = _run_benchmark(
                data=args.data,
                model=args.model,
                perturbation_type=pt,
                output_csv=str(output_dir / f"{pt}_prepare_run.csv"),
                max_records=args.max_records,
                max_repair=args.max_repair,
                base_constraints=args.base_constraints,
                prepared_output=str(prepared_path),
                no_wrapper_target=True,
                template_memory=False,
            )
            if rc != 0:
                print(f"  WARNING: Prepare step exited with code {rc}")
            # Clean up the throwaway prepare run CSV
            throwaway = output_dir / f"{pt}_prepare_run.csv"
            if throwaway.exists():
                throwaway.unlink()

        if not prepared_path.exists():
            print(f"  SKIP {pt}: no prepared puzzles (no matching clues?)")
            all_summaries.append({
                "perturbation_type": pt,
                "condition": "skipped",
                "n": 0,
            })
            continue

        # Count prepared puzzles
        with prepared_path.open(encoding="utf-8") as fh:
            n_prepared = sum(1 for line in fh if line.strip())
        print(f"  Prepared puzzles: {n_prepared}")

        if n_prepared == 0:
            print(f"  SKIP {pt}: 0 prepared puzzles")
            all_summaries.append({
                "perturbation_type": pt,
                "condition": "empty",
                "n": 0,
            })
            continue

        # Step 2: No-memory baseline
        if args.skip_existing and nomem_csv.exists():
            print(f"  SKIP no-memory (exists): {nomem_csv}")
        else:
            print(f"\n--- {pt}: No-memory baseline ---")
            _run_benchmark(
                data=args.data,
                model=args.model,
                perturbation_type=pt,
                output_csv=str(nomem_csv),
                trace_jsonl=str(nomem_trace),
                prepared_input=str(prepared_path),
                max_repair=args.max_repair,
                no_wrapper_target=True,
                template_memory=False,
            )

        # Step 3: Template-memory condition
        if args.skip_existing and memory_csv.exists():
            print(f"  SKIP template-memory (exists): {memory_csv}")
        else:
            print(f"\n--- {pt}: Template-memory ---")
            _run_benchmark(
                data=args.data,
                model=args.model,
                perturbation_type=pt,
                output_csv=str(memory_csv),
                trace_jsonl=str(memory_trace),
                prepared_input=str(prepared_path),
                max_repair=args.max_repair,
                no_wrapper_target=True,
                template_memory=True,
            )

        # Step 4: Collect summaries
        nomem_summary = _read_summary(str(nomem_csv))
        memory_summary = _read_summary(str(memory_csv))

        if nomem_summary:
            all_summaries.append({
                "perturbation_type": pt,
                "condition": "no_memory",
                **nomem_summary,
            })
        if memory_summary:
            all_summaries.append({
                "perturbation_type": pt,
                "condition": "template_memory",
                **memory_summary,
            })

        # Print comparison
        if nomem_summary and memory_summary:
            print(f"\n  --- {pt} comparison ---")
            print(
                f"  No-memory:       {nomem_summary['solved']}/{nomem_summary['n']} "
                f"({nomem_summary['accuracy_pct']}%)"
            )
            print(
                f"  Template-memory: {memory_summary['solved']}/{memory_summary['n']} "
                f"({memory_summary['accuracy_pct']}%)"
            )
            delta = memory_summary["accuracy_pct"] - nomem_summary["accuracy_pct"]
            print(f"  Delta: {delta:+.1f}pp")

    # Write unified summary CSV
    summary_path = output_dir / "suite_summary.csv"
    if all_summaries:
        keys = list(all_summaries[0].keys())
        # Ensure all keys are covered
        for s in all_summaries:
            for k in s:
                if k not in keys:
                    keys.append(k)
        with summary_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_summaries)
        print(f"\nSuite summary saved to: {summary_path}")

    # Print final table
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"{'Perturbation':<20} {'Condition':<18} {'N':>4} {'Solved':>8} {'Acc%':>6}")
    print("-" * 60)
    for s in all_summaries:
        print(
            f"{s.get('perturbation_type',''):<20} "
            f"{s.get('condition',''):<18} "
            f"{s.get('n',0):>4} "
            f"{s.get('solved',''):>8} "
            f"{s.get('accuracy_pct',''):>6}"
        )


def main() -> None:
    args = parse_args()
    _run_suite(args)


if __name__ == "__main__":
    main()
