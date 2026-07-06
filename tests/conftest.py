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

from prism.core.llm_client import LLMClient
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


# --------------------------------------------------------------------------- #
# Mock LLM client for trajectory collection tests                              #
# --------------------------------------------------------------------------- #


class MockLLMClient(LLMClient):
    """Mock LLM client for testing that returns safe, deterministic responses."""

    def __init__(self) -> None:
        """Initialize with empty call count and placeholder model."""
        # Don't call parent __init__ to avoid needing real model config
        self._call_count = 0
        self.model = "mock-gpt-4"

    def translate(self, *args, **kwargs) -> str:
        """Return a valid mock translation that is satisfiable."""
        self._call_count += 1
        # Return basic domain constraints for a 3-house puzzle
        return 'And(Int("color_Red") >= 1, Int("color_Red") <= 3, Int("color_Blue") >= 1, Int("color_Blue") <= 3, Int("color_Green") >= 1, Int("color_Green") <= 3, Distinct(Int("color_Red"), Int("color_Blue"), Int("color_Green")), Int("color_Red") == 1)'

    def repair(self, *args, **kwargs) -> str:
        """Return a simple repair that adds a Distinct constraint if not present."""
        self._call_count += 1
        # Just relax the constraint space by returning an empty repair (no-op)
        # This ensures the puzzle eventually becomes solvable
        return ""

    def generate_repair_candidates(self, **kwargs) -> list[str]:
        """Not used in these tests."""
        self._call_count += 1
        return []


@pytest.fixture
def mock_llm_client() -> MockLLMClient:
    """Fresh MockLLMClient for each test."""
    return MockLLMClient()
