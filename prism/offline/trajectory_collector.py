"""Offline trajectory collection for paradigm distillation.

Runs the Paper-1 pipeline (LLM+Z3, no memory) on a set of training puzzles and
records each solver step as a :class:`~prism.core.types.TrajectoryStep`, bundled
into a :class:`~prism.core.types.Trajectory`.

Multiple runs per puzzle (``n_runs > 1``) use different random seeds to generate
diverse trajectories from the same puzzle — important for paradigm coverage.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.core.translator import NLToZ3Translator
from prism.core.types import PuzzleInstance, StepType, Trajectory, TrajectoryStep

logger = logging.getLogger(__name__)

_DEFAULT_MAX_REPAIR_ROUNDS: int = 5
_DEFAULT_N_RUNS: int = 3


# Widest value range probed when the range is inferred from constraint
# literals rather than a known grid size; bounds the O(vars × range) probing
# cost and shields against outlier literals (years, large counts).
_MAX_INFERRED_RANGE_WIDTH: int = 12


def _compute_domain_sizes(
    solver: Z3SolverWrapper,
    n_houses: int = 0,
    value_range: Optional[tuple] = None,
) -> dict[str, int]:
    """Count how many values in the puzzle value range remain feasible per variable.

    For each Z3 Int variable mentioned in the current solver, probe how many
    values in the range are consistent with current constraints. Uses one Z3
    clone per variable × per candidate value — O(vars × range) solver calls,
    each very fast (milliseconds).

    Args:
        solver: The Z3SolverWrapper instance to analyze.
        n_houses: The grid size (e.g. 3 for a 3x3 puzzle); probes [1..n_houses].
        value_range: Explicit ``(lo, hi)`` range; overrides *n_houses*. Used by
            benchmarks without a grid size (see :func:`_infer_value_range`).

    Returns:
        A dict mapping variable name → count of feasible values in the range.
        Returns empty dict if no usable range or no variables found.
    """
    if value_range is not None:
        lo, hi = value_range
    elif n_houses > 0:
        lo, hi = 1, n_houses
    else:
        return {}
    if hi < lo:
        return {}
    variables = solver.get_variables()
    if not variables:
        return {}
    result: dict[str, int] = {}
    for var in variables:
        count = 0
        for val in range(lo, hi + 1):
            probe = Z3SolverWrapper()
            for c in solver.get_constraints():
                probe.add_constraint(c)
            probe.add_constraint(f"Int('{var}') == {val}")
            if probe.check() == "SAT":
                count += 1
        result[var] = max(count, 1)  # floor at 1 to avoid log2(0) in KDP info-gain
    return result


def _infer_value_range(constraints: List[str]) -> Optional[tuple]:
    """Infer a plausible variable value range from constraint integer literals.

    Benchmarks without a grid size (e.g. AR-LSAT) encode positions, slots, or
    0/1 selection flags whose bounds appear as literals in the translated
    domain constraints; the span of the non-negative literals approximates the
    value range. Literals inside quoted variable names are ignored. The width
    is capped at ``_MAX_INFERRED_RANGE_WIDTH`` so an outlier literal (a year,
    a large count) cannot explode the probing cost.

    Returns:
        ``(lo, hi)`` or ``None`` when no usable literals are found (domain
        tracking stays disabled for this puzzle).
    """
    literals: set = set()
    for constraint in constraints:
        unquoted = re.sub(r"'[^']*'", "", constraint or "")
        for match in re.findall(r"-?\d+", unquoted):
            literals.add(int(match))
    usable = sorted(v for v in literals if v >= 0)
    if not usable:
        return None
    lo, hi = usable[0], usable[-1]
    if hi == lo:
        return None
    hi = min(hi, lo + _MAX_INFERRED_RANGE_WIDTH - 1)
    return lo, hi


class TrajectoryCollector:
    """Runs the Paper-1 LLM+Z3 pipeline and records solving trajectories.

    One ``TrajectoryCollector`` instance should be used for a single collection
    session.  The LLM client is shared across runs; its call count reflects the
    total cost of the whole session.

    Args:
        llm_client: Pre-configured :class:`~prism.core.llm_client.LLMClient`.
        max_repair_rounds: Max repair iterations before declaring failure.
        output_dir: If set, each trajectory is immediately written to disk as
            a JSON file under this directory.  Useful for long collection runs.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        max_repair_rounds: int = _DEFAULT_MAX_REPAIR_ROUNDS,
        output_dir: Optional[str] = None,
    ) -> None:
        self._llm = llm_client
        self._translator = NLToZ3Translator(llm_client)
        self._max_rounds = max_repair_rounds
        self._output_dir = Path(output_dir) if output_dir else None
        if self._output_dir:
            self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(
        self,
        puzzles: List[PuzzleInstance],
        n_runs: int = _DEFAULT_N_RUNS,
        temperature: float = 0.7,
    ) -> List[Trajectory]:
        """Collect trajectories for all puzzles.

        Args:
            puzzles: Training puzzles to solve.
            n_runs: Number of independent runs per puzzle (diversity sampling).
            temperature: LLM sampling temperature (0.7 recommended for diversity).

        Returns:
            All collected trajectories (successful and failed).
        """
        all_trajectories: List[Trajectory] = []
        total = len(puzzles) * n_runs
        done = 0
        for puzzle in puzzles:
            for run_idx in range(n_runs):
                seed = run_idx * 1000 + hash(puzzle.puzzle_id) % 1000
                traj = self._solve_once(puzzle, temperature=temperature, seed=seed)
                all_trajectories.append(traj)
                if self._output_dir:
                    self._save(traj)
                done += 1
                if done % 50 == 0:
                    logger.info("Collected %d/%d trajectories", done, total)
        logger.info("Collection complete: %d trajectories from %d puzzles", len(all_trajectories), len(puzzles))
        return all_trajectories

    # ------------------------------------------------------------------
    # Private: solve one puzzle run
    # ------------------------------------------------------------------

    def _solve_once(
        self,
        puzzle: PuzzleInstance,
        temperature: float,
        seed: int,
    ) -> Trajectory:
        """Run the Paper-1 pipeline on *puzzle* and record the trajectory."""
        solver = Z3SolverWrapper()
        steps: List[TrajectoryStep] = []
        llm_calls_start = self._llm.call_count

        # ── Step 0: initial translation ────────────────────────────────
        constraints = self._translator.translate(puzzle)
        calls_after_translate = self._llm.call_count - llm_calls_start

        initial_step = TrajectoryStep(
            iteration=0,
            action="translate",
            step_type=StepType.BASIC,
            z3_result="PENDING",
            llm_call_count=calls_after_translate,
        )
        if not constraints:
            initial_step = initial_step.model_copy(update={
                "z3_result": "TRANSLATION_FAILED",
                "error_type": "NO_VALID_CONSTRAINTS",
            })
            steps.append(initial_step)
            total_calls = self._llm.call_count - llm_calls_start
            return Trajectory(
                trajectory_id=str(uuid.uuid4()),
                puzzle_id=puzzle.puzzle_id,
                puzzle_nl=puzzle.nl_description,
                temperature=temperature,
                seed=seed,
                steps=steps,
                final_result="TRANSLATION_FAILED",
                solved=False,
                total_llm_calls=total_calls,
                solution=None,
            )

        for c in constraints:
            solver.add_constraint(c)

        result = solver.check()
        initial_step = initial_step.model_copy(update={"z3_result": result})
        steps.append(initial_step)

        solution: Optional[dict] = solver.get_model() if result == "SAT" else None
        solved = result == "SAT" and self._model_within_puzzle_domain(puzzle, solution)
        if result == "SAT" and not solved:
            result = "INVALID_MODEL"
            initial_step = initial_step.model_copy(update={
                "z3_result": result,
                "error_type": "MODEL_OUT_OF_DOMAIN",
            })
            steps[-1] = initial_step

        # ── Repair loop ────────────────────────────────────────────────
        current_constraints = list(constraints)
        n_houses = self._puzzle_n_houses(puzzle)
        # Grid puzzles derive the value range from their size; benchmarks
        # without one (e.g. AR-LSAT) infer it from constraint literals so the
        # KDP domain-reduction conditions (A/C) stay alive.
        value_range = (1, n_houses) if n_houses > 0 else _infer_value_range(constraints)
        for iteration in range(1, self._max_rounds + 1):
            if solved:
                break

            unsat_core = solver.get_unsat_core() if result == "UNSAT" else []
            calls_before = self._llm.call_count

            # Capture domain sizes BEFORE this repair step
            sizes_before = _compute_domain_sizes(solver, value_range=value_range)

            repair_response = self._llm.repair(
                constraints=current_constraints,
                unsat_core=unsat_core,
                history_summary="初次修复" if iteration == 1 else f"第 {iteration} 次修复",
            )
            repair_str = self._translator.parse_repair_response(repair_response)
            calls_after = self._llm.call_count - calls_before

            step = TrajectoryStep(
                iteration=iteration,
                action="repair",
                step_type=self._classify_step(unsat_core, result),
                unsat_core=unsat_core,
                z3_result="PENDING",
                llm_call_count=calls_after,
                domain_sizes_before=sizes_before,
            )

            if repair_str:
                target_idx = self._find_repair_target(unsat_core, current_constraints)
                if target_idx is not None:
                    old = current_constraints[target_idx]
                    current_constraints[target_idx] = repair_str
                    step = step.model_copy(update={
                        "constraint_removed": old,
                        "constraint_added": repair_str,
                    })
                else:
                    current_constraints.append(repair_str)
                    step = step.model_copy(update={"constraint_added": repair_str})

                solver = Z3SolverWrapper()
                for c in current_constraints:
                    solver.add_constraint(c)

            result = solver.check()

            # Capture domain sizes AFTER applying repair
            sizes_after = _compute_domain_sizes(solver, value_range=value_range)
            step = step.model_copy(update={
                "z3_result": result,
                "domain_sizes_after": sizes_after,
            })
            steps.append(step)

            if result == "SAT":
                solution = solver.get_model()
                solved = self._model_within_puzzle_domain(puzzle, solution)
                if solved:
                    break
                result = "INVALID_MODEL"
                step = step.model_copy(update={
                    "z3_result": result,
                    "error_type": "MODEL_OUT_OF_DOMAIN",
                })
                steps[-1] = step
                break

        total_calls = self._llm.call_count - llm_calls_start
        return Trajectory(
            trajectory_id=str(uuid.uuid4()),
            puzzle_id=puzzle.puzzle_id,
            puzzle_nl=puzzle.nl_description,
            temperature=temperature,
            seed=seed,
            steps=steps,
            final_result=result,
            solved=solved,
            total_llm_calls=total_calls,
            solution=solution,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_step(unsat_core: List[str], result: str) -> StepType:
        if result == "UNSAT" and unsat_core:
            return StepType.CONTRADICTION
        return StepType.BASIC

    @staticmethod
    def _find_repair_target(
        unsat_core: List[str],
        constraints: List[str],
    ) -> Optional[int]:
        """Return index of the first UNSAT-core constraint in *constraints*, or None."""
        for i, c in enumerate(constraints):
            if c in unsat_core:
                return i
        return None

    @staticmethod
    def _puzzle_n_houses(puzzle: PuzzleInstance) -> int:
        """Parse n_houses from puzzle.size string like '3x3' or '4x5'.

        Args:
            puzzle: The puzzle instance with a size string.

        Returns:
            The first dimension (number of houses), or 0 if parsing fails.
        """
        try:
            return int(str(puzzle.size).lower().split("x", 1)[0])
        except (TypeError, ValueError, IndexError):
            return 0

    @staticmethod
    def _model_within_puzzle_domain(
        puzzle: PuzzleInstance,
        solution: Optional[dict],
    ) -> bool:
        """Reject SAT models with integer assignments outside the puzzle range."""
        if not solution or not puzzle.size:
            return True
        try:
            n_entities = int(str(puzzle.size).lower().split("x", 1)[0])
        except (TypeError, ValueError):
            return True

        for name, raw_value in solution.items():
            if str(name).startswith("_prism_track_"):
                continue
            try:
                value = int(str(raw_value))
            except ValueError:
                continue
            if value < 1 or value > n_entities:
                return False
        return True

    def _save(self, traj: Trajectory) -> None:
        path = self._output_dir / f"{traj.trajectory_id}.json"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(traj.model_dump(mode="json"), fh, ensure_ascii=False, indent=2)
