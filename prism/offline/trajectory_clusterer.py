"""Agglomerative clustering of KDPs for paradigm library construction.

Groups structurally similar Key Decision Points by their constraint-type feature
vectors using cosine distance.  Clusters with fewer than ``min_support`` members
are dropped — they represent isolated edge cases unlikely to yield a robust
generalizable paradigm.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import List

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

from prism.core.types import KDP, Cluster

logger = logging.getLogger(__name__)

_DEFAULT_THETA: float = 0.25
_DEFAULT_MIN_SUPPORT: int = 5


class TrajectoryClusterer:
    """Cluster KDPs by cosine distance on their constraint-type feature vectors.

    Args:
        theta: Distance threshold for agglomerative clustering.  A smaller value
            produces tighter, more homogeneous clusters; a larger value merges
            more KDPs into each cluster.  Paper default: 0.25.
        min_support: Minimum number of KDPs required for a cluster to be retained.
            Clusters below this threshold are discarded.
    """

    def __init__(
        self,
        theta: float = _DEFAULT_THETA,
        min_support: int = _DEFAULT_MIN_SUPPORT,
    ) -> None:
        self._theta = theta
        self._min_support = min_support

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cluster(self, kdps: List[KDP]) -> List[Cluster]:
        """Cluster *kdps* and return supported clusters.

        Args:
            kdps: List of KDP objects to cluster.  Each must have a non-empty
                ``feature_vector`` field.

        Returns:
            List of :class:`~prism.core.types.Cluster` objects sorted by
            ``support_count`` descending.  Clusters with fewer than
            ``min_support`` members are excluded.
        """
        if not kdps:
            return []

        matrix = self._build_matrix(kdps)
        labels = self._fit(matrix)
        clusters = self._build_clusters(kdps, labels, matrix)

        supported = [c for c in clusters if c.support_count >= self._min_support]
        supported.sort(key=lambda c: c.support_count, reverse=True)

        logger.info(
            "Clustered %d KDPs → %d raw clusters → %d with support ≥ %d",
            len(kdps), len(set(labels)), len(supported), self._min_support,
        )
        return supported

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_matrix(kdps: List[KDP]) -> np.ndarray:
        """Stack feature vectors into a normalized matrix for cosine clustering."""
        vectors = np.array([kdp.feature_vector for kdp in kdps], dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms

    def _fit(self, matrix: np.ndarray) -> np.ndarray:
        """Run agglomerative clustering and return per-KDP cluster labels."""
        if len(matrix) == 1:
            return np.array([0])
        clusterer = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="complete",
            distance_threshold=self._theta,
        )
        return clusterer.fit_predict(matrix)

    @staticmethod
    def _build_clusters(
        kdps: List[KDP],
        labels: np.ndarray,
        matrix: np.ndarray,
    ) -> List[Cluster]:
        """Assemble Cluster objects from per-KDP label assignments."""
        groups: dict[int, List[int]] = {}
        for idx, label in enumerate(labels):
            groups.setdefault(int(label), []).append(idx)

        clusters: List[Cluster] = []
        for cluster_id, indices in groups.items():
            members = [kdps[i] for i in indices]
            centroid = matrix[indices].mean(axis=0).tolist()
            all_types = [ct for kdp in members for ct in kdp.constraint_types]
            dominant = [t for t, _ in Counter(all_types).most_common(3)]
            clusters.append(Cluster(
                cluster_id=cluster_id,
                kdps=members,
                centroid=centroid,
                support_count=len(members),
                dominant_constraint_types=dominant,
            ))
        return clusters
