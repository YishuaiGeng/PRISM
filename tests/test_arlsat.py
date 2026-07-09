"""Tests for the AR-LSAT loader, question classifier, and option decision.

No API calls: option-check tests exercise the pure decision logic and the
Z3-backed ``_check_with`` helper with hand-written formulas; the evaluator
test uses a stub guided solver and a stub option checker.
"""

from __future__ import annotations

import json

import pytest

from prism.core.types import PuzzleInstance, SolveResult
from prism.evaluation.benchmarks.arlsat import (
    ARLSATOptionChecker,
    OptionCheck,
    _check_with,
    classify_question,
    decide_option,
    evaluate_arlsat,
    final_constraints,
    load_arlsat,
    parse_option_block,
    record_to_puzzle,
)

RECORD = {
    "id": "199106_2-G_1_1",
    "passage_id": "199106_2-G_1",
    "passage": (
        "Three speakers - Ann, Bob, and Cal - give talks in three consecutive "
        "slots numbered 1 to 3, one speaker per slot. Ann speaks before Bob."
    ),
    "question": "Which one of the following could be true?",
    "options": [
        "Bob speaks in slot 1",
        "Ann speaks in slot 3",
        "Cal speaks in slot 2",
        "Bob speaks before Ann",
        "Ann and Bob share a slot",
    ],
    "answer": "C",
    "is_except": "",
    "tags": ["", "", "miscellaneous", ""],
}

BACKGROUND = [
    "And(Int('slot_Ann') >= 1, Int('slot_Ann') <= 3)",
    "And(Int('slot_Bob') >= 1, Int('slot_Bob') <= 3)",
    "And(Int('slot_Cal') >= 1, Int('slot_Cal') <= 3)",
    "Distinct(Int('slot_Ann'), Int('slot_Bob'), Int('slot_Cal'))",
    "Int('slot_Ann') < Int('slot_Bob')",
]


# --------------------------------------------------------------------------- #
# Loader                                                                        #
# --------------------------------------------------------------------------- #

def test_record_to_puzzle_basic():
    puzzle = record_to_puzzle(dict(RECORD), split="test", index=0)
    assert puzzle.puzzle_id == "199106_2-G_1_1"
    assert puzzle.domain == "arlsat"
    raw = puzzle.raw_data
    assert raw["answer"] == "C"
    assert raw["question_type"] == "could_be_true"
    assert raw["is_except"] is False
    assert len(raw["options"]) == 5
    assert puzzle.nl_description.startswith(RECORD["passage"])
    assert "Question:" in puzzle.nl_description


def test_record_to_puzzle_rejects_bad_answer():
    bad = dict(RECORD, answer="F")
    with pytest.raises(ValueError):
        record_to_puzzle(bad)


def test_load_arlsat_from_jsonl(tmp_path):
    path = tmp_path / "test.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(RECORD) + "\n")
        fh.write(json.dumps(dict(RECORD, id="q2", answer="A")) + "\n")
    puzzles = load_arlsat(str(tmp_path), split="test")
    assert len(puzzles) == 2
    assert puzzles[1].puzzle_id == "q2"


def test_load_arlsat_missing_dir(tmp_path):
    assert load_arlsat(str(tmp_path / "nope"), split="test") == []


def test_load_arlsat_offset_shards_without_overlap(tmp_path):
    path = tmp_path / "test.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(5):
            fh.write(json.dumps(dict(RECORD, id=f"q{i}")) + "\n")
    first = load_arlsat(str(tmp_path), split="test", max_puzzles=2, offset=0)
    second = load_arlsat(str(tmp_path), split="test", max_puzzles=2, offset=2)
    rest = load_arlsat(str(tmp_path), split="test", offset=4)
    assert [p.puzzle_id for p in first] == ["q0", "q1"]
    assert [p.puzzle_id for p in second] == ["q2", "q3"]
    assert [p.puzzle_id for p in rest] == ["q4"]


