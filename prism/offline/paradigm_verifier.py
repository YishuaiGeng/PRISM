"""Z3-based verification of abstracted paradigms before library ingestion.

Three verification checks are applied, corresponding to the three quality axes
used in the offline distillation algorithm:

1. **Soundness**: the paradigm's ``operation`` is compatible with random subsets
   of its ``pre_condition`` constraints.  Measured as the fraction of trials that
   return SAT when the assertion is added to a random partial view of the
   pre-condition.  A score ≥ ``soundness_threshold`` is required.

2. **Effect**: the paradigm genuinely adds new information — the operation must
   be (a) satisfiable in combination with the pre-condition (non-contradictory),
   and (b) non-vacuous, i.e. not already implied by the pre-condition alone.
   The non-vacuousness check verifies that ``pre_condition ∧ ¬operation`` is SAT
   using a negated-operation probe.  This ensures the paradigm actually constrains
   the solution space rather than stating something trivially true.

3. **Trigger precision**: the ``trigger`` conditions are not overly broad.  A
   paradigm that fires on almost any constraint set provides no selectivity.
   Estimated by checking the trigger's ``constraint_types`` keywords against a
   representative pool of CSP constraint strings from both ZebraLogic-domain and
   generic integer-arithmetic contexts.  Higher non-matching rate = more precise.

Paradigms that pass all three checks receive a ``confidence`` score equal to the
soundness rate and are ready for insertion into the ``ParadigmLibrary``.
"""

from __future__ import annotations

import logging
import random
from typing import List, Optional

import z3

from prism.core.solver import _Z3_NS
from prism.core.solver import Z3SolverWrapper
from prism.paradigm_library.schema import Paradigm

logger = logging.getLogger(__name__)

_DEFAULT_N_SAMPLES: int = 50
_DEFAULT_SOUNDNESS_THRESHOLD: float = 0.90
_DEFAULT_TRIGGER_PRECISION_FLOOR: float = 0.20

# Canonical constraint kinds used for structured trigger matching.
# Each constraint in the pool is tagged with one or more kinds; trigger precision
# is estimated by *set-intersection* between a paradigm's declared
# ``constraint_types`` and the kinds of each pool sample — a structural match
# rather than substring containment.
#
# Tags are intentionally coarse and disjoint at the kind level so that a
# paradigm declaring ``["position_arithmetic"]`` does NOT match an
# ``attribute_binding`` constraint merely because both happen to mention the
# word "position".
_CONSTRAINT_KINDS: List[str] = [
    "position_arithmetic",   # e.g. position(X) == k + d, abs-difference on positions
    "position_equality",     # e.g. position(X) == position(Y), position(X) == c
    "position_inequality",   # e.g. position(X) != position(Y)
    "attribute_binding",     # e.g. drinks(English, Tea), keeps(Dog, X)
    "distinct",              # Distinct([...]) / all-different
    "quantified_exclusion",  # ForAll(..., Implies(..., !=))
    "integer_bound",         # Int('x') > k, < k, >= k, <= k
    "integer_equality",      # Int('x') == k
    "integer_inequality",    # Int('x') != Int('y')
    "integer_arithmetic",    # Int('x') + Int('y') < k, Int('z') > Int('x')
]

