from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List

from prism.core.constraint_tags import classify_constraint_tags
from prism.core.solver import Z3SolverWrapper
from prism.core.types import SolverState, StepType, Trajectory, TrajectoryStep
from prism.offline.kdp_identifier import KDPIdentifier
from prism.online.feature_extractor import FeatureExtractor
from prism.paradigm_library.schema import ErrorParadigm


def unsat_signature(unsat_core: List[str]) -> str:
    canonical = "|".join(sorted(c.strip() for c in unsat_core if c and c.strip()))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class ErrorParadigmExtractor:
    """Build deterministic negative paradigms from failed trajectory steps."""

    def __init__(self, min_support: int = 1) -> None:
        self._min_support = max(1, min_support)

    def extract(self, trajectories: Iterable[Trajectory]) -> List[ErrorParadigm]:
        groups: dict[str, list[tuple[Trajectory, TrajectoryStep]]] = {}
        for traj in trajectories:
            for step in traj.steps:
                if not self._is_error_step(step):
                    continue
                signature = unsat_signature(step.unsat_core or [])
                groups.setdefault(signature, []).append((traj, step))

        paradigms: List[ErrorParadigm] = []
        for idx, (signature, items) in enumerate(sorted(groups.items()), start=1):
            if len(items) < self._min_support:
                continue
            _, step = items[0]
            if not self._verify_unsat_core(step.unsat_core or []):
                continue
            paradigms.append(self._build(signature, items, idx))
        return paradigms

    def extract_from_trace_records(
        self,
        records: Iterable[dict],
        *,
        instance_specific: bool = False,
    ) -> List[ErrorParadigm]:
        """Mine typed replacement policies from online trace records.

        This path uses successful repair steps that contain both the wrong
        constraint and the corrected expression. It is intentionally separate
        from ``extract`` because online traces carry richer fields than the
        legacy ``TrajectoryStep`` schema.
        """
        groups: dict[str, list[tuple[dict, dict, dict]]] = {}
        for record in records:
            for step in record.get("steps", []) or []:
                item = _typed_repair_item(record, step)
                if not item:
                    continue
                key_parts = [
                    item["kind"],
                    item["bad_operation"],
                    item.get("source_clue", ""),
                ]
                if not instance_specific:
                    key_parts[1] = _constraint_shape(item["bad_operation"])
                    key_parts[2] = ""
                key = "|".join(key_parts)
                groups.setdefault(key, []).append((record, step, item))

        paradigms: List[ErrorParadigm] = []
        for idx, (_, items) in enumerate(sorted(groups.items()), start=1):
            if len(items) < self._min_support:
                continue
            paradigms.append(
                self._build_typed_replacement_paradigm(
                    items,
                    idx,
                    instance_specific=instance_specific,
                )
            )
        return paradigms

    def extract_from_trace_jsonl(
        self,
        path: str | Path,
        *,
        instance_specific: bool = False,
    ) -> List[ErrorParadigm]:
        return self.extract_from_trace_records(
            _load_trace_jsonl(Path(path)),
            instance_specific=instance_specific,
        )

    @staticmethod
    def _is_error_step(step: TrajectoryStep) -> bool:
        return (
            step.step_type == StepType.CONTRADICTION
            and step.z3_result == "UNSAT"
            and bool(step.unsat_core)
        )

    @staticmethod
    def _verify_unsat_core(unsat_core: List[str]) -> bool:
        solver = Z3SolverWrapper()
        added = 0
        for constraint in unsat_core:
            if solver.add_constraint(constraint):
                added += 1
        return added > 0 and solver.check() == "UNSAT"

    def _build(
        self,
        signature: str,
        items: list[tuple[Trajectory, TrajectoryStep]],
        index: int,
    ) -> ErrorParadigm:
        steps = [step for _, step in items]
        first = steps[0]
        scope = self._scope(first)
        bad_operation = first.constraint_added or (first.unsat_core or [""])[0]
        support = len(items)
        return ErrorParadigm(
            id=f"E-{index:03d}",
            name=f"avoid_unsat_core_{signature[:8]}",
            trigger={
                "constraint_types": scope,
                "unsat_signature": signature,
                "z3_result": "UNSAT",
            },
            bad_operation=bad_operation,
            unsat_signature=signature,
            avoid_instruction=(
                "Avoid repeating this constraint pattern; it reproduced an UNSAT core "
                f"in {support} trajectory step(s)."
            ),
            repair_hint=self._repair_hint(first),
            scope=scope,
            confidence=1.0,
            support_count=support,
            source_cluster=index,
            created_at=datetime.now(tz=timezone.utc),
        )

    def _build_typed_replacement_paradigm(
        self,
        items: list[tuple[dict, dict, dict]],
        index: int,
        *,
        instance_specific: bool,
    ) -> ErrorParadigm:
        record, step, item = items[0]
        support = len(items)
        source_clue = str(item.get("source_clue") or "")
        policy: dict = {
            "kind": item["policy_kind"],
        }
        if source_clue and instance_specific:
            policy["source_clue"] = source_clue
        if instance_specific:
            policy["puzzle_id"] = str(record.get("puzzle_id") or "")

        scope = _scope_for_operations(
            item["bad_operation"],
            str(item.get("target_constraint") or ""),
        )
        signature = unsat_signature(step.get("unsat_core") or [item["bad_operation"]])
        return ErrorParadigm(
            id=f"ET-{index:03d}",
            name=f"template_{item['kind']}_{index:03d}",
            trigger={
                "constraint_types": scope,
                "bad_constraint": item["bad_operation"],
                "replacement_policy": policy,
                "z3_result": "UNSAT",
            },
            bad_operation=item["bad_operation"],
            unsat_signature=signature,
            avoid_instruction=(
                "This constraint shape was repaired by a typed replacement "
                f"template in {support} trace step(s)."
            ),
            repair_hint=_typed_repair_hint(item["kind"]),
            scope=scope,
            confidence=1.0,
            support_count=support,
            source_cluster=index,
            created_at=datetime.now(tz=timezone.utc),
        )

    @staticmethod
    def _scope(step: TrajectoryStep) -> List[str]:
        constraints = list(step.unsat_core or [])
        for constraint in [
            step.constraint_added,
            step.constraint_modified,
            step.constraint_removed,
        ]:
            if constraint:
                constraints.append(constraint)
        state = SolverState(
            puzzle_id="error-paradigm-extraction",
            constraints=constraints,
            unsat_core=constraints if step.unsat_core else None,
            z3_result=step.z3_result,
        )
        online_types = FeatureExtractor().extract(state)
        legacy_types = KDPIdentifier._extract_constraint_types(step)
        types = sorted({
            tag
            for tag in [*online_types, *legacy_types]
            if tag and tag != "unknown"
        })
        return types if types else ["contradiction"]

    @staticmethod
    def _repair_hint(step: TrajectoryStep) -> str:
        core = step.unsat_core or []
        if step.constraint_added:
            return _repair_hint_for_operation(step.constraint_added)
        if core:
            kind_counts = Counter(KDPIdentifier._extract_constraint_types(step))
            common = ", ".join(kind for kind, _ in kind_counts.most_common(3))
            return f"Re-examine the UNSAT core constraints; likely types: {common}."
        return "Re-translate the relevant natural-language clue before repairing."