# --------------------------------------------------------------------------- #
# Question classification                                                       #
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "question, expected_type, expected_except",
    [
        ("Which one of the following could be true?", "could_be_true", False),
        ("Which one of the following must be true?", "must_be_true", False),
        ("Each of the following could be true EXCEPT:", "could_be_true", True),
        ("Which one of the following CANNOT be true?", "cannot_be_true", False),
        ("Which one of the following could be false?", "could_be_false", False),
        (
            "Which one of the following seating arrangements would NOT violate "
            "the stated conditions?",
            "could_be_true",
            False,
        ),
        (
            "Which one of the following arrangements would violate the "
            "conditions?",
            "cannot_be_true",
            False,
        ),
        (
            "If Londi sits next to Poirier, which one of the following is a "
            "pair of representatives who must sit next to each other?",
            "must_be_true",
            False,
        ),
        ("Which one of the following is a complete and accurate list?", "unknown", False),
    ],
)
def test_classify_question(question, expected_type, expected_except):
    qtype, is_except = classify_question(question)
    assert qtype == expected_type
    assert is_except == expected_except


def test_classify_question_is_except_field():
    _, is_except = classify_question("Which could be true?", is_except="yes")
    assert is_except is True


# --------------------------------------------------------------------------- #
# Option decision                                                                #
# --------------------------------------------------------------------------- #

def _checks(**verdicts):
    """Build {letter: OptionCheck} from letter=(sat_with, sat_with_neg) pairs."""
    return {
        letter: OptionCheck(sat_with=pair[0], sat_with_neg=pair[1])
        for letter, pair in verdicts.items()
    }


def test_decide_could_be_true_unique():
    checks = _checks(
        A=("UNSAT", "SAT"), B=("UNSAT", "SAT"), C=("SAT", "SAT"),
        D=("UNSAT", "SAT"), E=("UNSAT", "SAT"),
    )
    decision = decide_option(checks, "could_be_true")
    assert decision.predicted == "C"
    assert decision.ambiguous is False


def test_decide_must_be_true():
    checks = _checks(
        A=("SAT", "SAT"), B=("SAT", "UNSAT"), C=("SAT", "SAT"),
        D=("SAT", "SAT"), E=("SAT", "SAT"),
    )
    decision = decide_option(checks, "must_be_true")
    assert decision.predicted == "B"


def test_decide_except_inverts():
    # could-be-true EXCEPT: answer is the option that is NOT satisfiable.
    checks = _checks(
        A=("SAT", "SAT"), B=("SAT", "SAT"), C=("SAT", "SAT"),
        D=("UNSAT", "SAT"), E=("SAT", "SAT"),
    )
    decision = decide_option(checks, "could_be_true", is_except=True)
    assert decision.predicted == "D"


def test_decide_ambiguous_ties_break_by_letter():
    checks = _checks(A=("SAT", "SAT"), B=("SAT", "SAT"), C=("UNSAT", "SAT"))
    decision = decide_option(checks, "could_be_true")
    assert decision.predicted == "A"
    assert decision.ambiguous is True
    assert decision.candidates == ["A", "B"]


def test_decide_excludes_unavailable_verdicts():
    # A failed to parse (None) — it must not surface as an EXCEPT candidate.
    checks = _checks(A=(None, None), B=("SAT", "SAT"), C=("UNSAT", "SAT"))
    decision = decide_option(checks, "could_be_true", is_except=True)
    assert decision.predicted == "C"
    assert decision.candidates == ["C"]


def test_decide_no_candidates_returns_none():
    checks = _checks(A=(None, None), B=(None, None))
    decision = decide_option(checks, "must_be_true")
    assert decision.predicted is None


# --------------------------------------------------------------------------- #
# Z3 option checks (offline, no LLM)                                            #
# --------------------------------------------------------------------------- #

def test_check_with_sat_and_unsat():
    # "Cal speaks in slot 2" is consistent with the background.
    assert _check_with(BACKGROUND, "Int('slot_Cal') == 2") == "SAT"
    # "Bob speaks before Ann" contradicts Ann < Bob.
    assert _check_with(BACKGROUND, "Int('slot_Bob') < Int('slot_Ann')") == "UNSAT"


