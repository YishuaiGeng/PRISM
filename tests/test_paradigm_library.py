"""Unit tests for ParadigmLibrary.

All tests use an in-memory SQLite store (":memory:") via the ``lib`` fixture,
so no files are created in the test environment.  Persistence tests that must
exercise save/load use ``tmp_path`` (a pytest built-in) for real file I/O.
"""

from __future__ import annotations

import json
import uuid

import pytest

from prism.core.solver import Z3SolverWrapper
from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import Paradigm

from tests.conftest import make_paradigm


# --------------------------------------------------------------------------- #
# add() and basic retrieval                                                     #
# --------------------------------------------------------------------------- #

class TestAddAndRetrieve:

    def test_add_and_retrieve(self, lib: ParadigmLibrary) -> None:
        """A paradigm added to the library must appear in retrieve() results."""
        p = make_paradigm(scope=["scheduling"], confidence=0.90)
        assert lib.add(p, verify=False) is True

        results = lib.retrieve(["scheduling"], top_k=3)

        ids = [r.id for r in results]
        assert p.id in ids

    def test_retrieve_empty_library_returns_empty_list(
        self, lib: ParadigmLibrary
    ) -> None:
        assert lib.retrieve(["scheduling"]) == []

    def test_add_returns_false_on_failed_soundness(
        self, solver: Z3SolverWrapper
    ) -> None:
        """A paradigm whose operation is always UNSAT must be rejected when verify=True."""
        # threshold=1.1 is above any possible score → every paradigm is rejected.
        with ParadigmLibrary(":memory:", solver, soundness_threshold=1.1) as strict:
            p = make_paradigm(confidence=0.99)
            assert strict.add(p, verify=True) is False
            assert strict.get_all() == []

    def test_add_verify_false_bypasses_soundness(
        self, lib: ParadigmLibrary
    ) -> None:
        """verify=False must store the paradigm regardless of soundness score."""
        p = make_paradigm(confidence=0.10)
        assert lib.add(p, verify=False) is True
        assert len(lib.get_all()) == 1

    def test_add_duplicate_id_replaces_existing(
        self, lib: ParadigmLibrary
    ) -> None:
        """INSERT OR REPLACE semantics: second add with same id overwrites first."""
        pid = str(uuid.uuid4())
        lib.add(make_paradigm(paradigm_id=pid, confidence=0.70), verify=False)
        lib.add(make_paradigm(paradigm_id=pid, confidence=0.95), verify=False)

        all_p = lib.get_all()
        assert len(all_p) == 1
        assert all_p[0].confidence == 0.95


# --------------------------------------------------------------------------- #
# retrieve() ranking                                                            #
# --------------------------------------------------------------------------- #

class TestRetrieveRanking:

    def test_confidence_filter(self, lib: ParadigmLibrary) -> None:
        """When two paradigms share the same scope, the higher-confidence one
        must rank first and be the sole result when top_k=1.

        Both paradigms have a Jaccard score of 1.0 against the query ["scheduling"],
        so the weighted score is differentiated entirely by confidence:
            score = 0.60 * 1.0 + 0.40 * confidence
        High confidence (0.95) → 0.98 > Low confidence (0.10) → 0.64.
        """
        high = make_paradigm(scope=["scheduling"], confidence=0.95)
        low  = make_paradigm(scope=["scheduling"], confidence=0.10)
        lib.add(high, verify=False)
        lib.add(low,  verify=False)

        results = lib.retrieve(["scheduling"], top_k=1)

        assert len(results) == 1
        assert results[0].id == high.id

    def test_scope_overlap_improves_ranking(self, lib: ParadigmLibrary) -> None:
        """A paradigm with matching scope must outrank one with no overlap,
        even when the non-matching paradigm has higher confidence.
        """
        matching    = make_paradigm(scope=["scheduling"],    confidence=0.60)
        non_matching = make_paradigm(scope=["unrelated"],   confidence=0.99)
        lib.add(matching,     verify=False)
        lib.add(non_matching, verify=False)

        # The score for matching:     0.60*1.0 + 0.40*0.60 = 0.84
        # The score for non-matching: 0.60*0.0 + 0.40*0.99 = 0.396
        results = lib.retrieve(["scheduling"], top_k=1)
        assert results[0].id == matching.id

    def test_top_k_limits_results(self, lib: ParadigmLibrary) -> None:
        for _ in range(5):
            lib.add(make_paradigm(scope=["a"]), verify=False)
        assert len(lib.retrieve(["a"], top_k=3)) == 3

    def test_retrieve_returns_at_most_available_paradigms(
        self, lib: ParadigmLibrary
    ) -> None:
        lib.add(make_paradigm(), verify=False)
        results = lib.retrieve(["general"], top_k=10)
        assert len(results) == 1

    def test_retrieve_no_scope_overlap_falls_back_to_confidence(
        self, lib: ParadigmLibrary
    ) -> None:
        """When no paradigm matches the query scope, retrieve must not crash
        and must still return the highest-confidence paradigm."""
        lib.add(make_paradigm(scope=["logic"],       confidence=0.80), verify=False)
        lib.add(make_paradigm(scope=["arithmetic"],  confidence=0.50), verify=False)

        results = lib.retrieve(["scheduling"], top_k=1)
        assert len(results) == 1
        assert results[0].confidence == 0.80


