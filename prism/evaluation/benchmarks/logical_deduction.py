"""BIG-Bench-Hard LogicalDeduction benchmark loader and evaluator.

LogicalDeduction puzzles are pure ordering CSPs: a paragraph describes N
objects arranged in a fixed (unique) total order, followed by N options that
each assert the same positional claim about a different object.  Records use
the canonical BBH schema produced by ``scripts/download_datasets.py``::

    {"input": "<paragraph>\nOptions:\n(A) ...\n(B) ...", "target": "(A)"}

Scoring follows the benchmark's multiple-choice protocol rather than the
full-assignment protocol used for ZebraLogic: the solver derives a total
order, the evaluator determines which option's claim holds under that order,
and the resulting letter is compared against ``target``.

To keep the option-claim semantics well-defined, the loader appends a
canonical encoding note to the puzzle text: one integer variable per object,
``position_<ObjectName>`` in ``1..N`` (all distinct), where position 1 is the
leftmost / oldest / cheapest / first-place end of the scale and position N is
the rightmost / newest / most-expensive / last-place end.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from prism.core.model_validation import _make_schema_key
from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.metrics import solve_accuracy

logger = logging.getLogger(__name__)

DEFAULT_TASKS = [
    "logical_deduction_three_objects",
    "logical_deduction_five_objects",
    "logical_deduction_seven_objects",
]

_TASK_SIZES = {"three": 3, "five": 5, "seven": 7}

_OPTION_RE = re.compile(r"^\(([A-G])\)\s*(.+?)\s*$")
_ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.IGNORECASE)
_TARGET_RE = re.compile(r"\(?([A-G])\)?")

_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
}
_ORDINAL_ALT = "|".join(_ORDINALS)

# Scale families and their canonical anchors (position 1 vs position N).
_SCALE_HINTS = {
    "horizontal": "position 1 is the leftmost and position {n} is the rightmost",
    "age": "position 1 is the oldest and position {n} is the newest",
    "price": "position 1 is the cheapest and position {n} is the most expensive",
    "rank": "position 1 finished first (best) and position {n} finished last",
}


# --------------------------------------------------------------------------- #
# Loading                                                                       #
# --------------------------------------------------------------------------- #

def load_logical_deduction(
    data_dir: str = "data/hf/logical-deduction",
    tasks: Optional[List[str]] = None,
    max_puzzles: Optional[int] = None,
) -> List[PuzzleInstance]:
    """Load LogicalDeduction puzzles from JSONL snapshots under *data_dir*.

    Args:
        data_dir: Directory containing ``logical_deduction_*.jsonl`` files.
        tasks: Task-name filter (defaults to all three object counts).
        max_puzzles: Optional upper bound on the number of puzzles loaded.

    Returns:
        List of :class:`~prism.core.types.PuzzleInstance` objects.
    """
    root = Path(data_dir)
    if not root.exists():
        logger.warning("LogicalDeduction data dir not found: %s", data_dir)
        return []

    puzzles: List[PuzzleInstance] = []
    for task in tasks or DEFAULT_TASKS:
        path = root / f"{task}.jsonl"
        if not path.exists():
            logger.warning("Missing task file: %s", path)
            continue
        for index, record in enumerate(_iter_jsonl(path)):
            try:
                puzzles.append(record_to_puzzle(record, task=task, index=index))
            except ValueError as exc:
                logger.warning("Skipping %s[%d]: %s", task, index, exc)
            if max_puzzles and len(puzzles) >= max_puzzles:
                logger.info("Loaded %d LogicalDeduction puzzles", len(puzzles))
                return puzzles

    logger.info("Loaded %d LogicalDeduction puzzles", len(puzzles))
    return puzzles


def record_to_puzzle(record: dict, task: str = "", index: int = 0) -> PuzzleInstance:
    """Convert one canonical BBH record into a PuzzleInstance."""
    paragraph, options = _split_input(str(record.get("input", "")))
    entities = _parse_entities(paragraph)
    n = _task_object_count(task) or len(entities)
    if len(entities) != n:
        raise ValueError(
            f"parsed {len(entities)} entities, expected {n}: {entities}"
        )
    target = _normalise_target(str(record.get("target", "")))
    if not target:
        raise ValueError(f"unparseable target: {record.get('target')!r}")
    if target not in options:
        raise ValueError(f"target {target} not among options {sorted(options)}")

    scale = _detect_scale(paragraph, options)
    nl = _build_nl(paragraph, entities, n, scale)
    statements = _constraint_sentences(paragraph)
    return PuzzleInstance(
        puzzle_id=f"{task or 'logical_deduction'}_{index:04d}",
        nl_description=nl,
        variables=[_position_key(e) for e in entities],
        domains={"position": entities},
        constraints_nl=statements,
        solution=None,
        size=f"{n}x1",
        domain="logical_deduction",
        raw_data={
            "task": task,
            "options": options,
            "target": target,
            "entities": entities,
            "scale": scale,
        },
    )


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _split_input(text: str) -> Tuple[str, Dict[str, str]]:
    if "Options:" not in text:
        raise ValueError("record input lacks an 'Options:' section")
    paragraph, _, options_blob = text.partition("Options:")
    options: Dict[str, str] = {}
    for line in options_blob.strip().splitlines():
        match = _OPTION_RE.match(line.strip())
        if match:
            options[match.group(1)] = match.group(2)
    if len(options) < 2:
        raise ValueError(f"parsed {len(options)} options")
    return paragraph.strip(), options


def _parse_entities(paragraph: str) -> List[str]:
    """Extract the object list from the scene sentence (text after the colon)."""
    colon = paragraph.find(":")
    if colon < 0:
        raise ValueError("no entity list found (missing colon)")
    stop = paragraph.find(".", colon)
    segment = paragraph[colon + 1 : stop if stop > colon else None]
    parts: List[str] = []
    for chunk in segment.split(","):
        for piece in re.split(r"\band\b", chunk):
            piece = _ARTICLE_RE.sub("", piece.strip()).strip()
            if piece:
                parts.append(piece)
    return parts


def _constraint_sentences(paragraph: str) -> List[str]:
    colon = paragraph.find(":")
    stop = paragraph.find(".", colon) if colon >= 0 else -1
    tail = paragraph[stop + 1 :] if stop >= 0 else paragraph
    return [s.strip() + "." for s in tail.split(".") if s.strip()]


def _task_object_count(task: str) -> Optional[int]:
    for word, count in _TASK_SIZES.items():
        if word in task:
            return count
    return None


def _normalise_target(raw: str) -> str:
    match = _TARGET_RE.search(raw.strip())
    return match.group(1) if match else ""


def _detect_scale(paragraph: str, options: Dict[str, str]) -> str:
    text = (paragraph + " " + " ".join(options.values())).lower()
    if "left" in text or "right" in text:
        return "horizontal"
    if "old" in text or "new" in text:
        return "age"
    if "cheap" in text or "expensive" in text:
        return "price"
    if "finish" in text or "last" in text or "place" in text:
        return "rank"
    return "horizontal"


def _build_nl(paragraph: str, entities: List[str], n: int, scale: str) -> str:
    anchor = _SCALE_HINTS[scale].format(n=n)
    var_list = ", ".join(_position_key(e) for e in entities)
    note = (
        f"\n\nEncode the arrangement with one integer variable per object, "
        f"named exactly: {var_list}. Each variable takes a value in 1..{n}, "
        f"all values are distinct, and {anchor}."
    )
    return paragraph + note


def _position_key(entity: str) -> str:
    return _make_schema_key("position", entity)


# --------------------------------------------------------------------------- #
# Scoring                                                                       #
# --------------------------------------------------------------------------- #

def predict_option_letter(
    puzzle: PuzzleInstance,
    solution: Optional[Dict[str, str]],
) -> Optional[str]:
    """Map a solved total order to the option letter whose claim it satisfies.

    Returns ``None`` when no valid permutation can be extracted from
    *solution* or when no option claim matches.
    """
    raw = puzzle.raw_data or {}
    entities: List[str] = list(raw.get("entities") or [])
    options: Dict[str, str] = dict(raw.get("options") or {})
    if not entities or not options or not solution:
        return None

    n = len(entities)
    positions = _extract_positions(entities, solution, n)
    if positions is None:
        return None

    for letter in sorted(options):
        text = options[letter]
        entity = _option_entity(text, entities)
        rank = _claim_rank(text, n)
        if entity is None or rank is None:
            continue
        if positions[entity] == rank:
            return letter
    return None


def _extract_positions(
    entities: List[str],
    solution: Dict[str, str],
    n: int,
) -> Optional[Dict[str, int]]:
    """Match solver variables to entities and validate a 1..n permutation."""
    normalised = {
        _normalise(str(key)): value
        for key, value in solution.items()
        if not str(key).startswith("_prism_track_")
    }
    positions: Dict[str, int] = {}
    for entity in sorted(entities, key=len, reverse=True):
        token = _normalise(entity)
        candidates = [v for k, v in normalised.items() if token in k]
        if len({str(v) for v in candidates}) != 1:
            return None
        try:
            positions[entity] = int(str(candidates[0]))
        except ValueError:
            return None
    if sorted(positions.values()) != list(range(1, n + 1)):
        return None
    return positions


def _option_entity(text: str, entities: List[str]) -> Optional[str]:
    lowered = _normalise(text)
    for entity in sorted(entities, key=len, reverse=True):
        if _normalise(entity) in lowered:
            return entity
    return None


def _claim_rank(text: str, n: int) -> Optional[int]:
    """Parse the position rank asserted by an option claim.

    The claim vocabulary is the closed BBH template set; compound forms are
    checked before their bare-word prefixes (``second-newest`` before
    ``newest``, ``second-to-last`` before ``last``).
    """
    t = text.lower()

    match = re.search(rf"({_ORDINAL_ALT})\s+from\s+the\s+(left|right)", t)
    if match:
        k = _ORDINALS[match.group(1)]
        return k if match.group(2) == "left" else n + 1 - k
    if "leftmost" in t:
        return 1
    if "rightmost" in t:
        return n

    match = re.search(rf"({_ORDINAL_ALT})-(oldest|cheapest)", t)
    if match:
        return _ORDINALS[match.group(1)]
    match = re.search(rf"({_ORDINAL_ALT})-newest", t)
    if match:
        return n + 1 - _ORDINALS[match.group(1)]
    match = re.search(rf"({_ORDINAL_ALT})-most\s+expensive", t)
    if match:
        return n + 1 - _ORDINALS[match.group(1)]
    if "oldest" in t or "cheapest" in t:
        return 1
    if "newest" in t or "most expensive" in t:
        return n

    match = re.search(rf"({_ORDINAL_ALT})-to-last", t)
    if match:
        return n + 1 - _ORDINALS[match.group(1)]
    if re.search(r"\blast\b", t):
        return n
    match = re.search(rf"\b({_ORDINAL_ALT})\b", t)
    if match:
        return _ORDINALS[match.group(1)]
    return None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# --------------------------------------------------------------------------- #
# Evaluation                                                                    #
# --------------------------------------------------------------------------- #

def evaluate_logical_deduction(
    solver,
    puzzles: List[PuzzleInstance],
) -> List[dict]:
    """Run *solver* on all LogicalDeduction *puzzles* and return result dicts.

    Args:
        solver: An instance of :class:`~prism.online.guided_solver.GuidedSolver`.
        puzzles: LogicalDeduction puzzle instances.

    Returns:
        List of result dicts compatible with :mod:`prism.evaluation.metrics`.
    """
    results: List[dict] = []
    for i, puzzle in enumerate(puzzles):
        result: SolveResult = solver.solve(puzzle)
        target = (puzzle.raw_data or {}).get("target")
        predicted = predict_option_letter(puzzle, result.solution)
        result_dict = {
            "puzzle_id": puzzle.puzzle_id,
            "domain": "logical_deduction",
            "size": puzzle.size,
            "task": (puzzle.raw_data or {}).get("task"),
            "solved": predicted is not None and predicted == target,
            "ground_truth": target,
            "predicted": predicted,
            "prediction_extracted": predicted is not None,
            "llm_calls": result.total_llm_calls,
            "repair_rounds": result.repair_rounds,
            "final_z3_result": result.final_z3_result,
            "steps": result.steps,
        }
        results.append(result_dict)
        if (i + 1) % 25 == 0:
            acc = solve_accuracy(results)
            logger.info(
                "LogicalDeduction progress %d/%d | accuracy=%.1f%%",
                i + 1, len(puzzles), acc * 100,
            )

    return results
