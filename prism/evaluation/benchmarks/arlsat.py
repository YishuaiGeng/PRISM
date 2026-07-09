"""AR-LSAT benchmark loader and evaluator (cross-task generalization).

AR-LSAT (Zhong et al. 2022) contains LSAT analytical-reasoning questions:
each logic-game passage states background conditions over entities
(ordering, grouping, assignment) and asks a five-option multiple-choice
question. Records use the flattened schema produced by
``scripts/download_datasets.py``::

    {"id", "passage_id", "passage", "question", "options", "answer",
     "is_except", "tags"}

Official splits: train 1,630 / dev 231 / test 230 questions; Logic-LM and
Logic-LM++ report on the 230-question test split.

Scoring follows the neurosymbolic multiple-choice protocol (SatLM-style):
the guided solver formalises the passage (plus any local premise embedded in
the question stem) into background constraints ``C``; a separate LLM call
translates each option into a Z3 boolean formula ``phi_k``; the question type
decides the per-option solver check:

    could_be_true   -> pick k with   SAT(C  and  phi_k)
    must_be_true    -> pick k with UNSAT(C  and  Not(phi_k))
    cannot_be_true  -> pick k with UNSAT(C  and  phi_k)
    could_be_false  -> pick k with   SAT(C  and  Not(phi_k))

EXCEPT questions invert the predicate: the answer is the unique option that
FAILS the property every other option satisfies.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.metrics import solve_accuracy

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = "data/hf/ar-lsat"
LETTERS = "ABCDE"

_QUESTION_TYPES = (
    "could_be_true",
    "must_be_true",
    "cannot_be_true",
    "could_be_false",
    "unknown",
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


# --------------------------------------------------------------------------- #
# Loading                                                                       #
# --------------------------------------------------------------------------- #

def load_arlsat(
    data_dir: str = DEFAULT_DATA_DIR,
    split: str = "test",
    max_puzzles: Optional[int] = None,
    offset: int = 0,
) -> List[PuzzleInstance]:
    """Load AR-LSAT questions from JSONL snapshots under *data_dir*.

    Args:
        data_dir: Directory containing ``{train,dev,test}.jsonl``.
        split: Which split to load (``test`` for reporting, ``dev`` for
            hyper-parameter selection, ``train`` for library construction).
        max_puzzles: Optional upper bound on the number of questions loaded.
        offset: Skip the first *offset* records — lets parallel workers shard
            a split (worker k of n: ``offset=k*chunk, max_puzzles=chunk``).

    Returns:
        List of :class:`~prism.core.types.PuzzleInstance` objects.
    """
    path = Path(data_dir) / f"{split}.jsonl"
    if not path.exists():
        logger.warning("AR-LSAT split file not found: %s", path)
        return []

    puzzles: List[PuzzleInstance] = []
    for index, record in enumerate(_iter_jsonl(path)):
        if index < offset:
            continue
        try:
            puzzles.append(record_to_puzzle(record, split=split, index=index))
        except ValueError as exc:
            logger.warning("Skipping %s[%d]: %s", split, index, exc)
        if max_puzzles and len(puzzles) >= max_puzzles:
            break

    logger.info("Loaded %d AR-LSAT %s questions (offset=%d)", len(puzzles), split, offset)
    return puzzles


def record_to_puzzle(record: dict, split: str = "test", index: int = 0) -> PuzzleInstance:
    """Convert one flattened AR-LSAT record into a PuzzleInstance."""
    passage = str(record.get("passage", "")).strip()
    question = str(record.get("question", "")).strip()
    options = [str(o) for o in record.get("options", [])]
    answer = str(record.get("answer", "")).strip().upper()
    if not passage or not question:
        raise ValueError("record lacks passage or question text")
    if len(options) < 2:
        raise ValueError(f"record has {len(options)} options")
    if answer not in LETTERS[: len(options)]:
        raise ValueError(f"unparseable answer: {record.get('answer')!r}")

    qtype, is_except = classify_question(question, record.get("is_except", ""))
    return PuzzleInstance(
        puzzle_id=str(record.get("id") or f"arlsat_{split}_{index:04d}"),
        nl_description=_build_nl(passage, question),
        constraints_nl=_sentences(passage),
        solution=None,
        size=f"arlsat_{len(options)}opt",
        domain="arlsat",
        raw_data={
            "split": split,
            "schema_filter": False,  # no fixed variable schema; see translator
            "passage_id": record.get("passage_id"),
            "passage": passage,
            "question": question,
            "options": options,
            "answer": answer,
            "question_type": qtype,
            "is_except": is_except,
            "tags": record.get("tags", []),
        },
    )


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def _sentences(passage: str) -> List[str]:
    return [s.strip() + "." for s in passage.split(".") if s.strip()]


def _build_nl(passage: str, question: str) -> str:
    # Encoding rules live in the domain-specific translation prompt
    # (see llm_client._build_arlsat_translation_prompt); the description
    # only carries the game text and the question stem (whose "If ..."
    # premise the prompt instructs the model to include).
    return f"{passage}\n\nQuestion: {question}"


# --------------------------------------------------------------------------- #
# Question-type classification                                                  #
# --------------------------------------------------------------------------- #

def classify_question(question: str, is_except: object = "") -> Tuple[str, bool]:
    """Classify an AR-LSAT question stem into a solver-check type.

    Returns:
        ``(question_type, is_except)`` where *question_type* is one of
        ``could_be_true`` / ``must_be_true`` / ``cannot_be_true`` /
        ``could_be_false`` / ``unknown``.
    """
    text = question.lower()
    except_flag = bool(is_except) or bool(re.search(r"\bexcept\b", text))

    if re.search(r"\bcannot\b|\bcan\s*not\b|\bcould not\b|\bmust be false\b", text):
        return "cannot_be_true", except_flag
    if re.search(r"\bcould be false\b|\bcan be false\b|\bmay be false\b", text):
        return "could_be_false", except_flag
    if re.search(r"\bnot violate\b", text):
        return "could_be_true", except_flag
    if re.search(r"\bviolate\b", text):
        return "cannot_be_true", except_flag
    if re.search(r"\bmust\b|\bmust also\b", text):
        return "must_be_true", except_flag
    if re.search(r"\bcould\b|\bcan\b|\bcould each\b|\bany of the following\b", text):
        return "could_be_true", except_flag
    return "unknown", except_flag


# --------------------------------------------------------------------------- #
# Option checking and decision                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class OptionCheck:
    """Solver verdicts for one option formula against the background set.

    ``sat_with`` is the verdict of ``C and phi`` and ``sat_with_neg`` the
    verdict of ``C and Not(phi)``; either is ``None`` when the option formula
    was missing or failed to parse.
    """

    sat_with: Optional[str] = None
    sat_with_neg: Optional[str] = None
    formula: Optional[str] = None


@dataclass
class OptionDecision:
    predicted: Optional[str] = None
    ambiguous: bool = False
    candidates: List[str] = field(default_factory=list)


def decide_option(
    checks: Dict[str, OptionCheck],
    question_type: str,
    is_except: bool = False,
) -> OptionDecision:
    """Map per-option solver verdicts to an answer letter.

    An option satisfies the question predicate according to the table in the
    module docstring; EXCEPT questions select the option that explicitly
    FAILS the predicate. Options whose required verdict is unavailable are
    excluded from both candidate pools. Ties are broken by letter order and
    flagged as ambiguous.
    """
    positives: List[str] = []
    negatives: List[str] = []
    for letter in sorted(checks):
        verdict = _predicate(checks[letter], question_type)
        if verdict is True:
            positives.append(letter)
        elif verdict is False:
            negatives.append(letter)

    candidates = negatives if is_except else positives
    if not candidates:
        return OptionDecision(predicted=None, ambiguous=False, candidates=[])
    return OptionDecision(
        predicted=candidates[0],
        ambiguous=len(candidates) > 1,
        candidates=candidates,
    )


def _predicate(check: OptionCheck, question_type: str) -> Optional[bool]:
    """Evaluate the question predicate for one option; None when undecidable."""
    qtype = question_type if question_type in _QUESTION_TYPES else "could_be_true"
    if qtype in ("could_be_true", "unknown"):
        return _verdict_is(check.sat_with, "SAT")
    if qtype == "must_be_true":
        return _verdict_is(check.sat_with_neg, "UNSAT")
    if qtype == "cannot_be_true":
        return _verdict_is(check.sat_with, "UNSAT")
    return _verdict_is(check.sat_with_neg, "SAT")  # could_be_false


def _verdict_is(verdict: Optional[str], expected: str) -> Optional[bool]:
    if verdict is None or verdict == "UNKNOWN":
        return None
    return verdict == expected


class ARLSATOptionChecker:
    """Translates answer options to Z3 formulas and runs per-option checks."""

    def __init__(self, llm_client) -> None:
        self._llm = llm_client
        self.last_llm_calls = 0

    def check_options(
        self,
        background: List[str],
        puzzle: PuzzleInstance,
    ) -> Dict[str, OptionCheck]:
        """Return :class:`OptionCheck` verdicts for every option of *puzzle*."""
        raw = puzzle.raw_data or {}
        options: List[str] = list(raw.get("options") or [])
        calls_before = self._llm.call_count
        response = self._llm.translate_arlsat_options(
            passage_nl=str(raw.get("passage", "")),
            question=str(raw.get("question", "")),
            options=options,
            background_constraints=background,
        )
        self.last_llm_calls = self._llm.call_count - calls_before
        formulas = parse_option_block(response, n_options=len(options))

        checks: Dict[str, OptionCheck] = {}
        for i in range(len(options)):
            letter = LETTERS[i]
            formula = formulas.get(letter)
            if not formula:
                checks[letter] = OptionCheck(formula=formula)
                continue
            checks[letter] = OptionCheck(
                sat_with=_check_with(background, formula),
                sat_with_neg=_check_with(background, f"Not({formula})"),
                formula=formula,
            )
        return checks


def parse_option_block(response: str, n_options: int = 5) -> Dict[str, Optional[str]]:
    """Parse the fenced JSON letter->formula mapping from an LLM response."""
    match = _JSON_BLOCK_RE.search(response or "")
    blob = match.group(1) if match else (response or "").strip()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        logger.warning("Unparseable option block: %.200s", response)
        return {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, Optional[str]] = {}
    for letter in LETTERS[:n_options]:
        value = data.get(letter)
        result[letter] = str(value).strip() if isinstance(value, str) and value.strip() else None
    return result


def _check_with(background: List[str], formula: str) -> Optional[str]:
    """SAT-check *background* plus one extra formula in a fresh solver."""
    solver = Z3SolverWrapper()
    try:
        for constraint in background:
            if not solver.add_constraint(constraint):
                return None
        if not solver.add_constraint(formula):
            return None
    except Exception as exc:  # SolverError or eval failure
        logger.debug("Option check parse failure (%s): %s", formula, exc)
        return None
    return solver.check()


# --------------------------------------------------------------------------- #
# Evaluation                                                                    #
# --------------------------------------------------------------------------- #

def evaluate_arlsat(
    solver,
    puzzles: List[PuzzleInstance],
    option_checker: ARLSATOptionChecker,
    fallback: str = "none",
    seed: int = 42,
) -> List[dict]:
    """Run the guided *solver* plus option checks on all AR-LSAT *puzzles*.

    Args:
        solver: An instance of :class:`~prism.online.guided_solver.GuidedSolver`
            used to formalise the passage into background constraints.
        puzzles: AR-LSAT puzzle instances.
        option_checker: Component running the per-option solver checks.
        fallback: ``"random"`` answers questions with no solver-derived
            candidate by a seeded pseudo-random guess (the Logic-LM backup
            protocol); ``"none"`` leaves them unanswered (scored wrong).
        seed: Seed for the fallback guess; combined with the puzzle id so a
            given question always draws the same guess within one seed.

    Returns:
        List of result dicts compatible with :mod:`prism.evaluation.metrics`.
    """
    results: List[dict] = []
    for i, puzzle in enumerate(puzzles):
        raw = puzzle.raw_data or {}
        result: SolveResult = solver.solve(puzzle)
        background = final_constraints(result)

        predicted: Optional[str] = None
        ambiguous = False
        option_calls = 0
        option_checks_dump: Dict[str, dict] = {}
        if background:
            checks = option_checker.check_options(background, puzzle)
            option_calls = option_checker.last_llm_calls
            decision = decide_option(
                checks,
                str(raw.get("question_type", "unknown")),
                bool(raw.get("is_except", False)),
            )
            predicted, ambiguous = decision.predicted, decision.ambiguous
            option_checks_dump = {
                letter: {
                    "formula": check.formula,
                    "sat_with": check.sat_with,
                    "sat_with_neg": check.sat_with_neg,
                }
                for letter, check in checks.items()
            }

        extracted = predicted is not None
        fallback_used = False
        if predicted is None and fallback == "random":
            predicted = _fallback_guess(puzzle, seed)
            fallback_used = True

        target = raw.get("answer")
        results.append({
            "puzzle_id": puzzle.puzzle_id,
            "domain": "arlsat",
            "split": raw.get("split"),
            "passage_id": raw.get("passage_id"),
            "question_type": raw.get("question_type"),
            "is_except": raw.get("is_except"),
            "solved": predicted is not None and predicted == target,
            "ground_truth": target,
            "predicted": predicted,
            "prediction_extracted": extracted,
            "fallback_used": fallback_used,
            "ambiguous": ambiguous,
            "option_checks": option_checks_dump,
            "llm_calls": result.total_llm_calls + option_calls,
            "repair_rounds": result.repair_rounds,
            "final_z3_result": result.final_z3_result,
            "steps": result.steps,
        })
        if (i + 1) % 25 == 0:
            acc = solve_accuracy(results)
            logger.info(
                "AR-LSAT progress %d/%d | accuracy=%.1f%%",
                i + 1, len(puzzles), acc * 100,
            )

    return results


def _fallback_guess(puzzle: PuzzleInstance, seed: int) -> str:
    """Seeded pseudo-random option guess, stable per (seed, puzzle id)."""
    import random

    options = (puzzle.raw_data or {}).get("options") or []
    letters = list(LETTERS[: len(options)]) or list(LETTERS)
    return random.Random(f"{seed}:{puzzle.puzzle_id}").choice(letters)


def final_constraints(result: SolveResult) -> List[str]:
    """Extract the best background constraint set from a solve trace.

    Prefers the most recent step whose constraint set was verified SAT (a
    failed repair can leave the last recorded set UNSAT, which would make
    every option check vacuously UNSAT); falls back to the last recorded set.
    """
    steps = result.steps or []
    for step in reversed(steps):
        if step.get("constraints") and step.get("z3_result") == "SAT":
            return [str(c) for c in step["constraints"]]
    for step in reversed(steps):
        if step.get("constraints"):
            return [str(c) for c in step["constraints"]]
    return []
