"""LLM-driven paradigm abstraction from KDP clusters.

Takes a :class:`~prism.core.types.Cluster` (a group of structurally similar KDPs),
samples up to ``n_samples`` representative examples, and prompts the LLM to
abstract a general solving strategy.  The JSON response is parsed into a
:class:`~prism.paradigm_library.schema.Paradigm` object ready for Z3 verification.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from prism.core.llm_client import LLMClient
from prism.core.types import KDP, Cluster
from prism.paradigm_library.schema import Paradigm

logger = logging.getLogger(__name__)

_DEFAULT_N_SAMPLES: int = 10
_PARADIGM_ID_PREFIX: str = "P"


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

    def abstract(self, cluster: Cluster) -> Optional[Paradigm]:
        """Attempt to abstract a paradigm from *cluster*.

        Args:
            cluster: A supported cluster of similar KDPs.

        Returns:
            A :class:`~prism.paradigm_library.schema.Paradigm` object, or
            ``None`` if the LLM response could not be parsed.
        """
        samples = self._sample(cluster.kdps)
        response = self._llm.abstract_paradigm(samples)
        parsed = LLMClient.parse_paradigm_json(response)
        if parsed is None:
            logger.warning("Cluster %d: failed to parse paradigm JSON.", cluster.cluster_id)
            return None

        paradigm = self._build_paradigm(parsed, cluster)
        if paradigm is None:
            logger.warning("Cluster %d: incomplete paradigm fields.", cluster.cluster_id)
        return paradigm

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sample(self, kdps: List[KDP]) -> List[KDP]:
        """Sample up to ``n_samples`` KDPs, preferring structural diversity."""
        if len(kdps) <= self._n_samples:
            return kdps
        step = max(1, len(kdps) // self._n_samples)
        return kdps[::step][: self._n_samples]

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

        self._paradigm_counter += 1
        pid = f"{_PARADIGM_ID_PREFIX}-{self._paradigm_counter:03d}"

        return Paradigm(
            id=pid,
            name=data["name"],
            trigger=data["trigger"],
            operation=data["operation"],
            pre_condition=data["pre_condition"],
            post_condition=data["post_condition"],
            scope=scope,
            confidence=0.0,
            support_count=cluster.support_count,
            source_cluster=cluster.cluster_id,
            created_at=datetime.now(tz=timezone.utc),
        )
