"""Staged write-back candidate pool for online paradigm augmentation.

Implements the ``L†`` mechanism described in paper §3.6: successful online
inference / repair patterns are *not* admitted to the live paradigm library
immediately. Instead they are staged in this in-memory pool. Every ``K``
solved puzzles (or end-of-evaluation) the pool is drained, candidates are
de-duplicated against the live library by (trigger-kind signature,
operation-template hash), and survivors are re-screened by the same
``ParadigmVerifier`` triple-verification protocol used in offline distillation.
Promoted candidates enter the library with their confidence initialised from
the screening trials; failed candidates are discarded with provenance retained
on the pool's ``rejected`` log for later analysis.

Design notes:
    * In-memory only; pool state is per-evaluation, not persisted across runs.
    * De-duplication uses a coarse hash that ignores variable names so that
      semantically equivalent operations originating from different puzzles
      collapse to a single candidate.
    * The pool never blocks the online solver: ``stage()`` is O(1) and
      ``flush()`` is invoked from the caller at the right cadence.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from prism.offline.paradigm_verifier import ParadigmVerifier
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import Paradigm

logger = logging.getLogger(__name__)


def _candidate_hash(trigger_types: List[str], operation: str) -> str:
    """Coarse identity for de-duplication.

    Trigger types are sorted and lower-cased; the operation is stripped of
    whitespace. The combined string is SHA-256 hashed and truncated for
    storage friendliness.
    """
    types_sig = "|".join(sorted(t.strip().lower() for t in trigger_types if t.strip()))
    op_sig = "".join(operation.strip().split())
    return hashlib.sha256(f"{types_sig}::{op_sig}".encode()).hexdigest()[:16]


class CandidatePool:
    """In-memory candidate pool with batched re-verification.

    Args:
        library: The live ``ParadigmLibrary`` candidates are promoted into.
        verifier: ``ParadigmVerifier`` instance shared with the offline phase.
        batch_K: Number of staged candidates after which an automatic flush is
            triggered. Set to a large number to disable auto-flushing and call
            :meth:`flush` manually at end of evaluation.
        on_promote: Optional callback invoked with each promoted paradigm.
        on_reject: Optional callback invoked with (paradigm, reason).
    """

    def __init__(
        self,
        library: ParadigmLibrary,
        verifier: ParadigmVerifier,
        batch_K: int = 50,
        on_promote: Optional[Callable[[Paradigm], None]] = None,
        on_reject: Optional[Callable[[Paradigm, str], None]] = None,
    ) -> None:
        self._library: ParadigmLibrary = library
        self._verifier: ParadigmVerifier = verifier
        self._batch_K: int = max(1, int(batch_K))
        self._on_promote: Optional[Callable[[Paradigm], None]] = on_promote
        self._on_reject: Optional[Callable[[Paradigm, str], None]] = on_reject

        # Pending candidates keyed by coarse hash to suppress duplicates
        # *within* the pool. Live-library duplicates are filtered at flush().
        self._pending: Dict[str, Paradigm] = {}
        self._seen_solve_count: int = 0
        self._stats: Dict[str, int] = {
            "staged": 0,
            "duplicate_in_pool": 0,
            "duplicate_in_library": 0,
            "promoted": 0,
            "rejected": 0,
        }
        # Provenance log of rejections — small dicts for debugging only.
        self.rejected: List[Tuple[Paradigm, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def stage(
        self,
        trigger_types: List[str],
        operation: str,
        pre_condition: str,
        post_condition: str = "",
        scope: Optional[List[str]] = None,
        relational_predicates: Optional[List[dict]] = None,
        source_cluster: int = -1,
    ) -> bool:
        """Stage a candidate inferred from a successful online step.

        Args:
            trigger_types: Constraint-type tags that triggered the success.
            operation: The Z3 expression string applied in the successful step.
            pre_condition: SMT pre-condition observed in the state.
            post_condition: Optional post-condition; defaults to empty.
            scope: Applicable scope tags; defaults to trigger_types.
            relational_predicates: Optional structured predicates to attach.
            source_cluster: Cluster id for provenance (use -1 for online).

        Returns:
            True if newly staged; False if a duplicate was already pending.
        """
        if not operation.strip() or not trigger_types:
            return False
        h = _candidate_hash(trigger_types, operation)
        if h in self._pending:
            self._stats["duplicate_in_pool"] += 1
            return False

        trigger: Dict = {"constraint_types": list(trigger_types)}
        if relational_predicates:
            trigger["relational_predicates"] = list(relational_predicates)

        candidate = Paradigm(
            id=h,
            name=f"online-{h}",
            trigger=trigger,
            operation=operation.strip(),
            pre_condition=pre_condition.strip(),
            post_condition=post_condition.strip(),
            scope=list(scope if scope is not None else trigger_types),
            confidence=0.0,  # set on promotion from verifier output
            support_count=1,
            source_cluster=source_cluster,
            created_at=datetime.now(tz=timezone.utc),
        )
        self._pending[h] = candidate
        self._stats["staged"] += 1
        return True

    def maybe_flush(self) -> int:
        """Increment solved-puzzle counter; flush if the K-puzzle threshold is met.

        Returns:
            Number of newly promoted paradigms, or 0 if no flush occurred.
        """
        self._seen_solve_count += 1
        if self._seen_solve_count >= self._batch_K:
            return self.flush()
        return 0

    def flush(self) -> int:
        """Re-verify every pending candidate and promote those that pass.

        De-duplicates pending candidates against the live library by coarse
        hash before verification. Each surviving candidate is screened via
        the same triple-verification protocol used in offline distillation;
        passes are admitted with ``library.add(verify=False)`` (verification
        already happened) and confidence equal to the screening soundness.

        Returns:
            Number of promoted paradigms.
        """
        if not self._pending:
            self._seen_solve_count = 0
            return 0

        live_hashes = self._live_library_hashes()
        promoted = 0

        for h, candidate in list(self._pending.items()):
            if h in live_hashes:
                self._stats["duplicate_in_library"] += 1
                continue
            confidence = self._verifier.verify(candidate)
            if confidence <= 0.0:
                self._stats["rejected"] += 1
                self.rejected.append((candidate, "failed triple verification"))
                if self._on_reject is not None:
                    self._on_reject(candidate, "failed triple verification")
                continue
            verified = candidate.model_copy(update={"confidence": float(confidence)})
            try:
                if self._library.add(verified, verify=False):
                    promoted += 1
                    self._stats["promoted"] += 1
                    if self._on_promote is not None:
                        self._on_promote(verified)
                else:
                    self._stats["rejected"] += 1
                    self.rejected.append((candidate, "library refused insertion"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Library insertion failed for %s: %s", candidate.id, exc)
                self._stats["rejected"] += 1
                self.rejected.append((candidate, f"insertion error: {exc}"))

        self._pending.clear()
        self._seen_solve_count = 0
        logger.info(
            "CandidatePool flushed: promoted=%d, stats=%s", promoted, self._stats
        )
        return promoted

    def stats(self) -> Dict[str, int]:
        """Return a snapshot of pool-lifetime counters."""
        snap = dict(self._stats)
        snap["pending"] = len(self._pending)
        snap["since_last_flush"] = self._seen_solve_count
        return snap

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _live_library_hashes(self) -> set:
        """Compute coarse hashes of paradigms already in the live library."""
        live = set()
        try:
            for p in self._library.get_all():
                trigger_types = p.trigger.get("constraint_types", []) if isinstance(p.trigger, dict) else []
                live.add(_candidate_hash(trigger_types, p.operation))
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not enumerate library for dedup: %s", exc)
        return live