# Representative CSP constraint pool, each entry annotated with its canonical
# kind set. Covers ZebraLogic-domain patterns and generic integer arithmetic.
_REPRESENTATIVE_CONSTRAINT_POOL: List[tuple] = [
    # ZebraLogic-domain: ordering / position
    ("position(Norwegian) == 1",                                {"position_equality"}),
    ("position(English) != position(Spanish)",                  {"position_inequality"}),
    ("position(Blue) == position(Norwegian) + 1",               {"position_arithmetic"}),
    ("Abs(position(Green) - position(White)) == 1",             {"position_arithmetic"}),
    # ZebraLogic-domain: attribute binding
    ("drinks(English, Tea)",                                    {"attribute_binding"}),
    ("smokes(Kools, Yellow)",                                   {"attribute_binding"}),
    ("keeps(Dog, English)",                                     {"attribute_binding"}),
    ("drinks(Coffee, Green)",                                   {"attribute_binding"}),
    # ZebraLogic-domain: exclusion / uniqueness
    ("ForAll([h], Implies(color(h) == Red, nationality(h) != German))",
                                                                {"quantified_exclusion"}),
    ("Distinct([position(h) for h in houses])",                 {"distinct"}),
    ("owns(Zebra) != owns(Fox)",                                {"attribute_binding", "position_inequality"}),
    # Generic integer arithmetic (intentionally unrelated to ZebraLogic)
    ("Int('x') > 0",                                            {"integer_bound"}),
    ("Int('x') < 10",                                           {"integer_bound"}),
    ("Int('y') >= 1",                                           {"integer_bound"}),
    ("Int('y') <= 5",                                           {"integer_bound"}),
    ("Int('z') == 3",                                           {"integer_equality"}),
    ("Int('x') != Int('y')",                                    {"integer_inequality"}),
    ("Int('x') + Int('y') < 15",                                {"integer_arithmetic"}),
    ("Int('z') > Int('x')",                                     {"integer_arithmetic"}),
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

        if self.is_schema_invariant(paradigm):
            logger.debug("Paradigm %s rejected: schema invariant, not solving paradigm.", paradigm.id)
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
        if not pre:
            trial = Z3SolverWrapper()
            if not trial.add_constraint(operation):
                return 0.0
            return 1.0 if trial.check() == "SAT" else 0.0

        return base.verify_paradigm_soundness(
            current_constraints=pre,
            paradigm_assertion=operation,
            n_trials=self._n_samples,
        )

    @staticmethod
    def verify_effect(paradigm: Paradigm) -> bool:
        """Check that the paradigm's operation genuinely adds new information.

        Two conditions must both hold:

        1. **Non-contradiction**: ``pre_condition ∧ operation`` must be SAT.
           If the operation contradicts the pre-condition it is plainly wrong.

        2. **Non-vacuousness**: ``pre_condition ∧ ¬operation`` must also be SAT.
           If it were UNSAT, then ``pre_condition`` would already entail
           ``operation`` — the paradigm would add no information.  We assert the
           negation of the operation through ``Z3SolverWrapper.add_negated_constraint``
           and check satisfiability; a SAT result certifies that there exists
           at least one state where ``pre_condition`` holds but ``operation``
           does not, so the operation is genuinely informative.

        If ``pre_condition`` is empty (no precondition stated), non-vacuousness
        reduces to ``¬operation`` being SAT, i.e. the operation is not a
        tautology by itself.  False negatives on syntactically un-negatable
        operations are preferable to false positives on vacuous paradigms.

        Args:
            paradigm: Paradigm to test.

        Returns:
            True if the operation is both consistent with the pre-condition and
            genuinely informative.
        """
        operation = paradigm.operation.strip()
        if not operation:
            return False

        pre = paradigm.pre_condition.strip()

        # Condition 1: pre_condition ∧ operation must be SAT
        trial = Z3SolverWrapper()
        if pre:
            if not trial.add_constraint(pre):
                return False
        if not trial.add_constraint(operation):
            return False
        if trial.check() != "SAT":
            return False

        # Condition 2: pre_condition ∧ ¬operation must be SAT.
        # If UNSAT, pre_condition already entails operation → vacuous.
        # If pre is empty, we only test that ¬operation is SAT (operation is
        # not a tautology by itself).
        probe = Z3SolverWrapper()
        if pre:
            if not probe.add_constraint(pre):
                return False
        if not probe.add_negated_constraint(operation):
            # Could not parse / negate the operation. Be conservative: reject.
            return False
        if probe.check() != "SAT":
            return False  # pre entails operation → vacuous

        return True

    def verify_trigger_precision(self, paradigm: Paradigm) -> float:
        """Estimate how selectively the trigger fires on a representative pool.

        Samples random constraint subsets from ``_REPRESENTATIVE_CONSTRAINT_POOL``
        (annotated with canonical constraint kinds — see ``_CONSTRAINT_KINDS``)
        and checks whether the paradigm's declared ``constraint_types`` overlap
        with the kinds present in the sample.  The match is a *set-intersection*
        on canonical kinds rather than substring containment, so a paradigm
        declaring ``position_arithmetic`` does not spuriously match an
        ``attribute_binding`` constraint that incidentally mentions ``position``.

        A paradigm that fires on most samples is over-general; the test returns
        the fraction of samples where the trigger does *not* fire.

        Args:
            paradigm: Paradigm to test.

        Returns:
            Float in [0.0, 1.0]: fraction of samples where the trigger does
            *not* fire.  Higher is better (more selective trigger).
        """
        trigger_types_raw: List[str] = paradigm.trigger.get("constraint_types", [])
        if not trigger_types_raw:
            # A paradigm with no trigger types fires everywhere — reject.
            return 0.0
        trigger_types = {t.strip().lower() for t in trigger_types_raw if t and t.strip()}
        if not trigger_types:
            return 0.0

        rng = random.Random(42)
        pool_size = len(_REPRESENTATIVE_CONSTRAINT_POOL)
        non_matching = 0
        for _ in range(self._n_samples):
            k = rng.randint(2, min(5, pool_size))
            sample = rng.sample(_REPRESENTATIVE_CONSTRAINT_POOL, k=k)
            sample_kinds: set = set()
            for _text, kinds in sample:
                sample_kinds.update(kinds)
            fires = bool(trigger_types & sample_kinds)
            if not fires:
                non_matching += 1

        return non_matching / self._n_samples

    @staticmethod
    def is_schema_invariant(paradigm: Paradigm) -> bool:
        """Return True for generic puzzle-schema constraints, not solving paradigms.

        Domain bounds such as ``And(Int('x') >= 1, Int('x') <= 3)`` are validity
        guards for a generated puzzle, not reusable Zebra reasoning strategies.
        They should be enforced by translation/validation, not stored as
        positive memory.
        """
        if paradigm.pre_condition.strip():
            return False
        return _is_pure_domain_bound(paradigm.operation)


def _is_pure_domain_bound(operation: str) -> bool:
    try:
        expr = eval(operation, _Z3_NS)  # noqa: S307
    except Exception:
        return False
    if not z3.is_bool(expr):
        return False

    atoms: list[z3.BoolRef] = []

    def walk(node) -> bool:
        try:
            kind = node.decl().kind()
        except Exception:
            return False
        if kind == z3.Z3_OP_AND:
            return all(walk(node.arg(i)) for i in range(node.num_args()))
        if kind in (z3.Z3_OP_LE, z3.Z3_OP_LT, z3.Z3_OP_GE, z3.Z3_OP_GT):
            atoms.append(node)
            return _is_var_constant_bound(node)
        return False

    return walk(expr) and bool(atoms)


def _is_var_constant_bound(atom) -> bool:
    lhs = atom.arg(0)
    rhs = atom.arg(1)
    return (
        (_is_int_variable(lhs) and _is_int_literal(rhs))
        or (_is_int_literal(lhs) and _is_int_variable(rhs))
    )


def _is_int_variable(expr) -> bool:
    try:
        return (
            z3.is_const(expr)
            and expr.decl().kind() == z3.Z3_OP_UNINTERPRETED
            and expr.sort().kind() == z3.Z3_INT_SORT
        )
    except Exception:
        return False


def _is_int_literal(expr) -> bool:
    try:
        return z3.is_int_value(expr)
    except Exception:
        return False
