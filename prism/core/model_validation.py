"""Validation helpers for solver models produced by PRISM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from prism.core.types import PuzzleInstance


_HOUSE_ATTRIBUTE_RE = re.compile(r"^house\d+_.+", re.IGNORECASE)
_CATEGORY_LIST_RE = re.compile(
    r"(?:unique\s+)?(?P<label>[A-Za-z][A-Za-z ]*?):\s*`(?P<values>[^`]+)`(?P<tail>[^\n]*)",
    re.IGNORECASE,
)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_CLUE_VALUE_RE = re.compile(
    r"\b[Tt]he\s+(?P<value>[A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)*)\s+"
    r"(?P<category>[a-z][A-Za-z0-9]*(?:\s+[a-z][A-Za-z0-9]*)?)\b"
)


@dataclass(frozen=True)
class ModelValidation:
    """Diagnostic verdict for a SAT model."""

    domain_valid: bool = True
    schema_aligned: bool = True
    key_set_aligned: bool = True
    error_type: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.domain_valid and self.schema_aligned and self.key_set_aligned

    @property
    def final_z3_result(self) -> str:
        if not self.domain_valid:
            return "INVALID_MODEL"
        if not self.schema_aligned:
            return "MISALIGNED_MODEL"
        if not self.key_set_aligned:
            return "KEY_MISMATCH"
        return "SAT"


def validate_model(puzzle: PuzzleInstance, solution: Optional[dict]) -> ModelValidation:
    """Validate numeric range and semantic key schema for a SAT model."""

    schema_check = model_schema_alignment(puzzle, solution)
    if not model_within_puzzle_domain(puzzle, solution):
        return ModelValidation(
            domain_valid=False,
            schema_aligned=schema_check["schema_aligned"],
            key_set_aligned=schema_check["key_set_aligned"],
            error_type="MODEL_OUT_OF_DOMAIN",
            error="model contains assignments outside puzzle domain",
        )
    if not schema_check["schema_aligned"]:
        return ModelValidation(
            domain_valid=True,
            schema_aligned=False,
            key_set_aligned=schema_check["key_set_aligned"],
            error_type="MODEL_SCHEMA_MISMATCH",
            error="model variable names do not align with puzzle solution schema",
        )
    if not schema_check["key_set_aligned"]:
        return ModelValidation(
            domain_valid=True,
            schema_aligned=True,
            key_set_aligned=False,
            error_type="MODEL_KEY_SET_MISMATCH",
            error="model variable key set does not match puzzle solution schema",
        )
    return ModelValidation()


def model_within_puzzle_domain(
    puzzle: PuzzleInstance,
    solution: Optional[dict],
) -> bool:
    """Reject integer assignments outside the puzzle house range."""

    if not solution or not puzzle.size:
        return True
    try:
        n_entities = int(str(puzzle.size).lower().split("x", 1)[0])
    except (TypeError, ValueError):
        return True

    for name, raw_value in solution.items():
        if str(name).startswith("_prism_track_"):
            continue
        try:
            value = int(str(raw_value))
        except ValueError:
            continue
        if value < 1 or value > n_entities:
            return False
    return True


def model_category_assignments_are_permutations(
    puzzle: PuzzleInstance,
    solution: Optional[dict],
) -> bool:
    """Reject complete semantic categories that are not permutations of houses."""

    if not solution or not puzzle.size:
        return True
    try:
        n_entities = int(str(puzzle.size).lower().split("x", 1)[0])
    except (TypeError, ValueError):
        return True
    if n_entities <= 0:
        return True

    expected_values = {str(i) for i in range(1, n_entities + 1)}
    visible_categories = _visible_schema_categories(puzzle)
    groups: dict[str, list[str]] = {}
    for name, raw_value in solution.items():
        key = str(name)
        if key.startswith("_prism_track_") or _HOUSE_ATTRIBUTE_RE.match(key):
            continue
        category = _schema_key_category(key)
        if not category:
            continue
        try:
            value = str(int(str(raw_value)))
        except ValueError:
            continue
        groups.setdefault(category, []).append(value)

    for category, values in groups.items():
        expected_count = visible_categories.get(category, n_entities)
        if expected_count != n_entities or len(values) != n_entities:
            continue
        if set(values) != expected_values or len(values) != len(set(values)):
            return False
    return True


def model_schema_aligned(
    puzzle: PuzzleInstance,
    solution: Optional[dict],
) -> bool:
    return model_schema_alignment(puzzle, solution)["schema_aligned"]


def model_schema_alignment(
    puzzle: PuzzleInstance,
    solution: Optional[dict],
) -> dict:
    """Check whether model keys match the benchmark solution key convention.

    This uses only key names, never ground-truth values.  The check is
    conservative on semantic style but strict on key-set completeness once the
    style overlaps the expected benchmark schema.
    """

    expected = {
        str(key)
        for key in (puzzle.solution or {})
        if not str(key).startswith("_prism_track_")
    }
    if not expected:
        return {"schema_aligned": True, "key_set_aligned": True}

    predicted = {
        str(key)
        for key in (solution or {})
        if not str(key).startswith("_prism_track_")
    }
    if not predicted:
        return {"schema_aligned": False, "key_set_aligned": False}

    house_slot_count = sum(1 for key in predicted if _HOUSE_ATTRIBUTE_RE.match(key))
    if house_slot_count >= max(1, len(predicted) // 2):
        return {"schema_aligned": False, "key_set_aligned": False}

    overlap = expected & predicted
    if not overlap:
        return {"schema_aligned": False, "key_set_aligned": False}
    return {
        "schema_aligned": True,
        "key_set_aligned": predicted == expected,
    }


def expected_solution_key_hint(puzzle: PuzzleInstance, limit: int = 12) -> str:
    """Return expected solution keys for oracle upper-bound prompt guidance."""

    keys = sorted(str(key) for key in (puzzle.solution or {}).keys())
    return _format_key_hint(keys, limit)


def puzzle_schema_key_hint(puzzle: PuzzleInstance, limit: int = 60) -> str:
    """Return non-oracle schema keys from puzzle metadata or visible text.

    This intentionally avoids ``puzzle.solution``.  It can use explicit
    variables/domains already present on the puzzle and backtick-delimited value
    lists from benchmark puzzle text.
    """

    keys = visible_schema_keys(puzzle)
    return _format_key_hint(sorted(keys), limit)


def visible_schema_keys(puzzle: PuzzleInstance) -> set[str]:
    """Return non-oracle semantic variable keys visible in puzzle inputs."""

    keys: list[str] = []
    if puzzle.variables:
        keys.extend(str(var) for var in puzzle.variables)
    if puzzle.domains:
        for category, values in puzzle.domains.items():
            for value in values:
                keys.append(_make_schema_key(str(category), str(value)))

    keys.extend(_schema_keys_from_text(puzzle.nl_description))
    keys.extend(_schema_keys_from_clues(puzzle.nl_description))
    return {key for key in keys if key}


def schema_visibility_diagnostics(
    puzzle: PuzzleInstance,
    generated_keys: set[str] | None = None,
) -> dict:
    """Compare visible schema keys with expected and generated model keys.

    Expected keys come from benchmark metadata and are diagnostic only. They are
    not used to guide prompts or repair decisions in non-oracle mode.
    """

    visible = visible_schema_keys(puzzle)
    expected = {
        str(key)
        for key in (puzzle.solution or {})
        if not str(key).startswith("_prism_track_")
    }
    generated = set(generated_keys or set())
    return {
        "visible_schema_key_count": len(visible),
        "expected_schema_key_count": len(expected),
        "missing_visible_schema_keys": sorted(expected - visible),
        "generated_extra_schema_keys": sorted(generated - visible) if visible else [],
    }


def _schema_keys_from_text(text: str) -> list[str]:
    keys: list[str] = []
    for line in text.splitlines():
        if "`" not in line or ":" not in line:
            continue
        match = _CATEGORY_LIST_RE.search(line)
        if not match:
            continue
        category = _normalise_category_label(match.group("label"))
        if not category:
            continue
        for value in _BACKTICK_RE.findall(line):
            keys.append(_make_schema_key(category, value))
    return keys


def _schema_keys_from_clues(text: str) -> list[str]:
    keys: list[str] = []
    for match in _CLUE_VALUE_RE.finditer(text or ""):
        key = _make_schema_key(
            _clean_clue_category(match.group("category")),
            match.group("value"),
        )
        if key:
            keys.append(key)
    return keys


def _visible_schema_categories(puzzle: PuzzleInstance) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key in visible_schema_keys(puzzle):
        category = _schema_key_category(key)
        if category:
            counts[category] = counts.get(category, 0) + 1
    return counts


def _schema_key_category(key: str) -> str:
    if "_" not in key:
        return ""
    return key.split("_", 1)[0]


def _clean_clue_category(category: str) -> str:
    words = category.strip().split()
    while words and words[-1].lower() in {
        "person",
        "people",
        "is",
        "are",
        "lives",
        "live",
        "has",
        "have",
        "keeps",
        "drinks",
        "uses",
    }:
        words.pop()
    return " ".join(words)


def _normalise_category_label(label: str) -> str:
    raw = " ".join(label.strip().split())
    if not raw:
        return ""
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", raw):
        return raw
    lowered = raw.lower()
    replacements = {
        "each person has a unique name": "Name",
        "names": "Name",
        "name": "Name",
        "the people are of nationalities": "Nationality",
        "people are of nationalities": "Nationality",
        "nationalities": "Nationality",
        "nationality": "Nationality",
        "people have unique favorite book genres": "BookGenre",
        "favorite book genres": "BookGenre",
        "book genres": "BookGenre",
        "book genre": "BookGenre",
        "everyone has something unique for lunch": "Food",
        "favorite foods": "Food",
        "foods": "Food",
        "food": "Food",
        "each person has a favorite color": "Color",
        "house colors": "Color",
        "colors": "Color",
        "color": "Color",
        "the people keep unique animals": "Animal",
        "animals": "Animal",
        "animal": "Animal",
        "each person has a unique type of pet": "Pet",
        "pets": "Pet",
        "pet": "Pet",
        "everyone drinks": "Drink",
        "drinks": "Drink",
        "drink": "Drink",
        "each person has an occupation": "Occupation",
        "occupations": "Occupation",
        "occupation": "Occupation",
        "jobs": "Job",
        "job": "Job",
        "hobbies": "Hobby",
        "hobby": "Hobby",
        "people use unique phone models": "PhoneModel",
        "phone models": "PhoneModel",
        "phone model": "PhoneModel",
        "people have unique favorite music genres": "MusicGenre",
        "favorite music genres": "MusicGenre",
        "music genres": "MusicGenre",
        "music genre": "MusicGenre",
        "people have unique heights": "Height",
        "heights": "Height",
        "height": "Height",
        "each person has a unique level of education": "Education",
        "levels of education": "Education",
        "education": "Education",
        "each person prefers a unique type of vacation": "Vacation",
        "vacations": "Vacation",
        "vacation": "Vacation",
        "they all have a unique favorite flower": "Flower",
        "favorite flower": "Flower",
        "flower": "Flower",
        "each person lives in a unique style of house": "HouseStyle",
        "style of house": "HouseStyle",
        "house style": "HouseStyle",
        "the mothers' names in different houses are unique": "Mother",
        "mothers' names": "Mother",
        "mother": "Mother",
        "each mother is accompanied by their child": "Child",
        "child": "Child",
        "each person has a unique birthday month": "Month",
        "birthday month": "Month",
        "month": "Month",
    }
    if lowered in replacements:
        return replacements[lowered]
    words = [part for part in re.split(r"[^A-Za-z0-9]+", raw) if part]
    if not words:
        return ""
    return "".join(word[:1].upper() + word[1:] for word in words)


def _make_schema_key(category: str, value: str) -> str:
    cat = _normalise_key_category(_normalise_category_label(category))
    val = _normalise_value_label(value)
    if not cat or not val:
        return ""
    return f"{cat}_{val}"


def _normalise_key_category(category: str) -> str:
    if not category:
        return ""
    return category[:1].lower() + category[1:]


def _normalise_value_label(value: str) -> str:
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", value.strip()) if part]
    if not parts:
        return ""
    return "_".join(part[:1].upper() + part[1:] for part in parts)


def _format_key_hint(keys: list[str], limit: int) -> str:
    if not keys:
        return ""
    head = keys[:limit]
    suffix = "" if len(keys) <= limit else f", ... ({len(keys)} total)"
    return ", ".join(head) + suffix
