# PRISM Execution Plan

This document tracks the concrete implementation steps needed to turn the
current PRISM prototype into an auditable positive/negative paradigm pipeline.

## Goal

Build a solver-grounded memory pipeline for CSP agents:

1. Run LLM+Z3 solving trajectories.
2. Record both successful and failed trajectories.
3. Distill successful reasoning into positive paradigms.
4. Distill repeated failures and UNSAT patterns into error paradigms.
5. Use both positive and negative guidance during later online solving.

## Execution Order

### 1. Pipeline Audit Script

Implement `scripts/audit_pipeline.py`.

Required output:

- Number of trajectories.
- Final result distribution.
- Solved vs failed counts.
- Translation failures.
- UNSAT failures.
- LLM call distribution.
- Step/action distribution.
- KDP count and KDP type distribution.
- Cluster counts at configurable `min_support`.
- Positive paradigm library stats if a library path is supplied.
- Error paradigm library stats if a library path is supplied.

Acceptance criteria:

- Can audit `data/trajectories/gpt4o_mini_audit`.
- Can run without making API calls.
- Produces a compact JSON report and readable console summary.

### 2. ErrorParadigm Data Model and Store

Add explicit negative memory objects.

Proposed fields:

- `id`
- `name`
- `trigger`
- `bad_operation`
- `unsat_signature`
- `avoid_instruction`
- `repair_hint`
- `scope`
- `confidence`
- `support_count`
- `source_cluster`
- `created_at`

Acceptance criteria:

- Error paradigms can be saved to and loaded from SQLite/JSON.
- Stats include total, average confidence, and scope distribution.
- Unit tests cover add, retrieve, stats, and JSON round trip.

### 3. Error Paradigm Extraction and Verification

Create an offline branch for failed trajectories.

Extraction source:

- `TrajectoryStep.step_type == CONTRADICTION`
- non-empty `unsat_core`
- failed final result, especially `UNSAT`

Verification logic:

- Verify the bad operation or full UNSAT core is actually UNSAT in Z3.
- Store canonical UNSAT core fingerprint as `unsat_signature`.
- Reject unparseable or non-reproducible error paradigms.

Acceptance criteria:

- Existing GPT-4o-mini failed trajectories produce at least one error paradigm.
- Verification is deterministic and uses no LLM calls.

### 4. Online Negative Guidance

Use error paradigms in `GuidedSolver`.

Online behavior:

- Extract current constraint types and UNSAT core.
- Retrieve matching positive paradigms as "recommended patterns".
- Retrieve matching error paradigms as "avoid patterns".
- Inject both into repair prompt.

Acceptance criteria:

- Repair prompt includes avoid instructions when matching error paradigms exist.
- Behavior is feature-gated so ablations can disable error memory.

### 5. GPT-4o-mini Small-Scale Validation

Run a controlled low-cost experiment:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts/run_offline.py --config config/quick_test.yaml --model GPT-4o-mini --n-puzzles 2 --n-runs 2 --output paradigm_store/gpt4o_mini_audit.db --trajectories data/trajectories/gpt4o_mini_audit
python scripts/audit_pipeline.py --trajectories data/trajectories/gpt4o_mini_audit --library paradigm_store/gpt4o_mini_audit.db --min-support 1,2,5
```

Acceptance criteria:

- Audit shows successful and failed trajectories.
- KDPs are extracted from contradiction steps.
- At least one error paradigm is extracted from failed trajectories.
- Full pytest suite passes.

## Research Framing

The intended contribution is not generic agent memory. It is solver-grounded
memory:

- Positive memory: verified reusable CSP solving paradigms.
- Negative memory: verified UNSAT-producing anti-patterns.
- Online guidance: use positive paradigms as "do this" and error paradigms as
  "avoid this".

This makes the memory formal, inspectable, and tied to Z3 evidence.

## Execution Log

### Completed Implementation

- Added `scripts/audit_pipeline.py` for no-API trajectory/library auditing.
- Added `ErrorParadigm` schema and `ErrorParadigmLibrary`.
- Added deterministic failed-trajectory extraction in
  `prism/offline/error_paradigm_extractor.py`.
- Added `scripts/extract_error_paradigms.py`.
- Added online negative guidance injection through `GuidedSolver`.
- Added `--error-library` support to `scripts/run_online.py`.
- Tightened GPT-4o-mini-facing prompts with strict ASCII output contracts for
  translation, repair, retranslation, semantic matching, and paradigm JSON.
- Added regression tests for error paradigm storage, extraction, and repair
  prompt injection.

### Verification Commands

```powershell
python -m py_compile prism\core\llm_client.py prism\online\guided_solver.py scripts\run_online.py
python -m pytest -q
```

Result:

- `253 passed`

### GPT-4o-mini Offline Audit V2

Command:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts\run_offline.py --config config\quick_test.yaml --model GPT-4o-mini --n-puzzles 2 --n-runs 2 --output paradigm_store\gpt4o_mini_audit_v2.db --trajectories data\trajectories\gpt4o_mini_audit_v2 --seed 52
python scripts\extract_error_paradigms.py --trajectories data\trajectories\gpt4o_mini_audit_v2 --output paradigm_store\gpt4o_mini_error_audit_v2.db --min-support 1
python scripts\audit_pipeline.py --trajectories data\trajectories\gpt4o_mini_audit_v2 --library paradigm_store\gpt4o_mini_audit_v2.db --error-library paradigm_store\gpt4o_mini_error_audit_v2.db --min-support 1,2,5 --json-out results\gpt4o_mini_audit_v2_report_with_errors.json
```

