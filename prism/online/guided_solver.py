"""Online paradigm-guided inference with repair trajectory memory.

``GuidedSolver`` is the main PRISM online component.  It orchestrates:

1. **Initial translation** — NL puzzle → Z3 constraint strings via LLMClient.
2. **Paradigm-guided inference** — Layer-1 fast retrieval + Layer-2 semantic
   match + Z3 consistency pre-check before injecting paradigm hints to LLM.
3. **Repair loop** — iterative constraint repair using RepairMemory and
   StrategySwitcher for stagnation/loop detection and four-level escalation.
4. **Write-back** — successful repairs update the paradigm library's confidence.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.core.translator import NLToZ3Translator
from prism.core.types import PuzzleInstance, SolveResult, SolverState
from prism.online.feature_extractor import FeatureExtractor
from prism.online.repair_memory import RepairMemory
from prism.online.strategy_switcher import StrategySwitcher
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import ErrorType, Outcome, RepairAction, RepairRecord

logger = logging.getLogger(__name__)

_DEFAULT_MAX_REPAIR_ROUNDS: int = 5
_DEFAULT_PARADIGM_TOP_K: int = 3
_LAYER2_ENABLED: bool = True


class GuidedSolver:
    """Paradigm-guided CSP solver with four-level repair memory escalation.

    Args:
        llm_client: Pre-configured LLM client.
        library: Paradigm library (SQLite-backed or in-memory).
        max_repair_rounds: Maximum repair iterations before declaring failure.
        paradigm_top_k: Number of candidates from Layer-1 retrieval.
        layer2_enabled: Whether to apply Layer-2 LLM semantic matching.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        library: ParadigmLibrary,
        max_repair_rounds: int = _DEFAULT_MAX_REPAIR_ROUNDS,
        paradigm_top_k: int = _DEFAULT_PARADIGM_TOP_K,
        layer2_enabled: bool = _LAYER2_ENABLED,
        enable_paradigm: bool = True,
        enable_memory: bool = True,
    ) -> None:
        self._llm = llm_client
        self._library = library
        self._translator = NLToZ3Translator(llm_client)
        self._extractor = FeatureExtractor()
        self._max_rounds = max_repair_rounds
        self._top_k = paradigm_top_k
        self._layer2 = layer2_enabled
        self._enable_paradigm = enable_paradigm
        self._enable_memory = enable_memory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(self, puzzle: PuzzleInstance) -> SolveResult:
        """Solve *puzzle* using the full PRISM pipeline.

        Args:
            puzzle: Puzzle instance with a populated ``nl_description``.

        Returns:
            :class:`~prism.core.types.SolveResult` with correctness,
            cost, and diagnostic fields populated.
        """
        self._llm.reset_call_count()
        memory = (
            RepairMemory({"stagnation_jaccard": 0.75, "loop_cosine": 0.90})
            if self._enable_memory
            else None
        )
        solver = Z3SolverWrapper()
        steps: List[dict] = []
        paradigm_triggered = False
        stagnation_detected = False

        # ── Step 0: initial translation ─────────────────────────────────
        constraints = self._translator.translate(puzzle)
        for c in constraints:
            solver.add_constraint(c)

        result = solver.check()
        steps.append({"iteration": 0, "action": "translate", "z3_result": result})

        if result == "SAT":
            return self._success(puzzle, solver, steps, self._llm.call_count)

        switcher = StrategySwitcher(memory) if memory is not None else None
        current_constraints = list(constraints)

        # ── Repair loop ────────────────────────────────────────────────
        for iteration in range(1, self._max_rounds + 1):
            unsat_core = solver.get_unsat_core() if result == "UNSAT" else []
            state = self._build_state(puzzle, current_constraints, unsat_core, result, iteration)
            state = state.model_copy(update={"constraint_types": self._extractor.extract(state)})

            # Try paradigm guidance
            paradigm_hint, par_triggered = (
                self._build_paradigm_hint(state, solver)
                if self._enable_paradigm
                else ("", False)
            )
            paradigm_triggered = paradigm_triggered or par_triggered

            # Strategy switcher
            switch_level = switcher.should_switch() if switcher is not None else None
            switch_prompt = ""
            if switch_level is not None:
                stagnation_detected = True
                switch_prompt = switcher.get_switch_prompt(switch_level, {
                    "unsat_core": unsat_core,
                    "problem_nl": puzzle.nl_description,
                })
                if switch_level.value == "L4_FULL_RETRANSLATE":
                    current_constraints = self._translator.retranslate(
                        puzzle, current_constraints, "\n".join(unsat_core)
                    )
                    solver = self._rebuild_solver(current_constraints)
                    result = solver.check()
                    steps.append({"iteration": iteration, "action": "retranslate", "z3_result": result})
                    if result == "SAT":
                        break
                    continue
                if switch_level.value == "L3_REVERT_CHECKPOINT":
                    ckpt = switcher.get_checkpoint()
                    if ckpt and "constraints" in ckpt:
                        current_constraints = list(ckpt["constraints"])
                        solver = self._rebuild_solver(current_constraints)
                        result = solver.check()

            # Repair via LLM
            history_summary = (
                memory.get_history_summary()
                if memory is not None
                else "No repair memory is enabled for this run."
            )
            repair_response = self._llm.repair(
                constraints=current_constraints,
                unsat_core=unsat_core,
                history_summary=history_summary,
                paradigm_hint=paradigm_hint,
                switch_prompt=switch_prompt,
            )
            repair_str = self._translator.parse_repair_response(repair_response)

            # Apply repair
            old_constraint, new_constraint = self._apply_repair(
                current_constraints, unsat_core, repair_str
            )

            # Check for loop before appending
            action = RepairAction(
                type=self._infer_repair_type(old_constraint, new_constraint),
                target_constraint=old_constraint or "",
                summary=repair_str or "",
            )
            if memory is not None and memory.detect_loop(action) and switch_level is None:
                logger.debug("Loop detected at iteration %d; saving checkpoint.", iteration)
                if switcher is not None:
                    switcher.save_checkpoint({
                        "iteration": iteration,
                        "constraints": list(current_constraints),
                        "summary": f"pre-repair iteration {iteration}",
                    })

            solver = self._rebuild_solver(current_constraints)
            result = solver.check()
            new_core = solver.get_unsat_core() if result == "UNSAT" else None

            record = RepairRecord(
                iteration=iteration,
                error_type=ErrorType.OVER_CONSTRAINT,
                unsat_core=unsat_core,
                core_fingerprint="",
                repair_action=action,
                outcome=Outcome.SAT if result == "SAT" else Outcome.UNSAT,
                new_core=new_core,
            )
            if memory is not None:
                memory.append(record)

            step_info = {
                "iteration": iteration,
                "action": "repair",
                "z3_result": result,
                "paradigm_triggered": par_triggered,
                "stagnated": stagnation_detected,
            }
            steps.append(step_info)

            if result == "SAT":
                if self._enable_paradigm:
                    self._writeback_confidence(record, state)
                if switcher is not None:
                    switcher.save_checkpoint({
                        "iteration": iteration,
                        "constraints": list(current_constraints),
                        "summary": f"SAT checkpoint at iteration {iteration}",
                    })
                break

        if result == "SAT":
            return self._success(puzzle, solver, steps, self._llm.call_count,
                                 paradigm_triggered, stagnation_detected)

        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=False,
            total_llm_calls=self._llm.call_count,
            repair_rounds=len(steps) - 1,
            steps=steps,
            final_z3_result=result,
            paradigm_triggered=paradigm_triggered,
            stagnation_detected=stagnation_detected,
        )

    # ------------------------------------------------------------------
    # Paradigm guidance
    # ------------------------------------------------------------------

    def _build_paradigm_hint(
        self, state: SolverState, solver: Z3SolverWrapper
    ) -> tuple[str, bool]:
        """Layer-1 + optional Layer-2 + consistency pre-check.

        Returns:
            (paradigm_hint_string, triggered_bool)
        """
        candidates = self._library.retrieve(state.constraint_types, top_k=self._top_k)
        if not candidates:
            return "", False

        # Layer-2 semantic match (optional)
        if self._layer2:
            state_summary = self._translator.build_state_summary(
                state.problem_nl, state.constraints, state.unsat_core or []
            )
            candidates = [
                p for p in candidates
                if self._llm.judge_semantic_match(p.operation, state_summary)
            ]

        if not candidates:
            return "", False

        # Consistency pre-check via Z3 clone
        valid_candidates = []
        trial_solver = solver.clone()
        for paradigm in candidates:
            if paradigm.pre_condition.strip():
                trial_solver.add_constraint(paradigm.pre_condition)
                trial_result = trial_solver.check()
                if trial_result == "SAT":
                    valid_candidates.append(paradigm)

        if not valid_candidates:
            return "", True

        best = valid_candidates[0]
        hint = (
            f"以下范式已在类似情境中验证有效（供参考）：\n"
            f"[{best.name}] {best.operation}"
        )
        return hint, True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_state(
        puzzle: PuzzleInstance,
        constraints: List[str],
        unsat_core: List[str],
        z3_result: str,
        iteration: int,
    ) -> SolverState:
        return SolverState(
            puzzle_id=puzzle.puzzle_id,
            constraints=constraints,
            unsat_core=unsat_core if unsat_core else None,
            z3_result=z3_result,
            iteration=iteration,
            problem_nl=puzzle.nl_description,
        )

    @staticmethod
    def _rebuild_solver(constraints: List[str]) -> Z3SolverWrapper:
        s = Z3SolverWrapper()
        for c in constraints:
            s.add_constraint(c)
        return s

    @staticmethod
    def _apply_repair(
        constraints: List[str],
        unsat_core: List[str],
        repair_str: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """Apply *repair_str* in-place on *constraints*.

        Returns ``(old_constraint, new_constraint)`` for record keeping.
        """
        if not repair_str:
            return None, None

        target_idx = next(
            (i for i, c in enumerate(constraints) if c in unsat_core), None
        )
        if target_idx is not None:
            old = constraints[target_idx]
            constraints[target_idx] = repair_str
            return old, repair_str

        constraints.append(repair_str)
        return None, repair_str

    @staticmethod
    def _infer_repair_type(old: Optional[str], new: Optional[str]) -> str:
        if old is None:
            return "add_constraint"
        if new is None:
            return "remove_constraint"
        return "modify_constraint"

    def _writeback_confidence(
        self, record: RepairRecord, state: SolverState
    ) -> None:
        """Update library confidence after a successful repair.

        Looks for paradigms whose scope overlaps with the current state's
        constraint types and bumps their confidence upward toward 1.0.
        """
        if not state.constraint_types:
            return
        matched = self._library.retrieve(state.constraint_types, top_k=1)
        for paradigm in matched:
            new_conf = min(1.0, paradigm.confidence + 0.01)
            try:
                self._library.update_confidence(paradigm.id, new_conf)
            except KeyError:
                pass

    @staticmethod
    def _success(
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
        steps: List[dict],
        llm_calls: int,
        paradigm_triggered: bool = False,
        stagnation_detected: bool = False,
    ) -> SolveResult:
        try:
            solution = solver.get_model()
        except Exception:  # noqa: BLE001
            solution = None
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=True,
            solution=solution,
            total_llm_calls=llm_calls,
            repair_rounds=max(0, len(steps) - 1),
            steps=steps,
            final_z3_result="SAT",
            paradigm_triggered=paradigm_triggered,
            stagnation_detected=stagnation_detected,
        )
