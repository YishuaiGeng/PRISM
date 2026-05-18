"""Constraint-satisfaction puzzle generator for offline trajectory collection.

Generates Zebra-style logic puzzles with controlled size and difficulty.
Difficulty is estimated using Z3's conflict count — a fully automatic metric
that does not require any LLM calls or manual labelling.

Typical usage::

    gen = PuzzleGenerator(seed=42)
    puzzles = gen.generate(n=200, n_entities=4, n_attrs=5, difficulty="medium")
"""

from __future__ import annotations

import itertools
import random
import uuid
from enum import Enum
from typing import Dict, List, Optional, Tuple

import z3

from prism.core.types import PuzzleInstance

_EASY_CONFLICT_MAX: int = 5
_HARD_CONFLICT_MIN: int = 15

_ENTITY_POOLS: Dict[str, List[str]] = {
    "nationality": ["Norwegian", "British", "Swedish", "Danish", "German", "French", "Spanish"],
    "color":       ["Red", "Blue", "Green", "White", "Yellow", "Orange", "Purple"],
    "pet":         ["Dog", "Cat", "Bird", "Fish", "Horse", "Rabbit", "Snake"],
    "drink":       ["Coffee", "Tea", "Milk", "Beer", "Water", "Juice", "Wine"],
    "hobby":       ["Painting", "Reading", "Gardening", "Cooking", "Sports", "Music", "Chess"],
    "job":         ["Doctor", "Engineer", "Teacher", "Lawyer", "Artist", "Chef", "Pilot"],
}

