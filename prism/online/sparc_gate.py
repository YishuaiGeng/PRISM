"""SPARC π-gate (SBW work) — extracted from GuidedSolver as a mixin.

Implements the "Satisfiable but Wrong" solver-decidable selective-abstention
gate. NOT part of PRISM's paradigm-library / repair-memory path; mixed into
GuidedSolver only because it reuses the same Z3/LLM plumbing. Activated when
GuidedSolver is built with sparc=True. See scripts/sparc/* and docs/sparc/.

The methods reach shared GuidedSolver facilities via ``self`` (_safe_model,
_rebuild_solver, _apply_repair, _llm, _translator) and the SPARC config
attributes set in GuidedSolver.__init__ (_sparc_max_completions,
_sparc_blind_completion, _sparc_repair_budget, _sparc_no_invariant,
_sparc_va_mode).
"""
from __future__ import annotations

from typing import List, Optional

from prism.core.model_validation import normalise_schema_key, visible_schema_keys
from prism.core.solver import Z3SolverWrapper
from prism.core.types import PuzzleInstance


class SparcGateMixin:
    def _sparc_gate(
        self,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
        steps: List[dict],
    ) -> tuple[str, Z3SolverWrapper]:
        """Accept a SAT model only if the solution space matches the prior.

        Unique-solution prior: assert the negation of the found model and
        re-solve. A second model means the formalization is under-constrained;
        budget-limited diff-guided completion then adds missing constraints
        (each accepted completion provably excludes at least one current
        model, so the solution space shrinks monotonically). If a completion
        re-exposes a latent conflict (UNSAT), a small invariant-constrained
        repair budget applies. Returns ``("pass"|"abstain", solver)``.
        """
        current = list(solver.get_constraints())
        completions = 0
        answer_keys = self._answer_key_whitelist(puzzle)
        while True:
            model = self._safe_model(solver)
            projected, va_mode = self._answer_projection_vars(model, answer_keys)
            blocking = self._blocking_clause(model, answer_keys)
            if blocking is None:
                steps.append({
                    "iteration": len(steps),
                    "action": "pi_gate",
                    "gate": "skipped_no_model",
                    "z3_result": "SAT",
                    "va_mode": va_mode,
                    "blocked_vars": len(projected),
                })
                return "pass", solver
            probe = self._rebuild_solver(current)
            probe.add_constraint(blocking)
            probe_verdict = probe.check()
            if probe_verdict == "UNSAT":
                steps.append({
                    "iteration": len(steps),
                    "action": "pi_gate",
                    "gate": "unique",
                    "z3_result": "SAT",
                    "va_mode": va_mode,
                    "blocked_vars": len(projected),
                })
                return "pass", solver
            if probe_verdict == "UNKNOWN":
                steps.append({
                    "iteration": len(steps),
                    "action": "pi_gate",
                    "gate": "unknown_timeout",
                    "z3_result": "SAT",
                    "va_mode": va_mode,
                    "blocked_vars": len(projected),
                })
                return "pass", solver

            second = self._safe_model(probe)
            steps.append({
                "iteration": len(steps),
                "action": "pi_gate",
                "gate": "non_unique",
                "z3_result": "SAT",
                "va_mode": va_mode,
                "blocked_vars": len(projected),
            })
            if completions >= self._sparc_max_completions:
                return "abstain", solver
            completions += 1
            new_constraint = self._diff_completion(
                puzzle, current, model, second, steps, answer_keys
            )
            if not new_constraint:
                return "abstain", solver

            current.append(new_constraint)
            solver = self._rebuild_solver(current)
            result = solver.check()
            steps.append({
                "iteration": len(steps),
                "action": "diff_completion",
                "z3_result": result,
                "new_constraint": new_constraint,
            })
            if result == "UNSAT":
                # Visibility restored: the completion exposed a latent
                # mistranslation that weakening had hidden.
                solver, current, repaired = self._sparc_conflict_repair(
                    current, new_constraint, steps
                )
                if not repaired:
                    return "abstain", solver
            elif result == "UNKNOWN":
                return "abstain", solver
            # Loop back to the uniqueness probe with the enlarged set.

    def _diff_completion(
        self,
        puzzle: PuzzleInstance,
        current: List[str],
        model_a: Optional[dict],
        model_b: Optional[dict],
        steps: List[dict],
        answer_keys: frozenset = frozenset(),
    ) -> Optional[str]:
        """Ask the LLM for a missing constraint that separates two models.

        The candidate is accepted only if it mechanically discriminates the
        two models (progress guarantee) — a candidate satisfied by both is
        rejected and retried once.
        """
        model_a, model_b = model_a or {}, model_b or {}
        diff_vars = sorted(
            v for v in set(model_a) | set(model_b)
            if not str(v).startswith("_prism_track_")
            and model_a.get(v) != model_b.get(v)
        )
        if answer_keys:
            # Keep the diff summary on the same answer projection the gate
            # blocked on; auxiliary-only diffs fall back to the full diff.
            projected_diff = [
                v for v in diff_vars if normalise_schema_key(str(v)) in answer_keys
            ]
            if projected_diff:
                diff_vars = projected_diff
        if not diff_vars:
            return None
        if self._sparc_blind_completion:
            # Ablation: the LLM learns only that the formalization is
            # under-constrained — no diff attribution, no progress check.
            diff_summary = (
                "(no model diff available; the current constraints admit "
                "multiple solutions — add one missing constraint)"
            )
        else:
            diff_summary = "\n".join(
                f"- {v}: candidate A = {model_a.get(v)}, candidate B = {model_b.get(v)}"
                for v in diff_vars[:12]
            )
        for _ in range(2):
            response = self._llm.complete_constraint(
                puzzle.nl_description, current, diff_summary
            )
            candidate = self._translator.parse_repair_response(response)
            if not candidate:
                continue
            if not self._sparc_blind_completion and not self._discriminates(
                candidate, model_a, model_b
            ):
                steps.append({
                    "iteration": len(steps),
                    "action": "diff_completion_rejected",
                    "candidate": candidate,
                    "reason": "does_not_discriminate",
                })
                continue
            return candidate
        return None

    def _sparc_conflict_repair(
        self,
        current: List[str],
        protected: str,
        steps: List[dict],
    ) -> tuple[Z3SolverWrapper, List[str], bool]:
        """Core-guided repair after a completion exposed a conflict.

        Visibility invariant: the freshly added completion constraint is
        protected from being chosen as the repair target (deleting the
        evidence would re-hide the error), and repairs replace rather than
        remove constraints.
        """
        solver = self._rebuild_solver(current)
        result = solver.check()
        for _ in range(self._sparc_repair_budget):
            if result != "UNSAT":
                break
            core = solver.get_unsat_core()
            if self._sparc_no_invariant:
                # Ablation: no evidence protection, no no-weakening hint —
                # the repair may target (and effectively erase) the very
                # constraint that exposed the conflict.
                repair_targets = core
                history_summary = (
                    "The constraint set is unsatisfiable. Modify or relax "
                    "constraints so that it becomes satisfiable."
                )
            else:
                repair_targets = [c for c in core if c != protected] or core
                history_summary = (
                    "A newly recovered constraint exposed a conflict with an "
                    "earlier translation. Fix the mistranslated constraint; "
                    "do not delete or weaken constraints."
                )
            repair_response = self._llm.repair(
                constraints=current,
                unsat_core=repair_targets,
                history_summary=history_summary,
            )
            repair_str = self._translator.parse_repair_response(repair_response)
            if not repair_str:
                break
            old_constraint, new_constraint = self._apply_repair(
                current, repair_targets, repair_str
            )
            solver = self._rebuild_solver(current)
            result = solver.check()
            steps.append({
                "iteration": len(steps),
                "action": "sparc_conflict_repair",
                "z3_result": result,
                "old_constraint": old_constraint,
                "new_constraint": new_constraint,
            })
        return solver, current, result == "SAT"

    def _discriminates(
        self,
        constraint: str,
        model_a: dict,
        model_b: dict,
    ) -> bool:
        """Progress check: *constraint* must exclude at least one model."""
        holds_a = self._holds_under(constraint, model_a)
        holds_b = self._holds_under(constraint, model_b)
        if holds_a is None or holds_b is None:
            return False
        return not (holds_a and holds_b)

    @staticmethod
    def _holds_under(constraint: str, model: dict) -> Optional[bool]:
        probe = Z3SolverWrapper()
        for var, val in (model or {}).items():
            if str(var).startswith("_prism_track_"):
                continue
            if not str(val).lstrip("-").isdigit():
                continue
            if not probe.add_constraint(f"Int('{var}') == {val}"):
                return None
        if not probe.add_constraint(constraint):
            return None
        verdict = probe.check()
        if verdict == "UNKNOWN":
            return None
        return verdict == "SAT"

    def _answer_key_whitelist(self, puzzle: PuzzleInstance) -> frozenset:
        """Normalised answer-variable keys derived from visible puzzle inputs.

        Empty when ``sparc_va_mode`` is not "whitelist" or no keys can be
        derived; the probe then uses the legacy all-integer approximation.
        Never reads ``puzzle.solution``.
        """
        if (self._sparc_va_mode or "").strip().lower() != "whitelist":
            return frozenset()
        try:
            keys = visible_schema_keys(puzzle)
        except Exception:  # noqa: BLE001
            return frozenset()
        return frozenset(
            normalise_schema_key(key) for key in keys if normalise_schema_key(key)
        )

    @staticmethod
    def _answer_projection_vars(
        model: Optional[dict],
        answer_keys: frozenset = frozenset(),
    ) -> tuple[List[tuple[str, str]], str]:
        """Select the (var, value) pairs treated as the answer projection V_A.

        With a non-empty whitelist that matches at least one model variable,
        the projection is restricted to matching variables ("whitelist");
        otherwise it falls back to every non-tracked integer variable
        ("all_int"), preserving the legacy gate behaviour when schema
        extraction finds nothing usable.
        """
        int_pairs = [
            (str(var), str(val))
            for var, val in (model or {}).items()
            if not str(var).startswith("_prism_track_")
            and str(val).lstrip("-").isdigit()
        ]
        if answer_keys:
            matched = [
                (var, val)
                for var, val in int_pairs
                if normalise_schema_key(var) in answer_keys
            ]
            if matched:
                return matched, "whitelist"
        return int_pairs, "all_int"

    @staticmethod
    def _blocking_clause(
        model: Optional[dict],
        answer_keys: frozenset = frozenset(),
    ) -> Optional[str]:
        pairs, _ = SparcGateMixin._answer_projection_vars(model, answer_keys)
        equalities = [f"Int('{var}') == {val}" for var, val in pairs]
        if not equalities:
            return None
        return f"Not(And({', '.join(equalities)}))"
