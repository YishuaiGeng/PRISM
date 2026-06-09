"""Extract verified error paradigms from saved PRISM trajectories."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.types import Trajectory
from prism.offline.error_paradigm_extractor import ErrorParadigmExtractor
from prism.paradigm_library.error_library import ErrorParadigmLibrary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract negative/error paradigms from trajectories")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--trajectories")
    source.add_argument("--trace-jsonl")
    p.add_argument("--output", default="paradigm_store/error_prism.db")
    p.add_argument("--min-support", type=int, default=1)
    p.add_argument(
        "--instance-specific",
        action="store_true",
        help="Keep puzzle_id/source clue bindings when mining from trace JSONL.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    extractor = ErrorParadigmExtractor(min_support=args.min_support)
    trajectories = []
    if args.trajectories:
        trajectories = _load_trajectories(Path(args.trajectories))
        paradigms = extractor.extract(trajectories)
    else:
        paradigms = extractor.extract_from_trace_jsonl(
            Path(args.trace_jsonl),
            instance_specific=args.instance_specific,
        )

    output = Path(args.output)
    if output.exists():
        output.unlink()
    json_output = output.with_suffix(".json")
    if json_output.exists():
        json_output.unlink()

    with ErrorParadigmLibrary(str(output)) as library:
        for paradigm in paradigms:
            library.add(paradigm)
        library.save_json(str(json_output))
        stats = library.stats()

    print(f"Loaded trajectories: {len(trajectories)}")
    if args.trace_jsonl:
        print(f"Loaded trace JSONL: {args.trace_jsonl}")
    print(f"Extracted error paradigms: {len(paradigms)}")
    print(f"Library stats: {stats}")
    print(f"DB: {output}")
    print(f"JSON: {json_output}")


def _load_trajectories(traj_dir: Path) -> list[Trajectory]:
    trajectories: list[Trajectory] = []
    for path in sorted(traj_dir.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            trajectories.append(Trajectory.model_validate(json.load(fh)))
    return trajectories


if __name__ == "__main__":
    main()