Observed result:

- Trajectories: 4
- Solved / failed: 2 / 2
- Final results: `SAT=2`, `UNSAT=2`
- LLM calls: 10 total, 2.5 mean
- KDPs: 6 contradiction KDPs
- Clusters: 3 at `min_support=1`, 2 at `min_support=2`, 0 at `min_support=5`
- Positive paradigms: 0
- Error paradigms: 5
- Error library: `paradigm_store/gpt4o_mini_error_audit_v2.db`
- Error library JSON: `paradigm_store/gpt4o_mini_error_audit_v2.json`
- Audit report: `results/gpt4o_mini_audit_v2_report_with_errors.json`

Interpretation:

- The full framework path is now visible: trajectory collection -> KDP
  extraction -> clustering -> positive library attempt -> error paradigm
  extraction -> online positive/negative guidance.
- With only 4 trajectories, the positive library is expected to remain empty
  under `min_support=5`.
- GPT-4o-mini is weak enough to create useful failed trajectories and UNSAT
  patterns, which supports the negative-memory branch.

### GPT-4o-mini Online Smoke With Error Memory

Command:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts\run_online.py --config config\quick_test.yaml --model GPT-4o-mini --library paradigm_store\gpt4o_mini_audit_v2.db --error-library paradigm_store\gpt4o_mini_error_audit_v2.db --data-dir data\hf\zebralogic\grid_mode_test.jsonl --data-source local --sizes 3x5 --max-repair 1 --output results\gpt4o_mini_error_guided_online_v2b.csv
```

Observed result:

- Puzzles evaluated: 1
- Solved: 0
- LLM calls: 2
- Repair rounds: 1
- Error library loaded: 5 paradigms
- Output CSV: `results/gpt4o_mini_error_guided_online_v2b.csv`

Interpretation:

- Before the prompt cleanup, GPT-4o-mini repeatedly failed initial translation.
- After the prompt cleanup, it produced parseable constraints and entered repair.
- The remaining failure is now a solving/repair quality issue, not a pipeline
  wiring issue.

### GPT-4o Correct-Trajectory Audit

To obtain more successful trajectories, the offline runner now supports
explicit small-puzzle generation specs:

```powershell
python scripts\run_offline.py --config config\quick_test.yaml --model GPT-4o --puzzle-specs "10:3x3:easy" --n-runs 2 --output paradigm_store\gpt4o_3x3_valid_audit.db --trajectories data\trajectories\gpt4o_3x3_valid_audit --seed 79
```

Important implementation note:

- `TrajectoryCollector` now rejects SAT models with integer assignments outside
  the puzzle range, marking them as `INVALID_MODEL` / `MODEL_OUT_OF_DOMAIN`.
- This prevents obviously invalid solver-SAT traces from polluting the positive
  memory.

Observed result for `GPT-4o`, `10:3x3:easy`, `2` runs each:

- Trajectories: 20
- Valid SAT trajectories: 12
- Invalid out-of-domain SAT models: 7
- UNSAT failures: 1
- KDPs: 14 contradiction KDPs
- Clusters: 3 at `min_support=1`, 3 at `min_support=2`, 2 at `min_support=5`
- Positive paradigms accepted by strict verifier: 0
- Error paradigms: 7
- Audit report: `results/gpt4o_3x3_valid_audit_report.json`
- Error library: `paradigm_store/gpt4o_3x3_valid_error_audit.db`

Candidate positive paradigms were exported for diagnosis:

```powershell
python scripts\run_offline.py --config config\quick_test.yaml --model GPT-4o --puzzle-specs "10:3x3:easy" --n-runs 2 --output paradigm_store\gpt4o_3x3_valid_resume.db --trajectories data\trajectories\gpt4o_3x3_valid_audit --resume --seed 79
```

Candidate diagnostic file:

- `paradigm_store/gpt4o_3x3_valid_resume_candidates.json`

Key diagnostic finding:

- `GPT-4o` consistently abstracted a plausible positive repair/check paradigm:
  `And(Int('x') >= 1, Int('x') <= 3)`.
- It had support counts `7` and `5`, effect `true`, precision `1.0`, but
  verifier soundness `0.0`.
- The immediate reason is that current soundness verification returns `0.0`
  when `pre_condition` is empty, so generic domain-bound paradigms are rejected
  even when they are useful and supported.

Next positive-memory fix:

- Separate schema invariants from reusable solving paradigms. Domain-bound
  constraints are validity guards, not Zebra reasoning strategies.

### Positive-Memory Verification Fix

Implemented:

- `ParadigmVerifier.verify_soundness()` now handles empty `pre_condition`
  candidates by checking whether the operation itself is a satisfiable Z3
  expression.
- `GuidedSolver` online pre-check now tests candidate self-consistency
  (`pre_condition ∧ operation`) instead of checking the candidate against the
  already-UNSAT full solver state.
- Added tests for empty-precondition soundness and online hint injection.

Re-run on existing `GPT-4o 3x3` trajectories:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts\run_offline.py --config config\quick_test.yaml --model GPT-4o --puzzle-specs "10:3x3:easy" --n-runs 2 --output paradigm_store\gpt4o_3x3_positive_fixed.db --trajectories data\trajectories\gpt4o_3x3_valid_audit --resume --seed 79
python scripts\audit_pipeline.py --trajectories data\trajectories\gpt4o_3x3_valid_audit --library paradigm_store\gpt4o_3x3_positive_fixed.db --error-library paradigm_store\gpt4o_3x3_valid_error_audit.db --min-support 1,2,5 --json-out results\gpt4o_3x3_positive_fixed_report.json
```

