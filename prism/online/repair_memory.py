from __future__ import annotations

import hashlib
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


def _fingerprint(unsat_core: List[str]) -> str:
    """SHA-256 of the canonically sorted unsat core, truncated to 16 hex chars."""
    canonical = "|".join(sorted(unsat_core)).encode()
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

        Stagnation is defined as: at least one pair among the last *k* records
        has a Jaccard similarity on their ``unsat_core`` sets that meets or exceeds
        the ``stagnation_jaccard`` threshold.  A score of 1.0 means the exact same
        constraints keep appearing in the UNSAT core — the solver is stuck.

        Args:
            k: Window size (default 3).

        Returns:
            True if stagnation is detected, False otherwise or if fewer than 2
            records are available.
        """
        recent = self._records[-k:]
        if len(recent) < 2:
            return False
        for i in range(len(recent)):
            for j in range(i + 1, len(recent)):
                sim = _jaccard(set(recent[i].unsat_core), set(recent[j].unsat_core))
                if sim >= self._stagnation_jaccard:
                    return True
        return False

    def detect_loop(self, action: RepairAction) -> bool:
        """Return True if *action* is semantically too similar to a past repair.

        Computes the cosine similarity between *action*'s embedding and every
        stored embedding.  If the maximum similarity meets or exceeds the
        ``loop_cosine`` threshold, the proposed repair is considered a loop.

        If *action* has no embedding, the embedding is computed on-the-fly using
        the lazy-loaded sentence-transformer so the caller does not need to pre-
        populate it.

        Args:
            action: The candidate RepairAction to check before applying it.

        Returns:
            True if a near-duplicate past repair is found, False otherwise.
        """
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
        """Generate a Chinese-language prompt snippet summarising the repair history.

        Intended to be injected into the next LLM call so the model is aware of
        what has already been tried and is discouraged from repeating strategies.

        Returns:
            A single string of the form::

                "已尝试修复 N 次，包括：[第1次: <summary>，结果<SAT|UNSAT>; ...]，请尝试不同策略"

            Returns a fresh-start message when the history is empty.
        """
        n = len(self._records)
        if n == 0:
            return "尚无修复历史，请直接分析约束并提出修复方案。"

        parts: List[str] = []
        for idx, rec in enumerate(self._records, start=1):
            summary = rec.repair_action.summary or rec.repair_action.type
            parts.append(f"第{idx}次: {summary}，结果{rec.outcome.value}")

        return f"已尝试修复 {n} 次，包括：[{'; '.join(parts)}]，请尝试不同策略"

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
