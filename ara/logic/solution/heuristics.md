# Heuristics

## H01: Use a four-outcome evaluation ledger
- **Rationale**: Separating correct answers, SBW, gate rejection, and other non-answers prevents parsing failures or UNSAT states from being misclassified as deliberate abstention, and makes every run auditable.
- **Provenance**: ai-suggested
- **Sensitivity**: high
- **Code ref**: [`scripts/rescore_zebra_results.py`, `docs/paper_draft/sparc_paper_zh.tex`]

## H02: Gate only the projected answer variables
- **Rationale**: Blocking auxiliary variables can create apparent model multiplicity without changing the task answer. The gate must operate on an explicit answer projection.
- **Provenance**: ai-suggested
- **Sensitivity**: high
- **Code ref**: [`prism/online/guided_solver.py`, `docs/paper_draft/sparc_paper_zh.tex`]

## H03: Treat discriminative completion as complete-model filtering until the interface is constrained
- **Rationale**: A candidate that excludes one of two complete models need not remove an answer projection when it can reference auxiliary variables. Report full-model progress, not projected-answer contraction, until an answer-variable whitelist is mechanically enforced.
- **Provenance**: ai-suggested
- **Sensitivity**: high
- **Code ref**: [`prism/online/guided_solver.py`, `scripts/audit_sparc_evidence.py`, `docs/paper_draft/sparc_paper_zh.tex`]
