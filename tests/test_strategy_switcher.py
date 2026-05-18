"""Tests for StrategySwitcher — L1/L2/L3/L4 escalation logic.

Each test description in strategy_switcher.py comments is implemented here as
a concrete pytest test.  Tests use RepairMemory fixtures from conftest.py and
the make_repair_record factory to build controlled histories.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from prism.online.strategy_switcher import SwitchLevel, StrategySwitcher, _L4_ATTEMPT_THRESHOLD
from prism.paradigm_library.schema import Outcome

# Import factories from conftest (not a fixture — explicit import)
from tests.conftest import make_repair_record


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _make_switcher(memory):
    return StrategySwitcher(memory)


def _append_n_unsat(memory, n: int, vary_core: bool = True):
    """Append n UNSAT records; vary_core uses distinct cores to avoid stagnation."""
    for i in range(n):
        core = [f"Int('x_{i}') > 0"] if vary_core else ["Int('x') > 5"]
        memory.append(make_repair_record(
            iteration=i,
            unsat_core=core,
            outcome=Outcome.UNSAT,
            embedding=[0.0] * 8,
        ))


# --------------------------------------------------------------------------- #
# should_switch() — None on empty / normal history                              #
# --------------------------------------------------------------------------- #

class TestShouldSwitchBaseline:

    def test_none_on_empty_memory(self, memory):
        sw = _make_switcher(memory)
        assert sw.should_switch() is None

    def test_none_after_one_diverse_record(self, memory):
        memory.append(make_repair_record(
            iteration=0, unsat_core=["Int('x') > 5"],
            embedding=[1.0, 0.0, 0.0, 0.0],
        ))
        sw = _make_switcher(memory)
        assert sw.should_switch() is None

    def test_none_with_sat_outcome(self, memory):
        memory.append(make_repair_record(
            iteration=0, outcome=Outcome.SAT, embedding=[1.0, 0.0],
        ))
        sw = _make_switcher(memory)
        assert sw.should_switch() is None


# --------------------------------------------------------------------------- #
# L1 — same target constraint twice in a row                                    #
# --------------------------------------------------------------------------- #

class TestL1:

    def test_l1_triggered_on_repeated_target(self, memory):
        # Use DIFFERENT repair types so L2 does not trigger first
        for i, rtype in enumerate(["relax_bound", "tighten_bound"]):
            memory.append(make_repair_record(
                iteration=i,
                target_constraint="Int('x') > 5",
                repair_type=rtype,
                unsat_core=[f"Int('y_{i}') < 0"],
                embedding=[float(i), 0.0],
            ))
        sw = _make_switcher(memory)
        assert sw.should_switch() == SwitchLevel.L1_SWITCH_TARGET

    def test_l1_not_triggered_on_different_targets(self, memory):
        for i in range(2):
            memory.append(make_repair_record(
                iteration=i,
                target_constraint=f"Int('x_{i}') > 5",
                repair_type="relax_bound",
                unsat_core=[f"Int('y_{i}') < 0"],
                embedding=[float(i), 0.0],
            ))
        sw = _make_switcher(memory)
        assert sw.should_switch() != SwitchLevel.L1_SWITCH_TARGET


# --------------------------------------------------------------------------- #
# L2 — same repair type in recent window                                        #
# --------------------------------------------------------------------------- #

class TestL2:

    def test_l2_triggered_on_repeated_type(self, memory):
        for i in range(3):
            memory.append(make_repair_record(
                iteration=i,
                target_constraint=f"Int('x_{i}') > 0",
                repair_type="relax_bound",
                unsat_core=[f"Int('z_{i}') > 0"],
                embedding=[float(i), 0.0],
            ))
        sw = _make_switcher(memory)
        assert sw.should_switch() == SwitchLevel.L2_SWITCH_TYPE

    def test_l2_not_triggered_on_mixed_types(self, memory):
        for repair_type in ["relax_bound", "tighten_bound", "substitute_variable"]:
            memory.append(make_repair_record(
                iteration=0,
                repair_type=repair_type,
                unsat_core=["Int('x') > 0"],
                embedding=[1.0, 0.0],
            ))
        sw = _make_switcher(memory)
        assert sw.should_switch() != SwitchLevel.L2_SWITCH_TYPE

    def test_l2_takes_priority_over_l1(self, memory):
        """When both L1 (same target) and L2 (same type) conditions hold, L2 is returned."""
        for i in range(3):
            memory.append(make_repair_record(
                iteration=i,
                target_constraint="Int('x') > 5",
                repair_type="relax_bound",
                unsat_core=[f"Int('y_{i}') < 0"],
                embedding=[float(i), 0.0],
            ))
        sw = _make_switcher(memory)
        result = sw.should_switch()
        assert result == SwitchLevel.L2_SWITCH_TYPE


# --------------------------------------------------------------------------- #
# L3 / L4 — stagnation                                                          #
# --------------------------------------------------------------------------- #

class TestL3L4Stagnation:

    def test_l3_triggered_when_stagnation_and_checkpoint_present(self, memory):
        same_core = ["Int('x') > 5", "Int('x') < 3"]
        for i in range(3):
            memory.append(make_repair_record(
                iteration=i,
                unsat_core=same_core,
                embedding=[float(i), 0.0],
            ))
        sw = _make_switcher(memory)
        sw.save_checkpoint({"iteration": 2, "summary": "pre-stagnation"})
        assert sw.should_switch() == SwitchLevel.L3_REVERT_CHECKPOINT

    def test_l4_triggered_when_stagnation_no_checkpoint(self, memory):
        same_core = ["Int('x') > 5", "Int('x') < 3"]
        for i in range(3):
            memory.append(make_repair_record(
                iteration=i,
                unsat_core=same_core,
                embedding=[float(i), 0.0],
            ))
        sw = _make_switcher(memory)
        assert sw.should_switch() == SwitchLevel.L4_FULL_RETRANSLATE


# --------------------------------------------------------------------------- #
# L4 — threshold exhaustion                                                     #
# --------------------------------------------------------------------------- #

class TestL4Threshold:

    def test_l4_triggered_on_threshold_exhaustion(self, memory):
        """After _L4_ATTEMPT_THRESHOLD UNSAT records with no SAT, L4 fires."""
        _append_n_unsat(memory, _L4_ATTEMPT_THRESHOLD, vary_core=True)
        sw = _make_switcher(memory)
        assert sw.should_switch() == SwitchLevel.L4_FULL_RETRANSLATE

    def test_l4_not_triggered_if_any_sat_present(self, memory):
        """Even at threshold, one SAT record suppresses L4 exhaustion check."""
        _append_n_unsat(memory, _L4_ATTEMPT_THRESHOLD - 1, vary_core=True)
        memory.append(make_repair_record(
            iteration=_L4_ATTEMPT_THRESHOLD - 1,
            outcome=Outcome.SAT,
            unsat_core=["Int('w') > 0"],
            embedding=[9.0, 0.0],
        ))
        sw = _make_switcher(memory)
        assert sw.should_switch() != SwitchLevel.L4_FULL_RETRANSLATE

    def test_l4_not_triggered_below_threshold(self, memory):
        _append_n_unsat(memory, _L4_ATTEMPT_THRESHOLD - 1, vary_core=True)
        sw = _make_switcher(memory)
        assert sw.should_switch() != SwitchLevel.L4_FULL_RETRANSLATE


# --------------------------------------------------------------------------- #
# get_switch_prompt()                                                            #
# --------------------------------------------------------------------------- #

class TestSwitchPrompts:

    def test_l1_prompt_shows_tried_and_suggests_untried(self, memory):
        memory.append(make_repair_record(
            iteration=0,
            target_constraint="A > 0",
            unsat_core=["A > 0"],
            embedding=[1.0, 0.0],
        ))
        sw = _make_switcher(memory)
        state = {"unsat_core": ["A > 0", "B < 5", "C == 1"]}
        prompt = sw.get_switch_prompt(SwitchLevel.L1_SWITCH_TARGET, state)
        assert "A > 0" in prompt
        assert "B < 5" in prompt or "C == 1" in prompt

    def test_l2_prompt_reports_tried_suggests_new(self, memory):
        memory.append(make_repair_record(
            iteration=0,
            repair_type="relax_bound",
            unsat_core=["Int('x') > 0"],
            embedding=[1.0, 0.0],
        ))
        sw = _make_switcher(memory)
        prompt = sw.get_switch_prompt(SwitchLevel.L2_SWITCH_TYPE, {})
        assert "relax_bound" in prompt
        assert any(t in prompt for t in ["tighten_bound", "add_slack", "split_constraint"])

    def test_l3_prompt_includes_checkpoint_info(self, memory):
        sw = _make_switcher(memory)
        sw.save_checkpoint({"iteration": 4, "summary": "removed C3"})
        prompt = sw.get_switch_prompt(SwitchLevel.L3_REVERT_CHECKPOINT, {})
        assert "4" in prompt
        assert "removed C3" in prompt

    def test_l4_prompt_includes_problem_nl(self, memory):
        sw = _make_switcher(memory)
        state = {"problem_nl": "Alice must finish before Bob"}
        prompt = sw.get_switch_prompt(SwitchLevel.L4_FULL_RETRANSLATE, state)
        assert "Alice must finish before Bob" in prompt

    def test_l4_prompt_works_without_problem_nl(self, memory):
        sw = _make_switcher(memory)
        prompt = sw.get_switch_prompt(SwitchLevel.L4_FULL_RETRANSLATE, {})
        assert isinstance(prompt, str) and len(prompt) > 0


# --------------------------------------------------------------------------- #
# Checkpoint management                                                          #
# --------------------------------------------------------------------------- #

class TestCheckpoint:

    def test_checkpoint_none_before_save(self, memory):
        sw = _make_switcher(memory)
        assert sw.get_checkpoint() is None

    def test_checkpoint_roundtrip(self, memory):
        sw = _make_switcher(memory)
        sw.save_checkpoint({"iteration": 3, "constraints": ["x > 0"]})
        ckpt = sw.get_checkpoint()
        assert ckpt == {"iteration": 3, "constraints": ["x > 0"]}

    def test_checkpoint_copy_isolation(self, memory):
        """Mutating the returned copy must not affect the stored checkpoint."""
        sw = _make_switcher(memory)
        sw.save_checkpoint({"iteration": 3, "constraints": ["x > 0"]})
        ckpt = sw.get_checkpoint()
        ckpt["iteration"] = 99
        assert sw.get_checkpoint()["iteration"] == 3

    def test_checkpoint_overwritten_on_second_save(self, memory):
        sw = _make_switcher(memory)
        sw.save_checkpoint({"iteration": 1})
        sw.save_checkpoint({"iteration": 5})
        assert sw.get_checkpoint()["iteration"] == 5
