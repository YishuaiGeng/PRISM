"""Deterministic oracle for ZebraLogic grid-mode puzzles.

This parser targets the templated clue language used by ZebraLogicBench. It is
conservative: unsupported or non-unique puzzles return ``None`` instead of
producing a questionable ground truth.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import Any

Assignment = dict[str, int]

_ORDINALS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "1st": 1,
    "2nd": 2,
    "3rd": 3,
    "4th": 4,
    "5th": 5,
    "6th": 6,
}

_MONTH_ALIASES = {
    "january": "jan",
    "february": "feb",
    "march": "mar",
    "april": "april",
    "may": "may",
    "june": "jun",
    "july": "jul",
    "august": "aug",
    "september": "sept",
    "october": "oct",
    "november": "nov",
    "december": "dec",
}


@dataclass(frozen=True)
class ZebraParse:
    n_houses: int
    categories: dict[str, list[str]]
    alias_to_key: dict[str, str]
    clues: list[str]


@dataclass(frozen=True)
class Constraint:
    op: str
    left: str
    right: str | None = None
    position: int | None = None
    distance: int | None = None

    def __call__(self, assignment: Assignment) -> bool:
        left = assignment[self.left]
        if self.op == "eq_pos":
            return left == self.position
        if self.op == "ne_pos":
            return left != self.position
        if self.right is None:
            raise ValueError(f"Constraint {self.op} requires a right operand.")
        right = assignment[self.right]
        if self.op == "eq":
            return left == right
        if self.op == "direct_left":
            return left + 1 == right
        if self.op == "left_of":
            return left < right
        if self.op == "right_of":
            return left > right
        if self.op == "adjacent":
            return abs(left - right) == 1
        if self.op == "distance":
            return abs(left - right) == self.distance
        raise ValueError(f"Unsupported constraint op: {self.op}")

    def to_z3(self, variables: dict[str, Any]) -> Any:
        import z3  # noqa: PLC0415

        left = variables[self.left]
        if self.op == "eq_pos":
            return left == self.position
        if self.op == "ne_pos":
            return left != self.position
        if self.right is None:
            raise ValueError(f"Constraint {self.op} requires a right operand.")
        right = variables[self.right]
        if self.op == "eq":
            return left == right
        if self.op == "direct_left":
            return left + 1 == right
        if self.op == "left_of":
            return left < right
        if self.op == "right_of":
            return left > right
        if self.op == "adjacent":
            return z3.Abs(left - right) == 1
        if self.op == "distance":
            return z3.Abs(left - right) == self.distance
        raise ValueError(f"Unsupported constraint op: {self.op}")


def solve_zebra_puzzle(puzzle_text: str) -> dict[str, str] | None:
    parsed = parse_zebra_puzzle(puzzle_text)
    if parsed is None:
        return None
    constraints = []
    for clue in parsed.clues:
        constraint = parse_clue(clue, parsed.alias_to_key)
        if constraint is None:
            return None
        constraints.append(constraint)
    if not _constraints_reference_known_keys(parsed, constraints):
        return None
    return _solve(parsed, constraints)


def parse_zebra_puzzle(puzzle_text: str) -> ZebraParse | None:
    house_match = re.search(r"There are (\d+) houses", puzzle_text)
    if not house_match:
        return None
    n_houses = int(house_match.group(1))
    categories: dict[str, list[str]] = {}
    alias_to_key: dict[str, str] = {}
    clues: list[str] = []
    in_clues = False

    for raw_line in puzzle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "## Clues:":
            in_clues = True
            continue
        if in_clues:
            match = re.match(r"\d+\.\s+(.*)", line)
            if match:
                clues.append(match.group(1).strip())
            continue
        if line.startswith("- "):
            values = re.findall(r"`([^`]+)`", line)
            if not values:
                continue
            category = _infer_category(line)
            categories[category] = values
            for value in values:
                key = _key(category, value)
                for alias in _aliases(value, category):
                    alias_to_key[alias] = _preferred_alias_target(alias, key, alias_to_key)

    if not categories or not clues:
        return None
    return ZebraParse(n_houses, categories, alias_to_key, clues)


def parse_clue(clue: str, alias_to_key: dict[str, str]) -> Constraint | None:
    clue = clue.strip().rstrip(".")

    ordinal_match = re.match(r"(.+?) is (not )?in the (\w+) house$", clue, re.I)
    if ordinal_match:
        left = _resolve_entity(ordinal_match.group(1), alias_to_key)
        ordinal = _ORDINALS.get(ordinal_match.group(3).lower())
        if left is None or ordinal is None:
            return None
        if ordinal_match.group(2):
            return Constraint("ne_pos", left, position=ordinal)
        return Constraint("eq_pos", left, position=ordinal)

    direct_left = re.match(r"(.+?) is directly left of (.+)$", clue, re.I)
    if direct_left:
        left = _resolve_entity(direct_left.group(1), alias_to_key)
        right = _resolve_entity(direct_left.group(2), alias_to_key)
        if left is None or right is None:
            return None
        return Constraint("direct_left", left, right)

    somewhere_left = re.match(r"(.+?) is somewhere to the left of (.+)$", clue, re.I)
    if somewhere_left:
        left = _resolve_entity(somewhere_left.group(1), alias_to_key)
        right = _resolve_entity(somewhere_left.group(2), alias_to_key)
        if left is None or right is None:
            return None
        return Constraint("left_of", left, right)

    somewhere_right = re.match(r"(.+?) is somewhere to the right of (.+)$", clue, re.I)
    if somewhere_right:
        left = _resolve_entity(somewhere_right.group(1), alias_to_key)
        right = _resolve_entity(somewhere_right.group(2), alias_to_key)
        if left is None or right is None:
            return None
        return Constraint("right_of", left, right)

    next_to = re.match(r"(.+?) and (.+?) are next to each other$", clue, re.I)
    if next_to:
        left = _resolve_entity(next_to.group(1), alias_to_key)
        right = _resolve_entity(next_to.group(2), alias_to_key)
        if left is None or right is None:
            return None
        return Constraint("adjacent", left, right)

    one_between = re.match(r"There is one house between (.+?) and (.+)$", clue, re.I)
    if one_between:
        left = _resolve_entity(one_between.group(1), alias_to_key)
        right = _resolve_entity(one_between.group(2), alias_to_key)
        if left is None or right is None:
            return None
        return Constraint("distance", left, right, distance=2)

    two_between = re.match(r"There are two houses between (.+?) and (.+)$", clue, re.I)
    if two_between:
        left = _resolve_entity(two_between.group(1), alias_to_key)
        right = _resolve_entity(two_between.group(2), alias_to_key)
        if left is None or right is None:
            return None
        return Constraint("distance", left, right, distance=3)

    equality = _parse_equality_entities(clue, alias_to_key)
    if equality:
        left, right = equality
        return Constraint("eq", left, right)

    return None


def _parse_equality_entities(clue: str, alias_to_key: dict[str, str]) -> tuple[str, str] | None:
    for match in re.finditer(r"\bis\b", clue, re.I):
        left = _resolve_entity(clue[: match.start()], alias_to_key)
        right = _resolve_entity(clue[match.end() :], alias_to_key)
        if left is None or right is None:
            continue
        return left, right
    return None


def _solve(parsed: ZebraParse, constraints: list[Constraint]) -> dict[str, str] | None:
    z3_solution = _solve_with_z3(parsed, constraints)
    if z3_solution is not None:
        return z3_solution
    if sum(len(values) for values in parsed.categories.values()) > 18:
        return None
    return _solve_with_backtracking(parsed, constraints)


def _constraints_reference_known_keys(parsed: ZebraParse, constraints: list[Constraint]) -> bool:
    known_keys = {
        _key(category, value)
        for category, values in parsed.categories.items()
        for value in values
    }
    for constraint in constraints:
        if constraint.left not in known_keys:
            return False
        if constraint.right is not None and constraint.right not in known_keys:
            return False
    return True


def _solve_with_z3(parsed: ZebraParse, constraints: list[Constraint]) -> dict[str, str] | None:
    try:
        import z3  # noqa: PLC0415
    except ImportError:
        return None

    keys_by_category = [
        [_key(category, value) for value in values]
        for category, values in parsed.categories.items()
    ]
    all_keys = [key for keys in keys_by_category for key in keys]
    variables = {key: z3.Int(key) for key in all_keys}
    solver = z3.Solver()
    for key in all_keys:
        solver.add(variables[key] >= 1, variables[key] <= parsed.n_houses)
    for keys in keys_by_category:
        solver.add(z3.Distinct(*[variables[key] for key in keys]))
    for constraint in constraints:
        solver.add(constraint.to_z3(variables))

    if solver.check() != z3.sat:
        return None
    model = solver.model()
    assignment = {key: model[variables[key]].as_long() for key in all_keys}

    solver.add(z3.Or(*[variables[key] != value for key, value in assignment.items()]))
    if solver.check() != z3.unsat:
        return None
    return {key: f"house{pos}" for key, pos in sorted(assignment.items())}


def _solve_with_backtracking(parsed: ZebraParse, constraints: list[Constraint]) -> dict[str, str] | None:
    categories = list(parsed.categories.items())
    keys_by_category = [[_key(cat, value) for value in values] for cat, values in categories]
    solutions: list[Assignment] = []

    def backtrack(index: int, assignment: Assignment) -> None:
        if len(solutions) > 1:
            return
        if not all(_constraint_possible(c, assignment) for c in constraints):
            return
        if index == len(categories):
            if all(c(assignment) for c in constraints):
                solutions.append(dict(assignment))
            return

        keys = keys_by_category[index]
        for perm in itertools.permutations(range(1, parsed.n_houses + 1), len(keys)):
            next_assignment = dict(assignment)
            next_assignment.update(dict(zip(keys, perm)))
            backtrack(index + 1, next_assignment)

    backtrack(0, {})
    if len(solutions) != 1:
        return None
    return {key: f"house{pos}" for key, pos in sorted(solutions[0].items())}


def _constraint_possible(constraint: Constraint, assignment: Assignment) -> bool:
    try:
        return constraint(assignment)
    except KeyError:
        return True


def _infer_category(line: str) -> str:
    description = line.split(":", 1)[0]
    lower = description.lower()
    if "nationalit" in lower:
        return "Nationality"
    if "book" in lower:
        return "BookGenre"
    if "music" in lower:
        return "MusicGenre"
    if "lunch" in lower or "food" in lower or "eat" in lower:
        return "Food"
    if "color" in lower:
        return "Color"
    if "phone" in lower:
        return "PhoneModel"
    if "car" in lower or "vehicle" in lower:
        return "CarModel"
    if "smoothie" in lower:
        return "Smoothie"
    if "drink" in lower or "beverage" in lower:
        return "Drink"
    if "cigar" in lower or "smoke" in lower:
        return "Cigar"
    if "hair" in lower:
        return "HairColor"
    if "flower" in lower or "bouquet" in lower or "boquet" in lower:
        return "Flower"
    if "education" in lower or "degree" in lower or "diploma" in lower:
        return "Education"
    if "hobby" in lower:
        return "Hobby"
    if "occupation" in lower or "job" in lower:
        return "Occupation"
    if "child" in lower:
        return "Child"
    if "mother" in lower:
        return "Mother"
    if "height" in lower:
        return "Height"
    if "vacation" in lower:
        return "Vacation"
    if "birthday" in lower or "month" in lower:
        return "Month"
    if "style of house" in lower or "house" in lower or "home" in lower:
        return "House"
    if "name" in lower:
        return "Name"
    if re.search(r"\b(animal|animals|pet|pets)\b", lower):
        return "Animal"
    words = re.sub(r"[^A-Za-z ]", "", description).split()
    return words[-1].title() if words else "Attribute"


def _key(category: str, value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return f"{category}_{slug}"


def _aliases(value: str, category: str) -> set[str]:
    base = value.lower()
    aliases = {base}
    plural = _pluralize(base)
    if plural != base:
        aliases.add(plural)
    aliases.add(f"the {base}")
    aliases.add(f"{base} person")
    aliases.add(f"the {base} person")
    aliases.add(f"{base} books")
    aliases.add(f"the {base} books")
    aliases.add(f"{base} book lover")
    aliases.add(f"the {base} book lover")
    aliases.add(f"person who loves {base}")
    aliases.add(f"the person who loves {base}")
    aliases.add(f"person who loves {base} books")
    aliases.add(f"the person who loves {base} books")
    aliases.add(f"person who loves eating {base}")
    aliases.add(f"the person who loves eating {base}")
    aliases.add(f"person who loves the {base}")
    aliases.add(f"the person who loves the {base}")
    aliases.add(f"person who loves the {base} eater")
    aliases.add(f"the person who loves the {base} eater")
    aliases.add(f"{base} lover")
    aliases.add(f"the {base} lover")
    aliases.add(f"{base} eater")
    aliases.add(f"the {base} eater")
    aliases.add(f"{base} owner")
    aliases.add(f"the {base} owner")
    aliases.add(f"{base} keeper")
    aliases.add(f"the {base} keeper")
    aliases.add(f"{base} enthusiast")
    aliases.add(f"the {base} enthusiast")
    aliases.add(f"person who is a {base} lover")
    aliases.add(f"the person who is a {base} lover")
    aliases.add(f"person who is a {base}")
    aliases.add(f"the person who is a {base}")
    aliases.add(f"person who is an {base}")
    aliases.add(f"the person who is an {base}")
    aliases.add(f"person who is {base}")
    aliases.add(f"the person who is {base}")
    aliases.add(f"person who uses {base}")
    aliases.add(f"the person who uses {base}")
    aliases.add(f"person who uses a {base}")
    aliases.add(f"the person who uses a {base}")
    aliases.add(f"person who uses an {base}")
    aliases.add(f"the person who uses an {base}")
    aliases.add(f"person who owns {base}")
    aliases.add(f"the person who owns {base}")
    aliases.add(f"person who owns a {base}")
    aliases.add(f"the person who owns a {base}")
    aliases.add(f"person who owns an {base}")
    aliases.add(f"the person who owns an {base}")
    aliases.add(f"person who has {base}")
    aliases.add(f"the person who has {base}")
    aliases.add(f"person who has a {base}")
    aliases.add(f"the person who has a {base}")
    aliases.add(f"person who has an {base}")
    aliases.add(f"the person who has an {base}")
    aliases.add(f"person who has {base} hair")
    aliases.add(f"the person who has {base} hair")
    aliases.add(f"person who drinks {base}")
    aliases.add(f"the person who drinks {base}")
    aliases.add(f"person who likes {base}")
    aliases.add(f"the person who likes {base}")
    aliases.add(f"person who likes {base} smoothies")
    aliases.add(f"the person who likes {base} smoothies")
    aliases.add(f"person who drinks {base} smoothies")
    aliases.add(f"the person who drinks {base} smoothies")
    aliases.add(f"{base} smoothie lover")
    aliases.add(f"the {base} smoothie lover")
    aliases.add(f"{base} drinker")
    aliases.add(f"the {base} drinker")
    aliases.add(f"{base} smoker")
    aliases.add(f"the {base} smoker")
    aliases.add(f"person who smokes {base}")
    aliases.add(f"the person who smokes {base}")
    aliases.add(f"person partial to {base}")
    aliases.add(f"the person partial to {base}")
    aliases.add(f"person with {base}")
    aliases.add(f"the person with {base}")
    aliases.add(f"person with a {base}")
    aliases.add(f"the person with a {base}")
    aliases.add(f"person with an {base}")
    aliases.add(f"the person with an {base}")
    aliases.add(f"person who loves a bouquet of {plural}")
    aliases.add(f"the person who loves a bouquet of {plural}")
    aliases.add(f"person who loves a {base} bouquet")
    aliases.add(f"the person who loves a {base} bouquet")
    aliases.add(f"person who loves the boquet of {plural}")
    aliases.add(f"the person who loves the boquet of {plural}")
    aliases.add(f"person who loves a {plural} arrangement")
    aliases.add(f"the person who loves a {plural} arrangement")
    aliases.add(f"person who paints as a hobby")
    aliases.add(f"the person who paints as a hobby")
    aliases.add(f"person who loves {base} music")
    aliases.add(f"the person who loves {base} music")
    aliases.add(f"person who loves {base} vacations")
    aliases.add(f"the person who loves {base} vacations")
    aliases.add(f"person who enjoys {base} trips")
    aliases.add(f"the person who enjoys {base} trips")
    aliases.add(f"person who prefers {base} breaks")
    aliases.add(f"the person who prefers {base} breaks")
    aliases.add(f"person who likes going on {plural}")
    aliases.add(f"the person who likes going on {plural}")
    aliases.add(f"person who goes on {base} tours")
    aliases.add(f"the person who goes on {base} tours")
    aliases.add(f"person who has a {base} height")
    aliases.add(f"the person who has a {base} height")
    aliases.add(f"person who has an {base} height")
    aliases.add(f"the person who has an {base} height")
    aliases.add(f"person's child is named {base}")
    aliases.add(f"the person's child is named {base}")
    aliases.add(f"person who is the mother of {base}")
    aliases.add(f"the person who is the mother of {base}")
    aliases.add(f"person whose mother's name is {base}")
    aliases.add(f"the person whose mother's name is {base}")
    aliases.add(f"person whose birthday is in {base}")
    aliases.add(f"the person whose birthday is in {base}")
    aliases.add(f"person in a {base}-style home")
    aliases.add(f"the person in a {base}-style home")
    aliases.add(f"person in a {base}-style house")
    aliases.add(f"the person in a {base}-style house")
    aliases.add(f"person residing in a {base} house")
    aliases.add(f"the person residing in a {base} house")
    aliases.add(f"person living in a {base}-style house")
    aliases.add(f"the person living in a {base}-style house")
    if category == "Month":
        for full_name, abbreviated in _MONTH_ALIASES.items():
            if abbreviated == base:
                aliases.add(f"person whose birthday is in {full_name}")
                aliases.add(f"the person whose birthday is in {full_name}")
    if " " in base:
        hyphenated = base.replace(" ", "-")
        aliases.update(_aliases(hyphenated, category))
    aliases.add(f"person who keeps {base}")
    aliases.add(f"the person who keeps {base}")
    aliases.add(f"person who keeps {plural}")
    aliases.add(f"the person who keeps {plural}")
    aliases.add(f"person whose favorite color is {base}")
    aliases.add(f"the person whose favorite color is {base}")
    aliases.add(f"person who loves {base}")
    aliases.add(f"the person who loves {base}")
    if category == "Nationality":
        aliases.add(f"{base} person")
        aliases.add(f"the {base} person")
        aliases.add(_nationality_noun(base))
        aliases.add(f"the {_nationality_noun(base)}")
    return aliases


def _preferred_alias_target(alias: str, candidate: str, alias_to_key: dict[str, str]) -> str:
    current = alias_to_key.get(alias)
    if current is None:
        return candidate
    if current.startswith("Name_") and _is_bare_name_alias(alias, current):
        return current
    if candidate.startswith("Name_") and _is_bare_name_alias(alias, candidate):
        return candidate
    if not candidate.startswith("Name_") and current.startswith("Name_"):
        return candidate
    return current


def _is_bare_name_alias(alias: str, key: str) -> bool:
    name = key.removeprefix("Name_").replace("_", " ").lower()
    return alias in {name, f"the {name}"}


def _pluralize(value: str) -> str:
    if value.endswith("s"):
        return value
    if value.endswith("y"):
        return f"{value[:-1]}ies"
    return f"{value}s"


def _nationality_noun(value: str) -> str:
    mapping = {
        "german": "German",
        "norwegian": "Norwegian",
        "dane": "Dane",
        "brit": "British person",
        "swede": "Swede",
    }
    return mapping.get(value, value).lower()


def _resolve_entity(text: str, alias_to_key: dict[str, str]) -> str | None:
    normalized = text.lower().strip()
    normalized = normalized.rstrip(".")
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = _strip_leading_article(normalized)
    if normalized in alias_to_key:
        return alias_to_key[normalized]
    if normalized.startswith("the "):
        without_the = normalized[4:]
        if without_the in alias_to_key:
            return alias_to_key[without_the]
    return None


def _strip_leading_article(text: str) -> str:
    return re.sub(r"^the\s+", "", text, flags=re.I)
