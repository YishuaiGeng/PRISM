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

from prism.core.types import KDP, Trajectory, TrajectoryStep

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

_ALL_TYPES: List[str] = list(_CONSTRAINT_TYPE_KEYWORDS.keys())


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
        for step in trajectory.steps:
            if self._is_kdp(step, trajectory):
                constraint_types = self._extract_constraint_types(step)
                feature_vec = self._compute_feature_vector(constraint_types)
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
        """Classify the constraint involved in *step* by keyword matching."""
        text = " ".join(filter(None, [
            step.constraint_added,
            step.constraint_removed,
            step.constraint_modified,
        ])).lower()

        if not text:
            return ["unknown"]

        matched: List[str] = []
        for ctype, keywords in _CONSTRAINT_TYPE_KEYWORDS.items():
            if any(kw.lower() in text for kw in keywords):
                matched.append(ctype)
        return matched if matched else ["unknown"]

    @staticmethod
    def _compute_feature_vector(constraint_types: List[str]) -> List[float]:
        """Build a binary feature vector over all known constraint type dimensions."""
        type_set = set(constraint_types)
        return [1.0 if ct in type_set else 0.0 for ct in _ALL_TYPES]

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
