from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from prism.online.repair_memory import RepairMemory

# Repair types the LLM is expected to choose from.  Used to generate candidate
# suggestions in L2 prompts when the model has exhausted its recent repertoire.
_ALL_REPAIR_TYPES: List[str] = [
    "relax_bound",
    "tighten_bound",
    "add_slack",
    "split_constraint",
    "negate_condition",
    "change_operator",
    "reorder_scope",
    "substitute_variable",
]

# Escalate to L4 after this many failed attempts with zero SAT outcomes.
# Set conservatively high; real escalation usually happens via stagnation first.
_L4_ATTEMPT_THRESHOLD: int = 10


class SwitchLevel(str, Enum):
    """Escalation levels for the repair strategy-switching mechanism.

    Ordered from least to most disruptive:

    - **L1** — Change only *which* constraint to target next.  The repair type
      and overall approach are unchanged.
    - **L2** — Change the *class* of repair operation (e.g. from ``relax_bound``
      to ``split_constraint``).  The target may stay the same.
    - **L3** — Revert the solver state to the last verified SAT checkpoint and
      resume from a different inference branch.
    - **L4** — Abandon the current formalisation entirely; ask the LLM to
      retranslate from the original natural-language description.
    """

    L1_SWITCH_TARGET = "L1_SWITCH_TARGET"
    L2_SWITCH_TYPE = "L2_SWITCH_TYPE"
    L3_REVERT_CHECKPOINT = "L3_REVERT_CHECKPOINT"
    L4_FULL_RETRANSLATE = "L4_FULL_RETRANSLATE"


