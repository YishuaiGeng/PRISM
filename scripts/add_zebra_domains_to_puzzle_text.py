"""Add explicit candidate value lists to local ZebraLogic JSONL puzzles."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create a domain-explicit ZebraLogic JSONL file")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open(encoding="utf-8") as src, output_path.open(
        "w", encoding="utf-8"
    ) as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record["puzzle"] = _with_domain_section(
                str(record.get("puzzle", "")),
                record.get("solution") or {},
            )
            dst.write(json.dumps(record, ensure_ascii=False) + "\n")


def _with_domain_section(puzzle_text: str, solution: dict) -> str:
    domains: dict[str, list[str]] = defaultdict(list)
    for key in solution:
        if "_" not in str(key):
            continue
        category, value = str(key).split("_", 1)
        domains[category].append(value)
    if not domains or "Candidate values:" in puzzle_text:
        return puzzle_text

    lines = ["Candidate values:"]
    for category in sorted(domains):
        values = sorted(dict.fromkeys(domains[category]))
        value_text = ", ".join(f"`{value}`" for value in values)
        lines.append(f"- {category}: {value_text}")

    if "\n\nClues:" in puzzle_text:
        return puzzle_text.replace("\n\nClues:", "\n\n" + "\n".join(lines) + "\n\nClues:", 1)
    return puzzle_text + "\n\n" + "\n".join(lines)


if __name__ == "__main__":
    main()