def test_check_with_parse_failure_returns_none():
    assert _check_with(BACKGROUND, "this is not z3") is None


def test_full_option_protocol_on_toy_game():
    """End-to-end decision with hand-written option formulas (no LLM)."""
    formulas = {
        "A": "Int('slot_Bob') == 1",
        "B": "Int('slot_Ann') == 3",
        "C": "Int('slot_Cal') == 2",
        "D": "Int('slot_Bob') < Int('slot_Ann')",
        "E": "Int('slot_Ann') == Int('slot_Bob')",
    }
    checks = {
        letter: OptionCheck(
            sat_with=_check_with(BACKGROUND, f),
            sat_with_neg=_check_with(BACKGROUND, f"Not({f})"),
            formula=f,
        )
        for letter, f in formulas.items()
    }
    decision = decide_option(checks, "could_be_true")
    assert decision.predicted == "C"
    assert decision.ambiguous is False


# --------------------------------------------------------------------------- #
# Response parsing                                                              #
# --------------------------------------------------------------------------- #

def test_parse_option_block_fenced():
    response = (
        "Here are the formulas:\n```json\n"
        '{"A": "Int(\'x\') == 1", "B": null, "C": " ", '
        '"D": "Not(Int(\'y\') < 2)", "E": "Int(\'z\') > 0"}\n```'
    )
    parsed = parse_option_block(response)
    assert parsed["A"] == "Int('x') == 1"
    assert parsed["B"] is None
    assert parsed["C"] is None
    assert parsed["D"] == "Not(Int('y') < 2)"


def test_parse_option_block_bare_json():
    parsed = parse_option_block('{"A": "Int(\'x\') == 1"}', n_options=1)
    assert parsed == {"A": "Int('x') == 1"}


def test_parse_option_block_garbage():
    assert parse_option_block("no json here") == {}


# --------------------------------------------------------------------------- #
# Evaluator (stubbed solver + checker)                                          #
# --------------------------------------------------------------------------- #

class _StubGuidedSolver:
    def solve(self, puzzle: PuzzleInstance) -> SolveResult:
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=True,
            solution=None,
            total_llm_calls=2,
            repair_rounds=0,
            steps=[{"iteration": 0, "action": "translate", "z3_result": "SAT",
                    "constraints": list(BACKGROUND)}],
            final_z3_result="SAT",
        )


class _StubChecker:
    last_llm_calls = 1

    def check_options(self, background, puzzle):
        assert background == BACKGROUND
        return _checks(
            A=("UNSAT", "SAT"), B=("UNSAT", "SAT"), C=("SAT", "SAT"),
            D=("UNSAT", "SAT"), E=("UNSAT", "SAT"),
        )


def test_evaluate_arlsat_with_stubs():
    puzzle = record_to_puzzle(dict(RECORD))
    results = evaluate_arlsat(_StubGuidedSolver(), [puzzle], _StubChecker())
    assert len(results) == 1
    row = results[0]
    assert row["predicted"] == "C"
    assert row["solved"] is True
    assert row["prediction_extracted"] is True
    assert row["llm_calls"] == 3  # 2 solve + 1 option translation


class _StubCheckerNoCandidates:
    last_llm_calls = 1

    def check_options(self, background, puzzle):
        return _checks(
            A=(None, None), B=(None, None), C=(None, None),
            D=(None, None), E=(None, None),
        )


def test_evaluate_arlsat_random_fallback_is_seeded():
    puzzle = record_to_puzzle(dict(RECORD))
    run1 = evaluate_arlsat(
        _StubGuidedSolver(), [puzzle], _StubCheckerNoCandidates(),
        fallback="random", seed=42,
    )
    run2 = evaluate_arlsat(
        _StubGuidedSolver(), [puzzle], _StubCheckerNoCandidates(),
        fallback="random", seed=42,
    )
    assert run1[0]["fallback_used"] is True
    assert run1[0]["prediction_extracted"] is False
    assert run1[0]["predicted"] in list("ABCDE")
    assert run1[0]["predicted"] == run2[0]["predicted"]  # same seed, same guess


