"""Key Decision Point (KDP) extraction from solver trajectories.

A KDP is a trajectory step that represents a non-trivial inference — moments
where the solver made a meaningful reasoning jump that can be generalised into
a reusable paradigm.  Three detection conditions are used:

- **(A) Domain reduction**: the domain size of at least one variable dropped by
  ≥2 after the step (a large, decisive inference).
- **(B) Step type**: the step is classified as ``CHAIN`` or ``CONTRADICTION``,
  indicating a propagation chain or an error that required structural insight.
- **(C) Information gain**: the aggregate log-ratio of domain-size reductions
  across *all* variables exceeds a soft floor (default 1.0 bits). This catches
  "gradual tightening" steps that are individually below the hard ≥2 threshold
  of condition (A) but collectively constitute a meaningful inference — the
  dominant pattern in harder puzzles such as 6×6 ZebraLogic.

KDPs are annotated with constraint-type tags (used for Layer-1 retrieval) and
dense feature vectors (used for agglomerative clustering).
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import Dict, List, Optional

from prism.core.constraint_tags import classify_constraint_tags
from prism.core.types import KDP, StepType, Trajectory, TrajectoryStep

logger = logging.getLogger(__name__)

_DOMAIN_DROP_THRESHOLD: int = 2
_INFO_GAIN_BITS_THRESHOLD: float = 1.0

_CONSTRAINT_TYPE_KEYWORDS: Dict[str, List[str]] = {
    "direct_position": ["lives in house", "== house", "position"],
    "relative_position": ["left of", "right of"],
    "adjacent": ["immediately", "adjacent", "next to", "neighbor"],
    "exclusion": ["different", "not equal", "!=", "distinct"],
    "inclusion": ["also has", "same", "=="],
    "ordering": ["before", "after", "< ", "> "],
    "binding": ["if", "then", "implies", "=>"],
    "all_different": ["distinct(", "Distinct("],
    "logical_implication": ["And(", "Or(", "Not("],
}

# Specific relation tags shared with the online extractor
# (prism.core.constraint_tags). Keeping offline KDP tags in the same
# namespace as online retrieval queries is what makes Layer-1 scope
# Jaccard non-zero at inference time.
_SPECIFIC_TYPES: List[str] = [
    "directly_left",
    "directly_right",
    "somewhere_left",
    "somewhere_right",
    "same_house",
    "domain_bound",
]

_ALL_TYPES: List[str] = list(_CONSTRAINT_TYPE_KEYWORDS.keys()) + _SPECIFIC_TYPES

# Feature-vector layout (paper §Methodology, f(kdp) = [h_ct, b_dom, e_τ, n_var, n_con]):
_DOMAIN_SIZE_BINS = ((1, 1), (2, 2), (3, 4), (5, 10**9))
_STEP_TYPE_ORDER = (StepType.BASIC, StepType.CHAIN, StepType.CONTRADICTION)
_N_VAR_NORM = 36.0  # 6x6 puzzles: 36 entity-attribute variables
_N_CON_NORM = 30.0  # rough upper bound on formalized constraints per puzzle


class KDPIdentifier:
    """Extracts Key Decision Points from trajectories.

    Typical usage::

        identifier = KDPIdentifier()
        kdps = []
        for traj in trajectories:
            kdps.extend(identifier.identify(traj))
    """

    def __init__(
        self,
        domain_drop_threshold: int = _DOMAIN_DROP_THRESHOLD,
        info_gain_bits_threshold: float = _INFO_GAIN_BITS_THRESHOLD,
    ) -> None:
        self._threshold = domain_drop_threshold
        self._info_gain_threshold = info_gain_bits_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def identify(self, trajectory: Trajectory) -> List[KDP]:
        """Extract all KDPs from a trajectory.

        Args:
            trajectory: A solved or failed solving trajectory.

        Returns:
            List of KDP objects (may be empty for trivial trajectories).
        """
        kdps: List[KDP] = []
        n_constraints = 0
        for step in trajectory.steps:
            if step.constraint_added:
                n_constraints += 1
            if step.constraint_removed:
                n_constraints = max(0, n_constraints - 1)
            if self._is_kdp(step, trajectory):
                constraint_types = self._extract_constraint_types(step)
                feature_vec = self._compute_feature_vector(
                    constraint_types, step, n_constraints
                )
                kdp = KDP(
                    trajectory_id=trajectory.trajectory_id,
                    puzzle_id=trajectory.puzzle_id,
                    step=step,
                    constraint_types=constraint_types,
                    feature_vector=feature_vec,
                    kdp_type=self._kdp_type(step, trajectory),
                )
                kdps.append(kdp)
        logger.debug(
            "Trajectory %s: %d steps → %d KDPs",
            trajectory.trajectory_id[:8], len(trajectory.steps), len(kdps),
        )
        return kdps

    # ------------------------------------------------------------------
    # Detection conditions
    # ------------------------------------------------------------------

    def _is_kdp(self, step: TrajectoryStep, trajectory: Optional[Trajectory] = None) -> bool:
        """Return True if *step* satisfies condition (A), (B), or (C)."""
        if trajectory is not None and self._condition_successful_repair(step, trajectory):
            return True
        if self._condition_a(step):
            return True
        if self._condition_b(step):
            return True
        if self._condition_c(step):
            return True
        return False

    @staticmethod
    def _condition_successful_repair(step: TrajectoryStep, trajectory: Trajectory) -> bool:
        """Condition (D): a repair step that turns a solved trajectory SAT."""
        return (
            trajectory.solved
            and step.action == "repair"
            and step.z3_result == "SAT"
            and bool(step.constraint_added or step.constraint_modified)
        )

    def _condition_a(self, step: TrajectoryStep) -> bool:
        """Condition (A): domain size dropped by ≥threshold for any variable."""
        before = step.domain_sizes_before
        after = step.domain_sizes_after
        if not before or not after:
            return False
        for var, size_before in before.items():
            size_after = after.get(var, size_before)
            if size_before - size_after >= self._threshold:
                return True
        return False

    @staticmethod
    def _condition_b(step: TrajectoryStep) -> bool:
        """Condition (B): step type is CHAIN or CONTRADICTION."""
        from prism.core.types import StepType
        return step.step_type in (StepType.CHAIN, StepType.CONTRADICTION)

    def _condition_c(self, step: TrajectoryStep) -> bool:
        """Condition (C): aggregate information gain across all variables.

        Soft signal that complements the hard ``≥ threshold per variable``
        cutoff of condition (A). The aggregate gain is

            G(step) = Σ_x log2(|δ_before(x)| / |δ_after(x)|)

        summed over variables whose domains actually shrank. If at least one
        variable went to size ≤ 0 the step is treated as decisive (∞ gain).
        A step is a KDP under (C) iff ``G(step) ≥ self._info_gain_threshold``.
        """
        before = step.domain_sizes_before
        after = step.domain_sizes_after
        if not before or not after:
            return False
        total_gain = 0.0
        for var, size_before in before.items():
            size_after = after.get(var, size_before)
            if size_after <= 0:
                # Variable became impossible: treat as decisive.
                return True
            if size_after >= size_before:
                continue
            total_gain += math.log2(size_before / size_after)
            if total_gain >= self._info_gain_threshold:
                return True
        return total_gain >= self._info_gain_threshold

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_constraint_types(step: TrajectoryStep) -> List[str]:
        """Classify the constraint involved in *step*.

        Combines the legacy keyword table with the shared online classifier
        (:func:`prism.core.constraint_tags.classify_constraint_tags`) so that
        offline paradigm scopes and online retrieval queries live in the same
        tag namespace.
        """
        constraint_strings = [
            c for c in (
                step.constraint_added,
                step.constraint_removed,
                step.constraint_modified,
            ) if c
        ]
        if not constraint_strings:
            return ["unknown"]

        matched: set = set()
        text = " ".join(constraint_strings).lower()
        for ctype, keywords in _CONSTRAINT_TYPE_KEYWORDS.items():
            if any(kw.lower() in text for kw in keywords):
                matched.add(ctype)
        for constraint in constraint_strings:
            matched.update(classify_constraint_tags(constraint))
        return sorted(matched) if matched else ["unknown"]

    @staticmethod
    def _compute_feature_vector(
        constraint_types: List[str],
        step: Optional[TrajectoryStep] = None,
        n_constraints: int = 0,
    ) -> List[float]:
        """Build the clustering feature vector f(kdp) = [h_ct, b_dom, e_τ, n_var, n_con].

        - ``h_ct``: L1-normalised histogram over the known constraint types;
        - ``b_dom``: 4-bin distribution of post-step domain sizes
          (bins: {1}, {2}, {3-4}, {5+});
        - ``e_τ``: one-hot step-type encoding (BASIC / CHAIN / CONTRADICTION);
        - ``n_var`` / ``n_con``: normalised problem-scale metrics.
        """
        known = [ct for ct in constraint_types if ct in _ALL_TYPES]
        total = float(len(known)) or 1.0
        h_ct = [known.count(ct) / total for ct in _ALL_TYPES]

        b_dom = [0.0] * len(_DOMAIN_SIZE_BINS)
        n_var = 0.0
        if step is not None and step.domain_sizes_after:
            sizes = list(step.domain_sizes_after.values())
            for size in sizes:
                for bin_idx, (lo, hi) in enumerate(_DOMAIN_SIZE_BINS):
                    if lo <= size <= hi:
                        b_dom[bin_idx] += 1.0
                        break
            b_dom = [count / len(sizes) for count in b_dom]
            n_var = min(1.0, len(sizes) / _N_VAR_NORM)

        e_tau = [
            1.0 if step is not None and step.step_type == st else 0.0
            for st in _STEP_TYPE_ORDER
        ]
        n_con = min(1.0, max(0, n_constraints) / _N_CON_NORM)
        return h_ct + b_dom + e_tau + [n_var, n_con]

    @staticmethod
    def _kdp_type(step: TrajectoryStep, trajectory: Optional[Trajectory] = None) -> str:
        from prism.core.types import StepType
        if trajectory is not None and KDPIdentifier._condition_successful_repair(step, trajectory):
            return "SUCCESSFUL_REPAIR"
        if step.step_type == StepType.CHAIN:
            return "CHAIN"
        if step.step_type == StepType.CONTRADICTION:
            return "CONTRADICTION"
        return "DOMAIN_REDUCTION"