_ATTRIBUTE_KEYS = list(_ENTITY_POOLS.keys())


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class PuzzleGenerator:
    """Generates Zebra-style CSP puzzles for training trajectory collection.

    Args:
        seed: Base random seed.  Each ``generate()`` call increments a counter
            to produce reproducible but non-identical batches.
        max_attempts: How many times to retry if Z3 uniqueness check fails.
    """

    def __init__(self, seed: int = 42, max_attempts: int = 50) -> None:
        self._base_seed = seed
        self._counter = 0
        self._max_attempts = max_attempts

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        n: int,
        n_entities: int,
        n_attrs: int,
        difficulty: str = "medium",
    ) -> List[PuzzleInstance]:
        """Generate *n* puzzles of the requested size and difficulty.

        Args:
            n: Number of puzzles to generate.
            n_entities: Number of entities per attribute (e.g. houses).
            n_attrs: Number of attribute types (e.g. nationality, color, ...).
            difficulty: One of ``"easy"``, ``"medium"``, or ``"hard"``.

        Returns:
            List of :class:`~prism.core.types.PuzzleInstance` objects.
        """
        puzzles: List[PuzzleInstance] = []
        while len(puzzles) < n:
            self._counter += 1
            rng = random.Random(self._base_seed + self._counter)
            puzzle = self._try_generate(n_entities, n_attrs, difficulty, rng)
            if puzzle is not None:
                puzzles.append(puzzle)
        return puzzles

    # ------------------------------------------------------------------
    # Internal generation
    # ------------------------------------------------------------------

    def _try_generate(
        self,
        n_entities: int,
        n_attrs: int,
        difficulty: str,
        rng: random.Random,
    ) -> Optional[PuzzleInstance]:
        """Attempt to generate one valid puzzle; return None on failure."""
        attr_keys = rng.sample(_ATTRIBUTE_KEYS, min(n_attrs, len(_ATTRIBUTE_KEYS)))
        domains: Dict[str, List[str]] = {}
        solution: Dict[str, int] = {}
        positions = list(range(1, n_entities + 1))

        for key in attr_keys:
            pool = _ENTITY_POOLS[key]
            values = rng.sample(pool, n_entities)
            domains[key] = values
            perm = rng.sample(positions, len(positions))
            for val, pos in zip(values, perm):
                solution[f"{key}_{val}"] = pos

        clues = self._generate_clues(attr_keys, domains, solution, n_entities, rng)
        minimal_clues = self._minimize_clues(clues, solution, n_entities, rng)

        if not minimal_clues:
            return None

        conflicts = self._count_conflicts(minimal_clues, n_entities)
        actual_difficulty = self._classify_difficulty(conflicts)
        if not self._difficulty_matches(actual_difficulty, difficulty):
            return None

        nl_desc = self._to_natural_language(minimal_clues, attr_keys, domains, n_entities)
        solution_str = {k: str(v) for k, v in solution.items()}

        return PuzzleInstance(
            puzzle_id=str(uuid.uuid4()),
            nl_description=nl_desc,
            variables=list(solution.keys()),
            domains={k: v for k, v in domains.items()},
            constraints_nl=minimal_clues,
            solution=solution_str,
            size=f"{n_entities}x{n_attrs}",
            difficulty=actual_difficulty,
            domain="zebralogic",
            raw_data={"attr_keys": attr_keys, "conflict_count": conflicts},
        )

    def _generate_clues(
        self,
        attr_keys: List[str],
        domains: Dict[str, List[str]],
        solution: Dict[str, int],
        n: int,
        rng: random.Random,
    ) -> List[str]:
        """Generate a maximal set of clues that are all true for the solution."""
        clues: List[str] = []

        for key, values in domains.items():
            for val in values:
                pos = solution[f"{key}_{val}"]
                clues.append(f"The {val} {key} person lives in house {pos}.")

        for k1, k2 in itertools.combinations(attr_keys, 2):
            for v1 in domains[k1]:
                for v2 in domains[k2]:
                    if solution[f"{k1}_{v1}"] == solution[f"{k2}_{v2}"]:
                        clues.append(f"The person with {v1} also has {v2}.")

        for key, values in domains.items():
            for v1, v2 in itertools.combinations(values, 2):
                p1, p2 = solution[f"{key}_{v1}"], solution[f"{key}_{v2}"]
                diff = abs(p1 - p2)
                if diff == 1:
                    if p1 < p2:
                        clues.append(f"The {v1} {key} is immediately left of the {v2} {key}.")
                    else:
                        clues.append(f"The {v2} {key} is immediately left of the {v1} {key}.")
                elif p1 < p2:
                    clues.append(f"The {v1} {key} is to the left of the {v2} {key}.")

        rng.shuffle(clues)
        return clues

    def _minimize_clues(
        self,
        clues: List[str],
        solution: Dict[str, int],
        n: int,
        rng: random.Random,
    ) -> List[str]:
        """Greedily remove clues while the puzzle still has a unique solution."""
        minimal = list(clues)
        rng.shuffle(minimal)
        i = 0
        while i < len(minimal):
            candidate = minimal[:i] + minimal[i + 1:]
            if not self._has_unique_solution(candidate, solution, n):
                i += 1
            else:
                minimal = candidate
        if not self._has_unique_solution(minimal, solution, n):
            return []
        return minimal

    def _has_unique_solution(
        self,
        clues: List[str],
        solution: Dict[str, int],
        n: int,
    ) -> bool:
        """Return True if *clues* have exactly one solution (the given solution)."""
        solver = z3.Solver()
        vars_: Dict[str, z3.ArithRef] = {
            k: z3.Int(k) for k in solution
        }
        for v in vars_.values():
            solver.add(v >= 1, v <= n)

        for key_group in self._group_by_attr(list(vars_.keys())):
            solver.add(z3.Distinct(*[vars_[k] for k in key_group]))

        for clue in clues:
            exprs = self._clue_to_z3(clue, vars_, n)
            for expr in exprs:
                solver.add(expr)

        if solver.check() != z3.sat:
            return False

        solver2 = z3.Solver()
        for v in vars_.values():
            solver2.add(v >= 1, v <= n)
        for key_group in self._group_by_attr(list(vars_.keys())):
            solver2.add(z3.Distinct(*[vars_[k] for k in key_group]))
        for clue in clues:
            for expr in self._clue_to_z3(clue, vars_, n):
                solver2.add(expr)

        sol_constraints = z3.And([vars_[k] == v for k, v in solution.items()])
        solver2.add(z3.Not(sol_constraints))
        return solver2.check() == z3.unsat

    def _count_conflicts(self, clues: List[str], n: int) -> int:
        """Count Z3 solver conflicts (proxy for difficulty) for the given clue set."""
        solver = z3.Solver()
        solver.set("restart.max", 1000)
        vars_: Dict[str, z3.ArithRef] = {}

        for clue in clues:
            for word in clue.split():
                candidate = word.strip(".,!?")
                if "_" in candidate:
                    vars_[candidate] = z3.Int(candidate)

        for v in vars_.values():
            solver.add(v >= 1, v <= n)

        for clue in clues:
            for expr in self._clue_to_z3(clue, vars_, n):
                solver.add(expr)

        solver.check()
        stats = solver.statistics()
        for key, val in stats:
            if "conflicts" in key.lower():
                return int(val)
        return 0

    @staticmethod
    def _classify_difficulty(conflicts: int) -> str:
        if conflicts < _EASY_CONFLICT_MAX:
            return Difficulty.EASY
        if conflicts < _HARD_CONFLICT_MIN:
            return Difficulty.MEDIUM
        return Difficulty.HARD

    @staticmethod
    def _difficulty_matches(actual: str, requested: str) -> bool:
        if requested == "easy":
            return actual == Difficulty.EASY
        if requested == "hard":
            return actual == Difficulty.HARD
        return True

    @staticmethod
    def _group_by_attr(var_names: List[str]) -> List[List[str]]:
        """Group variable names by their attribute prefix (e.g. 'color_Red' → 'color')."""
        groups: Dict[str, List[str]] = {}
        for name in var_names:
            prefix = name.rsplit("_", 1)[0] if "_" in name else name
            groups.setdefault(prefix, []).append(name)
        return list(groups.values())

    @staticmethod
    def _clue_to_z3(
        clue: str,
        vars_: Dict[str, z3.ArithRef],
        n: int,
    ) -> List[z3.BoolRef]:
        """Best-effort parse of a generated clue into Z3 expressions.

        Returns an empty list for clues that can't be parsed (they are silently
        skipped by the solver; uniqueness checking handles correctness).
        """
        exprs: List[z3.BoolRef] = []
        c = clue.lower()

        def find_var(token: str) -> Optional[z3.ArithRef]:
            for k, v in vars_.items():
                if token in k.lower():
                    return v
            return None

        if "lives in house" in c:
            try:
                parts = clue.split()
                val_word = parts[1].lower()
                attr_word = parts[2].lower()
                pos = int(parts[-1].rstrip("."))
                key = f"{attr_word}_{val_word.capitalize()}"
                if key in vars_:
                    exprs.append(vars_[key] == pos)
            except (IndexError, ValueError):
                pass

        elif "immediately left of" in c:
            try:
                left_part, right_part = clue.split("immediately left of")
                l_words = left_part.split()
                r_words = right_part.split()
                l_val = l_words[1].lower().capitalize()
                l_attr = l_words[2].lower()
                r_val = r_words[1].lower().capitalize()
                r_attr = r_words[2].lower().rstrip(".")
                lv = vars_.get(f"{l_attr}_{l_val}")
                rv = vars_.get(f"{r_attr}_{r_val}")
                if lv is not None and rv is not None:
                    exprs.append(rv - lv == 1)
            except (IndexError, ValueError):
                pass

        elif "to the left of" in c:
            try:
                left_part, right_part = clue.split("to the left of")
                l_words = left_part.split()
                r_words = right_part.split()
                l_val = l_words[1].lower().capitalize()
                l_attr = l_words[2].lower()
                r_val = r_words[1].lower().capitalize()
                r_attr = r_words[2].lower().rstrip(".")
                lv = vars_.get(f"{l_attr}_{l_val}")
                rv = vars_.get(f"{r_attr}_{r_val}")
                if lv is not None and rv is not None:
                    exprs.append(lv < rv)
            except (IndexError, ValueError):
                pass

        elif "also has" in c:
            try:
                parts = clue.split()
                v1 = parts[2].lower().capitalize()
                v2 = parts[-1].rstrip(".").lower().capitalize()
                k1 = next((k for k in vars_ if k.endswith(f"_{v1}")), None)
                k2 = next((k for k in vars_ if k.endswith(f"_{v2}")), None)
                if k1 and k2:
                    exprs.append(vars_[k1] == vars_[k2])
            except (IndexError, StopIteration):
                pass

        return exprs

    @staticmethod
    def _to_natural_language(
        clues: List[str],
        attr_keys: List[str],
        domains: Dict[str, List[str]],
        n: int,
    ) -> str:
        """Format the clue list as a readable puzzle description string."""
        attrs_desc = ", ".join(attr_keys)
        intro = (
            f"There are {n} houses in a row numbered 1 to {n}. "
            f"Each house has exactly one: {attrs_desc}. "
            "All values within each category are distinct.\n\n"
            "Clues:\n"
        )
        clue_lines = "\n".join(f"{i+1}. {c}" for i, c in enumerate(clues))
        return intro + clue_lines
