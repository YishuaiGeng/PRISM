"""Audit PRISM pipeline artifacts without making API calls.

The script reads saved trajectories plus optional paradigm libraries and reports
where a run produced useful signal or dropped out.

Usage:

    python scripts/audit_pipeline.py \
      --trajectories data/trajectories/gpt4o_mini_audit \
      --library paradigm_store/gpt4o_mini_audit.db \
      --min-support 1,2,5 \
      --json-out results/audit.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.solver import Z3SolverWrapper
from prism.core.types import Trajectory
from prism.offline.kdp_identifier import KDPIdentifier
from prism.offline.trajectory_clusterer import TrajectoryClusterer
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit PRISM pipeline artifacts")
    p.add_argument("--trajectories", required=True, help="Directory containing trajectory JSON files")
    p.add_argument("--library", default=None, help="Optional positive paradigm SQLite DB")
    p.add_argument("--error-library", default=None, help="Optional error paradigm SQLite/JSON artifact")
    p.add_argument("--min-support", default="1,2,5", help="Comma-separated cluster support thresholds")
    p.add_argument("--json-out", default=None, help="Optional path for JSON audit report")
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    traj_dir = Path(args.trajectories)
    min_supports = _parse_int_list(args.min_support)

    trajectories = _load_trajectories(traj_dir)
    kdps = [kdp for traj in trajectories for kdp in KDPIdentifier().identify(traj)]
    report = {
        "trajectory_dir": str(traj_dir),
        "trajectories": _trajectory_stats(trajectories),
        "steps": _step_stats(trajectories),
        "kdps": _kdp_stats(kdps),
        "clusters": _cluster_stats(kdps, min_supports),
        "positive_library": _positive_library_stats(args.library),
        "error_library": _error_library_stats(args.error_library),
    }

    _print_summary(report)
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\nJSON report saved to {output}")


def _parse_int_list(raw: str) -> list[int]:
    values: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            values.append(int(part))
    return values or [1]


def _load_trajectories(traj_dir: Path) -> list[Trajectory]:
    if not traj_dir.exists():
        raise FileNotFoundError(f"Trajectory directory not found: {traj_dir}")
    trajectories: list[Trajectory] = []
    for path in sorted(traj_dir.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            trajectories.append(Trajectory.model_validate(json.load(fh)))
    return trajectories


def _trajectory_stats(trajectories: list[Trajectory]) -> dict[str, Any]:
    calls = [t.total_llm_calls for t in trajectories]
    return {
        "total": len(trajectories),
        "solved": sum(1 for t in trajectories if t.solved),
        "failed": sum(1 for t in trajectories if not t.solved),
        "final_results": dict(Counter(t.final_result for t in trajectories)),
        "translation_failed": sum(1 for t in trajectories if t.final_result == "TRANSLATION_FAILED"),
        "unsat_failed": sum(1 for t in trajectories if not t.solved and t.final_result == "UNSAT"),
        "llm_calls": {
            "total": sum(calls),
            "min": min(calls) if calls else 0,
            "max": max(calls) if calls else 0,
            "mean": round(statistics.mean(calls), 2) if calls else 0.0,
        },
    }


def _step_stats(trajectories: list[Trajectory]) -> dict[str, Any]:
    steps = [step for traj in trajectories for step in traj.steps]
    return {
        "total": len(steps),
        "actions": dict(Counter(step.action for step in steps)),
        "step_types": dict(Counter(str(step.step_type.value) for step in steps)),
        "z3_results": dict(Counter(step.z3_result for step in steps)),
        "error_types": dict(Counter(step.error_type for step in steps if step.error_type)),
        "with_unsat_core": sum(1 for step in steps if step.unsat_core),
    }


def _kdp_stats(kdps: list) -> dict[str, Any]:
    return {
        "total": len(kdps),
        "kdp_types": dict(Counter(kdp.kdp_type for kdp in kdps)),
        "constraint_types": dict(Counter(ct for kdp in kdps for ct in kdp.constraint_types)),
    }


def _cluster_stats(kdps: list, min_supports: list[int]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for min_support in min_supports:
        clusters = TrajectoryClusterer(theta=0.25, min_support=min_support).cluster(kdps)
        stats[str(min_support)] = {
            "total": len(clusters),
            "support_counts": [c.support_count for c in clusters],
            "dominant_constraint_types": [c.dominant_constraint_types for c in clusters],
        }
    return stats


def _positive_library_stats(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    db_path = Path(path)
    if not db_path.exists():
        return {"exists": False, "path": str(db_path)}
    with ParadigmLibrary(str(db_path), Z3SolverWrapper()) as library:
        stats = library.stats()
    stats["exists"] = True
    stats["path"] = str(db_path)
    return stats


def _error_library_stats(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    artifact = Path(path)
    if not artifact.exists():
        return {"exists": False, "path": str(artifact)}
    if artifact.suffix.lower() == ".json":
        with open(artifact, encoding="utf-8") as fh:
            data = json.load(fh)
        return {"exists": True, "path": str(artifact), "total": len(data)}
    with ErrorParadigmLibrary(str(artifact)) as library:
        stats = library.stats()
    stats["exists"] = True
    stats["path"] = str(artifact)
    return stats


def _print_summary(report: dict[str, Any]) -> None:
    print("PRISM Pipeline Audit")
    print("====================")
    print(f"Trajectory dir: {report['trajectory_dir']}")

    t = report["trajectories"]
    print("\nTrajectories")
    print(f"  total: {t['total']}")
    print(f"  solved/failed: {t['solved']} / {t['failed']}")
    print(f"  final_results: {t['final_results']}")
    print(f"  translation_failed: {t['translation_failed']}")
    print(f"  unsat_failed: {t['unsat_failed']}")
    print(f"  llm_calls: {t['llm_calls']}")

    s = report["steps"]
    print("\nSteps")
    print(f"  total: {s['total']}")
    print(f"  actions: {s['actions']}")
    print(f"  step_types: {s['step_types']}")
    print(f"  z3_results: {s['z3_results']}")
    print(f"  with_unsat_core: {s['with_unsat_core']}")

    k = report["kdps"]
    print("\nKDPs")
    print(f"  total: {k['total']}")
    print(f"  kdp_types: {k['kdp_types']}")
    print(f"  constraint_types: {k['constraint_types']}")

    print("\nClusters")
    for min_support, stats in report["clusters"].items():
        print(f"  min_support={min_support}: total={stats['total']}, support={stats['support_counts']}")

    if report["positive_library"] is not None:
        print("\nPositive Library")
        print(f"  {report['positive_library']}")
    if report["error_library"] is not None:
        print("\nError Library")
        print(f"  {report['error_library']}")


if __name__ == "__main__":
    main()