def _repair_hint_for_operation(operation: str) -> str:
    op = operation.strip()
    vars_ = re.findall(r"Int\('([^']+)'\)", op)
    a = f"Int('{vars_[0]}')" if len(vars_) >= 1 else "Int('a')"
    b = f"Int('{vars_[1]}')" if len(vars_) >= 2 else "Int('b')"

    if " Or(" in f" {op}" or op.startswith("Or("):
        return (
            "Do not use a broad symmetric Or(...) relation unless the clue says "
            f"'next to'. For directly-left/right clues, replace with one oriented "
            f"relation such as {a} == {b} - 1 or {a} == {b} + 1."
        )
    if re.search(r"\+\s*2|-\s*2", op):
        return (
            "This looks like a gap-distance relation. Use +/- 2 only for clues "
            f"that explicitly say one house between; otherwise use adjacency "
            f"Abs({a} - {b}) == 1 or an oriented +/- 1 relation."
        )
    if ">=" in op or "<=" in op or re.search(r">\s*1|<\s*1", op):
        return (
            "This inequality may be too weak or wrongly oriented. For Zebra "
            f"relative-position clues, prefer exact relations: {a} < {b}, "
            f"{a} > {b}, {a} == {b} - 1, or {a} == {b} + 1."
        )
    if re.search(r"==\s*.*[+-]\s*1", op):
        return (
            "Verify the direction of the +/-1 relation against the clue. "
            f"If the clue says A is directly left of B, use {a} == {b} - 1; "
            f"if A is directly right of B, use {a} == {b} + 1."
        )
    if "==" in op:
        return (
            "Use equality only for same-house attribute binding clues. If the "
            f"clue says left/right/next-to, replace equality with {a} < {b}, "
            f"{a} > {b}, or Abs({a} - {b}) == 1."
        )
    return f"Replace or re-translate this suspicious constraint: {op}"


