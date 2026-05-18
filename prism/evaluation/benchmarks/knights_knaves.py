"""Knights-and-Knaves benchmark loader and evaluator (L2 generalization).

KnK puzzles feature characters who are either knights (always truth) or knaves
(always lie).  Given a set of statements attributed to the characters, the solver
must determine each character's type.

Expected JSON format::

    {
        "id":         "knk_5_001",
        "n_chars":    3,
        "statements": ["A says: I am a knight.", "B says: A is a knave.", ...],
        "solution":   {"A": "knight", "B": "knave", "C": "knight"}
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.metrics import solve_accuracy

logger = logging.getLogger(__name__)


def load_knights_knaves(
    data_dir: str,
    max_puzzles: Optional[int] = None,
    source: str = "auto",
    subset: str = "test",
    splits: Optional[List[str]] = None,
    people_counts: Optional[List[int]] = None,
) -> List[PuzzleInstance]:
    """Load Knights-and-Knaves puzzles from *data_dir*.

    Args:
        data_dir: Directory containing ``*.json`` puzzle files.
        max_puzzles: Optional upper bound on the number of puzzles loaded.

    Returns:
        List of :class:`~prism.core.types.PuzzleInstance` objects.
    """
    if source in ("hf", "auto") and _looks_like_hf_dataset_id(data_dir):
        return _load_knk_hf(
            dataset_id=data_dir,
            subset=subset,
            people_counts=people_counts or _splits_to_people_counts(splits),
            max_puzzles=max_puzzles,
        )

    root = Path(data_dir)
    if not root.exists():
        logger.warning("KnK data dir not found: %s", data_dir)
        return []

    puzzles: List[PuzzleInstance] = []
    for record in _iter_records(root):
        puzzles.append(_record_to_puzzle(record))
        if max_puzzles and len(puzzles) >= max_puzzles:
            break

    logger.info("Loaded %d Knights-and-Knaves puzzles", len(puzzles))
    return puzzles


def _load_knk_hf(
    dataset_id: str,
    subset: str,
    people_counts: Optional[List[int]],
    max_puzzles: Optional[int],
) -> List[PuzzleInstance]:
    selected_counts = people_counts or [2, 3, 4, 5, 6, 7, 8]
    puzzles: List[PuzzleInstance] = []
    for people_count in selected_counts:
        path = _knk_hf_path(subset, people_count)
        for idx, record in enumerate(_load_hf_jsonl(dataset_id, path)):
            puzzles.append(knk_record_to_puzzle(dict(record), split=f"{people_count}ppl", index=idx))
            if max_puzzles and len(puzzles) >= max_puzzles:
                logger.info("Loaded %d Knights-and-Knaves HF puzzles", len(puzzles))
                return puzzles

    logger.info("Loaded %d Knights-and-Knaves HF puzzles", len(puzzles))
    return puzzles


def _load_hf_dataset(dataset_id: str, subset: str, split: str):
    try:
        from datasets import load_dataset  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("Install `datasets` to load Hugging Face datasets.") from exc
    return load_dataset(dataset_id, subset, split=split)


def _load_hf_jsonl(dataset_id: str, path: str) -> List[dict]:
    try:
        from huggingface_hub import hf_hub_download  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("Install `huggingface_hub` to load HF JSONL files.") from exc
    local_path = hf_hub_download(repo_id=dataset_id, filename=path, repo_type="dataset")
    records: List[dict] = []
    with open(local_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _knk_hf_path(subset: str, people_count: int) -> str:
    count = 200 if subset == "train" and people_count == 2 else 1000 if subset == "train" else 100
    return f"{subset}/people{people_count}_num{count}.jsonl"


def _splits_to_people_counts(splits: Optional[List[str]]) -> Optional[List[int]]:
    if not splits:
        return None
    counts: List[int] = []
    for split in splits:
        digits = "".join(ch for ch in split if ch.isdigit())
        if digits:
            counts.append(int(digits))
    return counts or None


def _looks_like_hf_dataset_id(path_or_id: str) -> bool:
    return "/" in path_or_id and not Path(path_or_id).exists()


def evaluate_knights_knaves(
    solver,
    puzzles: List[PuzzleInstance],
) -> List[dict]:
    """Run *solver* on all KnK *puzzles* and return result dicts.

    Args:
        solver: An instance of :class:`~prism.online.guided_solver.GuidedSolver`.
        puzzles: KnK puzzle instances.

    Returns:
        List of result dicts compatible with :mod:`prism.evaluation.metrics`.
    """
    results: List[dict] = []
    for i, puzzle in enumerate(puzzles):
        result: SolveResult = solver.solve(puzzle)
        ground_truth = _solution_to_str(puzzle.solution)
        predicted = _solution_to_str(result.solution)
        result_dict = {
            "puzzle_id": puzzle.puzzle_id,
            "domain": "knights_knaves",
            "solved": _is_correct(result, ground_truth, predicted),
            "ground_truth": ground_truth,
            "predicted": predicted,
            "llm_calls": result.total_llm_calls,
            "repair_rounds": result.repair_rounds,
            "steps": result.steps,
        }
        results.append(result_dict)
        if (i + 1) % 25 == 0:
            acc = solve_accuracy(results)
            logger.info("KnK progress %d/%d | accuracy=%.1f%%", i + 1, len(puzzles), acc * 100)

    return results


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _iter_records(root: Path) -> Iterator[dict]:
    for json_file in sorted(root.rglob("*.json")):
        try:
            with open(json_file, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                yield from data
            elif isinstance(data, dict):
                yield data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Skipping %s: %s", json_file, exc)


def _record_to_puzzle(record: dict) -> PuzzleInstance:
    stmts: List[str] = record.get("statements", [])
    n = record.get("n_chars", len(record.get("solution", {})))
    nl = _build_nl(stmts, n)
    solution = {k: v for k, v in record.get("solution", {}).items()}
    return PuzzleInstance(
        puzzle_id=str(record.get("id", "")),
        nl_description=nl,
        constraints_nl=stmts,
        solution=solution,
        size=f"knk_{n}",
        domain="knights_knaves",
        raw_data=record,
    )


def knk_record_to_puzzle(record: dict, split: str = "unknown", index: int = 0) -> PuzzleInstance:
    """Convert one Hugging Face Knights-and-Knaves record to a PuzzleInstance."""
    names = _coerce_names(record.get("names"))
    statements = _coerce_statements(record)
    solution = _coerce_knk_solution(names, record.get("solution"))
    n = len(names) if names else len(solution)
    return PuzzleInstance(
        puzzle_id=str(record.get("id") or f"knk_{split}_{index}"),
        nl_description=_build_nl(statements, n),
        constraints_nl=statements,
        solution=solution,
        size=f"knk_{n}",
        domain="knights_knaves",
        raw_data=record,
    )


def _build_nl(statements: List[str], n_chars: int) -> str:
    header = (
        f"There are {n_chars} characters. "
        "Each character is either a knight (always tells the truth) "
        "or a knave (always lies).\n\nStatements:\n"
    )
    return header + "\n".join(f"- {s}" for s in statements)


def _coerce_names(raw) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [part.strip() for part in raw.replace(";", ",").split(",") if part.strip()]
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _coerce_statements(record: dict) -> List[str]:
    raw = record.get("statements")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw]
    quiz = record.get("quiz")
    return [str(quiz)] if quiz else []


def _coerce_knk_solution(names: List[str], raw) -> Dict[str, str]:
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    if isinstance(raw, list):
        result: Dict[str, str] = {}
        for idx, value in enumerate(raw):
            name = names[idx] if idx < len(names) else f"char_{idx + 1}"
            role = "knight" if bool(value) else "knave"
            result[name] = role
        return result
    return {}


def _solution_to_str(sol: Optional[Dict[str, str]]) -> Optional[str]:
    if sol is None:
        return None
    return "|".join(f"{k}={v}" for k, v in sorted(sol.items()))


def _is_correct(
    result: SolveResult,
    ground_truth: Optional[str],
    predicted: Optional[str],
) -> bool:
    if ground_truth is None:
        return result.solved
    return predicted == ground_truth
