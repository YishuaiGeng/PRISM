"""Tests for the BBH LogicalDeduction loader, option scorer, and evaluator.

No API calls: the evaluator tests use a stub solver returning canned
SolveResult objects; Z3 is not required.
"""

from __future__ import annotations

import json

import pytest

from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.benchmarks.logical_deduction import (
    _claim_rank,
    evaluate_logical_deduction,
    load_logical_deduction,
    predict_option_letter,
    record_to_puzzle,
)
from scripts import download_datasets

_PREFIX = (
    "The following paragraphs each describe a set of three objects arranged in a "
    "fixed order. The statements are logically consistent within each paragraph. "
)

BIRDS_RECORD = {
    "input": _PREFIX
    + "On a branch, there are three birds: a blue jay, a quail, and a falcon. "
    "The falcon is to the right of the blue jay. "
    "The blue jay is to the right of the quail.\n"
    "Options:\n"
    "(A) The blue jay is the second from the left\n"
    "(B) The quail is the second from the left\n"
    "(C) The falcon is the second from the left",
    "target": "(A)",
}

GOLF_RECORD = {
    "input": _PREFIX
    + "In a golf tournament, there were three golfers: Amy, Eli, and Eve. "
    "Eve finished above Amy. Eli finished below Amy.\n"
    "Options:\n"
    "(A) Amy finished last\n"
    "(B) Eli finished last\n"
    "(C) Eve finished last",
    "target": "(B)",
}

FRUIT_RECORD = {
    "input": _PREFIX
    + "A fruit stand sells three fruits: watermelons, plums, and apples. "
    "The watermelons are more expensive than the plums. "
    "The apples are the cheapest.\n"
    "Options:\n"
    "(A) The watermelons are the most expensive\n"
    "(B) The plums are the most expensive\n"
    "(C) The apples are the most expensive",
    "target": "(A)",
}


# --------------------------------------------------------------------------- #
# Loader                                                                        #
# --------------------------------------------------------------------------- #

def test_record_to_puzzle_parses_entities_options_and_schema():
    puzzle = record_to_puzzle(BIRDS_RECORD, task="logical_deduction_three_objects", index=7)

    assert puzzle.size == "3x1"
    assert puzzle.domain == "logical_deduction"
    assert puzzle.raw_data["entities"] == ["blue jay", "quail", "falcon"]
    assert puzzle.raw_data["target"] == "A"
    assert set(puzzle.raw_data["options"]) == {"A", "B", "C"}
    assert puzzle.variables == ["position_Blue_Jay", "position_Quail", "position_Falcon"]
    # Canonical encoding note is appended for the translator.
    assert "position_Blue_Jay" in puzzle.nl_description
    assert "1..3" in puzzle.nl_description
    assert "leftmost" in puzzle.nl_description
    # Constraint sentences exclude the scene sentence.
    assert puzzle.constraints_nl[-1] == "The blue jay is to the right of the quail."


def test_record_to_puzzle_detects_rank_and_price_scales():
    golf = record_to_puzzle(GOLF_RECORD, task="logical_deduction_three_objects")
    fruit = record_to_puzzle(FRUIT_RECORD, task="logical_deduction_three_objects")

    assert golf.raw_data["scale"] == "rank"
    assert golf.raw_data["entities"] == ["Amy", "Eli", "Eve"]
    assert "finished first" in golf.nl_description
    assert fruit.raw_data["scale"] == "price"
    assert "cheapest" in fruit.nl_description


def test_record_to_puzzle_rejects_malformed_records():
    with pytest.raises(ValueError):
        record_to_puzzle({"input": "no options here", "target": "(A)"})
    with pytest.raises(ValueError):
        record_to_puzzle(
            {"input": BIRDS_RECORD["input"], "target": "(Z)"},
            task="logical_deduction_three_objects",
        )


def test_load_logical_deduction_reads_jsonl_snapshots(tmp_path):
    task = "logical_deduction_three_objects"
    path = tmp_path / f"{task}.jsonl"
    path.write_text(
        json.dumps(BIRDS_RECORD) + "\n" + json.dumps(GOLF_RECORD) + "\n",
        encoding="utf-8",
    )

    puzzles = load_logical_deduction(str(tmp_path), tasks=[task])
    assert len(puzzles) == 2
    assert puzzles[0].puzzle_id == f"{task}_0000"

    limited = load_logical_deduction(str(tmp_path), tasks=[task], max_puzzles=1)
    assert len(limited) == 1


# --------------------------------------------------------------------------- #
# Claim-rank parsing                                                            #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    ("claim", "n", "rank"),
    [
        ("The quail is the leftmost", 3, 1),
        ("The quail is the rightmost", 3, 3),
        ("The green book is the second from the left", 5, 2),
        ("The green book is the third from the right", 5, 3),
        ("The convertible is the oldest", 5, 1),
        ("The convertible is the newest", 5, 5),
        ("The convertible is the second-newest", 5, 4),
        ("The convertible is the third-oldest", 7, 3),
        ("The plums are the cheapest", 5, 1),
        ("The plums are the most expensive", 5, 5),
        ("The plums are the second-cheapest", 5, 2),
        ("The plums are the fourth-most expensive", 7, 4),
        ("Amy finished first", 3, 1),
        ("Amy finished second", 3, 2),
        ("Amy finished last", 3, 3),
        ("Amy finished second-to-last", 7, 6),
    ],
)
def test_claim_rank_parses_closed_template_vocabulary(claim, n, rank):
    assert _claim_rank(claim, n) == rank


