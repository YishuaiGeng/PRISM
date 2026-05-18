"""Constraint-type feature extraction for online paradigm retrieval.

Maps the current solver state's constraints to a set of constraint-type tags
that are used by ``ParadigmRetriever`` as the Layer-1 matching key.  The
mapping is done by lexical keyword analysis of the Z3 Python expression strings
— no LLM call is needed.

This module is intentionally kept stateless and dependency-light so it can be
used inside the hot path of ``GuidedSolver`` without adding latency.
"""

from __future__ import annotations

from typing import Dict, List, Set

from prism.core.types import SolverState

_KEYWORD_TO_TYPE: Dict[str, str] = {
    "distinct(":       "all_different",
    "Distinct(":       "all_different",
    "immediately":     "adjacent",
    "adjacent":        "adjacent",
    "next to":         "adjacent",
    "left of":         "relative_position",
    "right of":        "relative_position",
    "== 1":            "direct_position",
    "== 2":            "direct_position",
    "== 3":            "direct_position",
    "== 4":            "direct_position",
    "== 5":            "direct_position",
    "!= ":             "exclusion",
    "also has":        "inclusion",
    "< ":              "ordering",
    "> ":              "ordering",
    "and(":            "logical_implication",
    "And(":            "logical_implication",
    "or(":             "logical_implication",
    "Or(":             "logical_implication",
    "not(":            "logical_implication",
    "Not(":            "logical_implication",
    "if ":             "binding",
    "implies":         "binding",
}

_POSITION_EQUALITY = frozenset({"== 1", "== 2", "== 3", "== 4", "== 5", "== 6", "== 7"})


class FeatureExtractor:
    """Extracts constraint-type tags from a solver state's constraint strings.

    Tags are used as the query key for :class:`~prism.paradigm_library.retriever.ParadigmRetriever`
    Layer-1 lookup.  The extraction is purely lexical (no Z3 or LLM calls).

    Typical usage::

        extractor = FeatureExtractor()
        types = extractor.extract(state)   # e.g. ["adjacent", "all_different"]
        candidates = library.retrieve(types, top_k=5)
    """

    def extract(self, state: SolverState) -> List[str]:
        """Extract constraint-type tags from *state*.

        Args:
            state: Current solver state with populated ``constraints`` field.

        Returns:
            Deduplicated list of constraint-type tags present in the constraint
            set, sorted for deterministic output.
        """
        focus = state.unsat_core if state.unsat_core else state.constraints
        tags: Set[str] = set()
        for constraint in focus:
            tags.update(self._classify(constraint))
        return sorted(tags) if tags else ["unknown"]

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(constraint: str) -> List[str]:
        """Map a single Z3 constraint string to zero or more type tags."""
        types: List[str] = []
        for keyword, ctype in _KEYWORD_TO_TYPE.items():
            if keyword in constraint:
                types.append(ctype)
        return types or ["unknown"]

    def classify_constraint_type(self, constraint: str) -> str:
        """Return the most specific type tag for a single constraint.

        When multiple tags match, the first in insertion order is returned.
        Falls back to ``"unknown"`` when no keyword matches.

        Args:
            constraint: A Z3 Python expression string.

        Returns:
            A single constraint-type tag string.
        """
        types = self._classify(constraint)
        return types[0] if types else "unknown"
