from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, List, Optional

import numpy as np

from prism.paradigm_library.schema import Outcome, RepairAction, RepairRecord

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


def _jaccard(a: set, b: set) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _cosine(u: np.ndarray, v: np.ndarray) -> float:
    denom = np.linalg.norm(u) * np.linalg.norm(v)
    return float(np.dot(u, v) / denom) if denom > 1e-10 else 0.0


# Operator aliasing: pairs of equivalent syntactic forms that Z3 may emit
# differently across invocations. Mapping is applied to a string before
# canonical renaming so that Not(x > 0) and x <= 0 hash identically.
_OPERATOR_ALIASES = [
    (re.compile(r"Not\s*\(\s*(.+?)\s*>\s*(.+?)\s*\)"), r"(\1) <= (\2)"),
    (re.compile(r"Not\s*\(\s*(.+?)\s*<\s*(.+?)\s*\)"), r"(\1) >= (\2)"),
    (re.compile(r"Not\s*\(\s*(.+?)\s*>=\s*(.+?)\s*\)"), r"(\1) < (\2)"),
    (re.compile(r"Not\s*\(\s*(.+?)\s*<=\s*(.+?)\s*\)"), r"(\1) > (\2)"),
    (re.compile(r"Not\s*\(\s*(.+?)\s*==\s*(.+?)\s*\)"), r"(\1) != (\2)"),
    (re.compile(r"Not\s*\(\s*(.+?)\s*!=\s*(.+?)\s*\)"), r"(\1) == (\2)"),
]

# Identifier pattern used by canonical variable renaming. Conservative: matches
# names commonly emitted by NL→Z3 translation in our pipeline (alphabetic head
# plus optional digits / underscores). Reserved Z3 keywords are excluded.
_IDENT_PATTERN = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\b")
_Z3_RESERVED = frozenset({
    "Int", "Bool", "Real", "And", "Or", "Not", "Implies", "ForAll", "Exists",
    "Distinct", "Abs", "True", "False", "If", "Sum", "Product",
})


def _apply_operator_aliases(s: str) -> str:
    """Apply operator-aliasing regexes to a constraint string."""
    out = s.strip()
    for pat, repl in _OPERATOR_ALIASES:
        out = pat.sub(repl, out)
    return out


def _neutralize_identifiers(s: str) -> str:
    """Replace every non-reserved identifier with a single ``?`` placeholder.

    Used purely as a sort key so that ``"x > 0"`` and ``"y > 0"`` sort to the
    same bucket regardless of the variable name. The result is *not* the
    canonical form — it is only an order key.
    """
    def _strip(match):
        ident = match.group(1)
        if ident in _Z3_RESERVED or ident.isdigit():
            return ident
        return "?"
    return _IDENT_PATTERN.sub(_strip, _apply_operator_aliases(s))


def _canonicalize_constraint(s: str, mapping: dict) -> str:
    """Apply operator aliasing and variable renaming to a single constraint string.

    Variable identifiers are mapped to canonical names (``v1``, ``v2``, ...).
    The caller supplies and reuses ``mapping`` so that the same variable across
    constraints receives the same canonical name.
    """
    out = _apply_operator_aliases(s)

    def _replace(match):
        ident = match.group(1)
        if ident in _Z3_RESERVED or ident.isdigit():
            return ident
        if ident not in mapping:
            mapping[ident] = f"v{len(mapping) + 1}"
        return mapping[ident]

    return _IDENT_PATTERN.sub(_replace, out)


def _canonicalize_core(unsat_core: List[str]) -> List[str]:
    """Return the canonicalised view of an UNSAT core.

    The canonicalisation has three steps:

    1. Operator aliasing — rewrite negated comparators (``Not(x>y)`` →
       ``x<=y``, etc.) so syntactically distinct but logically equivalent
       atoms collapse to a single representative.
    2. Order-invariant sort — sort the constraints by an *identifier-neutral*
       skeleton (every variable replaced by ``?``) so that lists differing
       only in element order produce the same canonical ordering.
    3. First-occurrence variable renaming — in the now-sorted order, rename
       variables to ``v1, v2, ...`` so two cores that differ only in the
       choice of variable names produce identical strings.

    Together these guarantee both order-invariance and naming-invariance,
    which is what the stagnation detector and the SHA-256 fingerprint rely on.
    """
    if not unsat_core:
        return []
    aliased = [_apply_operator_aliases(c) for c in unsat_core]
    # Sort by identifier-neutral skeleton to obtain a canonical processing order.
    indexed = sorted(range(len(aliased)), key=lambda i: _neutralize_identifiers(aliased[i]))
    mapping: dict = {}
    canonical = [_canonicalize_constraint(aliased[i], mapping) for i in indexed]
    return canonical


