"""Filter online trace JSONL records into a reusable evaluation subset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Filter PRISM trace JSONL records")
    p.add_argument("--trace", required=True)
    p.add_argument("--data", required=True, help="Original JSONL dataset path")
    p.add_argument("--output", required=True, help="Filtered dataset JSONL path")
    p.add_argument(
        "--mode",
        choices=["memory_eligible", "validated_repair_success", "unsolved"],
        default="memory_eligible",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    selected_ids = _selected_ids(Path(args.trace), args.mode)
    written = _write_subset(Path(args.data), Path(args.output), selected_ids)
    print(f"Selected ids: {len(selected_ids)}")
    print(f"Written records: {written}")
    print(f"Output: {args.output}")


def _selected_ids(trace_path: Path, mode: str) -> set[str]:
    selected: set[str] = set()
    with trace_path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            if _matches(record, mode):
                selected.add(str(record.get("puzzle_id", "")))
    selected.discard("")
    return selected


def _matches(record: dict, mode: str) -> bool:
    if mode == "memory_eligible":
        return bool(record.get("memory_eligible")) or any(
            step.get("action") in {"repair", "repair_rejected", "loop_skipped", "retranslate"}
            for step in record.get("steps", []) or []
        )
    if mode == "validated_repair_success":
        return bool(record.get("validated_repair_success"))
    if mode == "unsolved":
        return record.get("solved") is False
    raise ValueError(f"unknown mode: {mode}")


def _write_subset(data_path: Path, output_path: Path, selected_ids: set[str]) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with data_path.open(encoding="utf-8") as src, output_path.open("w", encoding="utf-8") as dst:
        for line in src:
            if not line.strip():
                continue
            record = json.loads(line)
            if str(record.get("id", "")) not in selected_ids:
                continue
            dst.write(json.dumps(record, ensure_ascii=False))
            dst.write("\n")
            written += 1
    return written


if __name__ == "__main__":
    main()
