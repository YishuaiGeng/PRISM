from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from prism.core.solver import Z3SolverWrapper
from prism.paradigm_library.retriever import ParadigmRetriever
from prism.paradigm_library.schema import Paradigm

# --------------------------------------------------------------------------- #
# Schema                                                                        #
# --------------------------------------------------------------------------- #

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS paradigms (
    id            TEXT     PRIMARY KEY,
    name          TEXT     NOT NULL,
    trigger_json  TEXT     NOT NULL,
    operation     TEXT     NOT NULL,
    pre_condition TEXT     NOT NULL,
    post_condition TEXT    NOT NULL,
    scope_json    TEXT     NOT NULL,
    confidence    REAL     NOT NULL,
    support_count INTEGER  NOT NULL,
    source_cluster INTEGER NOT NULL,
    created_at    TEXT     NOT NULL
)
"""

# Default soundness floor; override via the soundness_threshold constructor arg.
_DEFAULT_SOUNDNESS_THRESHOLD = 0.90


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _row_to_paradigm(row: sqlite3.Row) -> Paradigm:
    """Convert a sqlite3.Row from the paradigms table into a Paradigm object."""
    return Paradigm(
        id=row["id"],
        name=row["name"],
        trigger=json.loads(row["trigger_json"]),
        operation=row["operation"],
        pre_condition=row["pre_condition"],
        post_condition=row["post_condition"],
        scope=json.loads(row["scope_json"]),
        confidence=row["confidence"],
        support_count=row["support_count"],
        source_cluster=row["source_cluster"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _paradigm_to_row(p: Paradigm) -> tuple:
    """Convert a Paradigm into a tuple matching the INSERT column order."""
    return (
        p.id,
        p.name,
        json.dumps(p.trigger, ensure_ascii=False),
        p.operation,
        p.pre_condition,
        p.post_condition,
        json.dumps(p.scope, ensure_ascii=False),
        p.confidence,
        p.support_count,
        p.source_cluster,
        p.created_at.isoformat(),
    )


# --------------------------------------------------------------------------- #
# ParadigmLibrary                                                               #
# --------------------------------------------------------------------------- #

class ParadigmLibrary:
    """SQLite-backed store of repair paradigms with optional soundness gating.

    Paradigms are indexed by their ``id`` (UUID string) and retrieved by matching
    the ``scope`` tag list against caller-supplied constraint type names.  Confidence
    scores are updated in-place as the online repair loop gathers evidence.

    Thread-safety note: the SQLite connection is opened with
    ``check_same_thread=False`` for convenience in research notebooks; production
    use in multi-threaded settings should serialise access externally.

    Typical lifecycle::

        lib = ParadigmLibrary("paradigm_store/paradigms.db", solver)

        lib.add(new_paradigm)                          # vetted by Z3
        candidates = lib.retrieve(["scheduling"], k=3) # top-3 by relevance
        lib.update_confidence(pid, 0.95)               # after a successful repair
        lib.save_json("backup.json")
    """

    def __init__(
        self,
        db_path: str,
        solver: Z3SolverWrapper,
        soundness_threshold: float = _DEFAULT_SOUNDNESS_THRESHOLD,
    ) -> None:
        """Open (or create) the paradigm database and ensure the table exists.

        Args:
            db_path: File-system path to the SQLite database.  Parent directories
                are created automatically.  Use ``":memory:"`` for an ephemeral
                in-process store (useful in tests).
            solver: ``Z3SolverWrapper`` instance used for soundness verification.
                The library calls ``verify_paradigm_soundness`` on it but never
                mutates its constraint state.
            soundness_threshold: Minimum soundness score in [0, 1] a paradigm
                must achieve before being accepted.  Defaults to 0.90.
        """
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self._db_path: str = db_path
        self._solver: Z3SolverWrapper = solver
        self._soundness_threshold: float = soundness_threshold

        self._conn: sqlite3.Connection = sqlite3.connect(
            db_path, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def add(self, paradigm: Paradigm, verify: bool = True) -> bool:
        """Insert or replace a paradigm, optionally vetting it via Z3 soundness.

        When ``verify=True`` the method calls
        ``solver.verify_paradigm_soundness(pre_condition, operation)`` on a cloned
        solver so the library's internal state is never modified.  Paradigms that
        score below ``soundness_threshold`` are rejected and not stored.

        Args:
            paradigm: The Paradigm to add.
            verify: If True, run Z3 soundness check before storing. Set to False
                when bulk-importing from a trusted JSON export.

        Returns:
            True if the paradigm was stored, False if rejected by the soundness
            check or if the operation/pre_condition strings are empty.
        """
        if verify:
            pre = [paradigm.pre_condition] if paradigm.pre_condition.strip() else []
            assertion = paradigm.operation.strip()
            if assertion:
                # Clone the solver so verification does not pollute its constraint set.
                trial_solver = self._solver.clone()
                score = trial_solver.verify_paradigm_soundness(
                    current_constraints=pre,
                    paradigm_assertion=assertion,
                )
                if score < self._soundness_threshold:
                    return False

        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO paradigms
                  (id, name, trigger_json, operation, pre_condition,
                   post_condition, scope_json, confidence, support_count,
                   source_cluster, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                _paradigm_to_row(paradigm),
            )
        return True

    def update_confidence(self, paradigm_id: str, new_score: float) -> None:
        """Overwrite the confidence score for an existing paradigm.

        Args:
            paradigm_id: The ``id`` of the paradigm to update.
            new_score: New confidence value; should be in [0.0, 1.0].

        Raises:
            KeyError: If no paradigm with ``paradigm_id`` exists in the database.
        """
        with self._conn:
            cursor = self._conn.execute(
                "UPDATE paradigms SET confidence = ? WHERE id = ?",
                (new_score, paradigm_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"No paradigm with id {paradigm_id!r}")

    def delete(self, paradigm_id: str) -> None:
        """Remove a paradigm by its id.

        Silently succeeds if the id does not exist (idempotent delete).

        Args:
            paradigm_id: The ``id`` of the paradigm to remove.
        """
        with self._conn:
            self._conn.execute(
                "DELETE FROM paradigms WHERE id = ?", (paradigm_id,)
            )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def retrieve(
        self,
        constraint_types: List[str],
        top_k: int = 3,
        type_bag: Optional[List[str]] = None,
    ) -> List[Paradigm]:
        """Return the top-k most relevant paradigms for the given constraint types.

        Delegates ranking to :class:`~prism.paradigm_library.retriever.ParadigmRetriever`
        (Layer-1 scope-Jaccard + confidence weighting + relational-predicate
        pruning).  Semantic Layer-2 filtering is the caller's responsibility
        (see ``GuidedSolver``).

        Args:
            constraint_types: Distinct tags describing constraint types
                currently present (de-duplicated form).
            top_k: Maximum number of paradigms to return (default 3).
            type_bag: Optional repetition-preserving list of constraint types
                used to evaluate paradigm relational predicates such as
                ``count_atleast`` / ``cooccur``. When omitted the retriever
                falls back to ``constraint_types``, which preserves the
                pre-relational-predicate behaviour.

        Returns:
            List of up to *top_k* Paradigm objects sorted by relevance descending.
        """
        return ParadigmRetriever().retrieve(
            self.get_all(), constraint_types, top_k, type_bag=type_bag
        )

    def get_all(self) -> List[Paradigm]:
        """Return every paradigm in the database, ordered by confidence descending.

        Returns:
            List of all stored Paradigm objects.
        """
        rows = self._conn.execute(
            "SELECT * FROM paradigms ORDER BY confidence DESC"
        ).fetchall()
        return [_row_to_paradigm(r) for r in rows]

    def stats(self) -> Dict:
        """Compute summary statistics over the entire paradigm store.

        Returns:
            Dict with keys:

            - ``total`` (int): number of stored paradigms.
            - ``avg_confidence`` (float): mean confidence score.
            - ``avg_support`` (float): mean support count.
            - ``scope_distribution`` (dict): mapping of each scope tag to the
              number of paradigms that include it.
        """
        paradigms = self.get_all()
        if not paradigms:
            return {
                "total": 0,
                "avg_confidence": 0.0,
                "avg_support": 0.0,
                "scope_distribution": {},
            }

        total = len(paradigms)
        avg_confidence = sum(p.confidence for p in paradigms) / total
        avg_support = sum(p.support_count for p in paradigms) / total

        scope_dist: Dict[str, int] = {}
        for p in paradigms:
            for tag in p.scope:
                scope_dist[tag] = scope_dist.get(tag, 0) + 1

        return {
            "total": total,
            "avg_confidence": round(avg_confidence, 4),
            "avg_support": round(avg_support, 2),
            "scope_distribution": scope_dist,
        }

    # ------------------------------------------------------------------
    # Import / export
    # ------------------------------------------------------------------

    def save_json(self, path: str) -> None:
        """Export all paradigms to a JSON file.

        The file is UTF-8 encoded with indentation for readability.  Existing
        files at *path* are overwritten.

        Args:
            path: Destination file path.
        """
        data = [p.model_dump(mode="json") for p in self.get_all()]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def load_json(self, path: str) -> int:
        """Import paradigms from a JSON file produced by ``save_json``.

        Verification is skipped for imported paradigms (they were already vetted
        when originally added).  Existing paradigms with the same ``id`` are
        replaced via ``INSERT OR REPLACE``.

        Args:
            path: Path to the JSON file to import.

        Returns:
            The number of paradigms successfully imported.
        """
        with open(path, "r", encoding="utf-8") as fh:
            records = json.load(fh)

        count = 0
        for item in records:
            paradigm = Paradigm.model_validate(item)
            if self.add(paradigm, verify=False):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection.

        Safe to call multiple times; subsequent calls are no-ops.
        """
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> ParadigmLibrary:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()
