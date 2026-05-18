from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel


class ErrorType(str, Enum):
    """Classifies the category of constraint error encountered during SMT solving.

    Used to route repair strategies: syntax errors require re-parsing, over/under
    constraints need scope adjustment, semantic flips indicate sign/direction bugs,
    scope errors reflect variable binding issues, and LEGACY covers unclassified cases
    from earlier pipeline versions.
    """

    SYNTAX = "SYNTAX"
    OVER_CONSTRAINT = "OVER_CONSTRAINT"
    UNDER_CONSTRAINT = "UNDER_CONSTRAINT"
    SEMANTIC_FLIP = "SEMANTIC_FLIP"
    SCOPE_ERROR = "SCOPE_ERROR"
    LEGACY = "LEGACY"


class Outcome(str, Enum):
    """The satisfiability result returned by the Z3 solver after a repair attempt.

    SAT means the constraint set is satisfiable (repair succeeded or problem is
    solvable); UNSAT means the solver proved unsatisfiability, indicating the repair
    did not resolve the conflict.
    """

    SAT = "SAT"
    UNSAT = "UNSAT"


class RepairAction(BaseModel):
    """Describes a single atomic repair applied to a constraint during a solver iteration.

    Captures both the symbolic description of the edit (type, target, summary) and
    an optional dense embedding of the action for similarity-based paradigm retrieval.
    """

    type: str
    target_constraint: str
    summary: str
    embedding: Optional[List[float]] = None


class RepairRecord(BaseModel):
    """A complete record of one repair attempt within a solver trajectory.

    Links the error diagnosis (error_type, unsat_core, core_fingerprint) to the
    repair that was applied (repair_action) and the resulting solver outcome. The
    core_fingerprint is a canonical hash of unsat_core used for fast deduplication
    and paradigm matching. new_core is populated only when outcome is UNSAT, holding
    the residual unsatisfied constraints for the next iteration.
    """

    iteration: int
    error_type: ErrorType
    unsat_core: List[str]
    core_fingerprint: str
    repair_action: RepairAction
    outcome: Outcome
    new_core: Optional[List[str]] = None


class Paradigm(BaseModel):
    """A reusable repair pattern mined from historical solver trajectories.

    Encodes a generalised fix strategy: when a constraint cluster matching `trigger`
    appears in an UNSAT core, apply `operation` subject to `pre_condition`, expecting
    `post_condition` to hold afterwards. Confidence and support_count track empirical
    reliability; source_cluster links back to the offline mining cluster from which
    the paradigm was abstracted.
    """

    id: str
    name: str
    trigger: dict
    operation: str
    pre_condition: str
    post_condition: str
    scope: List[str]
    confidence: float
    support_count: int
    source_cluster: int
    created_at: datetime
