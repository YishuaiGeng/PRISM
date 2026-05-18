"""Natural-language to Z3 constraint translator.

Wraps LLMClient.translate / retranslate and handles the parsing, basic
validation, and retry logic so that callers (GuidedSolver, TrajectoryCollector)
receive a clean list of Z3 expression strings.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.solver import SolverError, Z3SolverWrapper
from prism.core.types import PuzzleInstance

logger = logging.getLogger(__name__)

_MAX_PARSE_RETRIES: int = 2


class NLToZ3Translator:
    """Translates natural-language CSP descriptions into Z3 Python constraint strings.

    Calls the underlying LLM to produce a fenced Python code block, then
    extracts individual expression strings and optionally validates each one
    with a trial Z3SolverWrapper.

    Typical usage::

        translator = NLToZ3Translator(llm_client)
        constraints = translator.translate(puzzle)
        if not constraints:
            constraints = translator.translate(puzzle)  # retry on empty
    """

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm = llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(self, puzzle: PuzzleInstance) -> List[str]:
        """Translate puzzle NL description to a list of Z3 constraint strings.

        Retries up to ``_MAX_PARSE_RETRIES`` times if the parsed constraint
        list is empty (the LLM produced no parseable code).

        Args:
            puzzle: The puzzle instance whose ``nl_description`` is translated.

        Returns:
            List of Z3 Python expression strings (may be empty on persistent failure).
        """
        for attempt in range(1 + _MAX_PARSE_RETRIES):
            response = self._llm.translate(puzzle.nl_description)
            constraints = LLMClient.parse_constraints(response)
            validated = self._validate(constraints)
            if validated:
                return validated
            logger.warning("Translation attempt %d produced no valid constraints.", attempt + 1)
        return []

    def retranslate(
        self,
        puzzle: PuzzleInstance,
        failed_constraints: List[str],
        error_ctx: str,
    ) -> List[str]:
        """Request a full re-translation after L4 strategy escalation.

        Args:
            puzzle: Original puzzle instance.
            failed_constraints: The constraint set that led to irrecoverable UNSAT.
            error_ctx: Human-readable error description for LLM context.

        Returns:
            Fresh list of Z3 expression strings.
        """
        response = self._llm.retranslate(
            puzzle.nl_description, failed_constraints, error_ctx
        )
        constraints = LLMClient.parse_constraints(response)
        return self._validate(constraints)

    def parse_repair_response(self, response: str) -> Optional[str]:
        """Extract a single corrected constraint from a repair LLM response.

        Args:
            response: Raw LLM output from a repair call.

        Returns:
            A single Z3 expression string, or ``None`` if unparseable.
        """
        return LLMClient.parse_repair(response)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate(self, constraints: List[str]) -> List[str]:
        """Filter out constraints that raise a SolverError when parsed.

        Uses a temporary Z3SolverWrapper to attempt parsing each expression.
        Lines that fail (syntax errors, wrong types) are dropped with a warning.

        Args:
            constraints: Candidate constraint strings.

        Returns:
            Subset that parses cleanly.
        """
        valid: List[str] = []
        trial = Z3SolverWrapper()
        for c in constraints:
            if trial.add_constraint(c):
                valid.append(c)
            else:
                logger.debug("Skipping unparseable constraint: %s", c)
        return valid

    def build_state_summary(self, puzzle_nl: str, constraints: List[str], unsat_core: List[str]) -> str:
        """Build a concise state summary for paradigm semantic matching.

        Args:
            puzzle_nl: Natural language description.
            constraints: Current constraint set.
            unsat_core: Current UNSAT core (empty if SAT).

        Returns:
            A short multi-line string suitable for LLM context injection.
        """
        core_part = (
            f"UNSAT Core:\n" + "\n".join(f"  {c}" for c in unsat_core)
            if unsat_core
            else "当前约束集合 SAT"
        )
        return (
            f"谜题: {puzzle_nl[:200]}...\n"
            f"约束数量: {len(constraints)}\n"
            f"{core_part}"
        )
