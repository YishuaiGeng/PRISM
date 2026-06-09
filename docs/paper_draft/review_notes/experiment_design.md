# PRISM Diagnostic Experiments (dev-set, lightweight)

Three diagnostic experiment suites that can run on the 100-puzzle dev set within 1-2 days each and produce evidence supporting C1 (paradigm library) and C2 (repair escalation). These are not the main accuracy experiments; they are the "is the system actually doing what we say it is?" experiments.

---

## Suite A — Paradigm Library Diagnostics  (Task #22, supports C1)

Goal: prove that the library is non-trivial, diverse, and useful — not a degenerate by-product of triple verification.

Section in paper: §5.X "Paradigm Library Diagnostics" (or in Appendix if pages are tight).

### A.1 Confidence distribution

- Histogram of confidence scores across the ~35 admitted paradigms.
- Overlay the rejection rate (paradigms that failed triple verification) as a stacked bar.
- **Read**: are most paradigms barely passing (τ_s ≈ 0.90), or comfortably above? A long thin tail near 0.90 means the threshold matters; a fat distribution near 1.0 means we could safely raise τ_s.

### A.2 Trigger hit-rate ranking

- Bar chart: per-paradigm count of `(trigger_fires AND consistency_check_passes AND hint_injected)` over the dev set.
- Show top-10 most-used and bottom-10 least-used paradigms with names and one-line summaries.
- **Read**: identify "workhorse" paradigms and "dead weight" paradigms (zero or near-zero hits). Dead weight is fine if it has a coherent reason (rare constraint pattern); concerning if it suggests over-fitting to one trajectory cluster.

### A.3 Cross-scale firing distribution

- Heatmap: rows = paradigms, columns = puzzle scale ∈ {3×5, 4×4, 4×5, 5×5, 5×6, 6×6}, cell = normalized hit rate.
- **Read**: which paradigms generalize across scales (broad rows)? Which are scale-specific (one bright column)? This is direct evidence for C4 (transferability claim).

### A.4 Paradigm redundancy matrix

- Two co-firing measures:
  1. Trigger Jaccard between every pair of paradigms.
  2. Operation-text cosine similarity (embedded).
- Plot as a 35×35 heatmap with hierarchical clustering reordering.
- **Read**: clusters of high-overlap paradigms = redundancy. If three paradigms always co-fire with similar operations, they are partially redundant and should be flagged or merged.

### A.5 Dead-paradigm analysis (qualitative)

- For paradigms with zero dev-set hits, manually inspect:
  - Why did the trigger never fire?
  - Is the trigger over-specific, or is the constraint pattern truly absent in dev?
- Report 2-3 cases as a sub-table.

### Deliverables

- 4 figures (A.1 - A.4), 1 sub-table (A.5).
- ≈ 1 page in the paper or supplementary.

---

## Suite B — Repair Escalation Dynamics  (Task #23, supports C2)

Goal: prove that the four-level escalation is doing work, not just a complicated wrapper.

Section in paper: §5.Y "Repair Escalation Dynamics".

### B.1 Trigger frequency by level

- Stacked bar chart: per puzzle-scale bucket, stack the fraction of puzzles that trigger {L1 only, L2, L3, L4, never}.
- **Read**: harder puzzles should escalate more (right-shifted distribution). If L4 fires on >30% of 6×6 puzzles, the library is failing to cover hard cases.

### B.2 Per-level success rate

- For each level (L1/L2/L3/L4), fraction of triggers that *eventually* led to a SAT outcome within the remaining repair budget.
- Reported as a 4×6 matrix (level × scale).
- **Read**: a level with low success rate is either misfiring (escalating too early) or genuinely a last resort.

### B.3 Latency to success after escalation

- For puzzles where escalation eventually succeeded, histogram of "rounds between escalation trigger and SAT".
- **Read**: short latencies mean the escalation prompt actually steered the LLM out of stagnation; long latencies mean the level is more "buy time" than "fix problem".

### B.4 ErrorType × Level co-occurrence heatmap

- Rows = `ErrorType` ∈ {LegacyError, OverConstraint, SemanticFlip, ScopeError, Syntax}, columns = `SwitchLevel`.
- Cell = count of (ErrorType detected, then this level triggered).
- **Read**: should show non-random structure. E.g., `SemanticFlip` should disproportionately co-occur with L2 (switch type) since flipping a direction is a type-class change. `Syntax` should go straight to L1 or L4. If the heatmap is uniform, the routing is not adding value.

### B.5 Single-puzzle escalation timeline (case study)

- Pick one 6×6 puzzle that succeeded after L1 → L2 → L3.
- Vertical timeline: each repair round annotated with `(error_type, level_triggered, action_summary, outcome)`.
- Show the LLM hint that was injected at each escalation point.
- **Read**: a visual proof that the system is interpretable; reviewer can trace exactly how recovery happened.

### Deliverables

- 4 figures (B.1 - B.4) + 1 timeline diagram (B.5).
- ≈ 1.5 pages in the paper or supplementary.

---

## Suite C — Case Studies (Task #24, real-data replacement of Appendix D)

Goal: replace the current Appendix D placeholder numbers (94% / 86% / 85%) with actual dev-set runs that an evaluator can trust.

Section in paper: Appendix D revised.

### C.1 Successful paradigm extraction (replaces existing Case Study 1)

- Pick a 5×5 puzzle from the dev set where a paradigm was extracted and successfully reused.
- Dump for the paper:
  1. The puzzle statement (NL) and one true solution.
  2. The KDP cluster that produced this paradigm (cluster size, representative members).
  3. The LLM abstraction output (raw JSON tuple).
  4. Triple verification scores (real numbers: soundness, effect=True/False, precision).
  5. A subsequent puzzle in dev where this paradigm fired and contributed to SAT.

### C.2 Repair escalation case (replaces existing Case Study 2)

- Pick a 6×6 puzzle that failed under PRISM-no-memory baseline but succeeded under PRISM Full via L1 → L2 → L3 (or any non-trivial chain).
- Dump for the paper:
  1. Initial translation.
  2. First UNSAT core.
  3. Repair attempt → outcome → stagnation triggered.
  4. Escalation level chosen + prompt injected.
  5. Solver state at SAT.

### C.3 Negative case (NEW — supports the limitations section)

- Pick a puzzle where PRISM failed and explain why.
- This is a non-cherry-picked case study that strengthens credibility.
- Likely failure modes to look for:
  - Paradigm over-fires and misleads the LLM.
  - L4 retranslate destroys a correct translation.
  - Stagnation detector missed a real loop (canonicalisation insufficient).
- Report the dump as in C.1/C.2 and explicitly attribute the failure to one of the limitations enumerated in §6.

### Deliverables

- 3 detailed case studies replacing Appendix D, with real numbers.
- Raw logs (anonymised) attached to supplementary as JSON.

---

## Execution priority

1. **Suite B** (escalation dynamics) — supports C2, most novel claim, fastest to produce (single sweep over dev set with logging).
2. **Suite A** (library diagnostics) — supports C1, requires a completed paradigm library.
3. **Suite C** (case studies) — needs A and B to have produced runnable artifacts.

Each suite is gated on a single dev-set evaluation pass with full logging enabled. Plan for ~6 hours per pass × 3 passes = 1-2 days total, assuming one A100 / API budget for the LLM calls.
