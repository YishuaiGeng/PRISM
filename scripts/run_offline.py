"""Offline paradigm distillation pipeline.

Runs the full offline phase:
  1. Generate training puzzles using PuzzleGenerator
  2. Collect solving trajectories via TrajectoryCollector (Paper-1 pipeline)
  3. Extract KDPs with KDPIdentifier
  4. Cluster KDPs with TrajectoryClusterer
  5. Abstract paradigms from clusters with ParadigmAbstractor
  6. Verify and ingest paradigms into ParadigmLibrary

Usage::

    python scripts/run_offline.py --config config/default.yaml

Key flags::

    --config        Path to YAML configuration file
    --model         LLM model name (overrides config)
    --n-puzzles     Total training puzzles to generate (default: 600)
    --n-runs        Trajectory collection runs per puzzle (default: 3)
    --output        Path to output paradigm library (default: paradigm_store/prism.db)
    --trajectories  Path to save/load trajectory JSON files
    --resume        Load existing trajectories instead of regenerating
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.generator import PuzzleGenerator
from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.core.types import Trajectory
from prism.offline.kdp_identifier import KDPIdentifier
from prism.offline.paradigm_abstractor import ParadigmAbstractor
from prism.offline.paradigm_verifier import ParadigmVerifier
from prism.offline.trajectory_clusterer import TrajectoryClusterer
from prism.offline.trajectory_collector import TrajectoryCollector
from prism.paradigm_library.library import ParadigmLibrary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRISM offline paradigm distillation")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--model", default=None)
    p.add_argument(
        "--benchmark",
        default="zebra",
        choices=["zebra", "arlsat"],
        help="Training-puzzle source: 'zebra' generates grid puzzles, "
        "'arlsat' loads the AR-LSAT train split from --data-dir.",
    )
    p.add_argument("--data-dir", default="data/hf/ar-lsat")
    p.add_argument("--split", default="train")
    p.add_argument("--n-puzzles", type=int, default=None)
    p.add_argument("--n-runs", type=int, default=None)
    p.add_argument(
        "--puzzle-specs",
        default=None,
        help=(
            "Comma-separated generation specs: count:NxM:difficulty, "
            "e.g. '6:3x3:easy,6:3x4:easy'. Overrides --n-puzzles distribution."
        ),
    )
    p.add_argument("--output", default="paradigm_store/prism.db")
    p.add_argument("--trajectories", default="data/trajectories")
    p.add_argument("--resume", action="store_true", help="Load existing trajectories from --trajectories dir")
    p.add_argument(
        "--trajectory-verdicts",
        default=None,
        help="JSON file {trajectory_id: verdict} from verify_arlsat_trajectories.py; "
        "only 'correct' (answer-verified) trajectories are mined.",
    )
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    thresholds = config.get("thresholds", {})
    quick_test = config.get("quick_test", {})

    model_name = args.model or config.get("model_name", "GPT-4o")
    logger.info("Model: %s", model_name)
    n_puzzles = args.n_puzzles if args.n_puzzles is not None else quick_test.get("n_puzzles", 600)
    n_runs = args.n_runs if args.n_runs is not None else quick_test.get("n_runs", 3)
    # thresholds is the canonical source for R; quick_test may override it
    # for smoke runs (default.yaml has no quick_test section).
    max_repair_rounds = quick_test.get(
        "max_repair_rounds", thresholds.get("max_repair_rounds", 5)
    )

    # ── 1. Load or generate training puzzles ──────────────────────────
    traj_dir = Path(args.trajectories)
    puzzles = []
    if args.resume and traj_dir.exists():
        logger.info("Skipping puzzle loading because --resume is set and %s exists.", traj_dir)
    elif args.benchmark == "arlsat":
        from prism.evaluation.benchmarks.arlsat import load_arlsat  # noqa: PLC0415

        puzzles = load_arlsat(args.data_dir, split=args.split, max_puzzles=n_puzzles)
        logger.info("Loaded %d AR-LSAT %s questions.", len(puzzles), args.split)
    else:
        logger.info("Generating %d training puzzles...", n_puzzles)
        gen = PuzzleGenerator(seed=args.seed)
        specs = _parse_puzzle_specs(args.puzzle_specs, n_puzzles)
        for count, n_entities, n_attrs, difficulty in specs:
            if count <= 0:
                continue
            try:
                puzzles.extend(gen.generate(count, n_entities=n_entities, n_attrs=n_attrs, difficulty=difficulty))
            except RuntimeError as exc:
                if difficulty != "hard":
                    raise
                logger.warning("%s; falling back to medium %dx%d puzzles.", exc, n_entities, n_attrs)
                puzzles.extend(gen.generate(count, n_entities=n_entities, n_attrs=n_attrs, difficulty="medium"))
        logger.info("Generated %d puzzles.", len(puzzles))

    # ── 2. Collect trajectories ────────────────────────────────────────
    if args.resume and traj_dir.exists():
        logger.info("Loading trajectories from %s", traj_dir)
        trajectories = _load_trajectories(traj_dir)
        logger.info("Loaded %d trajectories.", len(trajectories))
        if args.trajectory_verdicts:
            with open(args.trajectory_verdicts, encoding="utf-8") as fh:
                verdicts = json.load(fh)
            before = len(trajectories)
            trajectories = [
                t for t in trajectories if verdicts.get(t.trajectory_id) == "correct"
            ]
            logger.info(
                "Verdict filter: kept %d/%d answer-verified trajectories.",
                len(trajectories), before,
            )
    else:
        llm = LLMClient(model_name=model_name, temperature=0.7)
        collector = TrajectoryCollector(
            llm_client=llm,
            max_repair_rounds=max_repair_rounds,
            output_dir=str(traj_dir),
        )
        logger.info("Collecting trajectories (%d runs/puzzle)...", n_runs)
        trajectories = collector.collect(puzzles, n_runs=n_runs, temperature=0.7)
        logger.info("Collected %d trajectories. Total LLM calls: %d", len(trajectories), llm.call_count)

    # ── 3. KDP extraction ─────────────────────────────────────────────
    logger.info("Extracting KDPs...")
    identifier = KDPIdentifier(
        domain_drop_threshold=thresholds.get("kdp_domain_drop", 2),
        info_gain_bits_threshold=thresholds.get("kdp_info_gain_bits", 1.0),
    )
    kdps = [kdp for traj in trajectories for kdp in identifier.identify(traj)]
    logger.info("Extracted %d KDPs from %d trajectories.", len(kdps), len(trajectories))

    # ── 4. Clustering ─────────────────────────────────────────────────
    theta = thresholds.get("cluster_distance", 0.25)
    min_support = thresholds.get("cluster_min_size", thresholds.get("min_support", 5))
    logger.info("Clustering KDPs (theta=%.2f, min_support=%d)...", theta, min_support)
    clusterer = TrajectoryClusterer(theta=theta, min_support=min_support)
    clusters = clusterer.cluster(kdps)
    logger.info("Produced %d clusters with sufficient support.", len(clusters))

    # ── 5. Paradigm abstraction ────────────────────────────────────────
    llm_eval = LLMClient(model_name=model_name, temperature=0.0)
    abstractor = ParadigmAbstractor(llm_client=llm_eval)
    logger.info("Abstracting paradigms from %d clusters...", len(clusters))
    candidates = [p for c in clusters if (p := abstractor.abstract(c)) is not None]
    logger.info("Abstracted %d candidate paradigms.", len(candidates))

    # ── 6. Verification and ingestion ─────────────────────────────────
    verifier = ParadigmVerifier(
        n_samples=thresholds.get("verification_trials", thresholds.get("verify_samples", 50)),
        soundness_threshold=thresholds.get("paradigm_soundness", 0.90),
        trigger_precision_floor=thresholds.get("paradigm_precision_floor", 0.20),
    )
    solver = Z3SolverWrapper()
    library = ParadigmLibrary(args.output, solver, soundness_threshold=thresholds.get("paradigm_soundness", 0.90))

    accepted = 0
    candidate_diagnostics = []
    for paradigm in candidates:
        soundness = verifier.verify_soundness(paradigm, solver)
        effect = verifier.verify_effect(paradigm)
        precision = verifier.verify_trigger_precision(paradigm)
        confidence = verifier.verify(paradigm, solver)
        candidate_diagnostics.append({
            "id": paradigm.id,
            "name": paradigm.name,
            "operation": paradigm.operation,
            "pre_condition": paradigm.pre_condition,
            "scope": paradigm.scope,
            "trigger": paradigm.trigger,
            "support_count": paradigm.support_count,
            "source_cluster": paradigm.source_cluster,
            "scores": {
                "soundness": soundness,
                "effect": effect,
                "precision": precision,
                "verify": confidence,
            },
        })
        if confidence >= thresholds.get("paradigm_soundness", 0.90):
            paradigm = paradigm.model_copy(update={"confidence": confidence})
            if library.add(paradigm, verify=False):
                accepted += 1

    stats = library.stats()
    logger.info(
        "Offline distillation complete. Accepted %d/%d paradigms. Library stats: %s",
        accepted, len(candidates), stats,
    )
    library.save_json(args.output.replace(".db", ".json"))
    diagnostics_path = args.output.replace(".db", "_candidates.json")
    with open(diagnostics_path, "w", encoding="utf-8") as fh:
        json.dump(candidate_diagnostics, fh, ensure_ascii=False, indent=2)
    logger.info("Candidate diagnostics saved to %s", diagnostics_path)


def _load_trajectories(traj_dir: Path) -> list[Trajectory]:
    trajectories = []
    for json_file in sorted(traj_dir.glob("*.json")):
        with open(json_file, encoding="utf-8") as fh:
            data = json.load(fh)
        trajectories.append(Trajectory.model_validate(data))
    return trajectories


def _parse_puzzle_specs(spec_text: str | None, n_puzzles: int) -> list[tuple[int, int, int, str]]:
    if not spec_text:
        counts = [n_puzzles // 3] * 3
        for i in range(n_puzzles % 3):
            counts[i] += 1
        return [
            (counts[0], 3, 5, "medium"),
            (counts[1], 4, 5, "medium"),
            (counts[2], 5, 5, "hard"),
        ]

    specs: list[tuple[int, int, int, str]] = []
    for item in spec_text.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            count_text, size_text, difficulty = item.split(":")
            n_entities_text, n_attrs_text = size_text.lower().split("x")
            specs.append((
                int(count_text),
                int(n_entities_text),
                int(n_attrs_text),
                difficulty.strip().lower(),
            ))
        except ValueError as exc:
            raise ValueError(
                f"Invalid --puzzle-specs item {item!r}; expected count:NxM:difficulty"
            ) from exc
    if not specs:
        raise ValueError("--puzzle-specs did not contain any valid specs")
    return specs


if __name__ == "__main__":
    main()
