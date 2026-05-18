"""Tests for TrajectoryClusterer — agglomerative KDP clustering."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from prism.core.types import KDP, StepType, TrajectoryStep
from prism.offline.trajectory_clusterer import TrajectoryClusterer


# --------------------------------------------------------------------------- #
# Factory                                                                       #
# --------------------------------------------------------------------------- #

def make_kdp(feature_vector: list[float], constraint_types: list[str] | None = None) -> KDP:
    step = TrajectoryStep(
        iteration=0,
        action="infer",
        step_type=StepType.CHAIN,
        z3_result="SAT",
    )
    return KDP(
        kdp_id=str(uuid.uuid4()),
        trajectory_id="traj_0",
        puzzle_id="puzzle_0",
        step=step,
        constraint_types=constraint_types or ["unknown"],
        feature_vector=feature_vector,
        kdp_type="CHAIN",
    )


def _make_group(vec: list[float], n: int) -> list[KDP]:
    """Create n identical KDPs with a given feature vector."""
    return [make_kdp(vec) for _ in range(n)]


@pytest.fixture
def clusterer():
    return TrajectoryClusterer(theta=0.25, min_support=3)


# --------------------------------------------------------------------------- #
# Edge cases                                                                     #
# --------------------------------------------------------------------------- #

class TestEdgeCases:

    def test_empty_input_returns_empty(self, clusterer):
        assert clusterer.cluster([]) == []

    def test_single_kdp_below_support_dropped(self):
        c = TrajectoryClusterer(theta=0.25, min_support=3)
        kdps = _make_group([1.0, 0.0, 0.0], 1)
        result = c.cluster(kdps)
        assert result == []

    def test_all_identical_vectors_form_one_cluster(self, clusterer):
        kdps = _make_group([1.0, 0.0, 0.0, 0.0], n=5)
        clusters = clusterer.cluster(kdps)
        assert len(clusters) == 1
        assert clusters[0].support_count == 5


# --------------------------------------------------------------------------- #
# Clustering logic                                                               #
# --------------------------------------------------------------------------- #

class TestClusteringLogic:

    def test_orthogonal_groups_form_separate_clusters(self):
        """Vectors [1,0,0,0] and [0,0,0,1] are maximally dissimilar → separate clusters."""
        c = TrajectoryClusterer(theta=0.10, min_support=3)
        group_a = _make_group([1.0, 0.0, 0.0, 0.0], n=4)
        group_b = _make_group([0.0, 0.0, 0.0, 1.0], n=4)
        clusters = c.cluster(group_a + group_b)
        assert len(clusters) == 2

    def test_near_identical_vectors_group_together(self):
        """Slight perturbation should not split a cluster at theta=0.50."""
        c = TrajectoryClusterer(theta=0.50, min_support=2)
        group = [make_kdp([1.0 + i * 0.01, 0.0]) for i in range(5)]
        clusters = c.cluster(group)
        # All should end up in one cluster
        assert len(clusters) == 1

    def test_min_support_filters_small_clusters(self):
        """A cluster with 2 KDPs is dropped when min_support=3."""
        c = TrajectoryClusterer(theta=0.10, min_support=3)
        large = _make_group([1.0, 0.0, 0.0, 0.0], n=5)
        small = _make_group([0.0, 0.0, 0.0, 1.0], n=2)
        clusters = c.cluster(large + small)
        assert all(cl.support_count >= 3 for cl in clusters)
        assert len(clusters) == 1  # small group dropped


# --------------------------------------------------------------------------- #
# Output properties                                                              #
# --------------------------------------------------------------------------- #

class TestOutputProperties:

    def test_sorted_by_support_descending(self):
        c = TrajectoryClusterer(theta=0.10, min_support=2)
        group_a = _make_group([1.0, 0.0, 0.0, 0.0], n=6)
        group_b = _make_group([0.0, 0.0, 0.0, 1.0], n=3)
        clusters = c.cluster(group_a + group_b)
        counts = [cl.support_count for cl in clusters]
        assert counts == sorted(counts, reverse=True)

    def test_centroid_is_populated(self, clusterer):
        kdps = _make_group([1.0, 0.0, 0.0, 0.0], n=4)
        clusters = clusterer.cluster(kdps)
        assert clusters[0].centroid is not None
        assert len(clusters[0].centroid) == 4

    def test_support_count_matches_member_count(self, clusterer):
        kdps = _make_group([1.0, 0.0, 0.0, 0.0], n=5)
        clusters = clusterer.cluster(kdps)
        cl = clusters[0]
        assert cl.support_count == len(cl.kdps)

    def test_dominant_types_populated(self):
        c = TrajectoryClusterer(theta=0.50, min_support=2)
        kdps = [make_kdp([1.0, 0.0], constraint_types=["adjacent"]) for _ in range(4)]
        clusters = c.cluster(kdps)
        assert "adjacent" in clusters[0].dominant_constraint_types

    def test_cluster_ids_are_integers(self, clusterer):
        kdps = _make_group([1.0, 0.0, 0.0, 0.0], n=4)
        clusters = clusterer.cluster(kdps)
        assert all(isinstance(cl.cluster_id, int) for cl in clusters)
