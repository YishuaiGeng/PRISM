"""Unit tests for RepairMemory.

Sentence-transformers are never loaded in this suite.  All RepairAction objects
that need embeddings receive pre-computed unit vectors so that
``RepairMemory.append()`` skips the encoder (it only calls _encode when
``action.embedding is None``), and ``detect_loop()`` uses the stored vectors
directly.
"""

from __future__ import annotations

import numpy as np
import pytest

from prism.online.repair_memory import RepairMemory, _cosine, _fingerprint
from prism.paradigm_library.schema import ErrorType, Outcome, RepairAction

from tests.conftest import make_repair_record


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

# Unit vectors whose cosine similarity is exactly 1.0 (identical direction).
_VEC_A = [1.0, 0.0, 0.0]
# Orthogonal to _VEC_A — cosine similarity = 0.0.
_VEC_B = [0.0, 1.0, 0.0]


def _action_with_vec(vec: list, summary: str = "fix", target: str = "x") -> RepairAction:
    return RepairAction(
        type="relax_bound",
        target_constraint=target,
        summary=summary,
        embedding=vec,
    )


# --------------------------------------------------------------------------- #
# Internal helper unit tests                                                    #
# --------------------------------------------------------------------------- #

class TestInternalHelpers:

    def test_fingerprint_is_order_independent(self) -> None:
        """Two cores with the same elements in different order yield equal fingerprints."""
        core = ["Int('x') > 5", "Int('y') < 3"]
        assert _fingerprint(core) == _fingerprint(list(reversed(core)))

    def test_fingerprint_differs_for_different_cores(self) -> None:
        assert _fingerprint(["a"]) != _fingerprint(["b"])

    def test_cosine_identical_vectors(self) -> None:
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert _cosine(v, v) == pytest.approx(1.0)

    def test_cosine_orthogonal_vectors(self) -> None:
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert _cosine(a, b) == pytest.approx(0.0)

    def test_cosine_zero_vector_returns_zero(self) -> None:
        zero = np.array([0.0, 0.0], dtype=np.float32)
        v    = np.array([1.0, 0.0], dtype=np.float32)
        assert _cosine(zero, v) == 0.0


# --------------------------------------------------------------------------- #
# append() — fingerprint auto-computation                                       #
# --------------------------------------------------------------------------- #

class TestAppend:

    def test_append_sets_core_fingerprint(self, memory: RepairMemory) -> None:
        """append() must overwrite the placeholder fingerprint with a real hash."""
        core = ["Int('x') > 5", "Int('x') < 3"]
        record = make_repair_record(unsat_core=core, embedding=_VEC_A)
        memory.append(record)

        stored = memory._records[0]
        assert stored.core_fingerprint == _fingerprint(core)
        assert stored.core_fingerprint != ""

    def test_append_does_not_call_encoder_when_embedding_provided(
        self, memory: RepairMemory
    ) -> None:
        """Encoder must never be initialised if embedding is pre-supplied."""
        record = make_repair_record(embedding=_VEC_A, summary="test")
        memory.append(record)

        # The lazy encoder attribute stays None — no SentenceTransformer loaded.
        assert memory._encoder is None

    def test_append_preserves_record_order(self, memory: RepairMemory) -> None:
        for i in range(3):
            memory.append(make_repair_record(iteration=i, embedding=_VEC_A))
        iterations = [r.iteration for r in memory._records]
        assert iterations == [0, 1, 2]


# --------------------------------------------------------------------------- #
# detect_stagnation()                                                           #
# --------------------------------------------------------------------------- #

class TestStagnationDetection:

    def test_stagnation_detection(self, memory: RepairMemory) -> None:
        """Three records with identical unsat_core must trigger stagnation.

        The pairwise Jaccard of identical sets is 1.0, which exceeds the default
        stagnation_jaccard threshold of 0.75.
        """
        same_core = ["Int('x') > 5", "Int('x') < 3"]
        for i in range(3):
            memory.append(make_repair_record(iteration=i, unsat_core=same_core))

        assert memory.detect_stagnation(k=3) is True

    def test_no_false_positive(self, memory: RepairMemory) -> None:
        """Records with pairwise-disjoint cores must NOT trigger stagnation.

        Each core is a singleton containing a different variable, so all pairwise
        Jaccard values are 0.0, well below the 0.75 threshold.
        """
        distinct_cores = [
            ["Int('x') > 5"],
            ["Int('y') < 0"],
            ["Int('z') == 10"],
        ]
        for i, core in enumerate(distinct_cores):
            memory.append(make_repair_record(iteration=i, unsat_core=core))

        assert memory.detect_stagnation(k=3) is False

    def test_stagnation_requires_minimum_two_records(
        self, memory: RepairMemory
    ) -> None:
        """A single record is never enough to declare stagnation."""
        memory.append(make_repair_record(unsat_core=["Int('x') > 5"]))
        assert memory.detect_stagnation(k=3) is False

    def test_stagnation_respects_window_k(self, memory: RepairMemory) -> None:
        """Stagnation in records outside the k-window must not fire the detector."""
        same_core = ["Int('x') > 5", "Int('x') < 3"]
        # Append 3 stagnating records first …
        for i in range(3):
            memory.append(make_repair_record(iteration=i, unsat_core=same_core))
        # … then 3 fresh records that escape the stagnation.
        for j in range(3, 6):
            memory.append(
                make_repair_record(
                    iteration=j, unsat_core=[f"Int('v{j}') > 0"]
                )
            )

        # Window k=3 covers only the three fresh records → no stagnation.
        assert memory.detect_stagnation(k=3) is False

    def test_partial_overlap_above_threshold_triggers_stagnation(
        self, memory: RepairMemory
    ) -> None:
        """Jaccard ≥ threshold (3/4 = 0.75) must trigger stagnation."""
        base = ["a", "b", "c"]
        # Second core shares 3 of 4 elements → Jaccard = 3/4 = 0.75 ≥ threshold.
        overlapping = ["a", "b", "c", "d"]
        memory.append(make_repair_record(iteration=0, unsat_core=base))
        memory.append(make_repair_record(iteration=1, unsat_core=overlapping))

        assert memory.detect_stagnation(k=2) is True

    def test_partial_overlap_below_threshold_no_stagnation(
        self, memory: RepairMemory
    ) -> None:
        """Jaccard < threshold (1/3 ≈ 0.33) must not trigger stagnation."""
        memory.append(make_repair_record(iteration=0, unsat_core=["a", "b"]))
        memory.append(make_repair_record(iteration=1, unsat_core=["b", "c", "d"]))

        assert memory.detect_stagnation(k=2) is False


