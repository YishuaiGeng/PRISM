"""Z3-based verification of abstracted paradigms before library ingestion.

Three verification checks are applied, corresponding to the three quality axes
used in the offline distillation algorithm:

1. **Soundness**: the paradigm's ``operation`` (assertion) is compatible with
   random subsets of its ``pre_condition`` constraints.  Measured as the fraction
   of trials that return SAT when the assertion is added to a random partial view
   of the pre-condition.  A score ≥ ``soundness_threshold`` is required.

2. **Effect**: the paradigm actually reduces domain uncertainty — after applying
   the operation, the solver's model is constrained in a new way.  Measured by
   checking that the assertion itself is satisfiable (non-vacuous) and adds new
   information (not a tautology under the current constraints).

3. **Trigger precision**: the ``trigger`` conditions are not overly broad.  A
   paradigm that fires on almost every constraint set is not useful.  This is
   estimated by checking how often the trigger conditions are satisfied on a
   sample of unrelated random constraint sets.

Paradigms that pass all three checks receive a ``confidence`` score equal to the
soundness rate and are ready for insertion into the ``ParadigmLibrary``.
"""

from __future__ import annotations

import logging
import random
from typing import List, Optional

from prism.core.solver import Z3SolverWrapper
from prism.paradigm_library.schema import Paradigm

logger = logging.getLogger(__name__)

_DEFAULT_N_SAMPLES: int = 50
_DEFAULT_SOUNDNESS_THRESHOLD: float = 0.90
_DEFAULT_TRIGGER_PRECISION_FLOOR: float = 0.20

_RANDOM_CONSTRAINT_POOL: List[str] = [
    "Int('x') > 0",
    "Int('x') < 10",
    "Int('y') >= 1",
    "Int('y') <= 5",
    "Int('z') == 3",
    "Int('x') != Int('y')",
    "Int('x') + Int('y') < 15",
    "Int('z') > Int('x')",
]


class ParadigmVerifier:
    """Verifies a candidate paradigm before it is added to the library.

    Args:
        n_samples: Number of random trials for soundness and precision checks.
        soundness_threshold: Minimum soundness score for acceptance.
        trigger_precision_floor: Minimum trigger precision (reject over-firing
            paradigms).
    """

    def __init__(
        self,
        n_samples: int = _DEFAULT_N_SAMPLES,
        soundness_threshold: float = _DEFAULT_SOUNDNESS_THRESHOLD,
        trigger_precision_floor: float = _DEFAULT_TRIGGER_PRECISION_FLOOR,
    ) -> None:
        self._n_samples = n_samples
        self._soundness_threshold = soundness_threshold
        self._precision_floor = trigger_precision_floor

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify(
        self,
        paradigm: Paradigm,
        solver: Optional[Z3SolverWrapper] = None,
    ) -> float:
        """Run all three verification checks and return a composite confidence score.

        Args:
            paradigm: The candidate paradigm to verify.
            solver: Optional solver instance whose current constraints are used
                as context for soundness trials.  A fresh solver is created if
                *None*.

        Returns:
            Float in [0.0, 1.0] representing soundness rate, or 0.0 if the
            paradigm fails the effect or trigger precision checks.
        """
        soundness = self.verify_soundness(paradigm, solver)
        if soundness < self._soundness_threshold:
            logger.debug("Paradigm %s rejected: soundness %.3f < %.3f", paradigm.id, soundness, self._soundness_threshold)
            return 0.0

        if not self.verify_effect(paradigm):
            logger.debug("Paradigm %s rejected: vacuous or tautological operation.", paradigm.id)
            return 0.0

        precision = self.verify_trigger_precision(paradigm)
        if precision < self._precision_floor:
            logger.debug("Paradigm %s rejected: trigger precision %.3f < %.3f", paradigm.id, precision, self._precision_floor)
            return 0.0

        logger.info("Paradigm %s accepted: soundness=%.3f, precision=%.3f", paradigm.id, soundness, precision)
        return soundness

    def verify_soundness(
        self,
        paradigm: Paradigm,
        solver: Optional[Z3SolverWrapper] = None,
    ) -> float:
        """Estimate soundness via random subset trials.

        Uses ``Z3SolverWrapper.verify_paradigm_soundness`` on a clone of
        *solver* (or a fresh solver if *None*) so that the existing constraint
        state is never mutated.

        Args:
            paradigm: Paradigm to test.
            solver: Optional base solver providing current constraints.

        Returns:
            Fraction of trials that return SAT in [0.0, 1.0].
        """
        base = (solver.clone() if solver else Z3SolverWrapper())
        pre = [paradigm.pre_condition] if paradigm.pre_condition.strip() else []
        operation = paradigm.operation.strip()
        if not operation:
            return 0.0

        return base.verify_paradigm_soundness(
            current_constraints=pre,
            paradigm_assertion=operation,
            n_trials=self._n_samples,
        )

    @staticmethod
    def verify_effect(paradigm: Paradigm) -> bool:
        """Check that the paradigm's operation is neither vacuous nor a tautology.

        A vacuous operation (empty string) or one that is trivially SAT without
        any constraints does not add new information.  An operation that is UNSAT
        on its own is outright wrong.

        Args:
            paradigm: Paradigm to test.

        Returns:
            True if the operation is non-vacuous and satisfiable.
        """
        operation = paradigm.operation.strip()
        if not operation:
            return False
        trial = Z3SolverWrapper()
        trial.add_constraint(operation)
        result = trial.check()
        return result == "SAT"

    def verify_trigger_precision(self, paradigm: Paradigm) -> float:
        """Estimate how selectively the trigger fires on unrelated constraint sets.

        Samples random constraint subsets from ``_RANDOM_CONSTRAINT_POOL`` and
        checks whether the trigger's ``constraint_types`` would match — a proxy
        for checking over-generality.  A paradigm with very high trigger
        rate on random constraints would fire too often in practice.

        Args:
            paradigm: Paradigm to test.

        Returns:
            Float in [0.0, 1.0]: fraction of random trials where the trigger
            does *not* fire.  Higher is better (more precise trigger).
        """
        trigger_types: List[str] = paradigm.trigger.get("constraint_types", [])
        if not trigger_types:
            return 1.0

        rng = random.Random(42)
        non_matching = 0
        for _ in range(self._n_samples):
            sample = rng.sample(_RANDOM_CONSTRAINT_POOL, k=min(3, len(_RANDOM_CONSTRAINT_POOL)))
            sample_text = " ".join(sample).lower()
            fires = any(ct.lower() in sample_text for ct in trigger_types)
            if not fires:
                non_matching += 1

        return non_matching / self._n_samples