def _load_trace_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))
    return records


def _typed_repair_item(record: dict, step: dict) -> dict | None:
    if step.get("action") != "repair" or step.get("z3_result") != "SAT":
        return None
    bad = str(step.get("old_constraint") or "")
    target = str(step.get("repair_expression") or step.get("new_constraint") or "")
    if not bad or not target:
        return None
    kind = _infer_typed_repair_kind(bad, target)
    if not kind:
        return None
    source_clue = str(
        record.get("controlled_source_clue")
        or _source_clue_from_step(step)
        or _source_clue_from_puzzle_text(str(record.get("puzzle") or ""), kind, bad)
        or ""
    )
    return {
        "kind": kind,
        "policy_kind": (
            "direct_position_from_source_clue"
            if kind == "direct_position"
            else f"{kind}_from_source_clue"
        ),
        "bad_operation": bad,
        "target_constraint": target,
        "source_clue": source_clue,
    }


def _source_clue_from_step(step: dict) -> str:
    for paradigm in step.get("error_paradigms") or []:
        policy = paradigm.get("replacement_policy") if isinstance(paradigm, dict) else None
        if isinstance(policy, dict) and policy.get("source_clue"):
            return str(policy["source_clue"])
    return ""


def _source_clue_from_puzzle_text(puzzle_text: str, kind: str, bad: str) -> str:
    parsed_direct = _parse_direct_position_constraint(bad)
    if kind == "direct_position" and parsed_direct:
        found = _find_direct_position_clue_for_key(puzzle_text, parsed_direct[0])
        return found[2] if found else ""
    parsed_relation = _parse_relation_constraint(bad)
    if parsed_relation:
        found = _find_relation_clue_for_vars(
            puzzle_text,
            kind,
            parsed_relation[1],
            parsed_relation[2],
        )
        return found[3] if found else ""
    return ""


def _infer_typed_repair_kind(bad: str, target: str) -> str:
    bad_direct = _parse_direct_position_constraint(bad)
    target_direct = _parse_direct_position_constraint(target)
    if bad_direct and target_direct and bad_direct[0] == target_direct[0]:
        return "direct_position"

    target_relation = _parse_relation_constraint(target)
    bad_relation = _parse_relation_constraint(bad)
    if target_relation and bad_relation and {target_relation[1], target_relation[2]} == {
        bad_relation[1],
        bad_relation[2],
    }:
        return target_relation[0]
    return ""


