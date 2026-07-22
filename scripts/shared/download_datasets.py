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

BBH_GITHUB_RAW = "https://raw.githubusercontent.com/suzgunmirac/BIG-Bench-Hard/main/bbh/{task}.json"
BBH_HF_DATASET = "Joschka/big_bench_hard"
DEFAULT_LOGICAL_DEDUCTION_TASKS = [
    "logical_deduction_three_objects",
    "logical_deduction_five_objects",
    "logical_deduction_seven_objects",
]

ARLSAT_GITHUB_RAW = "https://raw.githubusercontent.com/zhongwanjun/AR-LSAT/main/data/{filename}"
ARLSAT_SPLIT_FILES = {
    "train": "AR_TrainingData.json",
    "dev": "AR_DevelopmentData.json",
    "test": "AR_TestData.json",
}


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


def download_logical_deduction(
    output_dir: str | Path,
    tasks: list[str] | None = None,
    max_rows: int | None = None,
) -> dict[str, int]:
    """Download BIG-Bench-Hard logical_deduction (3/5/7 objects) in canonical BBH format.

    Records follow the official BBH schema ``{"input": str, "target": "(A)"}``.
    The canonical GitHub JSON is preferred; the HF parquet mirror is used as a
    fallback and converted to the same schema.
    """
    output_root = Path(output_dir) / "logical-deduction"
    counts: dict[str, int] = {}
    for task in tasks or DEFAULT_LOGICAL_DEDUCTION_TASKS:
        try:
            records = _load_bbh_task_github(task)
        except Exception:
            records = _load_bbh_task_hf(task)
        counts[task] = write_jsonl(output_root / f"{task}.jsonl", _limit(records, max_rows))
    return counts


def download_arlsat(
    output_dir: str | Path,
    splits: list[str] | None = None,
    max_rows: int | None = None,
) -> dict[str, int]:
    """Download official AR-LSAT splits (Zhong et al. 2022) from GitHub.

    Each passage (logic game) is flattened into one record per question:
    ``{"id", "passage_id", "passage", "question", "options", "answer",
    "is_except", "tags"}``. Official sizes: train 1,630 / dev 231 / test 230
    questions; Logic-LM and Logic-LM++ report results on the 230-question
    test split.
    """
    import urllib.request  # noqa: PLC0415

    output_root = Path(output_dir) / "ar-lsat"
    counts: dict[str, int] = {}
    for split in splits or list(ARLSAT_SPLIT_FILES):
        url = ARLSAT_GITHUB_RAW.format(filename=ARLSAT_SPLIT_FILES[split])
        with urllib.request.urlopen(url, timeout=120) as response:
            passages = json.load(response)
        records = [
            {
                "id": question["id"],
                "passage_id": passage["id"],
                "passage": passage["passage"],
                "question": question["question"],
                "options": question["options"],
                "answer": question["answer"],
                "is_except": question.get("isExcept", ""),
                "tags": question.get("tags", []),
            }
            for passage in passages
            for question in passage["questions"]
        ]
        counts[split] = write_jsonl(output_root / f"{split}.jsonl", _limit(records, max_rows))
    return counts


def _load_bbh_task_github(task: str) -> list[dict]:
    import urllib.request  # noqa: PLC0415

    with urllib.request.urlopen(BBH_GITHUB_RAW.format(task=task), timeout=60) as response:
        return json.load(response)["examples"]


def _load_bbh_task_hf(task: str) -> list[dict]:
    try:
        from huggingface_hub import hf_hub_download  # noqa: PLC0415
        import pyarrow.parquet as pq  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("Install `huggingface_hub` and `pyarrow` for the HF fallback.") from exc
    local_path = hf_hub_download(
        repo_id=BBH_HF_DATASET,
        filename=f"{task}/{task}-00000-of-00001.parquet",
        repo_type="dataset",
    )
    records: list[dict] = []
    for row in pq.read_table(local_path).to_pylist():
        options = "\n".join(
            f"({label.rstrip(')')}) {text}"
            for label, text in zip(row["choices"]["label"], row["choices"]["text"])
        )
        records.append(
            {"input": f"{row['question']}\nOptions:\n{options}", "target": f"({row['target']})"}
        )
    return records


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
    parser.add_argument(
        "--datasets",
        default="zebralogic,knights_knaves,logical_deduction,arlsat",
        help="Comma-separated subset of: zebralogic, knights_knaves, logical_deduction, arlsat",
    )
    parser.add_argument(
        "--arlsat-splits",
        default=",".join(ARLSAT_SPLIT_FILES),
        help="Comma-separated AR-LSAT splits: train, dev, test",
    )
    parser.add_argument(
        "--ld-tasks",
        default=",".join(DEFAULT_LOGICAL_DEDUCTION_TASKS),
        help="Comma-separated BBH logical_deduction task names",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = {name.strip() for name in args.datasets.split(",") if name.strip()}
    knk_splits = [s.strip() for s in args.knk_splits.split(",") if s.strip()]
    ld_tasks = [t.strip() for t in args.ld_tasks.split(",") if t.strip()]
    summary: dict[str, dict[str, int]] = {}
    if "zebralogic" in selected:
        summary["zebralogic"] = download_zebralogic(
            output_dir=args.output_dir,
            subset=args.zebra_subset,
            split=args.zebra_split,
            max_rows=args.max_rows,
        )
    if "knights_knaves" in selected:
        summary["knights_knaves"] = download_knights_knaves(
            output_dir=args.output_dir,
            subset=args.knk_subset,
            splits=knk_splits,
            max_rows=args.max_rows,
        )
    if "logical_deduction" in selected:
        summary["logical_deduction"] = download_logical_deduction(
            output_dir=args.output_dir,
            tasks=ld_tasks,
            max_rows=args.max_rows,
        )
    if "arlsat" in selected:
        arlsat_splits = [s.strip() for s in args.arlsat_splits.split(",") if s.strip()]
        summary["arlsat"] = download_arlsat(
            output_dir=args.output_dir,
            splits=arlsat_splits,
            max_rows=args.max_rows,
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
