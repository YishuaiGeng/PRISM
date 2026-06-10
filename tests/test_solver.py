"""Unit tests for Z3SolverWrapper.

Constraints use the Z3 Python-API string format (e.g. ``"Int('x') > 5"``)
because solver._parse() evaluates them against the z3 module namespace —
no ``z3.`` prefix is needed.
"""

from __future__ import annotations

import pytest

from prism.core.solver import SolverError, Z3SolverWrapper


# --------------------------------------------------------------------------- #
# SAT / UNSAT basics                                                            #
# --------------------------------------------------------------------------- #

class TestCheckResults:

    def test_sat_simple(self, solver: Z3SolverWrapper) -> None:
        """A consistent pair of bounds should yield SAT."""
        assert solver.add_constraint("Int('x') > 0")  is True
        assert solver.add_constraint("Int('x') < 10") is True
        assert solver.check() == "SAT"

    def test_unsat_two_conflicting_bounds(self, solver: Z3SolverWrapper) -> None:
        """x > 5 ∧ x < 3 has no integer solution → UNSAT."""
        solver.add_constraint("Int('x') > 5")
        solver.add_constraint("Int('x') < 3")
        assert solver.check() == "UNSAT"

    def test_empty_solver_is_sat(self, solver: Z3SolverWrapper) -> None:
        """An empty constraint set is trivially satisfiable."""
        assert solver.check() == "SAT"

    def test_add_constraint_rejects_invalid_syntax(
        self, solver: Z3SolverWrapper
    ) -> None:
        """add_constraint must return False for unparseable strings."""
        result = solver.add_constraint("this is not a z3 expression !!!")
        assert result is False
        # Solver should still be in a usable (SAT) state after rejection.
        assert solver.check() == "SAT"

    def test_add_constraint_rejects_non_boolean(
        self, solver: Z3SolverWrapper
    ) -> None:
        """Arithmetic expressions that are not Booleans must be rejected."""
        result = solver.add_constraint("Int('x') + 1")
        assert result is False


# --------------------------------------------------------------------------- #
# Unsat-core extraction                                                         #
# --------------------------------------------------------------------------- #

class TestUnsatCore:

    def test_unsat_core_contains_both_conflicting_constraints(
        self, solver: Z3SolverWrapper
    ) -> None:
        """get_unsat_core() must return both constraints forming the conflict."""
        c1 = "Int('x') > 5"
        c2 = "Int('x') < 3"
        solver.add_constraint(c1)
        solver.add_constraint(c2)
        assert solver.check() == "UNSAT"

        core = solver.get_unsat_core()

        assert isinstance(core, list)
        assert len(core) == 2
        assert c1 in core
        assert c2 in core

    def test_unsat_core_minimal_subset(self, solver: Z3SolverWrapper) -> None:
        """A redundant satisfiable constraint must NOT appear in the unsat core."""
        solver.add_constraint("Int('x') > 5")   # part of conflict
        solver.add_constraint("Int('x') < 3")   # part of conflict
        solver.add_constraint("Int('y') > 0")   # independent — satisfiable alone

        assert solver.check() == "UNSAT"
        core = solver.get_unsat_core()

        # y > 0 is irrelevant to the conflict and must not appear in the core.
        assert "Int('y') > 0" not in core

    def test_get_unsat_core_raises_when_sat(self, solver: Z3SolverWrapper) -> None:
        """get_unsat_core() must raise SolverError when the formula is SAT."""
        solver.add_constraint("Int('x') > 0")
        assert solver.check() == "SAT"
        with pytest.raises(SolverError):
            solver.get_unsat_core()


# --------------------------------------------------------------------------- #
# Model extraction                                                              #
# --------------------------------------------------------------------------- #

class TestGetModel:

    def test_get_model_returns_assignment(self, solver: Z3SolverWrapper) -> None:
        """get_model() must return a non-empty dict when the formula is SAT."""
        solver.add_constraint("Int('x') > 0")
        solver.add_constraint("Int('x') < 10")
        assert solver.check() == "SAT"

        model = solver.get_model()

        assert isinstance(model, dict)
        assert len(model) >= 1
        # Values are strings (the Z3 model expression, converted via str())
        for k, v in model.items():
            assert isinstance(k, str)
            assert isinstance(v, str)

    def test_get_model_omits_internal_tracking_variables(self, solver: Z3SolverWrapper) -> None:
        solver.add_constraint("Int('x') == 1")
        assert solver.check() == "SAT"

        model = solver.get_model()

        assert model == {"x": "1"}
        assert all(not key.startswith("_prism_track_") for key in model)

    def test_get_model_raises_when_unsat(self, solver: Z3SolverWrapper) -> None:
        """get_model() must raise SolverError when the formula is UNSAT."""
        solver.add_constraint("Int('x') > 5")
        solver.add_constraint("Int('x') < 3")
        assert solver.check() == "UNSAT"
        with pytest.raises(SolverError):
            solver.get_model()


# --------------------------------------------------------------------------- #
# Reset                                                                         #
# --------------------------------------------------------------------------- #

class TestReset:

    def test_reset_clears_constraints(self, solver: Z3SolverWrapper) -> None:
        """After reset() the solver must return to SAT with no constraints."""
        solver.add_constraint("Int('x') > 5")
        solver.add_constraint("Int('x') < 3")
        assert solver.check() == "UNSAT"

        solver.reset()

        assert solver.check() == "SAT"
        assert solver._constraint_strs == []
        assert solver._track_to_str == {}


# --------------------------------------------------------------------------- #
# Clone independence                                                            #
# --------------------------------------------------------------------------- #

class TestCloneIndependence:

    def test_clone_independence(self, solver: Z3SolverWrapper) -> None:
        """Modifying the original after cloning must not affect the clone."""
        solver.add_constraint("Int('x') > 0")
        clone = solver.clone()

        # Poison the original with a conflicting constraint.
        solver.add_constraint("Int('x') < 0")

        assert solver.check() == "UNSAT", "Original must be UNSAT after adding conflict"
        assert clone.check()  == "SAT",   "Clone must remain SAT"

    def test_clone_inherits_existing_constraints(
        self, solver: Z3SolverWrapper
    ) -> None:
        """Clone must have the same constraints as the original at clone time."""
        solver.add_constraint("Int('x') > 0")
        solver.add_constraint("Int('x') < 10")
        clone = solver.clone()

        # Both should be SAT with the inherited constraints.
        assert clone.check() == "SAT"

        # Clone should reproduce the same model range.
        model = clone.get_model()
        assert "x" in model

    def test_clone_does_not_share_tracking_state(
        self, solver: Z3SolverWrapper
    ) -> None:
        """Track counter in clone must advance independently of the original."""
        solver.add_constraint("Int('x') > 0")
        clone = solver.clone()

        original_counter_before = solver._track_counter
        clone.add_constraint("Int('y') > 0")

        # Adding to the clone must not increment the original's counter.
        assert solver._track_counter == original_counter_before
