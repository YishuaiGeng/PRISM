from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from prism.core.constraint_tags import SPECIFIC_RELATION_TAGS, relation_scope_for_operation
from prism.paradigm_library.schema import ErrorParadigm

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS error_paradigms (
    id                TEXT     PRIMARY KEY,
    name              TEXT     NOT NULL,
    trigger_json      TEXT     NOT NULL,
    bad_operation     TEXT     NOT NULL,
    unsat_signature   TEXT     NOT NULL,
    avoid_instruction TEXT     NOT NULL,
    repair_hint       TEXT     NOT NULL,
    scope_json        TEXT     NOT NULL,
    confidence        REAL     NOT NULL,
    support_count     INTEGER  NOT NULL,
    source_cluster    INTEGER  NOT NULL,
    created_at        TEXT     NOT NULL
)
"""


def _row_to_error(row: sqlite3.Row) -> ErrorParadigm:
    return ErrorParadigm(
        id=row["id"],
        name=row["name"],
        trigger=json.loads(row["trigger_json"]),
        bad_operation=row["bad_operation"],
        unsat_signature=row["unsat_signature"],
        avoid_instruction=row["avoid_instruction"],
        repair_hint=row["repair_hint"],
        scope=json.loads(row["scope_json"]),
        confidence=row["confidence"],
        support_count=row["support_count"],
        source_cluster=row["source_cluster"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _error_to_row(p: ErrorParadigm) -> tuple:
    return (
        p.id,
        p.name,
        json.dumps(p.trigger, ensure_ascii=False),
        p.bad_operation,
        p.unsat_signature,
        p.avoid_instruction,
        p.repair_hint,
        json.dumps(p.scope, ensure_ascii=False),
        p.confidence,
        p.support_count,
        p.source_cluster,
        p.created_at.isoformat(),
    )


class ErrorParadigmLibrary:
    """SQLite-backed store for negative/error paradigms."""

    def __init__(self, db_path: str) -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()

    def add(self, paradigm: ErrorParadigm) -> bool:
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO error_paradigms
                  (id, name, trigger_json, bad_operation, unsat_signature,
                   avoid_instruction, repair_hint, scope_json, confidence,
                   support_count, source_cluster, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                _error_to_row(paradigm),
            )
        return True

    def retrieve(
        self,
        constraint_types: List[str],
        unsat_signature: Optional[str] = None,
        top_k: int = 3,
        unsat_core: Optional[List[str]] = None,
        puzzle_id: Optional[str] = None,
    ) -> List[ErrorParadigm]:
        candidates = [
            p for p in self.get_all()
            if _policy_matches_puzzle(_replacement_policy(p), puzzle_id)
        ]
        query = set(constraint_types or [])
        core = set(unsat_core or [])
        exact_matches = [
            p for p in candidates
            if core and p.bad_operation in core and _replacement_policy(p)
        ]
        if exact_matches:
            ranked_exact = sorted(
                exact_matches,
                key=lambda p: (p.confidence, p.support_count),
                reverse=True,
            )
            return [_with_effective_scope(p) for p in ranked_exact[:top_k]]

        def score(p: ErrorParadigm) -> float:
            scope = set(_effective_scope(p))
            overlap = len(query & scope) / len(query | scope) if query or scope else 0.0
            query_specific = query & SPECIFIC_RELATION_TAGS
            scope_specific = scope & SPECIFIC_RELATION_TAGS
            specific_overlap = (
                len(query_specific & scope_specific) / len(query_specific | scope_specific)
                if query_specific or scope_specific
                else 0.0
            )
            signature_bonus = 1.0 if unsat_signature and p.unsat_signature == unsat_signature else 0.0
            exact_bad_operation_bonus = 1.0 if p.bad_operation in core else 0.0
            return (
                0.45 * exact_bad_operation_bonus
                + 0.25 * overlap
                + 0.15 * specific_overlap
                + 0.10 * p.confidence
                + 0.05 * signature_bonus
            )

        ranked = sorted(candidates, key=score, reverse=True)
        return [_with_effective_scope(p) for p in ranked[:top_k]]

    def get_all(self) -> List[ErrorParadigm]:
        rows = self._conn.execute(
            "SELECT * FROM error_paradigms ORDER BY confidence DESC"
        ).fetchall()
        return [_row_to_error(row) for row in rows]

    def stats(self) -> Dict:
        paradigms = self.get_all()
        if not paradigms:
            return {
                "total": 0,
                "avg_confidence": 0.0,
                "avg_support": 0.0,
                "scope_distribution": {},
            }
        scope_dist: Dict[str, int] = {}
        for p in paradigms:
            for tag in p.scope:
                scope_dist[tag] = scope_dist.get(tag, 0) + 1
        return {
            "total": len(paradigms),
            "avg_confidence": round(sum(p.confidence for p in paradigms) / len(paradigms), 4),
            "avg_support": round(sum(p.support_count for p in paradigms) / len(paradigms), 2),
            "scope_distribution": scope_dist,
        }

    def save_json(self, path: str) -> None:
        data = [p.model_dump(mode="json") for p in self.get_all()]
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def load_json(self, path: str) -> int:
        with open(path, encoding="utf-8") as fh:
            records = json.load(fh)
        count = 0
        for item in records:
            if self.add(ErrorParadigm.model_validate(item)):
                count += 1
        return count

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self) -> ErrorParadigmLibrary:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


def _effective_scope(paradigm: ErrorParadigm) -> list[str]:
    tags = set(paradigm.scope or [])
    tags.update(tag for tag in relation_scope_for_operation(paradigm.bad_operation) if tag != "unknown")
    return sorted(tags) if tags else ["contradiction"]


def _with_effective_scope(paradigm: ErrorParadigm) -> ErrorParadigm:
    scope = _effective_scope(paradigm)
    trigger = dict(paradigm.trigger or {})
    trigger["constraint_types"] = scope
    return paradigm.model_copy(update={"scope": scope, "trigger": trigger})


def _replacement_policy(paradigm: ErrorParadigm) -> Optional[dict]:
    trigger = paradigm.trigger or {}
    policy = trigger.get("replacement_policy")
    if isinstance(policy, dict):
        return policy
    if trigger.get("target_constraint") or trigger.get("correct_constraint"):
        return trigger
    return None


def _policy_matches_puzzle(policy: Optional[dict], puzzle_id: Optional[str]) -> bool:
    if not policy or not puzzle_id:
        return True
    policy_puzzle = policy.get("puzzle_id")
    return not policy_puzzle or str(policy_puzzle) == str(puzzle_id)