def _parse_direct_position_constraint(constraint: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"Int\('([^']+)'\)\s*==\s*(-?\d+)", (constraint or "").strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _parse_relation_constraint(constraint: str) -> tuple[str, str, str] | None:
    text = (constraint or "").strip()
    patterns = [
        (r"Int\('([^']+)'\)\s*==\s*Int\('([^']+)'\)\s*-\s*1", "directly_left"),
        (r"Int\('([^']+)'\)\s*\+\s*1\s*==\s*Int\('([^']+)'\)", "directly_left"),
        (r"Int\('([^']+)'\)\s*==\s*Int\('([^']+)'\)\s*\+\s*1", "directly_right"),
        (r"Int\('([^']+)'\)\s*-\s*1\s*==\s*Int\('([^']+)'\)", "directly_right"),
        (r"Int\('([^']+)'\)\s*<\s*Int\('([^']+)'\)", "somewhere_left"),
        (r"Int\('([^']+)'\)\s*>\s*Int\('([^']+)'\)", "somewhere_right"),
        (r"Abs\(Int\('([^']+)'\)\s*-\s*Int\('([^']+)'\)\)\s*==\s*1", "adjacent"),
    ]
    for pattern, relation_kind in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            return relation_kind, match.group(1), match.group(2)
    return None


def _find_direct_position_clue_for_key(
    puzzle_text: str,
    key: str,
) -> tuple[str, int, str] | None:
    for line in _numbered_clue_lines(puzzle_text):
        parsed = _parse_direct_position_source_clue(line)
        if parsed and parsed[0] == key:
            return parsed[0], parsed[1], line
    return None


def _parse_direct_position_source_clue(clue: str) -> tuple[str, int] | None:
    match = re.search(
        r"The\s+(?P<value>[A-Za-z0-9][A-Za-z0-9 ]*?)\s+"
        r"(?P<category>[A-Za-z][A-Za-z0-9 ]*?)(?:\s+person)?\s+"
        r"lives\s+in\s+house\s+(?P<house>\d+)",
        clue or "",
        re.I,
    )
    if not match:
        return None
    return _make_key(match.group("category"), match.group("value")), int(match.group("house"))


def _find_relation_clue_for_vars(
    puzzle_text: str,
    relation_kind: str,
    first_key: str,
    second_key: str,
) -> tuple[str, str, str, str] | None:
    wanted = {first_key, second_key}
    for line in _numbered_clue_lines(puzzle_text):
        parsed = _parse_relation_source_clue(line)
        if parsed and parsed[0] == relation_kind and {parsed[1], parsed[2]} == wanted:
            return parsed[0], parsed[1], parsed[2], line
    return None


def _parse_relation_source_clue(clue: str) -> tuple[str, str, str] | None:
    text = re.sub(r"^\s*\d+\.\s*", "", clue or "").strip().rstrip(".")
    patterns = [
        (r"(.+?)\s+is\s+(?:immediately|directly)\s+left\s+of\s+(.+)$", "directly_left"),
        (r"(.+?)\s+is\s+(?:immediately|directly)\s+right\s+of\s+(.+)$", "directly_right"),
        (r"(.+?)\s+is\s+(?:somewhere\s+)?to\s+the\s+left\s+of\s+(.+)$", "somewhere_left"),
        (r"(.+?)\s+is\s+(?:somewhere\s+)?to\s+the\s+right\s+of\s+(.+)$", "somewhere_right"),
        (r"(.+?)\s+and\s+(.+?)\s+are\s+next\s+to\s+each\s+other$", "adjacent"),
    ]
    for pattern, relation_kind in patterns:
        match = re.fullmatch(pattern, text, flags=re.I)
        if not match:
            continue
        left = _parse_relation_entity(match.group(1))
        right = _parse_relation_entity(match.group(2))
        if left and right:
            return relation_kind, left, right
    return None


def _parse_relation_entity(entity: str) -> str | None:
    text = re.sub(r"^\s*the\s+", "", entity or "", flags=re.I).strip()
    text = re.sub(r"\s+person\s*$", "", text, flags=re.I).strip()
    parts = [part for part in re.split(r"\s+", text) if part]
    if len(parts) < 2:
        return None
    return _make_key(parts[-1], " ".join(parts[:-1]))


def _make_key(category: str, value: str) -> str:
    category_slug = re.sub(r"[^A-Za-z0-9]+", "_", category.strip()).strip("_")
    category_slug = category_slug[:1].lower() + category_slug[1:]
    value_parts = [part for part in re.split(r"[^A-Za-z0-9]+", value.strip()) if part]
    value_slug = "_".join(part[:1].upper() + part[1:] for part in value_parts)
    return f"{category_slug}_{value_slug}"


def _numbered_clue_lines(puzzle_text: str) -> list[str]:
    return [
        line.strip()
        for line in (puzzle_text or "").splitlines()
        if re.match(r"^\s*\d+\.\s+", line.strip())
    ]


def _scope_for_operations(*operations: str) -> list[str]:
    tags: set[str] = set()
    for operation in operations:
        tags.update(classify_constraint_tags(operation))
    tags.discard("unknown")
    return sorted(tags) if tags else ["contradiction"]


def _constraint_shape(constraint: str) -> str:
    text = re.sub(r"Int\('[^']+'\)", "Int('$VAR')", constraint or "")
    text = re.sub(r"\b-?\d+\b", "$NUM", text)
    return re.sub(r"\s+", "", text)


def _typed_repair_hint(kind: str) -> str:
    if kind == "direct_position":
        return (
            "Parse the source clue's house number and return the corresponding "
            "direct-position equality exactly."
        )
    return (
        "Parse the source clue and return the corresponding typed relation "
        "constraint exactly. Do not weaken it to an inequality or less specific "
        "relation."
    )