def test_evaluate_arlsat_fallback_none_leaves_unanswered():
    puzzle = record_to_puzzle(dict(RECORD))
    results = evaluate_arlsat(
        _StubGuidedSolver(), [puzzle], _StubCheckerNoCandidates(),
        fallback="none",
    )
    assert results[0]["predicted"] is None
    assert results[0]["fallback_used"] is False
    assert results[0]["solved"] is False


def test_final_constraints_takes_last_step():
    result = SolveResult(
        puzzle_id="p", solved=False, final_z3_result="UNSAT",
        steps=[
            {"constraints": ["Int('a') == 1"]},
            {"action": "repair"},
            {"constraints": ["Int('a') == 2"]},
        ],
    )
    assert final_constraints(result) == ["Int('a') == 2"]


def test_final_constraints_prefers_last_sat_state():
    # A failed repair leaves an UNSAT set as the last step; the checker must
    # use the most recent SAT-verified set instead.
    result = SolveResult(
        puzzle_id="p", solved=False, final_z3_result="UNSAT",
        steps=[
            {"constraints": ["Int('a') == 1"], "z3_result": "SAT"},
            {"constraints": ["Int('a') == 2"], "z3_result": "SAT"},
            {"constraints": ["And(Int('a') == 3, Int('a') == 4)"], "z3_result": "UNSAT"},
        ],
    )
    assert final_constraints(result) == ["Int('a') == 2"]


def test_arlsat_translation_prompt_covers_game_types():
    from prism.core.llm_client import (
        _build_arlsat_retranslation_prompt,
        _build_arlsat_translation_prompt,
    )

    prompt = _build_arlsat_translation_prompt("GAME TEXT", paradigm_hint="")
    assert "GAME TEXT" in prompt
    for marker in ("Ordering / scheduling", "Grouping / assignment",
                   "Selection games", "Do NOT encode the answer options"):
        assert marker in prompt
    assert "logic-grid" not in prompt  # zebra prompt must not leak in

    reprompt = _build_arlsat_retranslation_prompt(
        "GAME TEXT", ["Int('a') == 1"], "unsat core: ...",
    )
    assert "Int('a') == 1" in reprompt
    assert "Selection games" in reprompt


def test_translator_routes_domain_to_llm():
    from prism.core.translator import NLToZ3Translator

    captured = {}

    class _DomainLLM:
        def translate(self, puzzle_nl, schema_hint="", paradigm_hint="", domain=""):
            captured["domain"] = domain
            return "```python\nInt('slot_Ann') == 1\n```"

    puzzle = record_to_puzzle(dict(RECORD))
    translator = NLToZ3Translator(_DomainLLM(), schema_hint_mode="none")
    constraints = translator.translate(puzzle)
    assert captured["domain"] == "arlsat"
    assert constraints == ["Int('slot_Ann') == 1"]


def test_option_checker_uses_llm_and_z3(monkeypatch):
    class _FakeLLM:
        call_count = 0

        def translate_arlsat_options(self, passage_nl, question, options,
                                     background_constraints):
            self.call_count += 1
            return (
                '```json\n{"A": "Int(\'slot_Bob\') == 1", '
                '"B": "Int(\'slot_Ann\') == 3", '
                '"C": "Int(\'slot_Cal\') == 2", '
                '"D": "Int(\'slot_Bob\') < Int(\'slot_Ann\')", '
                '"E": "Int(\'slot_Ann\') == Int(\'slot_Bob\')"}\n```'
            )

    puzzle = record_to_puzzle(dict(RECORD))
    checker = ARLSATOptionChecker(_FakeLLM())
    checks = checker.check_options(BACKGROUND, puzzle)
    assert checker.last_llm_calls == 1
    decision = decide_option(checks, "could_be_true")
    assert decision.predicted == "C"
