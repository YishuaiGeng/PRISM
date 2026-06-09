"""Constraint-type feature extraction for online paradigm retrieval.

Maps the current solver state's constraints to a set of constraint-type tags
that are used by ``ParadigmRetriever`` as the Layer-1 matching key.  The
mapping is done by lexical keyword analysis of the Z3 Python expression strings
— no LLM call is needed.

This module is intentionally kept stateless and dependency-light so it can be
used inside the hot path of ``GuidedSolver`` without adding latency.
"""

from __future__ import annotations

from typing import List

from prism.core.types import SolverState
from prism.core.constraint_tags import (
    classify_constraint_set_tags,
    classify_constraint_tags,
)


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
        return classify_constraint_set_tags(
            focus,
            is_unsat_core=bool(state.unsat_core),
        )

    def extract_bag(self, state: SolverState) -> List[str]:
        """Extract constraint-type tags **with multiplicity** from *state*.

        Unlike :meth:`extract`, this preserves repetitions so that a state with
        three ``adjacent`` constraints produces three ``"adjacent"`` entries.
        The returned bag is consumed by :meth:`ParadigmRetriever.retrieve` to
        evaluate relational predicates such as ``count_atleast`` and
        ``cooccur`` declared on paradigm triggers.

        Args:
            state: Current solver state with populated ``constraints`` field.

        Returns:
            List of constraint-type tags (with repetitions) appearing in the
            constraint set, in source order. Empty constraint set returns
            ``["unknown"]`` to mirror :meth:`extract`.
        """
        focus = state.unsat_core if state.unsat_core else state.constraints
        bag: List[str] = []
        for constraint in focus:
            bag.extend(self._classify(constraint))
        if state.unsat_core:
            contextual = classify_constraint_set_tags(focus, is_unsat_core=True)
            bag.extend(tag for tag in contextual if tag not in bag)
        return bag if bag else ["unknown"]

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(constraint: str) -> List[str]:
        """Map a single Z3 constraint string to zero or more type tags."""
        return classify_constraint_tags(constraint)

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