# --------------------------------------------------------------------------- #
# update_confidence() and delete()                                              #
# --------------------------------------------------------------------------- #

class TestUpdateAndDelete:

    def test_update_confidence(self, lib: ParadigmLibrary) -> None:
        p = make_paradigm(confidence=0.70)
        lib.add(p, verify=False)

        lib.update_confidence(p.id, 0.95)

        updated = lib.get_all()[0]
        assert updated.confidence == pytest.approx(0.95)

    def test_update_confidence_raises_for_unknown_id(
        self, lib: ParadigmLibrary
    ) -> None:
        with pytest.raises(KeyError):
            lib.update_confidence("nonexistent-id", 0.50)

    def test_delete_removes_paradigm(self, lib: ParadigmLibrary) -> None:
        p = make_paradigm()
        lib.add(p, verify=False)
        assert len(lib.get_all()) == 1

        lib.delete(p.id)

        assert lib.get_all() == []

    def test_delete_nonexistent_is_idempotent(
        self, lib: ParadigmLibrary
    ) -> None:
        """delete() must not raise for an id that does not exist."""
        lib.delete("does-not-exist")  # should not raise


# --------------------------------------------------------------------------- #
# save_json / load_json persistence                                             #
# --------------------------------------------------------------------------- #

class TestPersistence:

    def test_persistence(
        self, lib: ParadigmLibrary, tmp_path, solver: Z3SolverWrapper
    ) -> None:
        """Paradigms saved to JSON and loaded into a fresh library must be intact."""
        p = make_paradigm(scope=["logic"], confidence=0.88, support_count=42)
        lib.add(p, verify=False)

        json_path = str(tmp_path / "paradigms.json")
        lib.save_json(json_path)

        with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as fresh:
            count = fresh.load_json(json_path)

            assert count == 1
            loaded = fresh.get_all()
            assert len(loaded) == 1
            assert loaded[0].id            == p.id
            assert loaded[0].confidence    == pytest.approx(p.confidence)
            assert loaded[0].support_count == p.support_count
            assert loaded[0].scope         == p.scope

    def test_save_json_produces_valid_json(
        self, lib: ParadigmLibrary, tmp_path
    ) -> None:
        """save_json() output must be parseable as a JSON array."""
        lib.add(make_paradigm(), verify=False)
        path = str(tmp_path / "out.json")
        lib.save_json(path)

        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

        assert isinstance(data, list)
        assert len(data) == 1
        assert "id" in data[0]
        assert "confidence" in data[0]

    def test_load_json_multiple_paradigms(
        self, lib: ParadigmLibrary, tmp_path, solver: Z3SolverWrapper
    ) -> None:
        for _ in range(3):
            lib.add(make_paradigm(), verify=False)
        path = str(tmp_path / "multi.json")
        lib.save_json(path)

        with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as fresh:
            count = fresh.load_json(path)
            assert count == 3
            assert len(fresh.get_all()) == 3

    def test_roundtrip_preserves_trigger_and_scope(
        self, lib: ParadigmLibrary, tmp_path, solver: Z3SolverWrapper
    ) -> None:
        """JSON-serialised trigger dict and scope list must round-trip exactly."""
        p = make_paradigm(scope=["scheduling", "resource"])
        lib.add(p, verify=False)
        path = str(tmp_path / "rt.json")
        lib.save_json(path)

        with ParadigmLibrary(":memory:", solver, soundness_threshold=0.0) as fresh:
            fresh.load_json(path)
            loaded = fresh.get_all()[0]
            assert loaded.trigger == p.trigger
            assert loaded.scope   == p.scope


# --------------------------------------------------------------------------- #
# stats()                                                                       #
# --------------------------------------------------------------------------- #

class TestStats:

    def test_stats_empty_library(self, lib: ParadigmLibrary) -> None:
        s = lib.stats()
        assert s["total"] == 0
        assert s["avg_confidence"] == 0.0
        assert s["scope_distribution"] == {}

    def test_stats_total_and_avg_confidence(self, lib: ParadigmLibrary) -> None:
        lib.add(make_paradigm(confidence=0.80), verify=False)
        lib.add(make_paradigm(confidence=0.60), verify=False)

        s = lib.stats()
        assert s["total"] == 2
        assert s["avg_confidence"] == pytest.approx(0.70, abs=1e-4)

    def test_stats_scope_distribution(self, lib: ParadigmLibrary) -> None:
        lib.add(make_paradigm(scope=["scheduling"]),             verify=False)
        lib.add(make_paradigm(scope=["scheduling", "resource"]), verify=False)
        lib.add(make_paradigm(scope=["resource"]),               verify=False)

        dist = lib.stats()["scope_distribution"]
        assert dist["scheduling"] == 2
        assert dist["resource"]   == 2
