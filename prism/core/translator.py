"""Natural-language to Z3 constraint translator.

Wraps LLMClient.translate / retranslate and handles the parsing, basic
validation, and retry logic so that callers (GuidedSolver, TrajectoryCollector)
receive a clean list of Z3 expression strings.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.model_validation import (
    expected_solution_key_hint,
    validate_model,
    puzzle_schema_key_hint,
    visible_schema_keys,
)
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

    def __init__(
        self,
        llm_client: LLMClient,
        schema_hint_mode: str = "puzzle",
        normalize_mode: str = "none",
    ) -> None:
        self._llm = llm_client
        self._schema_hint_mode = schema_hint_mode
        self._normalize_mode = normalize_mode
        self.last_diagnostics: dict = {}
        self._last_normalization_diagnostics: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(
        self,
        puzzle: PuzzleInstance,
        paradigm_hint: str = "",
    ) -> List[str]:
        """Translate puzzle NL description to a list of Z3 constraint strings.

        Retries up to ``_MAX_PARSE_RETRIES`` times if the parsed constraint
        list is empty (the LLM produced no parseable code).

        Args:
            puzzle: The puzzle instance whose ``nl_description`` is translated.
            paradigm_hint: Optional initial positive guidance templates.

        Returns:
            List of Z3 Python expression strings (may be empty on persistent failure).
        """
        schema_hint = self._schema_hint(puzzle)
        for attempt in range(1 + _MAX_PARSE_RETRIES):
            self._last_normalization_diagnostics = {}
            response = self._translate_with_optional_schema_hint(
                puzzle.nl_description,
                schema_hint,
                paradigm_hint,
            )
            constraints = LLMClient.parse_constraints(response)
            if self._should_normalize_initial():
                constraints = self._normalize_constraints(
                    puzzle,
                    constraints,
                    schema_hint,
                    error_ctx="Clean up the initial translation before solving.",
                )
            validated = self._validate_constraints_for_puzzle(puzzle, constraints)
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
        self._last_normalization_diagnostics = {}
        response = self._retranslate_with_optional_schema_hint(
            puzzle.nl_description,
            failed_constraints,
            error_ctx,
            self._schema_hint(puzzle),
        )
        constraints = LLMClient.parse_constraints(response)
        if self._should_normalize_retranslation():
            constraints = self._normalize_constraints(
                puzzle,
                constraints,
                self._schema_hint(puzzle),
                error_ctx=error_ctx,
            )
        return self._validate_constraints_for_puzzle(puzzle, constraints)

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

    def _validate_constraints_for_puzzle(
        self,
        puzzle: PuzzleInstance,
        constraints: List[str],
    ) -> List[str]:
        valid = self._validate(constraints)
        if self._uses_oracle_schema_hint():
            self.last_diagnostics = self._with_normalization_diagnostics(
                self._constraint_diagnostics(puzzle, valid)
            )
            return valid

        visible = visible_schema_keys(puzzle)
        if not visible:
            self.last_diagnostics = self._with_normalization_diagnostics(
                self._constraint_diagnostics(puzzle, valid)
            )
            return valid

        filtered: List[str] = []
        dropped: List[str] = []
        for constraint in valid:
            semantic_vars = self._semantic_vars(constraint)
            if semantic_vars and not semantic_vars <= visible:
                dropped.append(constraint)
            else:
                filtered.append(constraint)
        self.last_diagnostics = self._with_normalization_diagnostics(
            self._constraint_diagnostics(
                puzzle,
                filtered,
                dropped,
            )
        )
        return filtered

    def _translate_with_optional_schema_hint(
        self,
        puzzle_nl: str,
        schema_hint: str,
        paradigm_hint: str = "",
    ) -> str:
        try:
            return self._llm.translate(
                puzzle_nl,
                schema_hint=schema_hint,
                paradigm_hint=paradigm_hint,
            )
        except TypeError:
            try:
                return self._llm.translate(puzzle_nl, schema_hint=schema_hint)
            except TypeError:
                return self._llm.translate(puzzle_nl)

    def _normalize_constraints(
        self,
        puzzle: PuzzleInstance,
        constraints: List[str],
        schema_hint: str,
        error_ctx: str = "",
    ) -> List[str]:
        if not constraints:
            return constraints
        try:
            response = self._llm.normalize_translation(
                puzzle.nl_description,
                constraints,
                schema_hint=schema_hint,
                error_ctx=error_ctx,
            )
        except TypeError:
            try:
                response = self._llm.normalize_translation(
                    puzzle.nl_description,
                    constraints,
                    schema_hint,
                    error_ctx,
                )
            except AttributeError:
                return constraints
        except AttributeError:
            return constraints
        normalized = LLMClient.parse_constraints(response)
        normalized = normalized or constraints
        return self._choose_better_constraints(puzzle, constraints, normalized)

    def _choose_better_constraints(
        self,
        puzzle: PuzzleInstance,
        original: List[str],
        normalized: List[str],
    ) -> List[str]:
        original_score = self._constraint_set_score(puzzle, original)
        normalized_score = self._constraint_set_score(puzzle, normalized)
        preserves_semantics, missing_semantics = self._preserves_original_semantics(
            puzzle,
            original,
            normalized,
        )
        selected = normalized_score > original_score and preserves_semantics
        reject_reason = ""
        if normalized_score <= original_score:
            reject_reason = "score_not_improved"
        elif not preserves_semantics:
            reject_reason = "changed_original_semantic_constraints"
        self._last_normalization_diagnostics = {
            "translation_normalization_attempted": True,
            "translation_normalization_selected": selected,
            "translation_normalization_original_score": list(original_score),
            "translation_normalization_normalized_score": list(normalized_score),
            "translation_normalization_reject_reason": reject_reason,
            "translation_normalization_missing_semantics": missing_semantics[:5],
        }
        if selected:
            return normalized
        return original

    def _with_normalization_diagnostics(self, diagnostics: dict) -> dict:
        if not self._last_normalization_diagnostics:
            return diagnostics
        return {**diagnostics, **self._last_normalization_diagnostics}

    def _constraint_set_score(
        self,
        puzzle: PuzzleInstance,
        constraints: List[str],
    ) -> tuple[int, int, int, int]:
        valid = self._validate(constraints)
        if not valid:
            return (0, 0, 0, 0)
        solver = Z3SolverWrapper()
        for constraint in valid:
            solver.add_constraint(constraint)
        result = solver.check()
        semantic_vars = {
            var
            for constraint in valid
            for var in self._semantic_vars(constraint)
        }
        visible = visible_schema_keys(puzzle)
        schema_overlap = len(semantic_vars & visible) if visible else len(semantic_vars)
        if result == "SAT":
            validation = validate_model(puzzle, solver.get_model())
            if validation.ok:
                return (5, schema_overlap, len(valid), len(semantic_vars))
            if validation.domain_valid and validation.schema_aligned:
                return (4, schema_overlap, len(valid), len(semantic_vars))
            if validation.domain_valid:
                return (3, schema_overlap, len(valid), len(semantic_vars))
            return (2, schema_overlap, len(valid), len(semantic_vars))
        if result == "UNSAT":
            return (1, schema_overlap, len(valid), len(semantic_vars))
        return (0, schema_overlap, len(valid), len(semantic_vars))

    def _retranslate_with_optional_schema_hint(
        self,
        puzzle_nl: str,
        failed_constraints: List[str],
        error_ctx: str,
        schema_hint: str,
    ) -> str:
        try:
            return self._llm.retranslate(
                puzzle_nl,
                failed_constraints,
                error_ctx,
                schema_hint=schema_hint,
            )
        except TypeError:
            return self._llm.retranslate(puzzle_nl, failed_constraints, error_ctx)

    def _schema_hint(self, puzzle: PuzzleInstance) -> str:
        mode = (self._schema_hint_mode or "puzzle").strip().lower()
        if mode in {"", "none", "off", "disabled"}:
            return ""
        if mode in {"solution", "solution_keys", "oracle", "oracle_solution_keys"}:
            return expected_solution_key_hint(puzzle)
        return puzzle_schema_key_hint(puzzle)

    def _uses_oracle_schema_hint(self) -> bool:
        mode = (self._schema_hint_mode or "puzzle").strip().lower()
        return mode in {"solution", "solution_keys", "oracle", "oracle_solution_keys"}

    def _should_normalize_initial(self) -> bool:
        mode = (self._normalize_mode or "none").strip().lower()
        return mode in {"initial", "always", "on", "true", "yes"}

    def _should_normalize_retranslation(self) -> bool:
        mode = (self._normalize_mode or "none").strip().lower()
        return mode in {"always", "retranslate", "retranslation"}

    @classmethod
    def _preserves_original_semantics(
        cls,
        puzzle: PuzzleInstance,
        original: List[str],
        normalized: List[str],
    ) -> tuple[bool, list[str]]:
        visible = visible_schema_keys(puzzle)
        original_semantics = cls._semantic_relation_signatures(original, visible)
        if not original_semantics:
            return True, []
        normalized_semantics = cls._semantic_relation_signatures(normalized, visible)
        missing = sorted(original_semantics - normalized_semantics)
        return not missing, missing

    @classmethod
    def _semantic_relation_signatures(
        cls,
        constraints: List[str],
        visible: set[str],
    ) -> set[str]:
        signatures: set[str] = set()
        for constraint in constraints:
            if cls._is_schema_constraint(constraint):
                continue
            signature = cls._semantic_relation_signature(constraint, visible)
            if signature:
                signatures.add(signature)
        return signatures

    @classmethod
    def _semantic_relation_signature(cls, constraint: str, visible: set[str]) -> str:
        text = cls._compact_constraint(constraint)
        text = cls._strip_single_arg_and(text)
        var = r"Int\('([^']+)'\)"
        number = r"(-?\d+)"

        match = re.fullmatch(fr"{var}=={number}", text)
        if match:
            return cls._position_signature(match.group(1), match.group(2), visible)
        match = re.fullmatch(fr"{number}=={var}", text)
        if match:
            return cls._position_signature(match.group(2), match.group(1), visible)

        match = re.fullmatch(fr"{var}=={var}", text)
        if match:
            left = cls._canonical_semantic_var(match.group(1), visible)
            right = cls._canonical_semantic_var(match.group(2), visible)
            if left and right:
                return "same:" + "|".join(sorted([left, right]))

        match = re.fullmatch(fr"{var}!={var}", text)
        if match:
            left = cls._canonical_semantic_var(match.group(1), visible)
            right = cls._canonical_semantic_var(match.group(2), visible)
            if left and right:
                return "neq:" + "|".join(sorted([left, right]))

        match = re.fullmatch(fr"{var}=={var}-1", text)
        if match:
            return cls._ordered_relation_signature("directly_left", match.group(1), match.group(2), visible)
        match = re.fullmatch(fr"{var}\+1=={var}", text)
        if match:
            return cls._ordered_relation_signature("directly_left", match.group(1), match.group(2), visible)
        match = re.fullmatch(fr"{var}=={var}\+1", text)
        if match:
            return cls._ordered_relation_signature("directly_left", match.group(2), match.group(1), visible)
        match = re.fullmatch(fr"{var}-1=={var}", text)
        if match:
            return cls._ordered_relation_signature("directly_left", match.group(2), match.group(1), visible)

        match = re.fullmatch(fr"{var}<{var}", text)
        if match:
            return cls._ordered_relation_signature("somewhere_left", match.group(1), match.group(2), visible)
        match = re.fullmatch(fr"{var}>{var}", text)
        if match:
            return cls._ordered_relation_signature("somewhere_left", match.group(2), match.group(1), visible)

        match = re.fullmatch(fr"Abs\({var}-{var}\)==1", text)
        if match:
            left = cls._canonical_semantic_var(match.group(1), visible)
            right = cls._canonical_semantic_var(match.group(2), visible)
            if left and right:
                return "adjacent:" + "|".join(sorted([left, right]))

        vars_in_constraint = cls._semantic_vars(constraint)
        if vars_in_constraint:
            return f"expr:{text}"
        return ""

    @classmethod
    def _position_signature(cls, var: str, value: str, visible: set[str]) -> str:
        canonical = cls._canonical_semantic_var(var, visible)
        return f"position:{canonical}:{value}" if canonical else ""

    @classmethod
    def _ordered_relation_signature(
        cls,
        relation: str,
        left: str,
        right: str,
        visible: set[str],
    ) -> str:
        left_key = cls._canonical_semantic_var(left, visible)
        right_key = cls._canonical_semantic_var(right, visible)
        if not left_key or not right_key:
            return ""
        return f"{relation}:{left_key}:{right_key}"

    @classmethod
    def _canonical_semantic_var(cls, var: str, visible: set[str]) -> str:
        if var.lower().startswith("house"):
            return ""
        for key in visible:
            if key.lower() == var.lower():
                return key
        return var

    @staticmethod
    def _compact_constraint(constraint: str) -> str:
        return re.sub(r"\s+", "", (constraint or "").strip())

    @classmethod
    def _strip_single_arg_and(cls, text: str) -> str:
        if not text.startswith("And(") or not text.endswith(")"):
            return text
        inner = text[4:-1]
        if cls._has_top_level_comma(inner):
            return text
        return inner

    @staticmethod
    def _has_top_level_comma(text: str) -> bool:
        depth = 0
        for char in text:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif char == "," and depth == 0:
                return True
        return False

    @classmethod
    def _is_schema_constraint(cls, constraint: str) -> bool:
        text = cls._compact_constraint(constraint)
        if text.startswith("Distinct("):
            return True
        var = r"Int\('([^']+)'\)"
        number = r"-?\d+"
        domain_patterns = [
            fr"And\({var}>={number},{var}<={number}\)",
            fr"And\({var}<={number},{var}>={number}\)",
        ]
        for pattern in domain_patterns:
            match = re.fullmatch(pattern, text)
            if match and match.group(1) == match.group(2):
                return True
        return False

    @classmethod
    def _constraint_diagnostics(
        cls,
        puzzle: PuzzleInstance,
        constraints: List[str],
        dropped: List[str] | None = None,
    ) -> dict:
        visible = visible_schema_keys(puzzle)
        generated = {
            var
            for constraint in constraints
            for var in cls._semantic_vars(constraint)
        }
        expected = {
            str(key)
            for key in (puzzle.solution or {})
            if not str(key).startswith("_prism_track_")
        }
        return {
            "visible_schema_key_count": len(visible),
            "expected_schema_key_count": len(expected),
            "generated_schema_key_count": len(generated),
            "missing_visible_schema_keys": sorted(expected - visible),
            "generated_extra_schema_keys": sorted(generated - visible) if visible else [],
            "dropped_invisible_schema_constraints": list(dropped or []),
        }

    @staticmethod
    def _semantic_vars(constraint: str) -> set[str]:
        return {
            var
            for var in re.findall(r"Int\('([^']+)'\)", constraint or "")
            if not var.lower().startswith("house")
        }

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
