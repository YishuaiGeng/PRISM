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
    p.add_argument("--n-puzzles", type=int, default=600)
    p.add_argument("--n-runs", type=int, default=3)
    p.add_argument("--output", default="paradigm_store/prism.db")
    p.add_argument("--trajectories", default="data/trajectories")
    p.add_argument("--resume", action="store_true", help="Load existing trajectories from --trajectories dir")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    thresholds = config.get("thresholds", {})

    model_name = args.model or config.get("model_name", "GPT-4o")
    logger.info("Model: %s", model_name)

    # ── 1. Generate training puzzles ──────────────────────────────────
    logger.info("Generating %d training puzzles...", args.n_puzzles)
    gen = PuzzleGenerator(seed=args.seed)
    puzzles_per_size = args.n_puzzles // 3
    puzzles = (
        gen.generate(puzzles_per_size, n_entities=3, n_attrs=5, difficulty="medium")
        + gen.generate(puzzles_per_size, n_entities=4, n_attrs=5, difficulty="medium")
        + gen.generate(puzzles_per_size, n_entities=5, n_attrs=5, difficulty="hard")
    )
    logger.info("Generated %d puzzles.", len(puzzles))

    # ── 2. Collect trajectories ────────────────────────────────────────
    traj_dir = Path(args.trajectories)
    if args.resume and traj_dir.exists():
        logger.info("Loading trajectories from %s", traj_dir)
        trajectories = _load_trajectories(traj_dir)
        logger.info("Loaded %d trajectories.", len(trajectories))
    else:
        llm = LLMClient(model_name=model_name, temperature=0.7)
        collector = TrajectoryCollector(
            llm_client=llm,
            max_repair_rounds=5,
            output_dir=str(traj_dir),
        )
        logger.info("Collecting trajectories (%d runs/puzzle)...", args.n_runs)
        trajectories = collector.collect(puzzles, n_runs=args.n_runs, temperature=0.7)
        logger.info("Collected %d trajectories. Total LLM calls: %d", len(trajectories), llm.call_count)

    # ── 3. KDP extraction ─────────────────────────────────────────────
    logger.info("Extracting KDPs...")
    identifier = KDPIdentifier(domain_drop_threshold=thresholds.get("kdp_drop", 2))
    kdps = [kdp for traj in trajectories for kdp in identifier.identify(traj)]
    logger.info("Extracted %d KDPs from %d trajectories.", len(kdps), len(trajectories))

    # ── 4. Clustering ─────────────────────────────────────────────────
    theta = thresholds.get("cluster_theta", 0.25)
    min_support = thresholds.get("min_support", 5)
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
        n_samples=thresholds.get("verify_samples", 50),
        soundness_threshold=thresholds.get("paradigm_soundness", 0.90),
    )
    solver = Z3SolverWrapper()
    library = ParadigmLibrary(args.output, solver, soundness_threshold=thresholds.get("paradigm_soundness", 0.90))

    accepted = 0
    for paradigm in candidates:
        confidence = verifier.verify(paradigm, solver)
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


def _load_trajectories(traj_dir: Path) -> list[Trajectory]:
    trajectories = []
    for json_file in sorted(traj_dir.glob("*.json")):
        with open(json_file, encoding="utf-8") as fh:
            data = json.load(fh)
        trajectories.append(Trajectory.model_validate(data))
    return trajectories


if __name__ == "__main__":
    main()
