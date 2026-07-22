"""Tests for the trajectory answer-verification verdict logic (no API)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "verify_arlsat_trajectories",
    Path(__file__).resolve().parent.parent / "scripts" / "prism" / "verify_arlsat_trajectories.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["verify_arlsat_trajectories"] = _mod
_spec.loader.exec_module(_mod)

judge = _mod.judge
model_holds = _mod.model_holds

MODEL = ["Int('slot_Ann') == 1", "Int('slot_Bob') == 2", "Int('slot_Cal') == 3"]


# --------------------------------------------------------------------------- #
# model_holds                                                                   #
# --------------------------------------------------------------------------- #

def test_model_holds_decides_ground_formulas():
    assert model_holds(MODEL, "Int('slot_Cal') == 3") == "holds"
    assert model_holds(MODEL, "Int('slot_Ann') > Int('slot_Bob')") == "fails"


def test_model_holds_free_variable_is_undecided():
    # 'slot_Dee' is not fixed by the model; a SAT check would be vacuous.
    assert model_holds(MODEL, "Int('slot_Dee') == 1") is None


def test_model_holds_unparseable_is_undecided():
    assert model_holds(MODEL, "not z3 at all") is None


# --------------------------------------------------------------------------- #
# judge: could_be_true                                                          #
# --------------------------------------------------------------------------- #

def _h(**kw):
    base = {letter: None for letter in "ABCDE"}
    base.update(kw)
    return base


def test_could_be_true_single_holder_matching_answer():
    holds = _h(A="fails", B="fails", C="holds", D="fails", E="fails")
    assert judge(holds, "C", "could_be_true", False) == "correct"


def test_could_be_true_single_holder_wrong_answer():
    holds = _h(A="holds", B="fails", C="fails", D="fails", E="fails")
    assert judge(holds, "C", "could_be_true", False) == "incorrect"


def test_could_be_true_two_holders_breaks_well_posedness():
    # Two options simultaneously possible => the formalization must be wrong.
    holds = _h(A="holds", B="holds", C="fails", D="fails", E="fails")
    assert judge(holds, "A", "could_be_true", False) == "incorrect"


def test_could_be_true_no_holder_indeterminate():
    holds = _h(A="fails", B="fails", C="fails", D="fails", E="fails")
    assert judge(holds, "C", "could_be_true", False) == "indeterminate"


# --------------------------------------------------------------------------- #
# judge: must_be_true / cannot_be_true                                          #
# --------------------------------------------------------------------------- #

def test_must_be_true_answer_fails_is_incorrect():
    holds = _h(A="holds", B="fails")
    assert judge(holds, "B", "must_be_true", False) == "incorrect"


def test_must_be_true_unique_holder_is_correct():
    holds = _h(A="fails", B="holds", C="fails", D="fails", E="fails")
    assert judge(holds, "B", "must_be_true", False) == "correct"


def test_must_be_true_multiple_holders_indeterminate():
    holds = _h(A="holds", B="holds", C="fails", D="fails", E="fails")
    assert judge(holds, "B", "must_be_true", False) == "indeterminate"


def test_cannot_be_true_answer_holds_is_incorrect():
    holds = _h(A="holds")
    assert judge(holds, "A", "cannot_be_true", False) == "incorrect"


def test_cannot_be_true_unique_failer_is_correct():
    holds = _h(A="holds", B="holds", C="fails", D="holds", E="holds")
    assert judge(holds, "C", "cannot_be_true", False) == "correct"


def test_cannot_be_true_undecided_option_blocks_correct():
    holds = _h(A="holds", B="holds", C="fails", D="holds", E=None)
    assert judge(holds, "C", "cannot_be_true", False) == "indeterminate"


# --------------------------------------------------------------------------- #
# judge: EXCEPT mirroring                                                       #
# --------------------------------------------------------------------------- #

def test_could_be_true_except_mirrors_to_cannot():
    # "each could be true EXCEPT" == exactly one cannot-be-true.
    holds = _h(A="holds", B="holds", C="holds", D="fails", E="holds")
    assert judge(holds, "D", "could_be_true", True) == "correct"
    assert judge(holds, "A", "could_be_true", True) == "incorrect"
