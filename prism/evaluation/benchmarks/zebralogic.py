"""ZebraLogic benchmark loader and evaluator.

ZebraLogic puzzles are stored as JSON files (one per puzzle or batched).
Each JSON record is expected to have:

.. code-block:: json

    {
        "id":        "puzzle_4x5_001",
        "clues":     ["Clue 1.", "Clue 2.", ...],
        "solution":  {"house1": {"nationality": "Norwegian", ...}, ...},
        "size":      "4x5"
    }

The ``size`` field follows the convention ``{n_entities}x{n_attrs}``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.metrics import solve_accuracy

logger = logging.getLogger(__name__)

_SUPPORTED_SIZES: frozenset[str] = frozenset(
    ["2x4", "3x5", "4x5", "5x5", "5x6", "6x6"]
)


def load_zebralogic(
    data_dir: str,
    sizes: Optional[List[str]] = None,
    split: str = "test",
    max_per_size: Optional[int] = None,
) -> List[PuzzleInstance]:
    """Load ZebraLogic puzzles from *data_dir*.

    Args:
        data_dir: Directory containing ``*.json`` puzzle files.  May also
            contain subdirectories per size (e.g. ``4x5/``) or a single
            flat JSON file with a list of records.
        sizes: Size filter, e.g. ``["4x5", "5x5"]``.  All sizes if *None*.
        split: ``"test"`` or ``"dev"`` (affects the 10%/90% partition).
        max_per_size: Limit the number of puzzles loaded per size.

    Returns:
        List of :class:`~prism.core.types.PuzzleInstance` objects.
    """
    root = Path(data_dir)
    if not root.exists():
        logger.warning("ZebraLogic data dir not found: %s", data_dir)
        return []

    size_filter = set(sizes) if sizes else _SUPPORTED_SIZES
    puzzles: List[PuzzleInstance] = []

    for record in _iter_records(root):
        size = record.get("size", "")
        if size not in size_filter:
            continue
        puzzle = _record_to_puzzle(record)
        puzzles.append(puzzle)

    if max_per_size:
        by_size: Dict[str, List[PuzzleInstance]] = {}
        for p in puzzles:
            by_size.setdefault(p.size, []).append(p)
        puzzles = [p for ps in by_size.values() for p in ps[:max_per_size]]

    logger.info("Loaded %d ZebraLogic puzzles (sizes=%s, split=%s)", len(puzzles), sizes, split)
    return puzzles


def evaluate_zebralogic(
    solver,
    puzzles: List[PuzzleInstance],
) -> List[dict]:
    """Run *solver* on all *puzzles* and collect result dicts.

    Args:
        solver: An instance of :class:`~prism.online.guided_solver.GuidedSolver`.
        puzzles: List of ZebraLogic puzzles.

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
            "domain": puzzle.size,
            "solved": _is_correct(result, ground_truth, predicted),
            "ground_truth": ground_truth,
            "predicted": predicted,
            "llm_calls": result.total_llm_calls,
            "repair_rounds": result.repair_rounds,
            "steps": result.steps,
        }
        results.append(result_dict)
        if (i + 1) % 50 == 0:
            acc = solve_accuracy(results)
            logger.info("Progress %d/%d | running accuracy=%.1f%%", i + 1, len(puzzles), acc * 100)

    return results


# --------------------------------------------------------------------------- #
# Private helpers                                                               #
# --------------------------------------------------------------------------- #

def _iter_records(root: Path) -> Iterator[dict]:
    """Yield raw puzzle dicts from all JSON files under *root*."""
    json_files = sorted(root.rglob("*.json"))
    if not json_files:
        logger.warning("No JSON files found under %s", root)
        return

    for json_file in json_files:
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
    clues: List[str] = record.get("clues", [])
    nl = _clues_to_nl(clues, record.get("size", ""))
    sol_raw = record.get("solution", {})
    solution = _flatten_solution(sol_raw)

    return PuzzleInstance(
        puzzle_id=str(record.get("id", "")),
        nl_description=nl,
        constraints_nl=clues,
        solution=solution,
        size=record.get("size", ""),
        domain="zebralogic",
        raw_data=record,
    )


def _clues_to_nl(clues: List[str], size: str) -> str:
    parts = size.split("x") if "x" in size else ["?", "?"]
    n_entities, n_attrs = parts[0], parts[1]
    header = (
        f"There are {n_entities} houses in a row numbered 1 to {n_entities}. "
        f"Each house has {n_attrs} distinct attributes.\n\nClues:\n"
    )
    return header + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(clues))


def _flatten_solution(raw: dict) -> Dict[str, str]:
    flat: Dict[str, str] = {}
    for house, attrs in raw.items():
        if isinstance(attrs, dict):
            for attr, value in attrs.items():
                flat[f"{attr}_{value}"] = house
        else:
            flat[house] = str(attrs)
    return flat


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