Observed result:

- Positive paradigms accepted: 2 / 2
- Positive library: `paradigm_store/gpt4o_3x3_positive_fixed.db`
- Positive library JSON: `paradigm_store/gpt4o_3x3_positive_fixed.json`
- Candidate diagnostics: `paradigm_store/gpt4o_3x3_positive_fixed_candidates.json`
- Audit report: `results/gpt4o_3x3_positive_fixed_report.json`

Accepted positive paradigms:

- `validate_domain_consistency`
  - operation: `And(Int('x') >= 1, Int('x') <= 3)`
  - support: 7
  - confidence: 1.0
- `check_domain_bounds`
  - operation: `And(Int('x') >= 1, Int('x') <= 3)`
  - support: 5
  - confidence: 1.0

Online smoke with positive + negative memory:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts\run_online.py --config config\quick_test.yaml --model GPT-4o-mini --library paradigm_store\gpt4o_3x3_positive_fixed.db --error-library paradigm_store\gpt4o_3x3_valid_error_audit.db --data-dir data\hf\zebralogic\grid_mode_test.jsonl --data-source local --sizes 3x5 --max-repair 1 --output results\gpt4o_positive_error_guided_online_smoke.csv
```

Observed result:

- Positive library loaded: 2 paradigms
- Error library loaded: 7 paradigms
- Puzzles evaluated: 1
- Solved: 0
- LLM calls: 4
- Repair rounds: 1
- Paradigm trigger rate: 0.0%

Interpretation:

- The positive-memory extraction and verification path is now working.
- This specific online smoke did not trigger the positive paradigms because the
  target `3x5` UNSAT core did not match the learned `3x3` scope tags.
- Next experiment should evaluate transfer on small `3x3`/`3x4` held-out
  puzzles or normalize the learned domain-bound paradigm into a size-parameterized
  form (`upper_bound = n_entities`) before expecting cross-size transfer.

### Schema-Invariant Filter

Correction:

- Zebra solving strategies should not depend on puzzle size.
- Constraints like `And(Int('x') >= 1, Int('x') <= 3)` are schema/domain
  validity constraints, not reusable solution paradigms.
- They should be enforced by translation validation and model checking, not
  stored as positive memory.

Implemented:

- `ParadigmVerifier.is_schema_invariant()` rejects empty-precondition pure
  domain-bound operations.
- These candidates can still appear in diagnostics, but their combined
  verification score is forced to `0.0`.
- Tests now cover that pure domain bounds are filtered while non-bound
  relational operations are not.

Re-run:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts\run_offline.py --config config\quick_test.yaml --model GPT-4o --puzzle-specs "10:3x3:easy" --n-runs 2 --output paradigm_store\gpt4o_3x3_schema_filtered.db --trajectories data\trajectories\gpt4o_3x3_valid_audit --resume --seed 79
python scripts\audit_pipeline.py --trajectories data\trajectories\gpt4o_3x3_valid_audit --library paradigm_store\gpt4o_3x3_schema_filtered.db --error-library paradigm_store\gpt4o_3x3_valid_error_audit.db --min-support 1,2,5 --json-out results\gpt4o_3x3_schema_filtered_report.json
```

