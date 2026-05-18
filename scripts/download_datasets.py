"""Download official PRISM benchmark datasets from Hugging Face.

The script writes JSONL snapshots under ``data/hf`` so experiments can be
re-run offline after the first download.
"""

from __future__ import annotations

import argparse
import json
from itertools import islice
from pathlib import Path
from typing import Iterable

ZEBRALOGIC_DATASET = "allenai/ZebraLogicBench"
KNK_DATASET = "K-and-K/knights-and-knaves"
DEFAULT_KNK_SPLITS = ["2ppl", "3ppl", "4ppl", "5ppl", "6ppl", "7ppl", "8ppl"]
DEFAULT_KNK_PEOPLE_COUNTS = [2, 3, 4, 5, 6, 7, 8]


def load_hf_dataset(dataset_id: str, subset: str, split: str):
    try:
        from datasets import load_dataset  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("Install `datasets` before downloading HF datasets.") from exc
    return load_dataset(dataset_id, subset, split=split)


def load_hf_jsonl(dataset_id: str, path: str) -> list[dict]:
    try:
        from huggingface_hub import hf_hub_download  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("Install `huggingface_hub` before downloading HF JSONL files.") from exc
    local_path = hf_hub_download(repo_id=dataset_id, filename=path, repo_type="dataset")
    records: list[dict] = []
    with open(local_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(dict(record), ensure_ascii=False) + "\n")
            count += 1
    return count


def _limit(records: Iterable[dict], max_rows: int | None):
    return islice(records, max_rows) if max_rows else records


def download_zebralogic(
    output_dir: str | Path,
    subset: str = "grid_mode",
    split: str = "test",
    max_rows: int | None = None,
) -> dict[str, int]:
    output_root = Path(output_dir) / "zebralogic"
    records = load_hf_dataset(ZEBRALOGIC_DATASET, subset, split)
    key = f"{subset}_{split}"
    count = write_jsonl(output_root / f"{key}.jsonl", _limit(records, max_rows))
    return {key: count}


def download_knights_knaves(
    output_dir: str | Path,
    subset: str = "test",
    splits: list[str] | None = None,
    people_counts: list[int] | None = None,
    max_rows: int | None = None,
) -> dict[str, int]:
    output_root = Path(output_dir) / "knights-and-knaves"
    selected_counts = people_counts or _splits_to_people_counts(splits) or DEFAULT_KNK_PEOPLE_COUNTS
    counts: dict[str, int] = {}
    for people_count in selected_counts:
        records = load_hf_jsonl(KNK_DATASET, _knk_hf_path(subset, people_count))
        key = f"{subset}_people{people_count}"
        counts[key] = write_jsonl(output_root / f"{key}.jsonl", _limit(records, max_rows))
    return counts


def _knk_hf_path(subset: str, people_count: int) -> str:
    count = 200 if subset == "train" and people_count == 2 else 1000 if subset == "train" else 100
    return f"{subset}/people{people_count}_num{count}.jsonl"


def _splits_to_people_counts(splits: list[str] | None) -> list[int] | None:
    if not splits:
        return None
    counts: list[int] = []
    for split in splits:
        digits = "".join(ch for ch in split if ch.isdigit())
        if digits:
            counts.append(int(digits))
    return counts or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download PRISM HF datasets")
    parser.add_argument("--output-dir", default="data/hf")
    parser.add_argument("--max-rows", type=int, default=None, help="Smoke-test row limit per split")
    parser.add_argument("--zebra-subset", default="grid_mode")
    parser.add_argument("--zebra-split", default="test")
    parser.add_argument("--knk-subset", default="test")
    parser.add_argument("--knk-splits", default=",".join(DEFAULT_KNK_SPLITS))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    knk_splits = [s.strip() for s in args.knk_splits.split(",") if s.strip()]
    zebra_counts = download_zebralogic(
        output_dir=args.output_dir,
        subset=args.zebra_subset,
        split=args.zebra_split,
        max_rows=args.max_rows,
    )
    knk_counts = download_knights_knaves(
        output_dir=args.output_dir,
        subset=args.knk_subset,
        splits=knk_splits,
        max_rows=args.max_rows,
    )
    print(json.dumps({"zebralogic": zebra_counts, "knights_knaves": knk_counts}, indent=2))


if __name__ == "__main__":
    main()
