"""Shared pytest fixtures for the PRISM test suite.

All fixtures here are automatically discovered by pytest across the entire
tests/ directory.  Test-file-specific helpers (make_repair_record,
make_paradigm) are module-level factory functions imported explicitly by the
files that need them, keeping the fixture namespace uncluttered.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from prism.core.solver import Z3SolverWrapper
from prism.online.repair_memory import RepairMemory
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import (
    ErrorType,
    Outcome,
    Paradigm,
    RepairAction,
    RepairRecord,
)


# --------------------------------------------------------------------------- #
# Shared fixtures                                                               #
# --------------------------------------------------------------------------- #

@pytest.fixture
def solver() -> Z3SolverWrapper:
    """Fresh Z3SolverWrapper for each test — no shared constraint state."""
    return Z3SolverWrapper()


@pytest.fixture
def memory_config() -> dict:
    """Threshold config matching config/default.yaml defaults."""
    return {"stagnation_jaccard": 0.75, "loop_cosine": 0.90}


@pytest.fixture
def memory(memory_config: dict) -> RepairMemory:
    """Fresh RepairMemory with default thresholds, cleared between tests."""
    m = RepairMemory(memory_config)
    yield m
    m.clear()


@pytest.fixture
def lib(solver: Z3SolverWrapper) -> ParadigmLibrary:
    """In-memory ParadigmLibrary.

    Uses soundness_threshold=0.0 so that add(..., verify=True) never rejects a
    paradigm during library-focused tests; soundness gating is tested separately
    in tests that control what the solver sees.
    """
    with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as library:
        yield library


# --------------------------------------------------------------------------- #
# Factory helpers (imported explicitly by test files that need them)           #
# --------------------------------------------------------------------------- #

def make_repair_record(
    *,
    iteration: int = 0,
    unsat_core: list | None = None,
    summary: str = "fix constraint",
    embedding: list | None = None,
    outcome: Outcome = Outcome.UNSAT,
    error_type: ErrorType = ErrorType.OVER_CONSTRAINT,
    target_constraint: str | None = None,
    repair_type: str = "relax_bound",
) -> RepairRecord:
    """Build a RepairRecord suitable for appending to RepairMemory in tests.

    ``core_fingerprint`` is intentionally left as an empty string because
    ``RepairMemory.append()`` always overwrites it with the correct hash.
    Providing a pre-computed ``embedding`` prevents sentence-transformers from
    being loaded — essential for keeping tests fast and GPU-free.
    """
    core = unsat_core or ["Int('x') > 5"]
    target = target_constraint or core[0]
    action = RepairAction(
        type=repair_type,
        target_constraint=target,
        summary=summary,
        embedding=embedding,
    )
    return RepairRecord(
        iteration=iteration,
        error_type=error_type,
        unsat_core=core,
        core_fingerprint="",  # overwritten by RepairMemory.append()
        repair_action=action,
        outcome=outcome,
    )


def make_paradigm(
    *,
    scope: list | None = None,
    confidence: float = 0.85,
    paradigm_id: str | None = None,
    name: str | None = None,
    support_count: int = 10,
    source_cluster: int = 0,
) -> Paradigm:
    """Build a minimal but valid Paradigm for library tests.

    ``pre_condition`` and ``operation`` use simple parseable Z3 strings so that
    tests that exercise soundness verification (``verify=True``) work correctly
    without needing a pre-populated solver state.
    """
    pid = paradigm_id or str(uuid.uuid4())
    return Paradigm(
        id=pid,
        name=name or f"paradigm-{pid[:8]}",
        trigger={"error_type": "OVER_CONSTRAINT"},
        operation="Int('x') >= 0",
        pre_condition="Int('x') > 0",
        post_condition="Int('x') >= 0",
        scope=scope or ["general"],
        confidence=confidence,
        support_count=support_count,
        source_cluster=source_cluster,
        created_at=datetime.now(tz=timezone.utc),
    )