Observed result:

- Candidate domain-bound patterns still diagnosed with support `7` and `5`.
- Their soundness/effect/precision can be high, but `verify=0.0` because they
  are schema invariants.
- Positive library after filtering: `0`.
- Candidate diagnostics:
  `paradigm_store/gpt4o_3x3_schema_filtered_candidates.json`
- Filtered report:
  `results/gpt4o_3x3_schema_filtered_report.json`

Updated framing:

- Positive memory should capture size-invariant reasoning patterns such as
  relative position, equality binding, exclusion, implication repair, and
  contradiction avoidance.
- Schema invariants should live in the translator/validator/oracle layer.
- Negative memory may still record schema-invariant violations as errors, but
  they should be used as "avoid invalid model/invalid formalization" guidance,
  not as positive solving paradigms.

### GPT-4o-mini Memory Ablation

Question:

- Does the current paradigm/error memory improve `GPT-4o-mini` solving accuracy?

Important setup:

- After schema-invariant filtering, the positive paradigm library is empty.
- Therefore this test mainly evaluates the current error/negative memory branch.
- Model: `GPT-4o-mini`
- Repair budget: `--max-repair 1`

Benchmark subset from local ZebraLogic test JSONL:

```powershell
$env:OPENZEBRA_API_PROVIDER='mmm'
python scripts\run_online.py --config config\quick_test.yaml --model GPT-4o-mini --library paradigm_store\gpt4o_3x3_schema_filtered.db --data-dir data\hf\zebralogic\grid_mode_test.jsonl --data-source local --sizes 2x4,3x5,4x5,5x5,5x6 --max-repair 1 --no-paradigm --output results\memory_ablation_gpt4omini_baseline.csv
python scripts\run_online.py --config config\quick_test.yaml --model GPT-4o-mini --library paradigm_store\gpt4o_3x3_schema_filtered.db --error-library paradigm_store\gpt4o_3x3_valid_error_audit.db --data-dir data\hf\zebralogic\grid_mode_test.jsonl --data-source local --sizes 2x4,3x5,4x5,5x5,5x6 --max-repair 1 --output results\memory_ablation_gpt4omini_error_memory.csv
```

Observed result:

| Setting | N | Accuracy | Mean LLM calls | Mean repair rounds |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 5 | 20.0% | 1.20 | 0.20 |
| Error memory | 5 | 20.0% | 1.20 | 0.20 |

Near-domain generated small eval set:

```powershell
python scripts\run_online.py --config config\quick_test.yaml --model GPT-4o-mini --library paradigm_store\gpt4o_3x3_schema_filtered.db --data-dir data\hf\zebralogic\generated_3x_small_eval.jsonl --data-source local --sizes 3x3,3x4 --max-repair 1 --no-paradigm --output results\memory_ablation_gpt4omini_small_baseline.csv
python scripts\run_online.py --config config\quick_test.yaml --model GPT-4o-mini --library paradigm_store\gpt4o_3x3_schema_filtered.db --error-library paradigm_store\gpt4o_3x3_valid_error_audit.db --data-dir data\hf\zebralogic\generated_3x_small_eval.jsonl --data-source local --sizes 3x3,3x4 --max-repair 1 --output results\memory_ablation_gpt4omini_small_error_memory.csv
```

Observed result:

| Setting | N | Accuracy | Mean LLM calls | Mean repair rounds |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 10 | 0.0% | 1.50 | 0.50 |
| Error memory | 10 | 0.0% | 1.30 | 0.30 |

Conclusion:

- Current memory does not improve `GPT-4o-mini` accuracy in these small tests.
- Error memory sometimes changes the repair path and lowers average calls/rounds,
  but it does not produce more correct final answers.
- The positive library is currently empty after correctly filtering schema
  invariants, so no valid positive solving experience is being tested yet.

Next diagnostic needs:

- Add explicit online metrics for `error_guidance_triggered` and
  `positive_guidance_triggered`.
- Save final Z3 result and predicted solution in online CSV.
- Mine size-invariant positive paradigms from successful non-schema steps, not
  from domain-bound repairs.
- Run repeated paired trials after the above instrumentation, because current
  `n=5` and `n=10` tests are too small for statistical claims.