class StrategySwitcher:
    """Monitors repair progress and decides when and how to escalate strategy.

    Reads the shared ``RepairMemory`` read-only; never appends records itself.
    Maintains one internal checkpoint that callers set via ``save_checkpoint``
    whenever a partially-solved state is worth preserving.

    Escalation logic in ``should_switch`` is intentionally conservative: it
    returns the *mildest* level that the observed history warrants, so the LLM
    gets the least-disruptive nudge first and only sees heavier instructions
    when lighter ones have already been tried.

    Typical lifecycle::

        switcher = StrategySwitcher(memory)

        # --- after each solver iteration ---
        level = switcher.should_switch()
        if level is not None:
            extra_prompt = switcher.get_switch_prompt(level, current_state)
            # prepend / append extra_prompt to the next LLM call

        # --- whenever solver reaches a cleaner partial state ---
        switcher.save_checkpoint({"iteration": i, "constraints": surviving})
    """

    def __init__(self, memory: RepairMemory) -> None:
        """Initialise with the shared repair memory for the current puzzle.

        Args:
            memory: ``RepairMemory`` instance tracking this puzzle's history.
                    The switcher holds a reference (not a copy) so it always
                    reflects the latest appended records.
        """
        self._memory: RepairMemory = memory
        self._checkpoint: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def should_switch(self) -> Optional[SwitchLevel]:
        """Inspect the repair history and return the warranted escalation level.

        Checks are performed in descending severity so the caller always receives
        the *least disruptive* level that the evidence supports:

        1. **L4** — total attempts ≥ threshold with no SAT outcomes ever.
        2. **L3** — ``detect_stagnation()`` fires and a checkpoint exists.
           Falls back to **L4** when stagnation is detected but no checkpoint
           is available to revert to.
        3. **L2** — the last ≤ 3 records all share the same ``repair_action.type``
           (the solver is trying the same class of fix repeatedly).
        4. **L1** — the last 2 records both targeted the same constraint
           (the solver keeps poking at the same expression without success).

        Returns:
            A ``SwitchLevel`` value, or ``None`` if normal repair should continue.
        """
        records = self._memory._records
        if not records:
            return None

        n = len(records)
        recent = records[-3:] if n >= 3 else records

        # ── L4: prolonged failure with no recovery ─────────────────────
        if n >= _L4_ATTEMPT_THRESHOLD and not self._memory.get_successful_repairs():
            return SwitchLevel.L4_FULL_RETRANSLATE

        # ── L3 / L4: stagnation (same unsat core keeps reappearing) ────
        if self._memory.detect_stagnation():
            if self._checkpoint is not None:
                return SwitchLevel.L3_REVERT_CHECKPOINT
            return SwitchLevel.L4_FULL_RETRANSLATE

        # ── L2: same repair type dominating the recent window ──────────
        if len(recent) >= 2:
            recent_types = [r.repair_action.type for r in recent]
            if len(set(recent_types)) == 1:
                return SwitchLevel.L2_SWITCH_TYPE

        # ── L1: same target constraint targeted twice in a row ─────────
        if n >= 2:
            last_two = [r.repair_action.target_constraint for r in records[-2:]]
            if len(set(last_two)) == 1:
                return SwitchLevel.L1_SWITCH_TARGET

        return None

    def get_switch_prompt(self, level: SwitchLevel, current_state: Dict) -> str:
        """Return an LLM-injectable instruction string for the given switch level.

        The strings are in Chinese and designed to be appended to the user turn
        or system prompt of the next LLM call so the model understands what has
        been tried and what it should attempt instead.

        Args:
            level: The ``SwitchLevel`` returned by ``should_switch()``.
            current_state: Snapshot of the solver state at the moment of switching.
                Required / optional keys per level:

                +-------+---------------------+----------+
                | Level | Key                 | Required |
                +-------+---------------------+----------+
                | L1    | ``"unsat_core"``     | yes      |
                | L2    | —                   | —        |
                | L3    | —                   | —        |
                | L4    | ``"problem_nl"``     | optional |
                +-------+---------------------+----------+

        Returns:
            A single instruction string, ready for LLM injection.
        """
        dispatch = {
            SwitchLevel.L1_SWITCH_TARGET: lambda: self._prompt_l1(current_state),
            SwitchLevel.L2_SWITCH_TYPE: lambda: self._prompt_l2(),
            SwitchLevel.L3_REVERT_CHECKPOINT: lambda: self._prompt_l3(),
            SwitchLevel.L4_FULL_RETRANSLATE: lambda: self._prompt_l4(current_state),
        }
        return dispatch[level]()

    def save_checkpoint(self, state: Dict) -> None:
        """Persist *state* as the latest revert point for L3 escalation.

        Call this whenever the solver reaches a partial state worth returning to —
        for example after a repair that reduced the UNSAT core size even though
        the overall result is still UNSAT.

        Suggested keys to include in *state*:

        - ``"iteration"`` (int): loop index at time of save.
        - ``"constraints"`` (List[str]): the surviving constraint set.
        - ``"summary"`` (str): human-readable description of the checkpoint.

        Args:
            state: Arbitrary JSON-serialisable dict; stored as a shallow copy.
        """
        self._checkpoint = dict(state)

    def get_checkpoint(self) -> Optional[Dict]:
        """Return a copy of the most recently saved checkpoint, or None.

        Returns:
            Shallow copy of the checkpoint dict, or ``None`` if
            ``save_checkpoint`` has never been called.
        """
        return dict(self._checkpoint) if self._checkpoint is not None else None

    # ------------------------------------------------------------------
    # Private prompt builders
    # ------------------------------------------------------------------

    def _tried_targets(self) -> List[str]:
        """Ordered, deduplicated list of constraint targets already attempted."""
        seen: List[str] = []
        for r in self._memory._records:
            t = r.repair_action.target_constraint
            if t and t not in seen:
                seen.append(t)
        return seen

    def _tried_types(self) -> List[str]:
        """Ordered, deduplicated list of repair types already attempted."""
        seen: List[str] = []
        for r in self._memory._records:
            tp = r.repair_action.type
            if tp and tp not in seen:
                seen.append(tp)
        return seen

    def _prompt_l1(self, current_state: Dict) -> str:
        tried = self._tried_targets()
        unsat_core: List[str] = current_state.get("unsat_core", [])
        candidates = [c for c in unsat_core if c not in tried]
        if not candidates:
            candidates = unsat_core  # all tried — suggest re-examining all
        tried_str = "、".join(tried) if tried else "无"
        cand_str = "、".join(candidates) if candidates else "UNSAT core 中的其他约束"
        return (
            f"请换一个约束作为修复目标，"
            f"已尝试修改 [{tried_str}]，"
            f"请尝试 [{cand_str}]"
        )

    def _prompt_l2(self) -> str:
        tried = self._tried_types()
        candidates = [t for t in _ALL_REPAIR_TYPES if t not in tried]
        if not candidates:
            candidates = _ALL_REPAIR_TYPES  # all tried — cycle back
        tried_str = "、".join(tried) if tried else "无"
        cand_str = "、".join(candidates[:3])  # surface top 3 unexplored types
        return (
            f"请换一种修复方式，"
            f"已尝试 [{tried_str}]，"
            f"请尝试 [{cand_str}]"
        )

    def _prompt_l3(self) -> str:
        ckpt = self._checkpoint or {}
        iteration = ckpt.get("iteration", "未知")
        summary = ckpt.get("summary", "最近稳定状态")
        return (
            f"回退到检查点 {iteration}（{summary}），"
            f"从另一个推断方向重新开始"
        )

    def _prompt_l4(self, current_state: Dict) -> str:
        problem_nl: str = current_state.get("problem_nl", "")
        base = "重新从自然语言翻译所有约束，忽略之前的形式化。"
        return base + (f" 原始描述：{problem_nl}" if problem_nl else "")


