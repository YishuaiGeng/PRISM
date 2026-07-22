"""Online paradigm-guided inference with repair trajectory memory.

``GuidedSolver`` is the main PRISM online component.  It orchestrates:

1. **Initial translation** — NL puzzle → Z3 constraint strings via LLMClient.
2. **Paradigm-guided inference** — Layer-1 fast retrieval + Layer-2 semantic
   match + Z3 consistency pre-check before injecting paradigm hints to LLM.
3. **Repair loop** — iterative constraint repair using RepairMemory and
   StrategySwitcher for stagnation/loop detection and four-level escalation.
4. **Write-back** — successful repairs update the paradigm library's confidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.model_validation import (
    ModelValidation,
    model_within_puzzle_domain,
    normalise_schema_key,
    puzzle_schema_key_hint,
    validate_model,
    visible_schema_keys,
)
from prism.core.solver import Z3SolverWrapper
from prism.core.translator import NLToZ3Translator
from prism.core.types import PuzzleInstance, SolveResult, SolverState
from prism.offline.paradigm_verifier import ParadigmVerifier
from prism.online.candidate_pool import CandidatePool
from prism.online.feature_extractor import FeatureExtractor
from prism.online.repair_memory import RepairMemory
from prism.online.strategy_switcher import StrategySwitcher
from prism.paradigm_library.error_library import ErrorParadigmLibrary
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import ErrorType, Outcome, RepairAction, RepairRecord

logger = logging.getLogger(__name__)

_DEFAULT_MAX_REPAIR_ROUNDS: int = 5
_DEFAULT_PARADIGM_TOP_K: int = 3
_DEFAULT_PARADIGM_CONFIDENCE_FLOOR: float = 0.50
_LAYER2_ENABLED: bool = True
_DEFAULT_WRITEBACK_BATCH_K: int = 50


@dataclass(frozen=True)
class ClueCoverageIssue:
    """A high-confidence mismatch between a clue relation and generated Z3."""

    issue_type: str
    clue_relation: str
    generated_relation: str
    expected_constraint: str
    offending_constraint: str
    source_clue: str


def _find_clue_coverage_issues(
    puzzle_text: str,
    constraints: List[str],
) -> list[ClueCoverageIssue]:
    """Find relation/position constraints that contradict explicit clues."""

    issues: list[ClueCoverageIssue] = []
    expected_positions = _expected_direct_position_constraints(puzzle_text)
    expected_relations = _expected_relation_constraints(puzzle_text)
    covered_positions: set[str] = set()
    covered_relations: set[tuple[str, str, str]] = set()

    for constraint in constraints:
        parsed_position = _parse_direct_position_constraint(constraint)
        if parsed_position:
            key, house = parsed_position
            expected = expected_positions.get(key)
            if expected and house == _parse_direct_position_constraint(expected[0])[1]:
                covered_positions.add(key)
            elif expected:
                issues.append(ClueCoverageIssue(
                    issue_type="wrong_direct_position",
                    clue_relation="direct_position",
                    generated_relation="direct_position",
                    expected_constraint=expected[0],
                    offending_constraint=constraint,
                    source_clue=expected[1],
                ))
            continue

        parsed_relation = _parse_relation_constraint(constraint)
        if not parsed_relation:
            continue
        relation_kind, left_key, right_key = parsed_relation
        for expected in expected_relations:
            expected_kind, expected_left, expected_right, expected_constraint, source_clue = expected
            if not _same_relation_variables(
                relation_kind,
                left_key,
                right_key,
                expected_kind,
                expected_left,
                expected_right,
            ):
                continue
            if _relation_matches_expected(
                relation_kind,
                left_key,
                right_key,
                expected_kind,
                expected_left,
                expected_right,
            ):
                covered_relations.add((expected_kind, expected_left, expected_right))
            else:
                issues.append(ClueCoverageIssue(
                    issue_type="wrong_relation",
                    clue_relation=expected_kind,
                    generated_relation=relation_kind,
                    expected_constraint=expected_constraint,
                    offending_constraint=constraint,
                    source_clue=source_clue,
                ))
            break
    for key, (expected_constraint, source_clue) in expected_positions.items():
        if key in covered_positions:
            continue
        if any(issue.expected_constraint == expected_constraint for issue in issues):
            continue
        issues.append(ClueCoverageIssue(
            issue_type="missing_direct_position",
            clue_relation="direct_position",
            generated_relation="missing",
            expected_constraint=expected_constraint,
            offending_constraint="",
            source_clue=source_clue,
        ))
    for expected_kind, expected_left, expected_right, expected_constraint, source_clue in expected_relations:
        key = (expected_kind, expected_left, expected_right)
        if key in covered_relations:
            continue
        if any(issue.expected_constraint == expected_constraint for issue in issues):
            continue
        issues.append(ClueCoverageIssue(
            issue_type="missing_relation",
            clue_relation=expected_kind,
            generated_relation="missing",
            expected_constraint=expected_constraint,
            offending_constraint="",
            source_clue=source_clue,
        ))
    return issues


def _expected_direct_position_constraints(puzzle_text: str) -> dict[str, tuple[str, str]]:
    expected: dict[str, tuple[str, str]] = {}
    for line in _numbered_clue_lines(puzzle_text):
        parsed = _parse_direct_position_source_clue(line)
        if not parsed:
            continue
        key, house = parsed
        expected[key] = (f"Int('{key}') == {house}", line)
    return expected


def _expected_relation_constraints(
    puzzle_text: str,
) -> list[tuple[str, str, str, str, str]]:
    expected: list[tuple[str, str, str, str, str]] = []
    for line in _numbered_clue_lines(puzzle_text):
        parsed = _parse_relation_source_clue(line)
        if not parsed:
            continue
        relation_kind, left_key, right_key = parsed
        expected.append((
            relation_kind,
            left_key,
            right_key,
            _relation_constraint(relation_kind, left_key, right_key),
            line,
        ))
    return expected


def _replacement_policy_from_error_paradigm(
    paradigm,
    state: Optional[SolverState] = None,
) -> Optional[dict]:
    trigger = getattr(paradigm, "trigger", {}) or {}
    policy = trigger.get("replacement_policy")
    if isinstance(policy, dict):
        materialized = _materialize_replacement_policy(dict(policy), paradigm, state)
        return materialized
    target = trigger.get("target_constraint") or trigger.get("correct_constraint")
    if target:
        return {
            "target_constraint": str(target),
            "source_clue": str(trigger.get("source_clue", "")),
        }
    return None


def _materialize_replacement_policy(
    policy: dict,
    paradigm,
    state: Optional[SolverState],
) -> dict:
    if policy.get("target_constraint"):
        return policy
    kind = str(policy.get("kind") or "")
    if kind == "direct_position_from_source_clue":
        return _materialize_direct_position_policy(policy, paradigm, state)

    relation_kind = _relation_kind_from_policy_kind(kind)
    if relation_kind:
        return _materialize_relation_policy(policy, paradigm, state, relation_kind)

    return policy


def _materialize_direct_position_policy(
    policy: dict,
    paradigm,
    state: Optional[SolverState],
) -> dict:
    source_clue = str(policy.get("source_clue", ""))
    clue = _parse_direct_position_source_clue(source_clue)

    candidates = [getattr(paradigm, "bad_operation", "")]
    if state is not None:
        candidates.extend(state.unsat_core or [])
    for constraint in candidates:
        bad = _parse_direct_position_constraint(constraint)
        if not bad:
            continue
        local_clue = clue
        local_source_clue = source_clue
        if not local_clue and state is not None:
            found = _find_direct_position_clue_for_key(state.problem_nl, bad[0])
            if found:
                local_clue = (found[0], found[1])
                local_source_clue = found[2]
        if local_clue and local_clue[0] == bad[0]:
            materialized = dict(policy)
            materialized["source_clue"] = local_source_clue
            materialized["target_constraint"] = f"Int('{bad[0]}') == {local_clue[1]}"
            return materialized
    return policy


def _materialize_relation_policy(
    policy: dict,
    paradigm,
    state: Optional[SolverState],
    relation_kind: str,
) -> dict:
    source_clue = str(policy.get("source_clue", ""))
    clue = _parse_relation_source_clue(source_clue)
    bad_candidates = _relation_bad_candidates(paradigm, state, relation_kind)
    if not clue and state is not None:
        for bad_for_lookup in bad_candidates:
            found = _find_relation_clue_for_vars(
                state.problem_nl,
                relation_kind,
                bad_for_lookup[1],
                bad_for_lookup[2],
            )
            if found:
                clue = found[:3]
                source_clue = found[3]
                break
    if not clue or clue[0] != relation_kind:
        return policy

    _, left_key, right_key = clue
    clue_vars = {left_key, right_key}
    if any({bad[1], bad[2]} == clue_vars for bad in bad_candidates):
        materialized = dict(policy)
        materialized["source_clue"] = source_clue
        materialized["target_constraint"] = _relation_constraint(
            relation_kind,
            left_key,
            right_key,
        )
        return materialized
    return policy


def _relation_bad_candidates(
    paradigm,
    state: Optional[SolverState],
    target_relation_kind: str,
) -> list[tuple[str, str, str]]:
    opposite_candidates: list[tuple[str, str, str]] = []
    fallback_candidates: list[tuple[str, str, str]] = []
    if state is not None:
        for constraint in state.unsat_core or []:
            parsed = _parse_relation_constraint(constraint)
            if not parsed:
                continue
            if _is_wrong_direction_candidate(parsed, target_relation_kind):
                opposite_candidates.append(parsed)
            else:
                fallback_candidates.append(parsed)
    parsed_bad_operation = _parse_relation_constraint(getattr(paradigm, "bad_operation", ""))
    if parsed_bad_operation and not opposite_candidates and not fallback_candidates:
        fallback_candidates.append(parsed_bad_operation)
    return opposite_candidates or fallback_candidates


def _is_wrong_direction_candidate(
    parsed: tuple[str, str, str],
    target_relation_kind: str,
) -> bool:
    return parsed[0] == {
        "directly_left": "directly_right",
        "directly_right": "directly_left",
        "somewhere_left": "somewhere_right",
        "somewhere_right": "somewhere_left",
    }.get(target_relation_kind)


def _parse_direct_position_constraint(constraint: str) -> Optional[tuple[str, int]]:
    match = re.fullmatch(r"Int\('([^']+)'\)\s*==\s*(\d+)", (constraint or "").strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _parse_direct_position_source_clue(clue: str) -> Optional[tuple[str, int]]:
    match = re.search(
        r"The\s+(?P<value>[A-Za-z0-9][A-Za-z0-9 ]*?)\s+"
        r"(?P<category>[A-Za-z][A-Za-z0-9 ]*?)(?:\s+person)?\s+"
        r"lives\s+in\s+house\s+(?P<house>\d+)",
        clue or "",
        re.I,
    )
    if not match:
        return None
    category = re.sub(r"[^A-Za-z0-9]+", "_", match.group("category").strip()).strip("_")
    category = category[:1].lower() + category[1:]
    value_parts = [part for part in re.split(r"[^A-Za-z0-9]+", match.group("value").strip()) if part]
    value = "_".join(part[:1].upper() + part[1:] for part in value_parts)
    return f"{category}_{value}", int(match.group("house"))


def _find_direct_position_clue_for_key(
    puzzle_text: str,
    key: str,
) -> Optional[tuple[str, int, str]]:
    for line in _numbered_clue_lines(puzzle_text):
        parsed = _parse_direct_position_source_clue(line)
        if parsed and parsed[0] == key:
            return parsed[0], parsed[1], line
    return None


def _relation_kind_from_policy_kind(kind: str) -> Optional[str]:
    if not kind.endswith("_from_source_clue"):
        return None
    base = kind[: -len("_from_source_clue")]
    aliases = {
        "direct_left": "directly_left",
        "directly_left": "directly_left",
        "direct_right": "directly_right",
        "directly_right": "directly_right",
        "left_of": "somewhere_left",
        "somewhere_left": "somewhere_left",
        "right_of": "somewhere_right",
        "somewhere_right": "somewhere_right",
        "adjacent": "adjacent",
    }
    return aliases.get(base)


def _parse_relation_source_clue(clue: str) -> Optional[tuple[str, str, str]]:
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


def _find_relation_clue_for_vars(
    puzzle_text: str,
    relation_kind: str,
    first_key: str,
    second_key: str,
) -> Optional[tuple[str, str, str, str]]:
    wanted = {first_key, second_key}
    for line in _numbered_clue_lines(puzzle_text):
        parsed = _parse_relation_source_clue(line)
        if not parsed:
            continue
        if parsed[0] == relation_kind and {parsed[1], parsed[2]} == wanted:
            return parsed[0], parsed[1], parsed[2], line
    return None


def _numbered_clue_lines(puzzle_text: str) -> list[str]:
    return [
        line.strip()
        for line in (puzzle_text or "").splitlines()
        if re.match(r"^\s*\d+\.\s+", line.strip())
    ]


def _parse_relation_entity(entity: str) -> Optional[str]:
    text = re.sub(r"^\s*the\s+", "", entity or "", flags=re.I).strip()
    text = re.sub(r"\s+person\s*$", "", text, flags=re.I).strip()
    parts = [part for part in re.split(r"\s+", text) if part]
    if len(parts) < 2:
        return None
    category = re.sub(r"[^A-Za-z0-9]+", "_", parts[-1]).strip("_")
    if not category:
        return None
    category = category[:1].lower() + category[1:]
    value = "_".join(
        re.sub(r"[^A-Za-z0-9]+", "_", part[:1].upper() + part[1:]).strip("_")
        for part in parts[:-1]
    )
    value = value.strip("_")
    if not value:
        return None
    return f"{category}_{value}"


def _parse_relation_constraint(constraint: str) -> Optional[tuple[str, str, str]]:
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


def _same_relation_variables(
    relation_kind: str,
    left_key: str,
    right_key: str,
    expected_kind: str,
    expected_left: str,
    expected_right: str,
) -> bool:
    return {left_key, right_key} == {expected_left, expected_right}


def _relation_matches_expected(
    relation_kind: str,
    left_key: str,
    right_key: str,
    expected_kind: str,
    expected_left: str,
    expected_right: str,
) -> bool:
    if expected_kind == "adjacent":
        return (
            relation_kind == "adjacent"
            and {left_key, right_key} == {expected_left, expected_right}
        )
    if relation_kind == expected_kind and left_key == expected_left and right_key == expected_right:
        return True
    inverse_pairs = {
        ("directly_left", "directly_right"),
        ("directly_right", "directly_left"),
        ("somewhere_left", "somewhere_right"),
        ("somewhere_right", "somewhere_left"),
    }
    return (
        (relation_kind, expected_kind) in inverse_pairs
        and left_key == expected_right
        and right_key == expected_left
    )


def _relation_constraint(relation_kind: str, left_key: str, right_key: str) -> str:
    if relation_kind == "directly_left":
        return f"Int('{left_key}') == Int('{right_key}') - 1"
    if relation_kind == "directly_right":
        return f"Int('{left_key}') == Int('{right_key}') + 1"
    if relation_kind == "somewhere_left":
        return f"Int('{left_key}') < Int('{right_key}')"
    if relation_kind == "somewhere_right":
        return f"Int('{left_key}') > Int('{right_key}')"
    if relation_kind == "adjacent":
        return f"Abs(Int('{left_key}') - Int('{right_key}')) == 1"
    return ""

# Cost-aware Layer-2 activation policies. ``always`` matches the previous
# behaviour. ``complexity_gated`` activates Layer-2 only when the puzzle is
# large enough (heuristic on number of variables) or after a UNSAT has been
# observed in this puzzle. ``stagnation_only`` defers Layer-2 until stagnation
# is detected by the repair memory.
_LAYER2_POLICY_ALWAYS = "always"
_LAYER2_POLICY_COMPLEXITY_GATED = "complexity_gated"
_LAYER2_POLICY_STAGNATION_ONLY = "stagnation_only"
_DEFAULT_LAYER2_POLICY: str = _LAYER2_POLICY_COMPLEXITY_GATED
_LAYER2_COMPLEXITY_VAR_FLOOR: int = 25  # ~5x5 ZebraLogic; below this skip Layer-2


class GuidedSolver:
    """Paradigm-guided CSP solver with four-level repair memory escalation.

    Args:
        llm_client: Pre-configured LLM client.
        library: Paradigm library (SQLite-backed or in-memory).
        max_repair_rounds: Maximum repair iterations before declaring failure.
        paradigm_top_k: Number of candidates from Layer-1 retrieval.
        layer2_enabled: Whether Layer-2 LLM semantic matching is permitted at all
            (master switch; when False, Layer-2 is never run regardless of policy).
        layer2_policy: Cost-aware activation policy for Layer-2. One of
            ``"always"`` (run on every retrieval — legacy behaviour),
            ``"complexity_gated"`` (default; run only when the puzzle is at least
            5x5 in size *or* at least one UNSAT has occurred in this puzzle), or
            ``"stagnation_only"`` (run only after the repair memory has flagged
            stagnation). Lower-cost policies still receive Layer-1 top-1 hints,
            so guidance is never fully suppressed.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        library: ParadigmLibrary,
        max_repair_rounds: int = _DEFAULT_MAX_REPAIR_ROUNDS,
        paradigm_top_k: int = _DEFAULT_PARADIGM_TOP_K,
        paradigm_confidence_floor: float = _DEFAULT_PARADIGM_CONFIDENCE_FLOOR,
        layer2_enabled: bool = _LAYER2_ENABLED,
        layer2_policy: str = _DEFAULT_LAYER2_POLICY,
        enable_paradigm: bool = True,
        enable_memory: bool = True,
        candidate_pool: Optional[CandidatePool] = None,
        error_library: Optional[ErrorParadigmLibrary] = None,
        enable_writeback: bool = True,
        writeback_batch_K: int = _DEFAULT_WRITEBACK_BATCH_K,
        schema_hint_mode: str = "puzzle",
        translation_normalize: str = "none",
        # === SPARC π-gate config (SPARC/SBW work) — belongs to the newer
        # "Satisfiable but Wrong" selective-abstention work, not PRISM's
        # paradigm/repair-memory path. Gate implementation is the tail of this
        # class (see "SPARC π-gate BEGIN" below). ===
        sparc: bool = False,
        sparc_max_completions: int = 3,
        sparc_repair_budget: int = 2,
        sparc_blind_completion: bool = False,
        sparc_no_invariant: bool = False,
        sparc_va_mode: str = "whitelist",
    ) -> None:
        self._llm = llm_client
        self._library = library
        self._translator = NLToZ3Translator(
            llm_client,
            schema_hint_mode=schema_hint_mode,
            normalize_mode=translation_normalize,
        )
        self._extractor = FeatureExtractor()
        self._max_rounds = max_repair_rounds
        self._top_k = paradigm_top_k
        self._confidence_floor = paradigm_confidence_floor
        self._layer2 = layer2_enabled
        self._layer2_policy = layer2_policy
        # SPARC: structural-prior gate on answer acceptance (unique-solution
        # prior). See docs/paper_A_method_definition.md §4.
        self._sparc = sparc
        self._sparc_max_completions = sparc_max_completions
        self._sparc_repair_budget = sparc_repair_budget
        # Ablation switches (paper §experiments/ablation):
        # blind completion = detection without diff attribution (no model-diff
        # summary, no progress check); no invariant = conflict repair without
        # evidence protection or the no-weakening instruction.
        self._sparc_blind_completion = sparc_blind_completion
        self._sparc_no_invariant = sparc_no_invariant
        # V_A selection for the uniqueness probe: "whitelist" restricts the
        # blocking clause to answer variables derived from visible puzzle
        # inputs (never puzzle.solution), falling back to the legacy
        # all-non-tracked-integer approximation when no model variable
        # matches; "all_int" forces the legacy approximation.
        self._sparc_va_mode = sparc_va_mode
        self._enable_paradigm = enable_paradigm
        self._enable_memory = enable_memory
        self._enable_writeback = enable_writeback
        self._error_library = error_library
        # Staged write-back pool L†. Built lazily with a default verifier if
        # the caller does not inject one; callers that want to share a verifier
        # (e.g. for unified hyperparameters across offline + online) should
        # pass their own.
        if enable_writeback and candidate_pool is None:
            candidate_pool = CandidatePool(
                library=library,
                verifier=ParadigmVerifier(),
                batch_K=writeback_batch_K,
            )
        self._candidate_pool: Optional[CandidatePool] = candidate_pool if enable_writeback else None
        # Per-puzzle bookkeeping for cost-aware Layer-2 gating.
        self._unsat_seen_in_puzzle: bool = False
        self._memory_ref: Optional[RepairMemory] = None
        # Persisted thresholds for RepairMemory construction; populated by
        # ``from_config`` and otherwise initialised to the legacy defaults so
        # callers using the bare ``__init__`` see no behaviour change.
        self._memory_config: dict = {
            "stagnation_jaccard": 0.75,
            "loop_cosine": 0.90,
        }
        # Layer-2 complexity floor (overridable via from_config).
        self._layer2_complexity_floor: int = _LAYER2_COMPLEXITY_VAR_FLOOR
        self._schema_hint_mode = schema_hint_mode
        self._translation_normalize = translation_normalize

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_config(
        cls,
        llm_client: LLMClient,
        library: ParadigmLibrary,
        config: dict,
        *,
        candidate_pool: Optional[CandidatePool] = None,
        error_library: Optional[ErrorParadigmLibrary] = None,
    ) -> "GuidedSolver":
        """Construct a GuidedSolver with all thresholds read from a config dict.

        The expected structure mirrors ``config/default.yaml``: a top-level
        ``thresholds`` mapping containing at least the online-relevant keys.
        Unknown keys are ignored, missing keys fall back to module defaults
        so partial configs remain usable.

        Args:
            llm_client: LLM facade.
            library: Paradigm library (already initialised).
            config: Configuration dictionary (typically the result of
                ``yaml.safe_load(open('config/default.yaml'))``).
            candidate_pool: Optional pre-built pool; auto-built otherwise.

        Returns:
            Configured GuidedSolver instance.
        """
        t = (config or {}).get("thresholds", {}) or {}
        solver = cls(
            llm_client=llm_client,
            library=library,
            max_repair_rounds=int(t.get("max_repair_rounds", _DEFAULT_MAX_REPAIR_ROUNDS)),
            paradigm_top_k=int(t.get("paradigm_top_k", _DEFAULT_PARADIGM_TOP_K)),
            paradigm_confidence_floor=float(
                t.get("paradigm_confidence_floor", _DEFAULT_PARADIGM_CONFIDENCE_FLOOR)
            ),
            layer2_enabled=bool(t.get("layer2_enabled", _LAYER2_ENABLED)),
            layer2_policy=str(t.get("layer2_policy", _DEFAULT_LAYER2_POLICY)),
            enable_paradigm=bool(t.get("enable_paradigm", True)),
            enable_memory=bool(t.get("enable_memory", True)),
            candidate_pool=candidate_pool,
            error_library=error_library,
            enable_writeback=bool(t.get("enable_writeback", True)),
            writeback_batch_K=int(t.get("writeback_batch_K", _DEFAULT_WRITEBACK_BATCH_K)),
            schema_hint_mode=str(t.get("schema_hint_mode", "puzzle")),
            translation_normalize=str(t.get("translation_normalize", "none")),
        )
        # Persist RepairMemory thresholds for use at solve() entry, and the
        # Layer-2 complexity floor for the cost-aware gate.
        solver._memory_config = {
            "stagnation_jaccard": float(t.get("stagnation_jaccard", 0.75)),
            "loop_cosine": float(t.get("loop_cosine", 0.90)),
        }
        solver._layer2_complexity_floor = int(
            t.get("layer2_complexity_floor", _LAYER2_COMPLEXITY_VAR_FLOOR)
        )
        return solver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def solve(self, puzzle: PuzzleInstance) -> SolveResult:
        """Solve *puzzle* using the full PRISM pipeline.

        Args:
            puzzle: Puzzle instance with a populated ``nl_description``.

        Returns:
            :class:`~prism.core.types.SolveResult` with correctness,
            cost, and diagnostic fields populated.
        """
        self._llm.reset_call_count()
        memory = (
            RepairMemory(dict(self._memory_config))
            if self._enable_memory
            else None
        )
        solver = Z3SolverWrapper()
        steps: List[dict] = []
        initial_paradigm_hint, initial_paradigm_triggered = (
            self._build_initial_translation_paradigm_hint(puzzle)
            if self._enable_paradigm
            else ("", False)
        )
        paradigm_triggered = initial_paradigm_triggered
        error_guidance_triggered = False
        stagnation_detected = False
        # Reset per-puzzle Layer-2 gating bookkeeping.
        self._unsat_seen_in_puzzle = False
        self._memory_ref = memory

        # ── Step 0: initial translation ─────────────────────────────────
        try:
            constraints = self._translator.translate(
                puzzle,
                paradigm_hint=initial_paradigm_hint,
            )
        except TypeError:
            constraints = self._translator.translate(puzzle)
        translation_diagnostics = dict(getattr(self._translator, "last_diagnostics", {}) or {})
        if initial_paradigm_triggered:
            translation_diagnostics["initial_translation_paradigm_hint"] = initial_paradigm_hint
        if not constraints:
            steps.append({
                "iteration": 0,
                "action": "translate",
                "z3_result": "TRANSLATION_FAILED",
                "error": "no_valid_constraints",
                "paradigm_triggered": initial_paradigm_triggered,
                "positive_guidance_triggered": initial_paradigm_triggered,
                **translation_diagnostics,
            })
            self._maybe_flush_pool()
            return SolveResult(
                puzzle_id=puzzle.puzzle_id,
                solved=False,
                solution=None,
                total_llm_calls=self._llm.call_count,
                repair_rounds=0,
                steps=steps,
                final_z3_result="TRANSLATION_FAILED",
                paradigm_triggered=paradigm_triggered,
                stagnation_detected=False,
                error="translation produced no valid constraints",
            )
        for c in constraints:
            solver.add_constraint(c)

        result = solver.check()
        steps.append({
            "iteration": 0,
            "action": "translate",
            "z3_result": result,
            "constraints": list(constraints),
            "paradigm_triggered": initial_paradigm_triggered,
            "positive_guidance_triggered": initial_paradigm_triggered,
            **translation_diagnostics,
        })

        if result == "SAT":
            return self._finalize_sat_result(
                puzzle=puzzle,
                solver=solver,
                current_constraints=list(constraints),
                steps=steps,
                mark_last_step=True,
                paradigm_triggered=paradigm_triggered,
                stagnation_detected=stagnation_detected,
            )

        switcher = StrategySwitcher(memory) if memory is not None else None
        current_constraints = list(constraints)
        l4_used = False  # L4 full retranslation fires at most once per puzzle

        # ── Repair loop ────────────────────────────────────────────────
        for iteration in range(1, self._max_rounds + 1):
            unsat_core = solver.get_unsat_core() if result == "UNSAT" else []
            if result == "UNSAT":
                self._unsat_seen_in_puzzle = True
            state = self._build_state(puzzle, current_constraints, unsat_core, result, iteration)
            state = state.model_copy(update={"constraint_types": self._extractor.extract(state)})

            # Try paradigm guidance
            paradigm_hint, par_triggered = (
                self._build_paradigm_hint(state, solver)
                if self._enable_paradigm
                else ("", False)
            )
            paradigm_triggered = paradigm_triggered or par_triggered
            error_hint, error_paradigms = self._build_error_guidance(state)
            error_triggered = bool(error_hint)
            error_guidance_triggered = error_guidance_triggered or error_triggered
            if error_hint:
                paradigm_hint = "\n\n".join(part for part in [paradigm_hint, error_hint] if part)

            # Strategy switcher
            switch_level = switcher.should_switch() if switcher is not None else None
            switch_prompt = ""
            if switch_level is not None:
                stagnation_detected = True
                switch_prompt = switcher.get_switch_prompt(switch_level, {
                    "unsat_core": unsat_core,
                    "problem_nl": puzzle.nl_description,
                })
                if switch_level.value == "L4_FULL_RETRANSLATE":
                    if l4_used:
                        # A second L4 condition is suppressed: stop repairing
                        # and mark the puzzle unsolved (bounds the per-puzzle
                        # LLM-call budget at translate + R repairs + one L4).
                        steps.append({
                            "iteration": iteration,
                            "action": "l4_suppressed",
                            "z3_result": result,
                            "stagnated": True,
                        })
                        break
                    l4_used = True
                    current_constraints = self._translator.retranslate(
                        puzzle, current_constraints, "\n".join(unsat_core)
                    )
                    solver = self._rebuild_solver(current_constraints)
                    result = solver.check()
                    steps.append({
                        "iteration": iteration,
                        "action": "retranslate",
                        "z3_result": result,
                        "constraints": list(current_constraints),
                        "paradigm_triggered": par_triggered,
                        "positive_guidance_triggered": par_triggered,
                        "error_guidance_triggered": error_triggered,
                        "stagnated": True,
                    })
                    if result == "SAT":
                        break
                    continue
                if switch_level.value == "L3_REVERT_CHECKPOINT":
                    # Pop (not peek): successive L3 escalations revert to
                    # progressively older checkpoints; once the stack is
                    # depleted the L4 fallback in should_switch() takes over.
                    ckpt = switcher.pop_checkpoint()
                    if ckpt and "constraints" in ckpt:
                        current_constraints = list(ckpt["constraints"])
                        solver = self._rebuild_solver(current_constraints)
                        result = solver.check()

            # Repair via LLM
            history_summary = (
                memory.get_history_summary()
                if memory is not None
                else "No repair memory is enabled for this run."
            )
            repair_response = self._llm.repair(
                constraints=current_constraints,
                unsat_core=unsat_core,
                history_summary=history_summary,
                paradigm_hint=paradigm_hint,
                switch_prompt=switch_prompt,
            )
            repair_str = self._translator.parse_repair_response(repair_response)
            constraints_before_repair = list(current_constraints)
            valid_repair, rejection_reason = self._validate_repair_output(
                repair_str,
                unsat_core,
                current_constraints,
                self._target_constraints_from_error_paradigms(error_paradigms),
            )
            if not valid_repair:
                if memory is not None:
                    memory.append(RepairRecord(
                        iteration=iteration,
                        error_type=ErrorType.SYNTAX,
                        unsat_core=unsat_core,
                        core_fingerprint="",
                        repair_action=RepairAction(
                            type="rejected_repair",
                            target_constraint="",
                            summary=repair_str or repair_response or "",
                        ),
                        outcome=Outcome.UNSAT,
                        new_core=unsat_core,
                    ))
                steps.append(self._build_rejected_repair_step(
                    iteration=iteration,
                    result=result,
                    par_triggered=par_triggered,
                    error_triggered=error_triggered,
                    stagnated=stagnation_detected,
                    state=state,
                    unsat_core=unsat_core,
                    constraints_before=constraints_before_repair,
                    repair_response=repair_response,
                    repair_str=repair_str,
                    rejection_reason=rejection_reason,
                    error_hint=error_hint,
                    error_paradigms=error_paradigms,
                ))
                continue

            # ── Loop detection (BEFORE applying the repair) ────────────
            # Mirror what _apply_repair would record (dry-run target
            # selection) so the structured triple (type, target, parameters)
            # is populated and the primary loop signal can actually fire;
            # the embedding fallback then only covers paraphrases of
            # different targets.
            provisional_idx = (
                self._select_repair_target_index(
                    current_constraints, unsat_core, repair_str
                )
                if repair_str
                else None
            )
            provisional_target = (
                current_constraints[provisional_idx]
                if provisional_idx is not None
                else ""
            )
            provisional_action = RepairAction(
                type="modify_constraint" if provisional_target else "add_constraint",
                target_constraint=provisional_target,
                parameter_signature=self._parameter_signature(repair_str),
                summary=repair_str or "",
            )
            if (
                memory is not None
                and switch_level is None
                and memory.detect_loop(provisional_action)
            ):
                logger.debug(
                    "Loop detected at iteration %d — skipping repair, forcing L2 switch.",
                    iteration,
                )
                stagnation_detected = True
                if switcher is not None:
                    switcher.save_checkpoint({
                        "iteration": iteration,
                        "constraints": list(current_constraints),
                        "summary": f"loop-detection checkpoint at iteration {iteration}",
                    })
                    switcher.force_switch()
                # Skip this repair; next iteration will execute the strategy switch.
                steps.append({
                    "iteration": iteration,
                    "action": "loop_skipped",
                    "z3_result": result,
                    "paradigm_triggered": par_triggered,
                    "positive_guidance_triggered": par_triggered,
                    "error_guidance_triggered": error_triggered,
                    "stagnated": True,
                })
                continue

            # ── Apply repair ───────────────────────────────────────────
            old_constraint, new_constraint = self._apply_repair(
                current_constraints, unsat_core, repair_str
            )

            action = RepairAction(
                type=self._infer_repair_type(old_constraint, new_constraint),
                target_constraint=old_constraint or "",
                parameter_signature=self._parameter_signature(repair_str),
                summary=repair_str or "",
            )

            solver = self._rebuild_solver(current_constraints)
            result = solver.check()
            new_core = solver.get_unsat_core() if result == "UNSAT" else None

            # ── UNSAT Attribution ──────────────────────────────────────
            # Classify error type based on whether the new repair is itself
            # in the resulting UNSAT core (NEW_ASSERTION) or not (LEGACY_ERROR).
            error_type = self._classify_error_type(
                new_constraint,
                new_core,
                declared_vars=set(solver.get_variables()),
            )

            record = RepairRecord(
                iteration=iteration,
                error_type=error_type,
                unsat_core=unsat_core,
                core_fingerprint="",
                repair_action=action,
                outcome=Outcome.SAT if result == "SAT" else Outcome.UNSAT,
                new_core=new_core,
            )
            if memory is not None:
                memory.append(record)

            step_info = {
                "iteration": iteration,
                "action": "repair",
                "z3_result": result,
                "paradigm_triggered": par_triggered,
                "positive_guidance_triggered": par_triggered,
                "error_guidance_triggered": error_triggered,
                "stagnated": stagnation_detected,
                "constraint_types": state.constraint_types,
                "unsat_core": unsat_core,
                "constraints_before": constraints_before_repair,
                "repair_response": repair_response,
                "repair_expression": repair_str,
                "old_constraint": old_constraint,
                "new_constraint": new_constraint,
                "new_unsat_core": new_core,
                "error_guidance": error_hint,
                "error_paradigms": error_paradigms,
            }
            steps.append(step_info)

            if result == "SAT":
                if self._validate_solver_model(puzzle, solver).ok and self._enable_paradigm:
                    self._writeback_confidence(record, state)
                    self._maybe_stage_candidate(state, current_constraints, new_constraint)
                if switcher is not None:
                    switcher.save_checkpoint({
                        "iteration": iteration,
                        "constraints": list(current_constraints),
                        "summary": f"SAT checkpoint at iteration {iteration}",
                    })
                break

        if result == "SAT":
            return self._finalize_sat_result(
                puzzle=puzzle,
                solver=solver,
                current_constraints=current_constraints,
                steps=steps,
                mark_last_step=False,
                paradigm_triggered=paradigm_triggered,
                stagnation_detected=stagnation_detected,
            )

        self._maybe_flush_pool()
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=False,
            total_llm_calls=self._llm.call_count,
            repair_rounds=len(steps) - 1,
            steps=steps,
            final_z3_result=result,
            paradigm_triggered=paradigm_triggered,
            stagnation_detected=stagnation_detected,
        )

    # ------------------------------------------------------------------
    # Paradigm guidance
    # ------------------------------------------------------------------

    def _build_initial_translation_paradigm_hint(
        self,
        puzzle: PuzzleInstance,
    ) -> tuple[str, bool]:
        """Return conservative positive guidance for the initial translation."""

        type_bag = [
            relation_kind
            for relation_kind, *_ in _expected_relation_constraints(puzzle.nl_description)
        ]
        positions = _expected_direct_position_constraints(puzzle.nl_description)
        type_bag.extend(["direct_position"] * len(positions))
        query_types = sorted(set(type_bag))
        if not query_types:
            return "", False

        try:
            candidates = self._library.retrieve(
                query_types,
                top_k=self._top_k,
                type_bag=type_bag,
                min_confidence=self._confidence_floor,
            )
        except TypeError:
            candidates = self._library.retrieve(query_types, top_k=self._top_k)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Initial paradigm retrieval failed: %s", exc)
            return "", False
        if not candidates:
            return "", False

        allowed = set(query_types)
        lines: list[str] = []
        seen: set[str] = set()
        for paradigm in candidates:
            tag, template = self._translation_template_from_positive_paradigm(paradigm)
            if not template or tag not in allowed or template in seen:
                continue
            name = getattr(paradigm, "name", "positive_paradigm")
            lines.append(f"- [{name}] {template}")
            seen.add(template)
            if len(lines) >= self._top_k:
                break
        if not lines:
            return "", False
        return "\n".join(lines), True

    @staticmethod
    def _translation_template_from_positive_paradigm(paradigm) -> tuple[str, str]:
        operation = str(getattr(paradigm, "operation", "") or "").strip()
        direct = _parse_direct_position_constraint(operation)
        if direct:
            return "direct_position", "direct position clue: Int('A') == house_number"

        relation = _parse_relation_constraint(operation)
        if not relation:
            same_house = re.fullmatch(
                r"Int\('([^']+)'\)\s*==\s*Int\('([^']+)'\)",
                operation,
            )
            if same_house:
                return "same_house", "same-house clue: Int('A') == Int('B')"
            different = re.fullmatch(
                r"Int\('([^']+)'\)\s*!=\s*Int\('([^']+)'\)",
                operation,
            )
            if different:
                return "different", "different-items clue: Int('A') != Int('B')"
            return "", ""

        relation_kind = relation[0]
        templates = {
            "directly_left": "directly-left clue: Int('A') == Int('B') - 1",
            "directly_right": "directly-right clue: Int('A') == Int('B') + 1",
            "somewhere_left": "somewhere-left clue: Int('A') < Int('B')",
            "somewhere_right": "somewhere-right clue: Int('A') > Int('B')",
            "adjacent": "next-to clue: Abs(Int('A') - Int('B')) == 1",
        }
        return relation_kind, templates.get(relation_kind, "")

    def _should_run_layer2(self, state: SolverState, candidates: list) -> bool:
        """Decide whether to invoke Layer-2 LLM semantic matching for this step.

        Layer-2 incurs one extra LLM call per invocation; gating it preserves
        most of the accuracy benefit while reducing the amortised cost.

        Activation rules (in order):

        - The ``layer2_policy`` setting overrides the default behaviour.
        - ``always`` — run whenever Layer-1 returned ≥ 2 candidates.
        - ``stagnation_only`` — run only if the repair memory has flagged
          stagnation in the current puzzle.
        - ``complexity_gated`` (default) — run when the puzzle is at least
          ``_LAYER2_COMPLEXITY_VAR_FLOOR`` constraints in size, or when at
          least one UNSAT has been observed in the current puzzle.

        When Layer-1 produced only one candidate, Layer-2 cannot disambiguate
        further and is skipped regardless of policy.
        """
        if len(candidates) < 2:
            return False
        policy = (self._layer2_policy or _DEFAULT_LAYER2_POLICY).strip().lower()
        if policy == _LAYER2_POLICY_ALWAYS:
            return True
        if policy == _LAYER2_POLICY_STAGNATION_ONLY:
            return bool(
                self._memory_ref is not None
                and self._memory_ref.detect_stagnation()
            )
        # complexity_gated (default)
        num_constraints = len(state.constraints or [])
        return (
            num_constraints >= self._layer2_complexity_floor
            or self._unsat_seen_in_puzzle
        )

    def _build_paradigm_hint(
        self, state: SolverState, solver: Z3SolverWrapper
    ) -> tuple[str, bool]:
        """Layer-1 + optional Layer-2 + consistency pre-check.

        The Layer-1 call passes a multiplicity-preserving ``type_bag`` so that
        relational predicates declared on paradigm triggers (e.g.
        ``count_atleast``, ``cooccur``) can actually be evaluated. Without the
        bag, the retriever falls back to set-membership only and the
        predicates soft-pass on every paradigm.

        Returns:
            (paradigm_hint_string, triggered_bool)
        """
        type_bag = self._extractor.extract_bag(state)
        candidates = self._library.retrieve(
            state.constraint_types,
            top_k=self._top_k,
            type_bag=type_bag,
            min_confidence=self._confidence_floor,
        )
        if not candidates:
            return "", False

        # Cost-aware Layer-2 activation. Layer-2 runs an extra LLM call per
        # invocation, so we gate it by policy. When skipped, we still return
        # the Layer-1 top-1 candidate (further filtered by Z3 consistency
        # pre-check below) — guidance is never fully suppressed.
        if self._layer2 and self._should_run_layer2(state, candidates):
            state_summary = self._translator.build_state_summary(
                state.problem_nl, state.constraints, state.unsat_core or []
            )
            candidates = [
                p for p in candidates
                if self._llm.judge_semantic_match(p.operation, state_summary)
            ]
        elif len(candidates) > 1:
            # Cheap fallback when Layer-2 is gated off: keep only the top-1
            # Layer-1 candidate to avoid injecting multiple unverified hints.
            candidates = candidates[:1]

        if not candidates:
            return "", False

        # Consistency pre-check: Z3-SAT(C_t ∪ {op(P)}) — the paradigm's
        # operation must be compatible with the *current puzzle state*, not
        # merely self-consistent with its own pre-condition. During repair
        # the raw C_t is itself UNSAT, which would vacuously reject every
        # paradigm, so the UNSAT-core constraints are excluded and the check
        # runs against the consistent remainder. Constraints that fail to
        # parse are skipped best-effort.
        conflicting = set(state.unsat_core or [])
        context_constraints = [
            c for c in state.constraints if c not in conflicting
        ]
        valid_candidates = []
        for paradigm in candidates:
            trial_solver = Z3SolverWrapper()
            for current_constraint in context_constraints:
                trial_solver.add_constraint(current_constraint)
            if paradigm.pre_condition.strip():
                if not trial_solver.add_constraint(paradigm.pre_condition):
                    continue
            if not trial_solver.add_constraint(paradigm.operation):
                continue
            if trial_solver.check() == "SAT":
                valid_candidates.append(paradigm)

        if not valid_candidates:
            return "", True

        best = valid_candidates[0]
        hint = (
            f"以下范式已在类似情境中验证有效（供参考）：\n"
            f"[{best.name}] {best.operation}"
        )
        return hint, True

    def _build_error_hint(self, state: SolverState) -> str:
        """Return negative guidance from matching error paradigms, if any."""
        hint, _ = self._build_error_guidance(state)
        return hint

    def _build_error_guidance(self, state: SolverState) -> tuple[str, list[dict]]:
        """Return negative guidance text plus traceable matched paradigms."""
        if self._error_library is None:
            return "", []
        try:
            candidates = self._error_library.retrieve(
                state.constraint_types,
                unsat_core=state.unsat_core or [],
                puzzle_id=state.puzzle_id,
                top_k=2,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error paradigm retrieval failed: %s", exc)
            return "", []
        if not candidates:
            return "", []

        lines = ["Avoid these verified UNSAT-producing patterns:"]
        trace = []
        for paradigm in candidates:
            replacement = _replacement_policy_from_error_paradigm(paradigm, state)
            if self._requires_materialized_replacement(paradigm) and not (
                replacement and replacement.get("target_constraint")
            ):
                continue
            lines.append(
                f"- [{paradigm.name}] bad_operation={paradigm.bad_operation}; "
                f"avoid={paradigm.avoid_instruction}; repair_hint={paradigm.repair_hint}"
            )
            if replacement:
                lines.append(
                    "  replacement_policy="
                    f"target={replacement.get('target_constraint', '')}; "
                    f"source_clue={replacement.get('source_clue', '')}; "
                    "return this target exactly when it matches the current UNSAT core."
                )
            trace.append({
                "id": paradigm.id,
                "name": paradigm.name,
                "scope": list(paradigm.scope),
                "bad_operation": paradigm.bad_operation,
                "avoid_instruction": paradigm.avoid_instruction,
                "repair_hint": paradigm.repair_hint,
                "replacement_policy": replacement,
                "confidence": paradigm.confidence,
                "support_count": paradigm.support_count,
            })
        if not trace:
            return "", []
        return "\n".join(lines), trace

    @staticmethod
    def _requires_materialized_replacement(paradigm) -> bool:
        policy = (getattr(paradigm, "trigger", {}) or {}).get("replacement_policy")
        if isinstance(policy, dict) and str(policy.get("kind") or "").endswith("_from_source_clue"):
            return True
        return bool(_parse_relation_constraint(getattr(paradigm, "bad_operation", "")))

    def _recover_invalid_model(
        self,
        puzzle: PuzzleInstance,
        current_constraints: List[str],
        steps: List[dict],
        iteration: int,
    ) -> Optional[tuple[Z3SolverWrapper, str, List[str]]]:
        """Try one full retranslation when SAT produced an invalid model."""
        error_ctx = (
            "The previous formalization was SAT, but its model assigned at least "
            "one integer variable outside the puzzle house range. Re-translate "
            "from scratch and include complete domain bounds plus uniqueness "
            "constraints for every attribute category."
        )
        fresh_constraints = self._translator.retranslate(
            puzzle,
            current_constraints,
            error_ctx,
        )
        translation_diagnostics = dict(getattr(self._translator, "last_diagnostics", {}) or {})
        if not fresh_constraints:
            steps.append({
                "iteration": iteration,
                "action": "invalid_model_retranslate",
                "z3_result": "TRANSLATION_FAILED",
                "error_type": "MODEL_OUT_OF_DOMAIN",
                "constraints": [],
                **translation_diagnostics,
            })
            return None

        solver = self._rebuild_solver(fresh_constraints)
        result = solver.check()
        validation = None
        if result == "SAT":
            validation = self._validate_solver_model(puzzle, solver)
            result = validation.final_z3_result
        steps.append({
            "iteration": iteration,
            "action": "invalid_model_retranslate",
            "z3_result": result,
            "error_type": validation.error_type if validation and not validation.ok else "MODEL_OUT_OF_DOMAIN",
            "model_domain_valid": validation.domain_valid if validation else None,
            "model_schema_aligned": validation.schema_aligned if validation else None,
            "model_key_set_aligned": validation.key_set_aligned if validation else None,
            "constraints": list(fresh_constraints),
            **translation_diagnostics,
        })
        return solver, result, fresh_constraints

    def _recover_misaligned_model(
        self,
        puzzle: PuzzleInstance,
        current_constraints: List[str],
        steps: List[dict],
        iteration: int,
    ) -> Optional[tuple[Z3SolverWrapper, str, List[str]]]:
        """Try one full retranslation when SAT used the wrong output schema."""
        key_hint = puzzle_schema_key_hint(puzzle)
        expected_section = (
            f" Expected solution variable keys include: {key_hint}."
            if key_hint
            else ""
        )
        error_ctx = (
            "The previous formalization was SAT and all integer assignments were "
            "inside the house range, but the model variable names did not match "
            "the benchmark answer schema. Do not create house-indexed slot "
            "variables such as house1_color. Represent each attribute value as "
            "one integer house position variable named exactly like the semantic "
            "attribute/value key, for example color_Blue, drink_Wine, job_Artist."
            f"{expected_section} Re-translate from scratch using those semantic "
            "variables, with complete domain bounds and Distinct constraints."
        )
        fresh_constraints = self._translator.retranslate(
            puzzle,
            current_constraints,
            error_ctx,
        )
        translation_diagnostics = dict(getattr(self._translator, "last_diagnostics", {}) or {})
        if not fresh_constraints:
            steps.append({
                "iteration": iteration,
                "action": "misaligned_model_retranslate",
                "z3_result": "TRANSLATION_FAILED",
                "error_type": "MODEL_SCHEMA_MISMATCH",
                "constraints": [],
                **translation_diagnostics,
            })
            return None

        solver = self._rebuild_solver(fresh_constraints)
        result = solver.check()
        validation = None
        if result == "SAT":
            validation = self._validate_solver_model(puzzle, solver)
            result = validation.final_z3_result
        steps.append({
            "iteration": iteration,
            "action": "misaligned_model_retranslate",
            "z3_result": result,
            "error_type": validation.error_type if validation and not validation.ok else "MODEL_SCHEMA_MISMATCH",
            "model_domain_valid": validation.domain_valid if validation else None,
            "model_schema_aligned": validation.schema_aligned if validation else None,
            "model_key_set_aligned": validation.key_set_aligned if validation else None,
            "constraints": list(fresh_constraints),
            **translation_diagnostics,
        })
        return solver, result, fresh_constraints

    def _repair_recovered_unsat(
        self,
        *,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
        current_constraints: List[str],
        steps: List[dict],
        paradigm_triggered: bool,
        stagnation_detected: bool,
    ) -> Optional[SolveResult]:
        """Run repair loop after validation retranslation yields UNSAT.

        Validation recovery is a full retranslation, but the resulting formula
        can still be contradictory. Treat that state like a normal repair-loop
        state so negative/error memory has a chance to guide the next step.
        """
        result = "UNSAT"
        memory = self._memory_ref if self._enable_memory else None
        switcher = StrategySwitcher(memory) if memory is not None else None
        local_paradigm_triggered = paradigm_triggered
        local_stagnation_detected = stagnation_detected

        for _ in range(self._remaining_repair_budget(steps)):
            iteration = len(steps)
            unsat_core = solver.get_unsat_core()
            self._unsat_seen_in_puzzle = True
            state = self._build_state(
                puzzle,
                current_constraints,
                unsat_core,
                result,
                iteration,
            )
            state = state.model_copy(update={"constraint_types": self._extractor.extract(state)})

            paradigm_hint, par_triggered = (
                self._build_paradigm_hint(state, solver)
                if self._enable_paradigm
                else ("", False)
            )
            local_paradigm_triggered = local_paradigm_triggered or par_triggered
            error_hint, error_paradigms = self._build_error_guidance(state)
            error_triggered = bool(error_hint)
            if error_hint:
                paradigm_hint = "\n\n".join(
                    part for part in [paradigm_hint, error_hint] if part
                )

            switch_level = switcher.should_switch() if switcher is not None else None
            switch_prompt = ""
            if switch_level is not None:
                local_stagnation_detected = True
                switch_prompt = switcher.get_switch_prompt(switch_level, {
                    "unsat_core": unsat_core,
                    "problem_nl": puzzle.nl_description,
                })

            history_summary = (
                memory.get_history_summary()
                if memory is not None
                else "No repair memory is enabled for this run."
            )
            repair_response = self._llm.repair(
                constraints=current_constraints,
                unsat_core=unsat_core,
                history_summary=history_summary,
                paradigm_hint=paradigm_hint,
                switch_prompt=switch_prompt,
            )
            repair_str = self._translator.parse_repair_response(repair_response)
            constraints_before_repair = list(current_constraints)
            valid_repair, rejection_reason = self._validate_repair_output(
                repair_str,
                unsat_core,
                current_constraints,
                self._target_constraints_from_error_paradigms(error_paradigms),
            )
            if not valid_repair:
                if memory is not None:
                    memory.append(RepairRecord(
                        iteration=iteration,
                        error_type=ErrorType.SYNTAX,
                        unsat_core=unsat_core,
                        core_fingerprint="",
                        repair_action=RepairAction(
                            type="rejected_repair",
                            target_constraint="",
                            summary=repair_str or repair_response or "",
                        ),
                        outcome=Outcome.UNSAT,
                        new_core=unsat_core,
                    ))
                steps.append(self._build_rejected_repair_step(
                    iteration=iteration,
                    result=result,
                    par_triggered=par_triggered,
                    error_triggered=error_triggered,
                    stagnated=local_stagnation_detected,
                    state=state,
                    unsat_core=unsat_core,
                    constraints_before=constraints_before_repair,
                    repair_response=repair_response,
                    repair_str=repair_str,
                    rejection_reason=rejection_reason,
                    error_hint=error_hint,
                    error_paradigms=error_paradigms,
                    source="validation_recovery",
                ))
                continue
            old_constraint, new_constraint = self._apply_repair(
                current_constraints,
                unsat_core,
                repair_str,
            )
            action = RepairAction(
                type=self._infer_repair_type(old_constraint, new_constraint),
                target_constraint=old_constraint or "",
                parameter_signature=self._parameter_signature(repair_str),
                summary=repair_str or "",
            )
            solver = self._rebuild_solver(current_constraints)
            result = solver.check()
            new_core = solver.get_unsat_core() if result == "UNSAT" else None
            record = RepairRecord(
                iteration=iteration,
                error_type=self._classify_error_type(
                    new_constraint,
                    new_core,
                    declared_vars=set(solver.get_variables()),
                ),
                unsat_core=unsat_core,
                core_fingerprint="",
                repair_action=action,
                outcome=Outcome.SAT if result == "SAT" else Outcome.UNSAT,
                new_core=new_core,
            )
            if memory is not None:
                memory.append(record)
            steps.append({
                "iteration": iteration,
                "action": "repair",
                "z3_result": result,
                "paradigm_triggered": par_triggered,
                "positive_guidance_triggered": par_triggered,
                "error_guidance_triggered": error_triggered,
                "stagnated": local_stagnation_detected,
                "source": "validation_recovery",
                "constraint_types": state.constraint_types,
                "unsat_core": unsat_core,
                "constraints_before": constraints_before_repair,
                "repair_response": repair_response,
                "repair_expression": repair_str,
                "old_constraint": old_constraint,
                "new_constraint": new_constraint,
                "new_unsat_core": new_core,
                "error_guidance": error_hint,
                "error_paradigms": error_paradigms,
            })

            if result == "SAT":
                return self._finalize_sat_result(
                    puzzle=puzzle,
                    solver=solver,
                    current_constraints=current_constraints,
                    steps=steps,
                    mark_last_step=False,
                    paradigm_triggered=local_paradigm_triggered,
                    stagnation_detected=local_stagnation_detected,
                )

        if result == "UNSAT":
            self._maybe_flush_pool()
            return SolveResult(
                puzzle_id=puzzle.puzzle_id,
                solved=False,
                total_llm_calls=self._llm.call_count,
                repair_rounds=max(0, len(steps) - 1),
                steps=steps,
                final_z3_result=result,
                paradigm_triggered=local_paradigm_triggered,
                stagnation_detected=local_stagnation_detected,
            )
        return None

    def _remaining_repair_budget(self, steps: List[dict]) -> int:
        return max(0, self._max_rounds - max(0, len(steps) - 1))

    @staticmethod
    def _validate_repair_output(
        repair_str: Optional[str],
        unsat_core: List[str],
        constraints: List[str],
        target_constraints: Optional[List[str]] = None,
    ) -> tuple[bool, str]:
        if not repair_str:
            return False, "empty_repair"
        materialized_targets = [
            target for target in target_constraints or []
            if target
        ]
        target_matched = bool(materialized_targets) and GuidedSolver._matches_any_target(
            repair_str,
            materialized_targets,
        )
        if any(repair_str == constraint for constraint in unsat_core) and not target_matched:
            return False, "no_op_repair"
        if GuidedSolver._is_shrinking_distinct_repair(repair_str, unsat_core):
            return False, "schema_shrinking_distinct"
        if materialized_targets and not target_matched:
            if GuidedSolver._is_weak_repair_for_any_target(
                repair_str,
                materialized_targets,
            ):
                return False, "weak_repair"
            return False, "target_mismatch"
        repair_vars = GuidedSolver._constraint_vars(repair_str)
        non_schema_core = [
            constraint for constraint in unsat_core
            if not GuidedSolver._is_schema_constraint(constraint)
        ]
        if non_schema_core:
            if not repair_vars:
                return False, "repair_has_no_variables"
            overlap = set()
            for constraint in non_schema_core:
                overlap.update(repair_vars & GuidedSolver._constraint_vars(constraint))
            if not overlap:
                return False, "low_variable_overlap"
        elif GuidedSolver._is_schema_constraint(repair_str):
            matching_schema = [
                constraint for constraint in unsat_core
                if GuidedSolver._schema_constraint_kind(constraint)
                == GuidedSolver._schema_constraint_kind(repair_str)
                and GuidedSolver._constraint_vars(constraint) == repair_vars
            ]
            if not matching_schema:
                return False, "schema_repair_without_matching_schema_core"
        return True, ""

    @staticmethod
    def _target_constraints_from_error_paradigms(error_paradigms: list[dict]) -> List[str]:
        targets: list[str] = []
        for item in error_paradigms or []:
            policy = item.get("replacement_policy") if isinstance(item, dict) else None
            if not isinstance(policy, dict):
                continue
            target = str(policy.get("target_constraint") or "").strip()
            if target:
                targets.append(target)
        return targets

    @staticmethod
    def _matches_any_target(repair_str: str, targets: List[str]) -> bool:
        return any(
            GuidedSolver._constraints_equivalent(repair_str, target)
            for target in targets
        )

    @staticmethod
    def _constraints_equivalent(left: str, right: str) -> bool:
        if GuidedSolver._canonical_constraint(left) == GuidedSolver._canonical_constraint(right):
            return True
        try:
            import z3  # noqa: PLC0415
            from prism.core.solver import _Z3_NS  # type: ignore  # noqa: PLC0415

            left_expr = eval(left, _Z3_NS)  # noqa: S307
            right_expr = eval(right, _Z3_NS)  # noqa: S307
            solver = z3.Solver()
            solver.add(left_expr != right_expr)
            return solver.check() == z3.unsat
        except Exception:
            return False

    @staticmethod
    def _canonical_constraint(constraint: str) -> str:
        return re.sub(r"\s+", "", constraint or "")

    @staticmethod
    def _is_weak_repair_for_any_target(repair_str: str, targets: List[str]) -> bool:
        for target in targets:
            if GuidedSolver._is_weak_direct_position_repair(repair_str, target):
                return True
            if GuidedSolver._is_weak_relation_repair(repair_str, target):
                return True
        return False

    @staticmethod
    def _is_weak_direct_position_repair(repair_str: str, target: str) -> bool:
        target_match = re.fullmatch(
            r"Int\('([^']+)'\)\s*==\s*(-?\d+)",
            (target or "").strip(),
        )
        repair_match = re.fullmatch(
            r"Int\('([^']+)'\)\s*!=\s*(-?\d+)",
            (repair_str or "").strip(),
        )
        return bool(
            target_match
            and repair_match
            and target_match.group(1) == repair_match.group(1)
            and target_match.group(2) != repair_match.group(2)
        )

    @staticmethod
    def _is_weak_relation_repair(repair_str: str, target: str) -> bool:
        target_relation = _parse_relation_constraint(target)
        repair_relation = _parse_relation_constraint(repair_str)
        if not target_relation:
            return False
        target_kind, target_left, target_right = target_relation
        if target_kind.startswith("directly_") and re.fullmatch(
            rf"Abs\(Int\('{re.escape(target_left)}'\)\s*-\s*Int\('{re.escape(target_right)}'\)\)\s*==\s*1",
            (repair_str or "").strip(),
        ):
            return True
        if not repair_relation:
            return False
        repair_kind, repair_left, repair_right = repair_relation
        return (
            target_kind in {"somewhere_left", "somewhere_right"}
            and repair_kind.startswith("directly_")
            and {target_left, target_right} == {repair_left, repair_right}
        )

    @staticmethod
    def _is_shrinking_distinct_repair(repair_str: str, unsat_core: List[str]) -> bool:
        if "Distinct(" not in (repair_str or ""):
            return False
        repair_vars = GuidedSolver._constraint_vars(repair_str)
        for constraint in unsat_core:
            if "Distinct(" not in constraint:
                continue
            core_vars = GuidedSolver._constraint_vars(constraint)
            if repair_vars < core_vars:
                return True
        return False

    @staticmethod
    def _build_rejected_repair_step(
        *,
        iteration: int,
        result: str,
        par_triggered: bool,
        error_triggered: bool,
        stagnated: bool,
        state: SolverState,
        unsat_core: List[str],
        constraints_before: List[str],
        repair_response: str,
        repair_str: Optional[str],
        rejection_reason: str,
        error_hint: str,
        error_paradigms: list[dict],
        source: Optional[str] = None,
    ) -> dict:
        step = {
            "iteration": iteration,
            "action": "repair_rejected",
            "z3_result": result,
            "paradigm_triggered": par_triggered,
            "positive_guidance_triggered": par_triggered,
            "error_guidance_triggered": error_triggered,
            "stagnated": stagnated,
            "constraint_types": state.constraint_types,
            "unsat_core": unsat_core,
            "constraints_before": constraints_before,
            "repair_response": repair_response,
            "repair_expression": repair_str,
            "repair_rejected": True,
            "repair_rejection_reason": rejection_reason,
            "error_guidance": error_hint,
            "error_paradigms": error_paradigms,
        }
        if source:
            step["source"] = source
        return step

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_state(
        puzzle: PuzzleInstance,
        constraints: List[str],
        unsat_core: List[str],
        z3_result: str,
        iteration: int,
    ) -> SolverState:
        return SolverState(
            puzzle_id=puzzle.puzzle_id,
            constraints=constraints,
            unsat_core=unsat_core if unsat_core else None,
            z3_result=z3_result,
            iteration=iteration,
            problem_nl=puzzle.nl_description,
        )

    @staticmethod
    def _rebuild_solver(constraints: List[str]) -> Z3SolverWrapper:
        s = Z3SolverWrapper()
        for c in constraints:
            s.add_constraint(c)
        return s

    @staticmethod
    def _apply_repair(
        constraints: List[str],
        unsat_core: List[str],
        repair_str: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        """Apply *repair_str* in-place on *constraints*.

        Returns ``(old_constraint, new_constraint)`` for record keeping.
        """
        if not repair_str:
            return None, None

        target_idx = GuidedSolver._select_repair_target_index(
            constraints,
            unsat_core,
            repair_str,
        )
        if target_idx is not None:
            old = constraints[target_idx]
            constraints[target_idx] = repair_str
            return old, repair_str

        constraints.append(repair_str)
        return None, repair_str

    @staticmethod
    def _select_repair_target_index(
        constraints: List[str],
        unsat_core: List[str],
        repair_str: str,
    ) -> Optional[int]:
        repair_vars = GuidedSolver._constraint_vars(repair_str)
        repair_op = GuidedSolver._constraint_operator(repair_str)
        ranked: list[tuple[int, int]] = []
        for idx, constraint in enumerate(constraints):
            if constraint not in unsat_core:
                continue
            repair_is_schema = GuidedSolver._is_schema_constraint(repair_str)
            constraint_is_schema = GuidedSolver._is_schema_constraint(constraint)
            if constraint_is_schema and not repair_is_schema:
                continue
            if constraint_is_schema and repair_is_schema:
                if GuidedSolver._schema_constraint_kind(constraint) != GuidedSolver._schema_constraint_kind(repair_str):
                    continue
                if GuidedSolver._constraint_vars(constraint) != repair_vars:
                    continue
            if repair_is_schema and not constraint_is_schema:
                continue
            overlap = len(repair_vars & GuidedSolver._constraint_vars(constraint))
            relation_bonus = 1 if GuidedSolver._is_relation_constraint(constraint) else 0
            operator_bonus = 1 if repair_op and repair_op == GuidedSolver._constraint_operator(constraint) else 0
            exact_repair_penalty = 100 if constraint == repair_str else 0
            if overlap:
                ranked.append((
                    overlap * 10 + operator_bonus * 5 + relation_bonus - exact_repair_penalty,
                    -idx,
                ))
        if ranked:
            return -max(ranked)[1]
        return None

    @staticmethod
    def _constraint_vars(constraint: str) -> set[str]:
        return set(re.findall(r"Int\('([^']+)'\)", constraint or ""))

    @staticmethod
    def _is_schema_constraint(constraint: str) -> bool:
        text = constraint or ""
        if "Distinct(" in text:
            return True
        return bool(
            text.startswith("And(")
            and ">=" in text
            and "<=" in text
            and len(GuidedSolver._constraint_vars(text)) == 1
        )

    @staticmethod
    def _schema_constraint_kind(constraint: str) -> str:
        text = constraint or ""
        if "Distinct(" in text:
            return "distinct"
        if GuidedSolver._is_schema_constraint(text):
            return "domain_bound"
        return ""

    @staticmethod
    def _is_relation_constraint(constraint: str) -> bool:
        return len(GuidedSolver._constraint_vars(constraint)) >= 2

    @staticmethod
    def _constraint_operator(constraint: str) -> Optional[str]:
        text = constraint or ""
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if op in text:
                return op
        return None

    @staticmethod
    def _infer_repair_type(old: Optional[str], new: Optional[str]) -> str:
        if old is None:
            return "add_constraint"
        if new is None:
            return "remove_constraint"
        return "modify_constraint"

    @staticmethod
    def _parameter_signature(repair_str: Optional[str]) -> Optional[str]:
        """Structural signature of a repair: operator | sorted vars | constants.

        Two repairs share a signature iff they assert the same relation over
        the same variables with the same numeric parameters — the exact-match
        granularity the loop detector's structured triple requires.
        """
        if not repair_str:
            return None
        op = GuidedSolver._constraint_operator(repair_str) or ""
        vars_ = ",".join(sorted(GuidedSolver._constraint_vars(repair_str)))
        consts = ",".join(re.findall(r"(?<![\w'])-?\d+(?![\w'])", repair_str))
        return f"{op}|{vars_}|{consts}"

    @staticmethod
    def _classify_error_type(
        new_constraint: Optional[str],
        new_core: Optional[List[str]],
        declared_vars: Optional[set] = None,
    ) -> ErrorType:
        """Classify the error type via UNSAT core attribution.

        Primary attribution (from the paper):
        - NEW_ASSERTION: ``new_constraint ∈ new_core`` — the repair itself
          caused the new contradiction.
        - LEGACY_ERROR: ``new_constraint ∉ new_core`` — the contradiction
          predated this repair; the formulation already had latent errors.

        Secondary classification refines NEW_ASSERTION via a structural pass
        over the Z3 AST of ``new_constraint``. Earlier versions of this method
        used substring heuristics on the raw string (``">=" in c and "<=" in c``);
        the AST-based pass is robust to Z3's many equivalent surface forms
        (e.g. ``Not(x > 0)`` is recognised as a flipped form of ``x <= 0``).

        - SYNTAX          — ``new_constraint`` fails Z3 parsing.
        - SCOPE_ERROR     — the parsed expression references an identifier
          that is not in ``declared_vars`` (when provided).
        - SEMANTIC_FLIP   — the AST contains contradictory comparison
          operators on identical operand pairs (e.g. ``x >= k ∧ x <= k - 1``,
          or ``x == k ∧ Not(x == k)``), or a top-level conjunction whose
          children directly negate one another.
        - OVER_CONSTRAINT — default: the new assertion legally tightens the
          formula beyond satisfiability.

        Args:
            new_constraint: The constraint string just applied (may be None
                if the repair produced no output).
            new_core: The UNSAT core returned by Z3 after the repair (None
                when the result was SAT or the repair produced no output).
            declared_vars: Optional set of currently-declared variable names.
                When provided, references outside this set trigger SCOPE_ERROR.

        Returns:
            The most specific ``ErrorType`` that applies.
        """
        if new_constraint is None or new_core is None:
            return ErrorType.LEGACY
        if new_constraint not in new_core:
            return ErrorType.LEGACY

        # Lazy import to avoid pulling z3 into modules that don't need it.
        try:
            import z3  # noqa: PLC0415
            from prism.core.solver import _Z3_NS  # type: ignore
        except Exception:
            # If we cannot parse, fall back to OVER_CONSTRAINT (the prior default).
            return ErrorType.OVER_CONSTRAINT

        # ── Parse new_constraint into a Z3 expression ─────────────────────
        try:
            expr = eval(new_constraint, _Z3_NS)  # noqa: S307
            if not z3.is_bool(expr):
                return ErrorType.SYNTAX
        except Exception:
            return ErrorType.SYNTAX

        # ── SCOPE_ERROR: identifiers used in the string not in declared_vars
        if declared_vars is not None:
            import re  # noqa: PLC0415
            _reserved = {
                "Int", "Bool", "Real", "And", "Or", "Not", "Implies",
                "ForAll", "Exists", "Distinct", "Abs", "True", "False",
                "If", "Sum", "Product",
            }
            for ident in re.findall(r"\b([A-Za-z][A-Za-z0-9_]*)\b", new_constraint):
                if ident in _reserved or ident.isdigit():
                    continue
                if ident not in declared_vars:
                    return ErrorType.SCOPE_ERROR

        # ── SEMANTIC_FLIP: collect comparison atoms over the AST and check
        # whether contradictory pairs occur on identical operand pairs.
        # Atoms are normalised so that ``Not(x > y)`` is treated as ``x <= y``.
        atoms: List[tuple] = []

        def _kind_of(e) -> Optional[str]:
            # Map z3 decl kind → canonical operator label.
            try:
                k = e.decl().kind()
            except Exception:
                return None
            mapping = {
                z3.Z3_OP_LE: "<=",
                z3.Z3_OP_LT: "<",
                z3.Z3_OP_GE: ">=",
                z3.Z3_OP_GT: ">",
                z3.Z3_OP_EQ: "==",
                z3.Z3_OP_DISTINCT: "!=",
            }
            return mapping.get(k)

        def _negate(op: str) -> str:
            return {"<=": ">", "<": ">=", ">=": "<", ">": "<=", "==": "!=", "!=": "=="}.get(op, op)

        def _walk(e, negated: bool) -> None:
            try:
                k = e.decl().kind()
            except Exception:
                return
            if k == z3.Z3_OP_NOT:
                _walk(e.arg(0), not negated)
                return
            if k in (z3.Z3_OP_AND, z3.Z3_OP_OR, z3.Z3_OP_IMPLIES):
                for i in range(e.num_args()):
                    _walk(e.arg(i), negated)
                return
            op = _kind_of(e)
            if op is None:
                return
            try:
                lhs = str(e.arg(0))
                rhs = str(e.arg(1))
            except Exception:
                return
            effective = _negate(op) if negated else op
            atoms.append((effective, lhs, rhs))

        try:
            _walk(expr, negated=False)
        except Exception:
            atoms = []

        contradictory_pairs = {
            frozenset(("<=", ">")),
            frozenset(("<", ">=")),
            frozenset(("==", "!=")),
        }
        for i in range(len(atoms)):
            op_i, l_i, r_i = atoms[i]
            for j in range(i + 1, len(atoms)):
                op_j, l_j, r_j = atoms[j]
                if (l_i, r_i) == (l_j, r_j) or (l_i, r_i) == (r_j, l_j):
                    if frozenset((op_i, op_j)) in contradictory_pairs:
                        return ErrorType.SEMANTIC_FLIP

        return ErrorType.OVER_CONSTRAINT

    def _writeback_confidence(
        self, record: RepairRecord, state: SolverState
    ) -> None:
        """Update library confidence after a successful repair.

        Looks for paradigms whose scope overlaps with the current state's
        constraint types and bumps their confidence upward toward 1.0.
        """
        if not state.constraint_types:
            return
        matched = self._library.retrieve(state.constraint_types, top_k=1)
        for paradigm in matched:
            new_conf = min(1.0, paradigm.confidence + 0.01)
            try:
                self._library.update_confidence(paradigm.id, new_conf)
                self._library.increment_support(paradigm.id)
            except KeyError:
                pass

    def _maybe_stage_candidate(
        self,
        state: SolverState,
        constraints_at_sat: List[str],
        new_constraint: Optional[str],
    ) -> None:
        """Stage the just-succeeded repair as a candidate paradigm in L†.

        Implements paper §3.6 staged write-back. The candidate is not
        verified online; it sits in the in-memory pool until the next batch
        flush triggers triple verification against an offline-grade
        ``ParadigmVerifier``. Calls are silent no-ops when write-back is
        disabled or when no new constraint exists (e.g. the initial
        translation was SAT without any repair).
        """
        if self._candidate_pool is None or not new_constraint:
            return
        trigger_types = list(state.constraint_types or [])
        if not trigger_types:
            return
        try:
            self._candidate_pool.stage(
                trigger_types=trigger_types,
                operation=new_constraint,
                pre_condition="",  # no formal pre-condition recovered online
                post_condition="",
                scope=trigger_types,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("CandidatePool stage failed: %s", exc)

    def _maybe_flush_pool(self) -> None:
        """Bump the pool's solved-puzzle counter and possibly trigger a flush.

        Called at every solve() exit point (SAT or final UNSAT). When write-back
        is disabled this is a no-op.
        """
        if self._candidate_pool is not None:
            try:
                self._candidate_pool.maybe_flush()
            except Exception as exc:  # noqa: BLE001
                logger.debug("CandidatePool maybe_flush failed: %s", exc)

    def flush_candidate_pool(self) -> int:
        """Force a batch flush of the staged candidate pool.

        Intended to be called from evaluation scripts at end-of-run so any
        pending candidates that did not trip the K-puzzle auto-flush are
        re-verified before the library is dumped to disk.

        Returns:
            Number of paradigms promoted by the flush, or 0 if no pool.
        """
        if self._candidate_pool is None:
            return 0
        return self._candidate_pool.flush()

    def _finalize_sat_result(
        self,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
        current_constraints: List[str],
        steps: List[dict],
        *,
        mark_last_step: bool,
        paradigm_triggered: bool = False,
        stagnation_detected: bool = False,
    ) -> SolveResult:
        """Validate a SAT model before accepting it as solved."""

        validation = self._validate_solver_model(puzzle, solver)
        if validation.ok:
            clue_repaired = self._try_repair_clue_coverage_issues(
                puzzle=puzzle,
                solver=solver,
                current_constraints=current_constraints,
                steps=steps,
                mark_last_step=mark_last_step,
                paradigm_triggered=paradigm_triggered,
                stagnation_detected=stagnation_detected,
            )
            if clue_repaired is not None:
                return clue_repaired
            self._maybe_flush_pool()
            return self._success(
                puzzle,
                solver,
                steps,
                self._llm.call_count,
                paradigm_triggered,
                stagnation_detected,
            )

        self._mark_validation_failure_step(
            steps,
            validation,
            mark_last_step=mark_last_step,
        )
        if self._can_attempt_validation_recovery(steps):
            recovered = (
                self._recover_invalid_model(
                    puzzle,
                    current_constraints,
                    steps,
                    iteration=len(steps),
                )
                if not validation.domain_valid
                else self._recover_misaligned_model(
                    puzzle,
                    current_constraints,
                    steps,
                    iteration=len(steps),
                )
            )
            if recovered is not None:
                recovered_solver, recovered_result, recovered_constraints = recovered
                if recovered_result == "SAT":
                    recovered_validation = self._validate_solver_model(
                        puzzle, recovered_solver
                    )
                    if recovered_validation.ok:
                        self._maybe_flush_pool()
                        return self._success(
                            puzzle,
                            recovered_solver,
                            steps,
                            self._llm.call_count,
                            paradigm_triggered,
                            stagnation_detected,
                        )
                    recovered_result = recovered_validation.final_z3_result
                    self._mark_validation_failure_step(
                        steps,
                        recovered_validation,
                        mark_last_step=True,
                    )
                if (
                    recovered_result == "UNSAT"
                    and self._remaining_repair_budget(steps) > 0
                ):
                    repaired = self._repair_recovered_unsat(
                        puzzle=puzzle,
                        solver=recovered_solver,
                        current_constraints=recovered_constraints,
                        steps=steps,
                        paradigm_triggered=paradigm_triggered,
                        stagnation_detected=stagnation_detected,
                    )
                    if repaired is not None:
                        return repaired
                self._maybe_flush_pool()
                return SolveResult(
                    puzzle_id=puzzle.puzzle_id,
                    solved=False,
                    solution=self._safe_model(recovered_solver),
                    total_llm_calls=self._llm.call_count,
                    repair_rounds=max(0, len(steps) - 1),
                    steps=steps,
                    final_z3_result=recovered_result,
                    paradigm_triggered=paradigm_triggered,
                    stagnation_detected=stagnation_detected,
                    error=(
                        "model remains invalid after retranslation"
                        if recovered_result == "INVALID_MODEL"
                        else "model remains schema-misaligned after retranslation"
                        if recovered_result == "MISALIGNED_MODEL"
                        else "model key set remains mismatched after retranslation"
                        if recovered_result == "KEY_MISMATCH"
                        else None
                    ),
                )

        self._maybe_flush_pool()
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=False,
            solution=self._safe_model(solver),
            total_llm_calls=self._llm.call_count,
            repair_rounds=max(0, len(steps) - 1),
            steps=steps,
            final_z3_result=validation.final_z3_result,
            paradigm_triggered=paradigm_triggered,
            stagnation_detected=stagnation_detected,
            error=validation.error,
        )

    def _try_repair_clue_coverage_issues(
        self,
        *,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
        current_constraints: List[str],
        steps: List[dict],
        mark_last_step: bool,
        paradigm_triggered: bool,
        stagnation_detected: bool,
    ) -> Optional[SolveResult]:
        issues = _find_clue_coverage_issues(puzzle.nl_description, current_constraints)
        if not issues:
            return None
        if (
            not self._enable_memory
            or self._remaining_repair_budget(steps) <= 0
        ):
            return None

        repairable_issues = self._coverage_issues_with_memory_targets(
            puzzle,
            current_constraints,
            issues,
        )
        if not repairable_issues:
            return None
        issue = repairable_issues[0]
        coverage_state = SolverState(
            puzzle_id=puzzle.puzzle_id,
            constraints=current_constraints,
            unsat_core=[issue.offending_constraint or issue.expected_constraint],
            z3_result="CLUE_MISMATCH",
            iteration=len(steps),
            constraint_types=[issue.clue_relation, issue.issue_type, "clue_coverage_mismatch"],
            problem_nl=puzzle.nl_description,
        )
        error_hint, error_paradigms = self._build_error_guidance(coverage_state)
        error_triggered = bool(error_hint)
        self._mark_clue_coverage_step(
            steps,
            issues,
            mark_last_step=mark_last_step,
        )
        repaired_constraints = list(current_constraints)
        applied_issues: list[ClueCoverageIssue] = []
        for item in repairable_issues:
            if not item.expected_constraint:
                continue
            if item.offending_constraint:
                try:
                    index = repaired_constraints.index(item.offending_constraint)
                except ValueError:
                    continue
                repaired_constraints[index] = item.expected_constraint
            elif any(
                self._constraints_equivalent(item.expected_constraint, constraint)
                for constraint in repaired_constraints
            ):
                continue
            else:
                repaired_constraints.append(item.expected_constraint)
            applied_issues.append(item)
        if not applied_issues:
            return None
        repaired_solver = self._rebuild_solver(repaired_constraints)
        result = repaired_solver.check()
        repair_response = "\n".join(item.expected_constraint for item in applied_issues)
        old_constraint = issue.offending_constraint
        new_constraint = issue.expected_constraint
        coverage_core = [old_constraint or new_constraint]
        steps.append({
            "iteration": len(steps),
            "action": "repair",
            "z3_result": result,
            "source": "clue_coverage",
            "paradigm_triggered": False,
            "positive_guidance_triggered": False,
            "error_guidance_triggered": error_triggered,
            "stagnated": stagnation_detected,
            "constraint_types": [issue.clue_relation, issue.issue_type],
            "unsat_core": coverage_core,
            "constraints_before": current_constraints,
            "repair_response": repair_response,
            "repair_expression": repair_response,
            "old_constraint": old_constraint,
            "new_constraint": new_constraint,
            "new_unsat_core": repaired_solver.get_unsat_core() if result == "UNSAT" else None,
            "clue_coverage_issue": issue.__dict__,
            "clue_coverage_repairs": [item.__dict__ for item in applied_issues],
            "clue_coverage_repair_count": len(applied_issues),
            "error_guidance": error_hint,
            "error_paradigms": error_paradigms,
        })
        if result == "SAT" and self._validate_solver_model(puzzle, repaired_solver).ok:
            self._maybe_flush_pool()
            return self._success(
                puzzle,
                repaired_solver,
                steps,
                self._llm.call_count,
                paradigm_triggered,
                stagnation_detected,
            )
        if result == "UNSAT" and self._remaining_repair_budget(steps) > 0:
            return self._repair_recovered_unsat(
                puzzle=puzzle,
                solver=repaired_solver,
                current_constraints=repaired_constraints,
                steps=steps,
                paradigm_triggered=paradigm_triggered,
                stagnation_detected=stagnation_detected,
            )
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=False,
            solution=self._safe_model(repaired_solver),
            total_llm_calls=self._llm.call_count,
            repair_rounds=max(0, len(steps) - 1),
            steps=steps,
            final_z3_result=result,
            paradigm_triggered=paradigm_triggered,
            stagnation_detected=stagnation_detected,
            error="clue coverage repair did not produce a valid SAT model",
        )

    def _coverage_issues_with_memory_targets(
        self,
        puzzle: PuzzleInstance,
        constraints: List[str],
        issues: list[ClueCoverageIssue],
    ) -> list[ClueCoverageIssue]:
        repairable: list[ClueCoverageIssue] = [
            issue for issue in issues
            if self._is_deterministic_clue_coverage_issue(issue)
        ]
        if self._error_library is None:
            return repairable

        seen = {
            (issue.issue_type, issue.expected_constraint, issue.offending_constraint)
            for issue in repairable
        }
        for issue in issues:
            state = SolverState(
                puzzle_id=puzzle.puzzle_id,
                constraints=constraints,
                unsat_core=[issue.offending_constraint or issue.expected_constraint],
                z3_result="CLUE_MISMATCH",
                iteration=0,
                constraint_types=[
                    issue.clue_relation,
                    issue.issue_type,
                    "clue_coverage_mismatch",
                ],
                problem_nl=puzzle.nl_description,
            )
            _, paradigms = self._build_error_guidance(state)
            targets = self._target_constraints_from_error_paradigms(paradigms)
            key = (issue.issue_type, issue.expected_constraint, issue.offending_constraint)
            if key not in seen and self._matches_any_target(issue.expected_constraint, targets):
                repairable.append(issue)
                seen.add(key)
        return repairable

    @staticmethod
    def _is_deterministic_clue_coverage_issue(issue: ClueCoverageIssue) -> bool:
        return (
            bool(issue.expected_constraint)
            and bool(issue.source_clue)
            and issue.issue_type in {
                "wrong_direct_position",
                "wrong_relation",
                "missing_direct_position",
                "missing_relation",
            }
        )

    @staticmethod
    def _mark_clue_coverage_step(
        steps: List[dict],
        issues: list[ClueCoverageIssue],
        *,
        mark_last_step: bool,
    ) -> None:
        payload = {
            "iteration": (
                steps[-1].get("iteration", max(0, len(steps) - 1))
                if mark_last_step and steps
                else len(steps)
            ),
            "action": "validate_clue_coverage",
            "z3_result": "CLUE_MISMATCH",
            "error_type": "CLUE_COVERAGE_MISMATCH",
            "clue_coverage_issues": [issue.__dict__ for issue in issues],
            "clue_coverage_issue_count": len(issues),
        }
        if mark_last_step and steps:
            if "raw_z3_result" not in steps[-1]:
                payload["raw_z3_result"] = steps[-1].get("z3_result")
            steps[-1] = {**steps[-1], **payload}
        else:
            steps.append(payload)

    @staticmethod
    def _safe_model(solver: Z3SolverWrapper) -> Optional[dict]:
        try:
            return solver.get_model()
        except Exception:  # noqa: BLE001
            return None

    @classmethod
    def _solver_model_within_puzzle_domain(
        cls,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
    ) -> bool:
        return cls._model_within_puzzle_domain(puzzle, cls._safe_model(solver))

    @staticmethod
    def _model_within_puzzle_domain(
        puzzle: PuzzleInstance,
        solution: Optional[dict],
    ) -> bool:
        return model_within_puzzle_domain(puzzle, solution)

    def _validate_solver_model(
        self,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
    ) -> ModelValidation:
        return validate_model(puzzle, self._safe_model(solver))

    @staticmethod
    def _mark_validation_failure_step(
        steps: List[dict],
        validation: ModelValidation,
        *,
        mark_last_step: bool,
    ) -> None:
        step = {
            "iteration": (
                steps[-1].get("iteration", max(0, len(steps) - 1))
                if mark_last_step and steps
                else len(steps)
            ),
            "action": "validate_model",
            "z3_result": validation.final_z3_result,
            "error_type": validation.error_type,
            "model_domain_valid": validation.domain_valid,
            "model_schema_aligned": validation.schema_aligned,
            "model_key_set_aligned": validation.key_set_aligned,
        }
        if mark_last_step and steps:
            if "raw_z3_result" not in steps[-1]:
                step["raw_z3_result"] = steps[-1].get("z3_result")
            steps[-1] = {**steps[-1], **step}
        else:
            steps.append(step)

    def _can_attempt_validation_recovery(self, steps: List[dict]) -> bool:
        used_rounds = max(0, len(steps) - 1)
        if used_rounds >= self._max_rounds:
            return False
        return not any(
            step.get("action") in {
                "invalid_model_retranslate",
                "misaligned_model_retranslate",
            }
            for step in steps
        )

    def _success(
        self,
        puzzle: PuzzleInstance,
        solver: Z3SolverWrapper,
        steps: List[dict],
        llm_calls: int,
        paradigm_triggered: bool = False,
        stagnation_detected: bool = False,
    ) -> SolveResult:
        if self._sparc:
            verdict, solver = self._sparc_gate(puzzle, solver, steps)
            llm_calls = self._llm.call_count
            if verdict == "abstain":
                return SolveResult(
                    puzzle_id=puzzle.puzzle_id,
                    solved=False,
                    solution=None,
                    total_llm_calls=llm_calls,
                    repair_rounds=max(0, len(steps) - 1),
                    steps=steps,
                    final_z3_result="SAT_NONUNIQUE",
                    paradigm_triggered=paradigm_triggered,
                    stagnation_detected=stagnation_detected,
                    error="sparc: solution space not unique within completion budget",
                )
        try:
            solution = solver.get_model()
        except Exception:  # noqa: BLE001
            solution = None
        return SolveResult(
            puzzle_id=puzzle.puzzle_id,
            solved=True,
            solution=solution,
            total_llm_calls=llm_calls,
            repair_rounds=max(0, len(steps) - 1),
            steps=steps,
            final_z3_result="SAT",
            paradigm_triggered=paradigm_triggered,
            stagnation_detected=stagnation_detected,
        )

    # ==================================================================
    # === SPARC π-gate BEGIN ===========================================
    # Everything from here to the end of this class belongs to the SPARC
    # / SBW ("Satisfiable but Wrong") selective-abstention work, NOT to
    # PRISM's paradigm-library / repair-memory path. It is co-located here
    # because it reuses the same GuidedSolver/Z3 plumbing. Activated only
    # when the solver is built with sparc=True (see scripts/sparc/*).
    # Methods: _sparc_gate, _diff_completion, _sparc_conflict_repair,
    #   _discriminates, _holds_under, _answer_key_whitelist,
    #   _answer_projection_vars, _blocking_clause.
    # Do not entangle new PRISM logic below this line.
    # ==================================================================

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
        pairs, _ = GuidedSolver._answer_projection_vars(model, answer_keys)
        equalities = [f"Int('{var}') == {val}" for var, val in pairs]
        if not equalities:
            return None
        return f"Not(And({', '.join(equalities)}))"

    # === SPARC π-gate END (end of class) ===
