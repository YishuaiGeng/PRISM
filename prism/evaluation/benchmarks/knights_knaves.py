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
) -> List[PuzzleInstance]:
    """Load Knights-and-Knaves puzzles from *data_dir*.

    Args:
        data_dir: Directory containing ``*.json`` puzzle files.
        max_puzzles: Optional upper bound on the number of puzzles loaded.

    Returns:
        List of :class:`~prism.core.types.PuzzleInstance` objects.
    """
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


def _build_nl(statements: List[str], n_chars: int) -> str:
    header = (
        f"There are {n_chars} characters. "
        "Each character is either a knight (always tells the truth) "
        "or a knave (always lies).\n\nStatements:\n"
    )
    return header + "\n".join(f"- {s}" for s in statements)


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
