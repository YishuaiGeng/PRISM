"""Lexical constraint tagging shared by online and offline components."""

from __future__ import annotations

import re
from typing import Iterable

KEYWORD_TO_TYPE: dict[str, str] = {
    "distinct(": "all_different",
    "Distinct(": "all_different",
    "immediately": "adjacent",
    "adjacent": "adjacent",
    "next to": "adjacent",
    "left of": "relative_position",
    "right of": "relative_position",
    "!= ": "exclusion",
    "also has": "inclusion",
    "and(": "logical_implication",
    "And(": "logical_implication",
    "or(": "logical_implication",
    "Or(": "logical_implication",
    "not(": "logical_implication",
    "Not(": "logical_implication",
    "if ": "binding",
    "implies": "binding",
}

SPECIFIC_RELATION_TAGS = frozenset({
    "directly_left",
    "directly_right",
    "somewhere_left",
    "somewhere_right",
    "adjacent",
    "same_house",
    "domain_candidate_mismatch",
    "distinct_group_mismatch",
})

_INT_VAR_RE = re.compile(r"Int\('([^']+)'\)")
_DOMAIN_BOUND_RE = re.compile(
    r"And\(Int\('([^']+)'\)\s*>=\s*(-?\d+),\s*Int\('\1'\)\s*<=\s*(-?\d+)\)"
)
_ASSIGN_RE = re.compile(r"Int\('([^']+)'\)\s*==\s*(-?\d+)")


def classify_constraint_tags(constraint: str) -> list[str]:
    """Return lexical and relation-specific tags for one constraint string."""
    text = constraint or ""
    tags: set[str] = set()
    for keyword, ctype in KEYWORD_TO_TYPE.items():
        if keyword in text:
            tags.add(ctype)

    tags.update(_relation_tags(text))
    if _DOMAIN_BOUND_RE.search(text):
        tags.add("domain_bound")
    if _ASSIGN_RE.search(text):
        tags.add("direct_position")
    if re.search(r"\bInt\('[^']+'\)\s*<\s*Int\('[^']+'\)", text):
        tags.add("ordering")
    if re.search(r"\bInt\('[^']+'\)\s*>\s*Int\('[^']+'\)", text):
        tags.add("ordering")
    if re.search(r"\bInt\('[^']+'\)\s*<\s*-?\d+", text):
        tags.add("ordering")
    if re.search(r"\bInt\('[^']+'\)\s*>\s*-?\d+", text):
        tags.add("ordering")
    return sorted(tags) if tags else ["unknown"]


def classify_constraint_set_tags(
    constraints: Iterable[str],
    *,
    is_unsat_core: bool = False,
) -> list[str]:
    """Classify a set of constraints and add UNSAT-core contextual tags."""
    tags: set[str] = set()
    materialized = [c for c in constraints if c]
    for constraint in materialized:
        tags.update(classify_constraint_tags(constraint))
    if is_unsat_core:
        tags.update(infer_unsat_context_tags(materialized))
    tags.discard("unknown")
    return sorted(tags) if tags else ["unknown"]


def relation_scope_for_operation(operation: str) -> list[str]:
    """Infer tags from a stored bad operation for scoring error paradigms."""
    return classify_constraint_tags(operation)


def infer_unsat_context_tags(constraints: Iterable[str]) -> set[str]:
    """Infer mismatch tags that only make sense for an UNSAT core."""
    materialized = [c for c in constraints if c]
    tags: set[str] = set()
    bounds = _domain_bounds(materialized)
    assignments = _assignments(materialized)

    for var, value in assignments.items():
        if var in bounds:
            lo, hi = bounds[var]
            if value < lo or value > hi:
                tags.add("domain_candidate_mismatch")

    for constraint in materialized:
        if "Distinct(" not in constraint:
            continue
        vars_ = _constraint_vars(constraint)
        if len(vars_) < 2:
            continue
        assigned_values = [assignments[var] for var in vars_ if var in assignments]
        if len(assigned_values) != len(set(assigned_values)):
            tags.add("distinct_group_mismatch")

        capacities = [
            bounds[var][1] - bounds[var][0] + 1
            for var in vars_
            if var in bounds
        ]
        if capacities and len(vars_) > min(capacities):
            tags.add("distinct_group_mismatch")
            tags.add("domain_candidate_mismatch")
    return tags


def _relation_tags(text: str) -> set[str]:
    tags: set[str] = set()
    if "Abs(" in text and re.search(r"==\s*1\b", text):
        tags.add("adjacent")
    if "Or(" in text and re.search(r"[+-]\s*1", text):
        tags.add("adjacent")

    if re.search(r"Int\('[^']+'\)\s*==\s*Int\('[^']+'\)\s*-\s*1", text):
        tags.add("directly_left")
    if re.search(r"Int\('[^']+'\)\s*\+\s*1\s*==\s*Int\('[^']+'\)", text):
        tags.add("directly_left")
    if re.search(r"Int\('[^']+'\)\s*==\s*Int\('[^']+'\)\s*\+\s*1", text):
        tags.add("directly_right")
    if re.search(r"Int\('[^']+'\)\s*-\s*1\s*==\s*Int\('[^']+'\)", text):
        tags.add("directly_right")

    if re.search(r"Int\('[^']+'\)\s*<\s*Int\('[^']+'\)", text):
        tags.add("somewhere_left")
    if re.search(r"Int\('[^']+'\)\s*>\s*Int\('[^']+'\)", text):
        tags.add("somewhere_right")

    if (
        re.search(r"Int\('[^']+'\)\s*==\s*Int\('[^']+'\)\s*$", text.strip())
        and not re.search(r"[+-]\s*\d", text)
    ):
        tags.add("same_house")
    return tags


def _domain_bounds(constraints: Iterable[str]) -> dict[str, tuple[int, int]]:
    bounds: dict[str, tuple[int, int]] = {}
    for constraint in constraints:
        match = _DOMAIN_BOUND_RE.search(constraint)
        if match:
            bounds[match.group(1)] = (int(match.group(2)), int(match.group(3)))
    return bounds


def _assignments(constraints: Iterable[str]) -> dict[str, int]:
    assignments: dict[str, int] = {}
    for constraint in constraints:
        match = _ASSIGN_RE.search(constraint)
        if match:
            assignments[match.group(1)] = int(match.group(2))
    return assignments


def _constraint_vars(constraint: str) -> list[str]:
    return _INT_VAR_RE.findall(constraint or "")