def _fingerprint(unsat_core: List[str]) -> str:
    """SHA-256 of the canonicalised unsat core, truncated to 16 hex chars.

    Canonicalisation combines operator aliasing and first-occurrence variable
    renaming so that syntactically-equivalent cores (e.g. differing only in
    variable naming or Not(...) vs negated comparator) yield the same
    fingerprint.
    """
    canonical = "|".join(_canonicalize_core(unsat_core)).encode()
    return hashlib.sha256(canonical).hexdigest()[:16]


class RepairMemory:
    """Tracks the history of repair attempts for a single solver session.

    Provides two loop/stagnation detectors that guard against the LLM repeating
    already-tried strategies, plus a natural-language summary suitable for inclusion
    in the next LLM prompt.

    Typical lifecycle::

        mem = RepairMemory(config["thresholds"])
        mem.append(record)          # called after each solver iteration
        if mem.detect_stagnation(): # switch to a different repair family
            ...
        if mem.detect_loop(action): # this exact repair was tried before
            ...
        mem.clear()                 # reset between puzzle instances
    """

    # Sentence-transformer model is loaded once per instance on first use.
    _ENCODER_MODEL = "all-MiniLM-L6-v2"

    def __init__(self, config: dict) -> None:
        """Initialise from a thresholds config dict.

        Args:
            config: Dict with at least ``stagnation_jaccard`` and ``loop_cosine``
                keys (floats in [0, 1]).  Extra keys are ignored.
        """
        self._stagnation_jaccard: float = float(config["stagnation_jaccard"])
        self._loop_cosine: float = float(config["loop_cosine"])
        self._records: List[RepairRecord] = []
        self._encoder: Optional[SentenceTransformer] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_encoder(self) -> Optional[SentenceTransformer]:
        """Lazy-load the sentence-transformer model on first call.

        Deferred to avoid the several-second initialisation cost (and GPU memory
        allocation) in environments where embeddings are not needed.  Returns
        ``None`` when the ``sentence_transformers`` package is not installed so
        that callers can fall back to embedding-free operation.
        """
        if self._encoder is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415
                self._encoder = SentenceTransformer(self._ENCODER_MODEL)
            except ImportError:
                return None
        return self._encoder

    def _encode(self, text: str) -> Optional[List[float]]:
        encoder = self._get_encoder()
        if encoder is None:
            return None
        return encoder.encode(text, show_progress_bar=False).tolist()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def append(self, record: RepairRecord) -> None:
        """Append a repair record, filling in fingerprint and embedding automatically.

        The method always overwrites ``core_fingerprint`` with a freshly computed
        value so callers do not need to set it.  If the record's ``repair_action``
        has a non-empty ``summary`` but no ``embedding``, the embedding is computed
        and stored before the record is saved.

        Args:
            record: The RepairRecord to add; mutated copies are stored internally.
        """
        fp = _fingerprint(record.unsat_core)
        record = record.model_copy(update={"core_fingerprint": fp})

        action = record.repair_action
        if action.summary and action.embedding is None:
            embedding = self._encode(action.summary)
            if embedding is not None:
                action = action.model_copy(update={"embedding": embedding})
                record = record.model_copy(update={"repair_action": action})

        self._records.append(record)

    def detect_stagnation(self, k: int = 3) -> bool:
        """Return True if the last *k* records show unsat-core stagnation.

        Stagnation is defined as: **any** pair among the last *k* records has a
        Jaccard similarity on their ``unsat_core`` sets that meets or exceeds the
        ``stagnation_jaccard`` threshold (MAX semantics — early-warning trigger).

        Using MAX (any pair) rather than MIN (all pairs) is intentional: we want
        to detect the first sign that the solver is recycling the same constraints
        and switch strategy before exhausting the repair budget.

        A Jaccard score of 1.0 means the exact same constraints keep appearing in
        the UNSAT core — the solver is definitively stuck.

        Args:
            k: Window size (default 3).

        Returns:
            True if stagnation is detected, False otherwise or if fewer than 2
            records are available.
        """
        recent = self._records[-k:]
        if len(recent) < 2:
            return False
        fingerprints = [r.core_fingerprint or _fingerprint(r.unsat_core) for r in recent]
        if len(fingerprints) != len(set(fingerprints)):
            return True
        # Canonicalise once per record to amortise the cost across pairwise
        # comparisons and to ensure cross-iteration comparison is robust to
        # Z3's non-unique core listings (different runs may return the same
        # underlying contradiction with different surface forms / variable
        # naming). See methodology Section 3.5 for the rationale.
        canon = [set(_canonicalize_core(r.unsat_core)) for r in recent]
        for i in range(len(canon)):
            for j in range(i + 1, len(canon)):
                sim = _jaccard(canon[i], canon[j])
                if sim >= self._stagnation_jaccard:
                    return True
        return False

    def detect_loop(self, action: RepairAction) -> bool:
        """Return True if *action* duplicates a past repair, using two signals.

        Loop detection combines a fast structural check with a slower semantic
        fallback so that LLM paraphrase noise does not defeat detection:

        1. **Structured signal (hard match, O(1)).** A repair is flagged as a
           loop if its triple ``(type, target_constraint, parameter_signature)``
           matches that of any previously-stored record exactly.  This catches
           cases where the LLM proposes the same atomic edit in different words.
        2. **Semantic signal (soft, fallback).** Only when the structured check
           does not fire (or when ``parameter_signature`` is missing on either
           side) we fall back to cosine similarity between the
           sentence-transformer embedding of ``action.summary`` and the embeddings
           of stored records.  A maximum similarity at or above
           ``self._loop_cosine`` flags the action as a loop.

        Args:
            action: The candidate RepairAction to check before applying it.

        Returns:
            True if a near-duplicate past repair is found, False otherwise.
        """
        # ── Signal 1: structured triple match ─────────────────────────────
        new_type = (action.type or "").strip()
        new_target = (action.target_constraint or "").strip()
        new_param = (action.parameter_signature or "").strip()
        if new_type and new_target:
            for record in self._records:
                rt = (record.repair_action.type or "").strip()
                rtg = (record.repair_action.target_constraint or "").strip()
                rp = (record.repair_action.parameter_signature or "").strip()
                if rt == new_type and rtg == new_target:
                    # Same type + same target: require also matching parameter
                    # signature if both sides provide one; otherwise treat as
                    # a loop conservatively (type+target alone is a strong
                    # structural signal in this codebase's repair vocabulary).
                    if new_param and rp:
                        if new_param == rp:
                            return True
                    else:
                        return True

        # ── Signal 2: semantic fallback via embedding cosine ──────────────
        summary = action.summary
        if not summary:
            return False

        if action.embedding is not None:
            new_vec = np.array(action.embedding, dtype=np.float32)
        else:
            encoded = self._encode(summary)
            if encoded is None:
                return False  # sentence_transformers unavailable; skip loop detection
            new_vec = np.array(encoded, dtype=np.float32)

        for record in self._records:
            hist_emb = record.repair_action.embedding
            if hist_emb is None:
                continue
            hist_vec = np.array(hist_emb, dtype=np.float32)
            if _cosine(new_vec, hist_vec) >= self._loop_cosine:
                return True
        return False

    def get_history_summary(self) -> str:
        """Generate a prompt snippet summarising the repair history for LLM injection.

        Intended to be injected into the next LLM call so the model is aware of
        what has already been tried and is discouraged from repeating strategies.

        Returns:
            A single string of the form::

                "Attempted N repairs: [#1: <summary> → <SAT|UNSAT>; ...].
                 Please try a different strategy."

            Returns a fresh-start message when the history is empty.
        """
        n = len(self._records)
        if n == 0:
            return "No repair history yet. Analyse the constraints and propose a fix."

        parts: List[str] = []
        for idx, rec in enumerate(self._records, start=1):
            summary = rec.repair_action.summary or rec.repair_action.type
            parts.append(f"#{idx}: {summary} → {rec.outcome.value}")

        return f"Attempted {n} repair(s): [{'; '.join(parts)}]. Please try a different strategy."

    def get_successful_repairs(self) -> List[RepairRecord]:
        """Return all records whose solver outcome was SAT.

        Useful for building a positive training signal or for selecting a
        verified repair to apply when the paradigm library returns no match.
        """
        return [r for r in self._records if r.outcome == Outcome.SAT]

    def clear(self) -> None:
        """Reset the memory for a new puzzle instance.

        The loaded sentence-transformer encoder is retained to avoid re-initialisation
        overhead across back-to-back puzzle evaluations.
        """
        self._records.clear()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialise the full memory state to a JSON-compatible dict.

        The encoder object is not serialised; it will be lazily reloaded on the
        next call that requires embeddings.
        """
        return {
            "config": {
                "stagnation_jaccard": self._stagnation_jaccard,
                "loop_cosine": self._loop_cosine,
            },
            "records": [r.model_dump(mode="json") for r in self._records],
        }

    @classmethod
    def from_dict(cls, d: dict) -> RepairMemory:
        """Reconstruct a RepairMemory instance from a previously serialised dict.

        Args:
            d: Dict produced by ``to_dict()``.

        Returns:
            A fully populated RepairMemory with all historical records restored.
        """
        instance = cls(d["config"])
        instance._records = [
            RepairRecord.model_validate(r) for r in d.get("records", [])
        ]
        return instance
