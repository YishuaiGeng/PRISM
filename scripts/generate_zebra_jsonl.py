"""Generate local Zebra-style JSONL records for PRISM experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prism.core.generator import PuzzleGenerator
from prism.core.types import PuzzleInstance
from scripts.add_zebra_domains_to_puzzle_text import _with_domain_section


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate Zebra-style benchmark JSONL")
    p.add_argument(
        "--specs",
        required=True,
        help=(
            "Comma-separated specs count:NxM:difficulty, e.g. "
            "'25:3x3:medium,25:3x4:medium'."
        ),
    )
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--domain-explicit",
        action="store_true",
        help="Insert Candidate values sections into puzzle text.",
    )
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    specs = _parse_specs(args.specs)
    records = _generate_records(
        specs,
        seed=args.seed,
        domain_explicit=args.domain_explicit,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False))
            fh.write("\n")
    print(f"Generated records: {len(records)}")
    print(f"Output: {output_path}")


def _parse_specs(spec_text: str) -> list[tuple[int, int, int, str]]:
    specs: list[tuple[int, int, int, str]] = []
    for raw_spec in (spec_text or "").split(","):
        raw_spec = raw_spec.strip()
        if not raw_spec:
            continue
        count_text, size_text, difficulty = raw_spec.split(":", 2)
        n_entities_text, n_attrs_text = size_text.lower().replace("*", "x").split("x", 1)
        specs.append(
            (
                int(count_text),
                int(n_entities_text),
                int(n_attrs_text),
                difficulty.strip().lower(),
            )
        )
    if not specs:
        raise ValueError("At least one generation spec is required.")
    return specs


def _generate_records(
    specs: list[tuple[int, int, int, str]],
    *,
    seed: int,
    domain_explicit: bool,
) -> list[dict]:
    generator = PuzzleGenerator(seed=seed)
    records: list[dict] = []
    for count, n_entities, n_attrs, difficulty in specs:
        puzzles = generator.generate(
            count,
            n_entities=n_entities,
            n_attrs=n_attrs,
            difficulty=difficulty,
        )
        for puzzle in puzzles:
            records.append(_puzzle_to_record(puzzle, domain_explicit=domain_explicit))
    return records


def _puzzle_to_record(puzzle: PuzzleInstance, *, domain_explicit: bool) -> dict:
    solution = {
        str(key): str(value)
        for key, value in (puzzle.solution or {}).items()
    }
    puzzle_text = puzzle.nl_description
    if domain_explicit:
        puzzle_text = _with_domain_section(puzzle_text, solution)
    record = {
        "id": puzzle.puzzle_id,
        "size": puzzle.size,
        "puzzle": puzzle_text,
        "solution": solution,
    }
    if puzzle.difficulty:
        record["difficulty"] = puzzle.difficulty
    raw_data = puzzle.raw_data or {}
    if "conflict_count" in raw_data:
        record["conflict_count"] = raw_data["conflict_count"]
    return record


if __name__ == "__main__":
    main()
