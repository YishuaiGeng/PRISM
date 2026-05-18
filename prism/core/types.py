from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class StepType(str, Enum):
    """Classifies the nature of a trajectory step.

    BASIC covers routine constraint additions; CHAIN records multi-hop
    propagation steps; CONTRADICTION marks steps that led to UNSAT, indicating
    a reasoning error or over-constrained formulation.
    """

    BASIC = "BASIC"
    CHAIN = "CHAIN"
    CONTRADICTION = "CONTRADICTION"


class TrajectoryStep(BaseModel):
    """One solver iteration recorded during trajectory collection.

    Captures the before/after domain sizes, the Z3 verdict, and which
    constraint was mutated so that KDPIdentifier can locate high-impact steps.
    """

    iteration: int
    action: str
    step_type: StepType
    constraint_added: Optional[str] = None
    constraint_removed: Optional[str] = None
    constraint_modified: Optional[str] = None
    z3_result: str
    unsat_core: Optional[List[str]] = None
    domain_sizes_before: Dict[str, int] = Field(default_factory=dict)
    domain_sizes_after: Dict[str, int] = Field(default_factory=dict)
    llm_call_count: int = 0
    error_type: Optional[str] = None


class Trajectory(BaseModel):
    """Complete solving trajectory for a single puzzle run.

    One puzzle may produce several Trajectories when collected at
    temperature > 0.0 (diversity sampling).
    """

    trajectory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    puzzle_id: str
    puzzle_nl: str
    temperature: float
    seed: int
    steps: List[TrajectoryStep] = Field(default_factory=list)
    final_result: str = "UNKNOWN"
    solved: bool = False
    total_llm_calls: int = 0
    solution: Optional[Dict[str, str]] = None


class KDP(BaseModel):
    """Key Decision Point extracted from a trajectory.

    A KDP is a step where domain sizes dropped sharply (≥2 for any variable)
    or whose step_type is CHAIN or CONTRADICTION — moments where the solver made
    a non-trivial inference that can be generalised into a paradigm.
    """

    kdp_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trajectory_id: str
    puzzle_id: str
    step: TrajectoryStep
    constraint_types: List[str]
    feature_vector: List[float]
    kdp_type: str


class Cluster(BaseModel):
    """A group of structurally similar KDPs produced by agglomerative clustering."""

    cluster_id: int
    kdps: List[KDP]
    centroid: Optional[List[float]] = None
    support_count: int = 0
    dominant_constraint_types: List[str] = Field(default_factory=list)

    def model_post_init(self, __context: Any) -> None:
        if self.support_count == 0:
            object.__setattr__(self, "support_count", len(self.kdps))


class SolverState(BaseModel):
    """Snapshot of the constraint solver at a given moment during online inference."""

    puzzle_id: str
    constraints: List[str]
    domain_sizes: Dict[str, int] = Field(default_factory=dict)
    unsat_core: Optional[List[str]] = None
    z3_result: str = "UNKNOWN"
    iteration: int = 0
    constraint_types: List[str] = Field(default_factory=list)
    problem_nl: str = ""


class PuzzleInstance(BaseModel):
    """A single puzzle problem to be solved or used as training data."""

    puzzle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nl_description: str
    variables: List[str] = Field(default_factory=list)
    domains: Dict[str, List[str]] = Field(default_factory=dict)
    constraints_nl: List[str] = Field(default_factory=list)
    solution: Optional[Dict[str, str]] = None
    size: str = ""
    difficulty: Optional[str] = None
    domain: str = "zebralogic"
    raw_data: Optional[Dict[str, Any]] = None


class SolveResult(BaseModel):
    """The outcome of running GuidedSolver on a PuzzleInstance."""

    puzzle_id: str
    solved: bool
    solution: Optional[Dict[str, str]] = None
    total_llm_calls: int = 0
    repair_rounds: int = 0
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    final_z3_result: str = "UNKNOWN"
    paradigm_triggered: bool = False
    stagnation_detected: bool = False
    error: Optional[str] = None