# --------------------------------------------------------------------------- #
# detect_loop()                                                                 #
# --------------------------------------------------------------------------- #

class TestLoopDetection:

    def test_loop_detection(self, memory: RepairMemory) -> None:
        """Two records with the same embedding vector must trigger a loop.

        The cosine similarity of two identical unit vectors is 1.0, which
        exceeds the default loop_cosine threshold of 0.90.
        """
        for i in range(2):
            memory.append(
                make_repair_record(
                    iteration=i,
                    unsat_core=[f"Int('x{i}') > 0"],
                    summary="relax upper bound",
                    embedding=_VEC_A,
                )
            )

        new_action = _action_with_vec(_VEC_A, summary="relax upper bound")
        assert memory.detect_loop(new_action) is True

    def test_no_loop_for_orthogonal_embeddings(
        self, memory: RepairMemory
    ) -> None:
        """Orthogonal embeddings (cosine = 0.0) must not trigger a loop."""
        memory.append(
            make_repair_record(
                summary="relax upper bound",
                embedding=_VEC_A,
            )
        )
        new_action = _action_with_vec(_VEC_B, summary="negate condition")
        assert memory.detect_loop(new_action) is False

    def test_no_loop_when_history_has_no_embeddings(
        self, memory: RepairMemory
    ) -> None:
        """detect_loop() must return False when no stored record has an embedding."""
        # Append without an embedding so the encoder would be needed —
        # but since summary is also blank, _encode is never called.
        memory.append(make_repair_record(summary="", embedding=None))
        new_action = _action_with_vec(_VEC_A, summary="relax")
        assert memory.detect_loop(new_action) is False

    def test_no_loop_when_action_has_no_summary(
        self, memory: RepairMemory
    ) -> None:
        """Actions with an empty summary short-circuit before any embedding work."""
        memory.append(make_repair_record(summary="relax", embedding=_VEC_A))
        empty_action = RepairAction(
            type="relax_bound",
            target_constraint="x",
            summary="",
            embedding=None,
        )
        assert memory.detect_loop(empty_action) is False


# --------------------------------------------------------------------------- #
# get_history_summary()                                                         #
# --------------------------------------------------------------------------- #

class TestHistorySummary:

    def test_summary_empty_history(self, memory: RepairMemory) -> None:
        summary = memory.get_history_summary()
        assert "尚无" in summary

    def test_summary_contains_attempt_count(self, memory: RepairMemory) -> None:
        for i in range(3):
            memory.append(make_repair_record(iteration=i, summary=f"step {i}"))
        summary = memory.get_history_summary()
        assert "3" in summary
        assert "请尝试不同策略" in summary

    def test_summary_contains_each_repair_summary(
        self, memory: RepairMemory
    ) -> None:
        memory.append(make_repair_record(iteration=0, summary="relax bound"))
        memory.append(make_repair_record(iteration=1, summary="split constraint"))
        summary = memory.get_history_summary()
        assert "relax bound" in summary
        assert "split constraint" in summary


# --------------------------------------------------------------------------- #
# serialisation                                                                 #
# --------------------------------------------------------------------------- #

class TestSerialisation:

    def test_roundtrip_preserves_records(self, memory: RepairMemory) -> None:
        """to_dict → from_dict must restore all records with correct fields."""
        core = ["Int('a') > 1", "Int('b') < 0"]
        memory.append(make_repair_record(iteration=0, unsat_core=core))

        restored = RepairMemory.from_dict(memory.to_dict())

        assert len(restored._records) == 1
        rec = restored._records[0]
        assert rec.unsat_core == core
        assert rec.outcome == Outcome.UNSAT

    def test_roundtrip_with_empty_memory(
        self, memory_config: dict
    ) -> None:
        empty = RepairMemory(memory_config)
        restored = RepairMemory.from_dict(empty.to_dict())
        assert restored._records == []

    def test_to_dict_preserves_thresholds(self, memory: RepairMemory) -> None:
        d = memory.to_dict()
        assert d["config"]["stagnation_jaccard"] == 0.75
        assert d["config"]["loop_cosine"] == 0.90


# --------------------------------------------------------------------------- #
# clear() and get_successful_repairs()                                          #
# --------------------------------------------------------------------------- #

class TestMisc:

    def test_clear_removes_all_records(self, memory: RepairMemory) -> None:
        for i in range(3):
            memory.append(make_repair_record(iteration=i))
        memory.clear()
        assert memory._records == []

    def test_get_successful_repairs_filters_sat(
        self, memory: RepairMemory
    ) -> None:
        memory.append(make_repair_record(outcome=Outcome.UNSAT))
        memory.append(make_repair_record(outcome=Outcome.SAT))
        memory.append(make_repair_record(outcome=Outcome.UNSAT))

        successes = memory.get_successful_repairs()
        assert len(successes) == 1
        assert successes[0].outcome == Outcome.SAT