# =============================================================================
# Unit test case descriptions
# =============================================================================
#
# test_should_switch_returns_none_on_empty_memory
#   mem = RepairMemory({stagnation_jaccard: 0.75, loop_cosine: 0.90})
#   sw = StrategySwitcher(mem)
#   assert sw.should_switch() is None
#
# test_l1_triggered_on_repeated_target
#   Append two records with the same target_constraint, different types.
#   assert sw.should_switch() == SwitchLevel.L1_SWITCH_TARGET
#
# test_l2_triggered_on_repeated_type
#   Append three records with different targets but the same repair type.
#   assert sw.should_switch() == SwitchLevel.L2_SWITCH_TYPE
#
# test_l2_takes_priority_over_l1
#   Arrange history so both L1 and L2 conditions are met simultaneously.
#   assert sw.should_switch() == SwitchLevel.L2_SWITCH_TYPE   (L2 checked first)
#
# test_l3_triggered_when_stagnation_and_checkpoint_present
#   Mock memory.detect_stagnation() -> True; sw.save_checkpoint({"iteration": 2})
#   assert sw.should_switch() == SwitchLevel.L3_REVERT_CHECKPOINT
#
# test_l4_triggered_when_stagnation_no_checkpoint
#   Mock memory.detect_stagnation() -> True; no checkpoint saved.
#   assert sw.should_switch() == SwitchLevel.L4_FULL_RETRANSLATE
#
# test_l4_triggered_on_threshold_exhaustion
#   Append _L4_ATTEMPT_THRESHOLD records all with Outcome.UNSAT.
#   assert sw.should_switch() == SwitchLevel.L4_FULL_RETRANSLATE
#
# test_l4_not_triggered_if_any_sat_present
#   Append threshold records but one has Outcome.SAT.
#   assert sw.should_switch() != SwitchLevel.L4_FULL_RETRANSLATE
#
# test_get_switch_prompt_l1_excludes_tried_targets
#   state = {"unsat_core": ["A > 0", "B < 5", "C == 1"]}
#   (memory has one record targeting "A > 0")
#   prompt = sw.get_switch_prompt(L1, state)
#   assert "A > 0" in prompt        # shows what was tried
#   assert "B < 5" in prompt        # suggests untried candidates
#
# test_get_switch_prompt_l2_suggests_unexplored_types
#   History contains only "relax_bound" repairs.
#   prompt = sw.get_switch_prompt(L2, {})
#   assert "relax_bound" in prompt  # reports tried
#   assert "tighten_bound" in prompt or "add_slack" in prompt  # suggests new
#
# test_get_switch_prompt_l3_includes_checkpoint_iteration
#   sw.save_checkpoint({"iteration": 4, "summary": "removed C3"})
#   prompt = sw.get_switch_prompt(L3, {})
#   assert "4" in prompt and "removed C3" in prompt
#
# test_get_switch_prompt_l4_includes_problem_nl
#   state = {"problem_nl": "Alice must finish before Bob"}
#   prompt = sw.get_switch_prompt(L4, state)
#   assert "Alice must finish before Bob" in prompt
#
# test_save_and_get_checkpoint_roundtrip
#   sw.save_checkpoint({"iteration": 3, "constraints": ["x > 0"]})
#   ckpt = sw.get_checkpoint()
#   assert ckpt == {"iteration": 3, "constraints": ["x > 0"]}
#   # Mutating returned copy does not affect internal state
#   ckpt["iteration"] = 99
#   assert sw.get_checkpoint()["iteration"] == 3
#
# test_get_checkpoint_returns_none_before_save
#   sw = StrategySwitcher(mem)
#   assert sw.get_checkpoint() is None
