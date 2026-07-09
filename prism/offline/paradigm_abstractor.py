"""LLM-driven paradigm abstraction from KDP clusters.

Takes a :class:`~prism.core.types.Cluster` (a group of structurally similar KDPs),
samples up to ``n_samples`` representative examples, and prompts the LLM to
abstract a general solving strategy.  The JSON response is parsed into a
:class:`~prism.paradigm_library.schema.Paradigm` object ready for Z3 verification.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.types import KDP, Cluster
from prism.paradigm_library.schema import Paradigm

logger = logging.getLogger(__name__)

_DEFAULT_N_SAMPLES: int = 10
_PARADIGM_ID_PREFIX: str = "P"

# Trigger selectivity: keep only constraint types shared by a majority of the
# cluster's KDPs, capped at the most frequent few. Taking the raw union makes
# the trigger fire everywhere on heterogeneous states (AR-LSAT games carry
# 10+ constraint types per state) and the paradigm then fails the
# trigger-precision screen.
_MAX_TRIGGER_TYPES: int = 4
_TRIGGER_TYPE_MIN_FRACTION: float = 0.5


class ParadigmAbstractor:
    """Prompts an LLM to abstract a paradigm from a cluster of KDPs.

    Args:
        llm_client: Pre-configured :class:`~prism.core.llm_client.LLMClient`
            for making abstraction requests.
        n_samples: Maximum number of KDPs to include in the prompt.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        n_samples: int = _DEFAULT_N_SAMPLES,
    ) -> None:
        self._llm = llm_client
        self._n_samples = n_samples
        self._paradigm_counter: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def abstract(self, cluster: Cluster, max_retries: int = 2) -> Optional[Paradigm]:
        """Attempt to abstract a paradigm from *cluster*.

        Args:
            cluster: A supported cluster of similar KDPs.
            max_retries: Additional LLM attempts when the response cannot be
                parsed or lacks required fields (paper: up to 2 retries).

        Returns:
            A :class:`~prism.paradigm_library.schema.Paradigm` object, or
            ``None`` if no attempt produced a complete paradigm.
        """
        samples = self._sample(cluster.kdps)
        for attempt in range(1 + max_retries):
            response = self._llm.abstract_paradigm(samples)
            parsed = LLMClient.parse_paradigm_json(response)
            if parsed is None:
                logger.warning(
                    "Cluster %d: failed to parse paradigm JSON (attempt %d/%d).",
                    cluster.cluster_id, attempt + 1, 1 + max_retries,
                )
                continue
            paradigm = self._build_paradigm(parsed, cluster)
            if paradigm is not None:
                return paradigm
            logger.warning(
                "Cluster %d: incomplete paradigm fields (attempt %d/%d).",
                cluster.cluster_id, attempt + 1, 1 + max_retries,
            )
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sample(self, kdps: List[KDP]) -> List[KDP]:
        """Sample up to ``n_samples`` KDPs, preferring structural diversity."""
        if len(kdps) <= self._n_samples:
            return kdps
        step = max(1, len(kdps) // self._n_samples)
        return kdps[::step][: self._n_samples]

    @staticmethod
    def _dominant_types(kdps: List[KDP]) -> List[str]:
        """Constraint types shared by a majority of *kdps*, most frequent first.

        Falls back to the top few most frequent types when no type clears the
        majority threshold, so a paradigm never ends up with an empty trigger
        merely because its cluster is heterogeneous.
        """
        counts: Counter = Counter(
            ctype
            for kdp in kdps
            for ctype in set(kdp.constraint_types)
            if ctype and ctype != "unknown"
        )
        if not counts:
            return []
        threshold = _TRIGGER_TYPE_MIN_FRACTION * len(kdps)
        dominant = [t for t, c in counts.most_common() if c >= threshold]
        selected = dominant or [t for t, _ in counts.most_common()]
        return sorted(selected[:_MAX_TRIGGER_TYPES])

    def _build_paradigm(self, data: dict, cluster: Cluster) -> Optional[Paradigm]:
        """Assemble a Paradigm from the parsed LLM JSON and cluster metadata."""
        required = {"name", "operation", "pre_condition", "post_condition", "scope", "trigger"}
        if not required.issubset(data.keys()):
            missing = required - set(data.keys())
            logger.debug("Paradigm missing fields: %s", missing)
            return None

        scope = data.get("scope", [])
        if isinstance(scope, str):
            scope = [scope]

        # Anchor trigger types and scope in the cluster's own KDP tag
        # namespace instead of trusting LLM free-form labels: retrieval
        # matches paradigm scope against online-extracted tags, so both
        # sides must share one vocabulary.
        cluster_types = self._dominant_types(cluster.kdps)
        trigger = data["trigger"] if isinstance(data["trigger"], dict) else {}
        if cluster_types:
            trigger = {**trigger, "constraint_types": cluster_types}
            scope = cluster_types

        self._paradigm_counter += 1
        pid = f"{_PARADIGM_ID_PREFIX}-{self._paradigm_counter:03d}"

        return Paradigm(
            id=pid,
            name=data["name"],
            trigger=trigger,
            operation=data["operation"],
            pre_condition=data["pre_condition"],
            post_condition=data["post_condition"],
            scope=scope,
            confidence=0.0,
            support_count=cluster.support_count,
            source_cluster=cluster.cluster_id,
            created_at=datetime.now(tz=timezone.utc),
        )