def test_claim_rank_returns_none_for_unknown_claims():
    assert _claim_rank("The quail sings beautifully", 3) is None


# --------------------------------------------------------------------------- #
# Option scoring                                                                #
# --------------------------------------------------------------------------- #

def _birds_puzzle() -> PuzzleInstance:
    return record_to_puzzle(BIRDS_RECORD, task="logical_deduction_three_objects")


def test_predict_option_letter_maps_permutation_to_letter():
    # Ground order: quail=1, blue jay=2, falcon=3 -> "(A)" (blue jay second from left).
    solution = {
        "position_Blue_Jay": "2",
        "position_Quail": "1",
        "position_Falcon": "3",
    }
    assert predict_option_letter(_birds_puzzle(), solution) == "A"


def test_predict_option_letter_handles_variant_key_styles():
    solution = {"pos_blue_jay": "2", "pos_quail": "1", "pos_falcon": "3"}
    assert predict_option_letter(_birds_puzzle(), solution) == "A"


def test_predict_option_letter_rejects_non_permutations_and_missing_keys():
    puzzle = _birds_puzzle()
    assert predict_option_letter(puzzle, None) is None
    assert predict_option_letter(puzzle, {"position_Blue_Jay": "2"}) is None
    assert (
        predict_option_letter(
            puzzle,
            {"position_Blue_Jay": "2", "position_Quail": "2", "position_Falcon": "3"},
        )
        is None
    )
    assert (
        predict_option_letter(
            puzzle,
            {"position_Blue_Jay": "9", "position_Quail": "1", "position_Falcon": "3"},
        )
        is None
    )


# --------------------------------------------------------------------------- #
# Evaluator                                                                     #
# --------------------------------------------------------------------------- #

class _StubSolver:
    """Returns a canned SolveResult; never touches an LLM or Z3."""

    def __init__(self, solution):
        self._solution = solution

    def solve(self, puzzle: PuzzleInstance) -> SolveResult:
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=self._solution is not None,
            solution=self._solution,
            total_llm_calls=1,
            repair_rounds=0,
            final_z3_result="SAT" if self._solution else "UNSAT",
        )


def test_evaluate_logical_deduction_scores_by_option_letter():
    puzzles = [_birds_puzzle()]
    good = {"position_Blue_Jay": "2", "position_Quail": "1", "position_Falcon": "3"}
    wrong = {"position_Blue_Jay": "1", "position_Quail": "2", "position_Falcon": "3"}

    solved_rows = evaluate_logical_deduction(_StubSolver(good), puzzles)
    assert solved_rows[0]["solved"] is True
    assert solved_rows[0]["predicted"] == "A"
    assert solved_rows[0]["ground_truth"] == "A"
    assert solved_rows[0]["prediction_extracted"] is True

    wrong_rows = evaluate_logical_deduction(_StubSolver(wrong), puzzles)
    assert wrong_rows[0]["solved"] is False
    assert wrong_rows[0]["predicted"] == "B"

    failed_rows = evaluate_logical_deduction(_StubSolver(None), puzzles)
    assert failed_rows[0]["solved"] is False
    assert failed_rows[0]["predicted"] is None
    assert failed_rows[0]["prediction_extracted"] is False


# --------------------------------------------------------------------------- #
# Download plumbing                                                             #
# --------------------------------------------------------------------------- #

def test_download_logical_deduction_writes_snapshots(tmp_path, monkeypatch):
    def fake_github(task):
        return [{"input": f"{task} q", "target": "(A)"}] * 3

    monkeypatch.setattr(download_datasets, "_load_bbh_task_github", fake_github)

    written = download_datasets.download_logical_deduction(
        tmp_path,
        tasks=["logical_deduction_three_objects"],
        max_rows=2,
    )

    assert written == {"logical_deduction_three_objects": 2}
    output = tmp_path / "logical-deduction" / "logical_deduction_three_objects.jsonl"
    assert output.exists()


def test_download_logical_deduction_falls_back_to_hf(tmp_path, monkeypatch):
    def fail_github(task):
        raise OSError("network down")

    def fake_hf(task):
        return [{"input": "q", "target": "(B)"}]

    monkeypatch.setattr(download_datasets, "_load_bbh_task_github", fail_github)
    monkeypatch.setattr(download_datasets, "_load_bbh_task_hf", fake_hf)

    written = download_datasets.download_logical_deduction(
        tmp_path, tasks=["logical_deduction_five_objects"]
    )

    assert written == {"logical_deduction_five_objects": 1}
