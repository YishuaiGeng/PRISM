# Memory Effect Optimization TODO

Goal: make PRISM's memory effects measurable and improve the chance of
accuracy gains for GPT-4o-mini.

## 1. Separate Valid Positive Paradigms From Schema Invariants

Status: completed for prompt and verifier guard.

Tasks:

- Keep domain bounds and all-different constraints in schema/validation layers.
- Reject schema invariants from positive paradigm ingestion.
- Bias abstraction toward size-invariant Zebra reasoning patterns:
  relative position, adjacency, equality binding, exclusion, implication repair.

Acceptance:

- Domain-bound candidates remain visible in diagnostics but are not stored.
- Abstractor prompt explicitly forbids domain bounds and all-different as
  positive paradigms.

## 2. Mine Positive KDPs From Successful Repairs

Status: implemented; awaiting trajectories with solved repair steps.

Tasks:

- Add successful-repair KDP extraction.
- Source examples should be repair steps where:
  `z3_result == SAT`, a constraint was added/replaced, and the trajectory solved.
- Label these as `SUCCESSFUL_REPAIR` rather than `CONTRADICTION`.

Acceptance:

- Successful repair KDPs appear in audit reports.
- Positive abstraction can cluster repaired constraints separately from failure
  states.

Current observation:

- Existing `gpt4o_3x3_valid_audit` trajectories contain valid direct-SAT runs
  and invalid/failed repair runs, but no `solved=True` repair step. The extractor
  is ready, but new data is needed to populate `SUCCESSFUL_REPAIR` KDPs.

## 3. Instrument Online Guidance

Status: completed.

Tasks:

- Track `positive_guidance_triggered`.
- Track `error_guidance_triggered`.
- Track `final_z3_result`, `translation_failed`, and repair outcome in CSV.
- Preserve current aggregate metrics.

Acceptance:

- Online CSV can show whether memory actually entered the repair prompt.
- Ablation reports can distinguish "memory loaded" from "memory used".

Implemented CSV fields:

- `final_z3_result`
- `translation_failed`
- `repair_success`
- `positive_guidance_triggered`
- `error_guidance_triggered`
- `ground_truth`
- `predicted`

## 4. Re-run Paired GPT-4o-mini Ablations

Status: ready to rerun after mining real positive paradigms.

Tasks:

- Baseline.
- Schema guard only.
- Negative/error memory.
- Positive memory.
- Positive + negative memory.

Acceptance:

- Compare accuracy, repair success, invalid-model rate, guidance trigger rate,
  and LLM calls.
- Do not claim accuracy improvement unless paired trials show it.

## 5. Improve Error Guidance Actionability

Status: completed initial pass.

Tasks:

- Convert generic "inspect this constraint" hints into relation-level repair
  templates.
- Detect common Zebra formalization mistakes:
  symmetric `Or(...)` for directed clues, wrong `+/-1` orientation, mistaken
  equality for relative clues, and inappropriate `+/-2` gap relations.
- Update the repair prompt to treat verified error patterns as negative
  examples and use repair hints as preferred templates.

Acceptance:

- Error paradigm JSON contains actionable repair hints.
- Repair prompt explicitly tells GPT-4o-mini not to repeat `bad_operation`.

Artifacts:

- `paradigm_store/gpt4o_3x3_error_actionable.db`
- `paradigm_store/gpt4o_3x3_error_actionable.json`

Observation:

- The enhanced hints are more interpretable, but a 3x3 smoke test still showed
  `0/5` accuracy. The bottleneck shifted toward SAT-but-invalid initial
  translations rather than only UNSAT repair failures.

## 6. Add Online Invalid-Model Guard

Status: completed conservative guard.

Tasks:

- Treat SAT models with integer assignments outside puzzle range as
  `INVALID_MODEL`, not successful solver outputs.
- Surface this in online CSV through `final_z3_result`.

Acceptance:

- Online CSV distinguishes `SAT` from `INVALID_MODEL`.
- SAT-but-wrong runs no longer look like successful solver states.

Artifacts:

- `results/online_guard_actionable_smoke.csv`

Observed 3x3 smoke comparison:

| Run | Final SAT | INVALID_MODEL | UNSAT | Error guidance triggered |
| --- | ---: | ---: | ---: | ---: |
| Before online guard | 4 | 0 | 1 | 1 |
| After online guard | 0 | 4 | 1 | 2 |

Interpretation:

- Many GPT-4o-mini failures are invalid-model failures caused by incomplete or
  schema-invalid translations.
- This gives a clearer next ablation axis: schema guard / invalid-model repair
  should be evaluated separately from memory guidance.

## 7. Invalid-Model Recovery

Status: completed conservative first pass.

Tasks:

- When initial translation is `SAT` but model values are outside the puzzle
  range, run one full retranslation if repair budget allows.
- Make the retranslation prompt explicitly require domain bounds,
  all-different constraints, and consistent variable names.

Acceptance:

- `INVALID_MODEL` can be reduced without mislabeling invalid SAT as solved.
- CSV exposes whether recovery resulted in `SAT`, `UNSAT`, or still
  `INVALID_MODEL`.

Artifact:

- `results/invalid_model_recovery_smoke.csv`

Observed 3x3 smoke comparison:

| Run | SAT | INVALID_MODEL | UNSAT | Mean calls | Mean rounds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Guard only | 0 | 4 | 1 | 1.40 | 0.60 |
| Guard + invalid-model recovery | 1 | 2 | 2 | 2.00 | 1.40 |

Interpretation:

- Recovery reduced invalid models from `4/5` to `2/5`.
- It did not improve accuracy yet (`0/5`), because the recovered SAT model can
  still be semantically wrong against ground truth.
- The next bottleneck is semantic alignment: variable naming and predicted
  assignments must match the puzzle solution schema, not merely be in range.

Next step:

- Add semantic/model-alignment validation that checks whether predicted variable
  names correspond to puzzle solution keys before accepting a SAT model.
- Feed alignment failures into a targeted retranslation prompt.

## 8. Semantic Model-Schema Alignment

Status: implemented first pass; initial translation now receives non-oracle
schema guidance when visible in the puzzle text/metadata.

Tasks:

- Strip internal Z3 tracking literals from exported solver models.
- Validate SAT models against two non-answer-leaking criteria:
  integer assignments must be inside the house range, and predicted model keys
  must overlap the puzzle solution key schema when that schema is available.
- Classify in-range but semantically wrong variable schemas as
  `MISALIGNED_MODEL` rather than generic `SAT`.
- Trigger one targeted retranslation when repair budget remains, instructing the
  model to use semantic attribute-value variables such as `color_Blue`,
  `drink_Wine`, and `job_Artist` instead of house-slot variables such as
  `house1_color`.
- Surface `invalid_model`, `model_schema_aligned`, and `misaligned_model` in
  online CSV output.
- Pass visible puzzle schema names, without answer values, into initial
  translation and retranslation prompts as an expected variable schema.
- Keep `solution_keys` schema hint as an explicit oracle upper-bound diagnostic
  mode only; do not use it for main benchmark claims.
- Remove `house1_color` as a positive naming example from the translation
  prompt; keep it only as an explicitly forbidden house-slot pattern.

Acceptance:

- A model like `house1_color=1` is rejected for ZebraLogic records whose
  expected keys look like `color_Blue`.
- A model using expected semantic keys can still be accepted as `SAT`.
- Online result tables separate solver satisfiability, numeric-domain failures,
  and semantic-schema failures.

Next step:

- Rerun GPT-4o-mini smoke/ablation with the same 3x3 generated subset and
  compare `MISALIGNED_MODEL` rate before and after targeted retranslation.
- If the rate remains high, add a post-translation schema normalizer that
  rejects constraints whose declared variable set has no overlap with expected
  semantic keys before Z3 solving.
- Report the 3x3 `solution_keys` result separately as an upper-bound ablation:
  it can show whether schema naming is the bottleneck, but it may reveal
  hidden candidate values when the puzzle text does not list all values.

Implemented follow-up:

- Added `KEY_MISMATCH` to distinguish semantic-style overlap from exact
  variable-key-set agreement.
- Added `model_key_set_aligned` and `key_mismatch` to online CSV output.
- Added `--schema-hint-mode {puzzle,none,solution_keys}`:
  `puzzle` is the default non-oracle mode; `solution_keys` is oracle/upper-bound
  only.
- Added `scripts/add_zebra_domains_to_puzzle_text.py` to create a fair
  domain-explicit local eval set where all candidate values are visible in the
  puzzle text.

Observed GPT-4o-mini 3x3 smoke results:

| Setting | Data | Accuracy | Main failure mode |
| --- | --- | ---: | --- |
| Hidden-domain puzzle schema | `generated_3x_small_eval.jsonl` | 0/5 | hidden candidate values; partial/wrong key sets |
| Domain-explicit puzzle schema, before key canonicalization | `generated_3x_small_eval_domain_explicit.jsonl` | 0/5 | case/style `MISALIGNED_MODEL` |
| Domain-explicit puzzle schema, after key canonicalization | `generated_3x_small_eval_domain_explicit.jsonl` | 5/5 | none in 5-puzzle smoke |
| Oracle `solution_keys` schema | `generated_3x_small_eval.jsonl` | 5/5 | upper bound, not main claim |

Interpretation:

- The large measured gain is not from paradigm memory yet; the positive
  paradigm library is still empty in these runs.
- The bottleneck isolated by this experiment is schema/variable-set visibility.
  GPT-4o-mini can solve the small 3x3 cases once the full candidate domain is
  visible and canonicalized into expected variable keys.
- For defensible experiments, use domain-explicit puzzle text or benchmark
  records that already list all candidate values. Keep `solution_keys` only as
  an upper-bound diagnostic.

## 9. Schema-Controlled Memory Ablation

Status: completed diagnostic run on the local domain-explicit 3-house subset.

Artifacts:

- `results/schema_controlled_summary.csv`
- `results/schema_ablation_domain_explicit_full_summary.csv`
- `results/schema_ablation_domain_explicit_schema_only_no_recovery.csv`
- `results/schema_ablation_domain_explicit_baseline.csv`
- `results/schema_ablation_domain_explicit_empty_positive.csv`
- `results/schema_ablation_domain_explicit_error_memory.csv`
- `results/schema_ablation_domain_explicit_no_schema_hint_recovery.csv`
- `results/schema_ablation_domain_explicit_3x4_schema_only_no_recovery.csv`
- `results/schema_ablation_domain_explicit_3x4_baseline.csv`
- `results/schema_ablation_domain_explicit_3x4_error_memory.csv`

Controlled summary:

| Setting | Size | N | Accuracy | Avg calls | Avg rounds | Invalid-model retranslate | Repair success | Any memory guidance |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Schema hint, no recovery | 3x3 | 5 | 1/5 | 1.00 | 0.00 | 0 | 0 | 0 |
| Schema hint + validation recovery, no memory | 3x3 | 5 | 4/5 | 1.80 | 0.80 | 4 | 0 | 0 |
| Empty positive library | 3x3 | 5 | 5/5 | 1.80 | 0.80 | 4 | 0 | 0 |
| Error memory library | 3x3 | 5 | 5/5 | 2.00 | 1.00 | 5 | 0 | 0 |
| No schema hint + validation recovery | 3x3 | 5 | 4/5 | 2.00 | 1.00 | 5 | 0 | 0 |
| Schema hint, no recovery | 3x4 | 5 | 1/5 | 1.00 | 0.00 | 0 | 0 | 0 |
| Schema hint + validation recovery, no memory | 3x4 | 5 | 4/5 | 1.80 | 0.80 | 4 | 0 | 0 |
| Error memory library | 3x4 | 5 | 4/5 | 1.80 | 0.80 | 4 | 0 | 0 |

Interpretation:

- Initial GPT-4o-mini translations remain weak even after schema guidance:
  without validation recovery, both 3x3 and 3x4 domain-explicit subsets solve
  only `1/5`. The dominant failure mode is `INVALID_MODEL`, not UNSAT repair.
- One validation-driven retranslation is the main measured gain in this run:
  it raises both 3x3 and 3x4 from `1/5` to `4/5` under the no-memory baseline.
- The positive library result cannot be claimed as a memory effect because
  `gpt4o_3x3_schema_filtered.db` contains zero paradigms and
  `positive_guidance_triggered=0`.
- The error-memory result also cannot be claimed as a memory effect because
  `error_guidance_triggered=0`. The current error library is only used inside
  the UNSAT repair loop, but these controlled runs mostly follow the
  `SAT -> INVALID_MODEL -> retranslate` path.
- The current defensible claim is therefore: schema-visible variables plus
  validation/retranslation substantially improve GPT-4o-mini on small
  domain-explicit ZebraLogic cases. PRISM memory gain is not yet demonstrated.

Next execution plan:

- Add a `memory_eligible` diagnostic or derive it in the summarizer: count runs
  that actually enter the UNSAT repair loop, because only those can use error
  memory. Completed in code and CSV output.
- Build a repair-triggered evaluation subset by collecting GPT-4o-mini cases
  whose initial formalization or post-validation formalization reaches UNSAT.
  Completed for the hidden-domain local probe.
- Run paired baseline vs error-memory trials only on memory-eligible cases,
  keeping schema hint and validation recovery fixed. Completed as a diagnostic
  ablation; see Section 10.
- Mine positive paradigms from verified successful repairs so the positive
  library is non-empty before testing positive-memory gains.
- Repeat each small subset with multiple independent GPT-4o-mini calls, or use
  a larger local subset, because 5-puzzle smoke tests show visible output
  variance.

## 10. Memory-Eligible Hidden-Domain Diagnostic

Status: completed first paired diagnostic after opening the
`validation_recovery -> UNSAT -> repair` path.

Implementation changes:

- Added `initial_solver_result` to preserve the raw Z3 result before model
  validation rewrites an initial SAT into `INVALID_MODEL`, `MISALIGNED_MODEL`,
  or `KEY_MISMATCH`.
- Added `memory_eligible` to indicate whether a run actually entered a repair
  loop where positive/error memory can be used.
- Added `validated_repair_success` to distinguish a repair step that merely
  returns SAT from one whose final prediction is correct against ground truth.
- If validation recovery retranslation returns `UNSAT`, the solver now runs a
  remaining-budget repair step instead of terminating immediately. This gives
  the error paradigm library a real opportunity to guide the repair.

Artifacts:

- `results/memory_eligible_probe_all_summary.csv`
- `results/memory_eligible_hidden_domain_baseline_v2.csv`
- `results/memory_eligible_hidden_domain_error_memory_v2.csv`
- `results/memory_eligible_hidden_domain_ablation_summary_v2.csv`

Paired hidden-domain summary:

| Setting | N | Accuracy | Avg calls | Avg rounds | Memory eligible | Error guidance | Repair success | Validated repair success |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No memory | 10 | 0/10 | 2.50 | 1.60 | 5 | 0 | 1 | 0 |
| Error memory | 10 | 0/10 | 2.50 | 1.60 | 5 | 5 | 1 | 0 |

Interpretation:

- The memory path is now actually exercised: `5/10` hidden-domain runs are
  `memory_eligible`, and error memory triggers on all 5 eligible runs.
- Error memory does not yet improve accuracy: both paired runs remain `0/10`,
  and `validated_repair_success=0`.
- This is useful negative evidence. The bottleneck is no longer "memory was
  never called"; it is now "the retrieved negative hints do not produce a
  correct post-repair formalization."
- The hidden-domain setting remains especially difficult because full candidate
  values are not visible. Even after repair, many failures end as
  `KEY_MISMATCH`, `UNSAT`, or `INVALID_MODEL`.

Next execution plan:

- For memory-eligible rows, persist the repair prompt context, retrieved error
  paradigms, LLM repair output, and final validation failure. This is needed to
  inspect whether hints are irrelevant, too generic, or ignored. Completed via
  `--trace-output`; see Section 11.
- Improve error hint matching with relation-specific scope tags such as
  `directly_left`, `somewhere_left`, `adjacent`, `same_house`, and
  `candidate_domain`, rather than broad tags like `logical_implication`.
- Add a candidate-domain recovery step for hidden-domain puzzles, or keep
  hidden-domain results as a stress test and make the main memory claim on
  domain-explicit data.
- Mine positive paradigms only from `validated_repair_success=True` trajectories;
  current hidden-domain paired runs provide none.

## 11. Repair Trace and Target-Selection Fix

Status: completed first trace-driven repair-loop fix.

Implementation changes:

- Added `scripts/run_online.py --trace-output <path>` to write full per-puzzle
  JSONL traces, including all solver steps.
- Repair steps now record:
  `constraint_types`, `unsat_core`, `constraints_before`, raw
  `repair_response`, parsed `repair_expression`, `old_constraint`,
  `new_constraint`, `new_unsat_core`, `error_guidance`, and matched
  `error_paradigms`.
- `_apply_repair` now chooses the replacement target by variable overlap and
  operator compatibility, while avoiding schema/domain constraints for ordinary
  relation repairs.
- Schema repairs are constrained: a schema expression can replace only a schema
  constraint of the same kind and the same variable set. This prevents GPT from
  shrinking `Distinct(...)` groups or replacing domain bounds with unrelated
  relations.

Artifacts:

- `results/memory_trace_hidden_domain_error_memory_v3.jsonl`
- `results/memory_trace_hidden_domain_error_memory_targetfix.jsonl`
- `results/memory_trace_hidden_domain_error_memory_schemafix.jsonl`
- `results/memory_trace_repair_target_summary.csv`

Trace finding:

- Before the target fix, `4/5` repair steps replaced schema constraints such as
  domain bounds with relation repairs. This corrupted otherwise useful
  retranslation outputs.
- After variable/operator target selection, schema replacements dropped to
  `2/4`, but GPT still sometimes replaced full `Distinct(...)` constraints with
  incomplete smaller `Distinct(...)` groups.
- After the schema compatibility guard, schema replacements dropped to `0/4`.

Summary after schemafix:

| Setting | N | Accuracy | Avg calls | Avg rounds | Memory eligible | Repair success | Error guidance | Final UNSAT | Final KEY_MISMATCH |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Error memory + trace/schemafix | 10 | 0/10 | 2.40 | 1.40 | 4 | 0 | 4 | 4 | 6 |

Interpretation:

- The target-selection bug was real and is now fixed: repair no longer destroys
  domain bounds or all-different schema constraints.
- Accuracy did not improve yet. The remaining failure is semantic: the LLM
  repair often returns an irrelevant schema expression, repeats an unchanged
  relation, or flips a relation direction incorrectly.
- Current error paradigms are too broad. They retrieve mostly
  `logical_implication`/`inclusion` hints even when the actual UNSAT core is a
  candidate-domain or all-different mismatch caused by hidden values.

Next execution plan:

- Add a repair-output validator: reject no-op repairs, schema-shrinking
  `Distinct(...)`, and repairs whose variable set has low overlap with
  non-schema UNSAT-core constraints. Completed; see Section 12.
- Add relation-specific error scopes and extraction:
  `directly_left`, `directly_right`, `somewhere_left`, `adjacent`,
  `same_house`, `domain_candidate_mismatch`, and `distinct_group_mismatch`.
  Initial implementation added; next step is to rebuild scoped error libraries
  and rerun paired online tests.
- For hidden-domain puzzles, treat missing candidate values as a separate
  recovery problem. Memory guidance should not be blamed for failures caused by
  unobservable candidates.

## 12. Repair-Output Validator and Trace Summarizer

Status: completed first validator pass; trace observability improved.

Implementation changes:

- Added a repair-output validator before applying an LLM repair. It rejects:
  empty repairs, no-op repairs that repeat an UNSAT-core constraint,
  schema-shrinking `Distinct(...)` repairs, schema repairs without matching
  schema core, and low-variable-overlap repairs against non-schema cores.
- Rejected repairs are recorded as `repair_rejected` trace steps instead of
  mutating solver state.
- Rejected repairs are also appended to `RepairMemory` as UNSAT outcomes, so
  repeated bad repair patterns can still contribute to stagnation detection.
- Added `scripts/summarize_trace_jsonl.py` to summarize full trace JSONL files,
  including repair-step counts, rejection-reason distribution, schema
  replacements, guidance-trigger counts, and final result distribution.

Artifacts:

- `results/memory_trace_hidden_domain_error_memory_validator.csv`
- `results/memory_trace_hidden_domain_error_memory_validator.jsonl`
- `results/memory_trace_validator_summary.csv`

Validator comparison:

| Setting | N | Accuracy | Memory eligible | Error guidance | Repair success | Repair rejected | Final UNSAT | Final KEY_MISMATCH |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Error memory + schemafix | 10 | 0/10 | 4 | 4 | 0 | 0 | 4 | 6 |
| Error memory + validator | 10 | 0/10 | 5 | 5 | 0 | 3 | 5 | 5 |

Rejected repair distribution:

- `schema_shrinking_distinct=2`
- `no_op_repair=1`

Interpretation:

- The validator prevents GPT-4o-mini repairs from corrupting schema constraints
  or wasting a repair round by repeating the exact UNSAT-core assertion.
- This improves trace quality and state safety, but it does not improve
  accuracy yet. The main remaining failure is that retrieved error hints are
  still too generic or do not address hidden candidate-domain mismatches.
- The memory effect is therefore not yet a positive accuracy result. The
  current evidence supports a narrower claim: validation, schema visibility,
  trace instrumentation, and repair validation make the pipeline measurable and
  prevent several bad repair modes.

Next execution plan:

- Rebuild the error library with relation-specific scopes rather than broad
  `logical_implication` / `inclusion` scopes. Initial scoped retrieval probe
  completed; see Section 13.
- Rerun the same hidden-domain paired probe to check whether scoped retrieval
  changes the matched error paradigms and repair-rejection distribution.
  Completed; see Section 13.
- Add candidate-domain recovery for hidden-domain puzzles, or keep hidden-domain
  as a stress test and use domain-explicit data for the main memory claim.
  Current evidence favors treating hidden-domain as a stress test; see
  Section 13.

## 13. Relation-Scoped Error Retrieval and Visible-Schema Probe

Status: completed diagnostic implementation and GPT-4o-mini probe.

Implementation changes:

- Added shared lexical constraint tagging in `prism/core/constraint_tags.py`.
- Online and offline error paths now expose relation-specific tags such as
  `directly_left`, `directly_right`, `somewhere_left`, `somewhere_right`,
  `adjacent`, `same_house`, `domain_candidate_mismatch`, and
  `distinct_group_mismatch`.
- Error-library retrieval now augments old paradigms with relation tags inferred
  from `bad_operation`, so existing broad-scope libraries can still be scored
  more specifically without rebuilding the DB.
- Added visible-schema extraction from hidden-domain clue text. This extracts
  non-oracle keys that are actually mentioned in the puzzle, such as
  `job_Chef`, `job_Pilot`, `color_Purple`, and `drink_Wine`.
- Translation diagnostics now record visible schema key count, expected key
  count, missing visible keys, generated extra keys, and dropped invisible
  schema constraints in trace steps.

Artifacts:

- `results/memory_trace_hidden_domain_error_memory_scoped.csv`
- `results/memory_trace_hidden_domain_error_memory_scoped.jsonl`
- `results/memory_trace_scoped_summary.csv`
- `results/memory_trace_scoped_jsonl_summary.csv`
- `results/memory_trace_hidden_domain_error_memory_visible_schema.csv`
- `results/memory_trace_hidden_domain_error_memory_visible_schema.jsonl`
- `results/memory_trace_visible_schema_summary.csv`
- `results/memory_trace_visible_schema_jsonl_summary.csv`

Comparison:

| Setting | N | Accuracy | Avg calls | Avg rounds | Memory eligible | Error guidance | Repair rejected | Final UNSAT | Final KEY_MISMATCH |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Validator | 10 | 0/10 | 2.50 | 1.50 | 5 | 5 | 3 | 5 | 5 |
| Relation-scoped retrieval | 10 | 0/10 | 2.50 | 1.50 | 5 | 5 | 1 | 5 | 5 |
| Visible-schema filtering/diagnostic | 10 | 0/10 | 2.00 | 1.00 | 0 | 0 | 0 | 0 | 10 |

Trace finding:

- Relation-scoped retrieval changed behavior even though accuracy stayed 0:
  rejected repairs dropped from `3` to `1`, and matched error paradigms were no
  longer always the same two broad `logical_implication` patterns.
- The visible-schema run made the hidden-domain bottleneck explicit. Every run
  ended as `KEY_MISMATCH`, and trace diagnostics showed that the puzzle text
  exposed only part of the real candidate domain. In the first 3x3 case, for
  example, the visible schema had `7` keys while the expected answer schema had
  `9`; missing keys were `color_Blue` and `drink_Beer`.
- This explains why hidden-domain repair memory cannot be expected to improve
  final accuracy: the model is asked to output a complete answer key while some
  candidate values are not present in the puzzle text.

Interpretation:

- Relation-scoped memory improves observability and repair behavior, but not
  final correctness on hidden-domain data.
- Visible-schema diagnostics strengthen the experimental argument: hidden-domain
  failures are candidate-visibility failures, not clean evidence that memory is
  ineffective.
- The main memory-effect experiment should therefore move back to
  domain-explicit data, but use a deliberately repair-triggered subset so error
  or positive repair memory is actually eligible.

Next execution plan:

- Build a domain-explicit repair-triggered subset: cases where GPT-4o-mini
  reaches UNSAT after initial translation or validation retranslation, while all
  candidate keys are visible. Added `scripts/filter_trace_subset.py` to turn
  trace JSONL probes into reusable JSONL subsets. Initial 10-puzzle probe found
  zero memory-eligible rows; see Section 14.
- Mine positive paradigms only from `validated_repair_success=True` traces.
- Run paired trials on that subset:
  no memory, scoped error memory, positive repair memory, and positive+error
  memory.

## 14. Domain-Explicit Repair-Eligibility Check

Status: completed on the current 10-puzzle local domain-explicit probe.

Artifacts:

- `results/domain_explicit_trace_error_memory_visible_schema.csv`
- `results/domain_explicit_trace_error_memory_visible_schema.jsonl`
- `results/domain_explicit_trace_error_memory_visible_schema_summary.csv`
- `results/domain_explicit_trace_error_memory_visible_schema_jsonl_summary.csv`
- `data/hf/zebralogic/domain_explicit_memory_eligible_probe.jsonl`

Observed summary:

| Data | N | Accuracy | Avg calls | Avg rounds | Final SAT | Memory eligible | Invalid-model retranslate | Avg missing visible keys |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Domain-explicit 3x3+3x4 local probe | 10 | 9/10 | 2.00 | 1.00 | 10 | 0 | 10 | 0.00 |

Interpretation:

- Domain-explicit data removes the hidden-candidate problem: average missing
  visible schema keys is `0.00`.
- Accuracy is high (`9/10`), but this still is not a memory result. All 10 runs
  follow the validation/retranslation path and none enter the repair loop:
  `memory_eligible=0`, `error_guidance_triggered=0`, and
  `positive_guidance_triggered=0`.
- `scripts/filter_trace_subset.py` correctly produced an empty
  `domain_explicit_memory_eligible_probe.jsonl`, confirming that this small
  probe cannot support a memory-effect ablation.

Next execution plan:

- Expand the domain-explicit probe beyond the current 10 examples, preferably
  using a larger generated/local split, then filter traces for
  `memory_eligible=True`.
- If natural memory-eligible rows remain rare, construct a controlled
  repair-triggered benchmark by perturbing one relation in otherwise valid
  formalizations. First controlled benchmark implemented; see Section 15.
- Keep reporting schema/validation gains separately from memory gains.

## 15. Controlled Repair-Triggered Benchmark

Status: implemented and run on a 5-puzzle GPT-4o-mini smoke probe.

Purpose:

- Isolate the repair-loop question from NL translation and candidate visibility.
- Start from a complete domain-explicit formalization derived from the benchmark
  solution.
- Inject one wrong direct-position constraint, such as replacing
  `Int('color_Purple') == 1` with `Int('color_Purple') == 2`.
- Evaluate whether GPT-4o-mini can repair that single formalization error.

Artifacts:

- `scripts/run_controlled_repair_benchmark.py`
- `results/controlled_repair_baseline_5.csv`
- `results/controlled_repair_error_memory_5.csv`
- `results/controlled_repair_target_baseline_5.csv`
- `results/controlled_repair_target_error_memory_5.csv`
- `results/controlled_repair_5_all_summary.csv`
- `results/controlled_repair_5_all_jsonl_summary.csv`

Controlled comparison:

| Setting | N | Accuracy | Memory eligible | Repair success | Repair rejected | Error guidance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No target, no error memory | 5 | 3/5 | 5 | 3 | 2 | 0 |
| No target, generic error memory | 5 | 2/5 | 5 | 3 | 2 | 5 |
| Explicit repair target, no error memory | 5 | 5/5 | 5 | 5 | 0 | 0 |
| Explicit repair target + error memory | 5 | 5/5 | 5 | 5 | 0 | 5 |

Trace finding:

- Without explicit repair target, GPT-4o-mini often returns weak repairs such
  as `Int('color_Purple') != 2`. This can make the formula SAT and sometimes
  recover the correct model, but it is not a faithful formalization of the
  source clue.
- Generic error memory did not improve the 5-puzzle smoke result. It changed
  the prompt, but still allowed schema-shrinking `Distinct(...)` repairs and
  weak repairs.
- When the controlled benchmark injects the source clue and the exact target
  equality into the repair prompt, GPT-4o-mini returns the correct replacement
  constraint on all 5 cases.

Interpretation:

- The strongest effect is not generic retrieval; it is normalized,
  solver-checkable repair guidance: "replace this bad assertion with this exact
  relation derived from the formalized clue."
- This supports the research framing that PRISM should formalize memory into
  explicit correct/error repair paradigms, not merely append natural-language
  hints.
- To claim a memory effect, the next version should make the explicit repair
  target come from retrieved memory/paradigm structure rather than from the
  benchmark harness.

Next execution plan:

- Convert controlled repair targets into reusable positive/error paradigms with
  fields like `bad_pattern`, `correct_pattern`, `source_relation_type`, and
  `replacement_policy`. Implemented first instance-specific structured memory;
  see Section 16.
- Add a stricter repair validator that flags weak SAT repairs (`!= wrong_house`)
  as `weak_repair` when a direct-position equality target is available.
- Rerun controlled benchmark on all 10 domain-explicit puzzles and then on a
  larger generated split. Completed on current 10-puzzle local split; see
  Section 16.

## 16. Structured Replacement Memory

Status: implemented and validated on the 10-puzzle controlled repair benchmark.

Implementation changes:

- Error paradigms can now carry structured replacement memory in
  `trigger.replacement_policy`, for example:
  `bad_operation = Int('color_Purple') == 2` and
  `target_constraint = Int('color_Purple') == 1`.
- `GuidedSolver._build_error_guidance` renders this as an explicit
  `replacement_policy=target=...` repair instruction and records it in trace.
- `ErrorParadigmLibrary.retrieve` now:
  - receives the current `unsat_core` and `puzzle_id`,
  - prioritizes exact `bad_operation in unsat_core` matches,
  - when exact structured targets exist, returns only those matches,
  - filters instance-specific replacement policies by `puzzle_id` to avoid
    applying another puzzle's exact target.
- The controlled benchmark supports `--memory-targets --no-wrapper-target`,
  so exact repair targets come from structured memory retrieval rather than the
  benchmark LLM wrapper.

Artifacts:

- `results/controlled_repair_memory_targets_exact_5.csv`
- `results/controlled_repair_memory_targets_exact_10.csv`
- `results/controlled_repair_memory_targets_exact_filtered_10.csv`
- `results/controlled_repair_memory_targets_puzzle_filtered_10.csv`
- `results/controlled_repair_memory_targets_final_summary.csv`
- `results/controlled_repair_memory_targets_final_jsonl_summary.csv`

Final controlled comparison:

| Setting | N | Accuracy | Memory eligible | Repair success | Repair rejected | Error guidance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No target, no error memory | 5 | 3/5 | 5 | 3 | 2 | 0 |
| No target, generic error memory | 5 | 2/5 | 5 | 3 | 2 | 5 |
| Structured target memory, puzzle-filtered | 10 | 10/10 | 10 | 10 | 0 | 10 |

Trace finding:

- Before exact filtering, structured targets could still retrieve distractor
  targets from another puzzle with the same broad scope. This produced wrong
  repairs despite the correct target being present.
- After exact `bad_operation` and `puzzle_id` filtering, every repair step
  retrieved the intended target and GPT-4o-mini returned the exact replacement:
  e.g. `Int('color_Purple') == 2 -> Int('color_Purple') == 1`.

Interpretation:

- This is the first clean positive evidence for the method, but it is a
  controlled repair-loop result, not a full NL-to-Z3 pipeline result.
- The result supports the core thesis: memory is useful when it is formalized as
  solver-addressable replacement knowledge, not when it is only generic
  natural-language warning text.
- The next scientific step is to generalize instance-specific replacements into
  typed repair templates, so the memory can transfer across puzzles without
  relying on `puzzle_id`.

Next execution plan:

- Replace instance-specific `puzzle_id` memory with typed templates:
  `direct_position_wrong_house(variable, wrong_house) -> direct_position(variable, clue_house)`.
  Implemented first direct-position clue template; see Section 17.
- Store the clue-derived target extraction separately from the benchmark harness
  so full pipeline traces can produce the same structured memory automatically.
- Add `weak_repair` validation for cases where a target equality exists but the
  LLM returns a weaker inequality.

## 17. Typed Direct-Position Repair Template

Status: implemented and validated on the 10-puzzle controlled repair benchmark.

Implementation changes:

- Added typed replacement policy:
  `kind = direct_position_from_source_clue`.
- This policy stores the source clue and relation type, but does not store a
  concrete `target_constraint`.
- `GuidedSolver` materializes the target at guidance time by parsing:
  - the current bad direct-position assertion, e.g. `Int('color_Purple') == 2`,
  - the source clue, e.g. `The Purple color person lives in house 1`,
  - and generating `Int('color_Purple') == 1`.
- The controlled benchmark now supports `--template-memory --no-wrapper-target`,
  so GPT-4o-mini receives the repair target only through structured memory
  materialization, not through benchmark wrapper injection or pre-stored exact
  answer constraints.

Artifacts:

- `results/controlled_repair_template_memory_10.csv`
- `results/controlled_repair_template_memory_10.jsonl`
- `results/controlled_repair_template_memory_summary.csv`
- `results/controlled_repair_template_memory_jsonl_summary.csv`

Comparison:

| Setting | N | Accuracy | Memory eligible | Repair success | Repair rejected | Error guidance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| No target, no error memory | 5 | 3/5 | 5 | 3 | 2 | 0 |
| No target, generic error memory | 5 | 2/5 | 5 | 3 | 2 | 5 |
| Instance-specific structured target memory | 10 | 10/10 | 10 | 10 | 0 | 10 |
| Typed direct-position template memory | 10 | 10/10 | 10 | 10 | 0 | 10 |

Trace example:

- `bad_operation`: `Int('color_Purple') == 2`
- `replacement_policy.kind`: `direct_position_from_source_clue`
- `source_clue`: `The Purple color person lives in house 1.`
- materialized `target_constraint`: `Int('color_Purple') == 1`
- GPT-4o-mini repair expression: `Int('color_Purple') == 1`

Interpretation:

- This is stronger than Section 16 because the memory no longer stores the exact
  replacement constraint directly. It stores a typed repair procedure that
  derives the target from the clue and current bad operation.
- The result supports the method's central claim more directly: memory becomes
  a formal repair rule that constrains the LLM's repair output.
- The experiment remains controlled because the benchmark harness still creates
  the source-clue link and injects one synthetic direct-position error. It is
  not yet a full NL-to-Z3 end-to-end memory result.

Next execution plan:

- Add typed templates for relation direction errors:
  `directly_left`, `directly_right`, `somewhere_left`, `somewhere_right`, and
  `adjacent`.
- Add weak-repair validation: if a materialized target exists, reject repairs
  that do not exactly match it or an equivalent normalized expression.
- Mine these typed templates from failed/repair traces instead of constructing
  them in the controlled benchmark script.

## 18. Typed Relation Repair Templates and Repair-Shape Evaluation

Status: implemented and validated with GPT-4o-mini on controlled relation
repair loops.

Implementation changes:

- Extended typed replacement policies beyond direct-position:
  - `directly_left_from_source_clue`
  - `directly_right_from_source_clue`
  - `somewhere_left_from_source_clue`
  - `somewhere_right_from_source_clue`
  - `adjacent_from_source_clue`
- `GuidedSolver` now materializes relation targets from the source clue and the
  current bad operation. Example:
  - source clue: `The Chef job is immediately left of the Pilot job.`
  - bad operation: `Int('job_Chef') == Int('job_Pilot') + 1`
  - materialized target: `Int('job_Chef') == Int('job_Pilot') - 1`
- Added target-aware repair validation:
  - if a materialized replacement target exists, repairs must match it or an
    equivalent normalized expression;
  - weak direct-position repairs such as `Int('x') != 2` are rejected as
    `weak_repair`;
  - weaker relation repairs such as `Abs(a - b) == 1` for a directly-left clue
    are rejected as `weak_repair`;
  - other non-target repairs are rejected as `target_mismatch`.
- Extended the controlled repair benchmark:
  - `--perturbation-type direct_position|directly_left|directly_right|somewhere_left|somewhere_right|adjacent`
  - `--relation-hard-mode`, which creates boundary-triggered relation UNSAT
    cores and reduces leakage from complete endpoint assignments.
- Added `exact_target_repair_steps`, `target_repair_steps`, and
  `exact_target_repair_pct` to `scripts/summarize_trace_jsonl.py`.

Artifacts:

- `results/controlled_repair_directly_left_template_10.csv`
- `results/controlled_repair_directly_left_template_10.jsonl`
- `results/controlled_repair_directly_left_no_memory_10.csv`
- `results/controlled_repair_directly_left_no_memory_10.jsonl`
- `results/controlled_repair_directly_left_hard_no_memory_10.csv`
- `results/controlled_repair_directly_left_hard_no_memory_10.jsonl`
- `results/controlled_repair_directly_left_hard_template_10.csv`
- `results/controlled_repair_directly_left_hard_template_10.jsonl`
- `results/controlled_repair_relation_hard_summary.csv`
- `results/controlled_repair_relation_hard_jsonl_summary.csv`

Controlled relation results:

| Setting | N | Accuracy | Error guidance | Exact target repairs |
| --- | ---: | ---: | ---: | ---: |
| Directly-left, no memory | 10 | 10/10 | 0 | 10/10 in easy mode |
| Directly-left, typed template memory | 10 | 10/10 | 10 | 10/10 |
| Directly-left hard mode, no memory | 10 | 10/10 | 0 | 8/10 |
| Directly-left hard mode, typed template memory | 10 | 10/10 | 10 | 10/10 |

Interpretation:

- Relation direction errors are easier than direct-position errors for
  GPT-4o-mini in the current controlled setup. In easy mode, the UNSAT core
  exposes enough endpoint assignments for the baseline to infer the correct
  direction without memory.
- Hard mode reduces but does not eliminate this shortcut. The baseline still
  reaches 10/10 final SAT accuracy, but it sometimes repairs by direct assignment
  instead of restoring the clue-level relation. This is why the new
  `exact_target_repair_pct` metric is necessary.
- Typed relation memory improves repair-shape conformity from 8/10 to 10/10 in
  hard mode. This supports the narrower claim that formalized memory constrains
  the LLM toward the intended solver-addressable repair paradigm, even when
  final SAT accuracy is already saturated.
- This remains a controlled repair-loop result, not an end-to-end NL-to-Z3
  accuracy claim.

Next execution plan:

- Add a perturbation mode that creates multiple SAT-preserving but
  clue-inconsistent repair options, so the main metric is not just final SAT.
- Mine typed replacement policies from actual failed/repair traces rather than
  constructing them in the benchmark harness.
- Report both final accuracy and repair-shape conformity in the paper:
  `validated_repair_success` and `exact_target_repair_pct`.

## 19. Trace-Mined Typed Replacement Memory

Status: implemented and validated with GPT-4o-mini on controlled relation repair
loops.

Implementation changes:

- `ErrorParadigmExtractor` now supports mining typed replacement policies from
  online trace JSONL records, not only legacy `TrajectoryStep` UNSAT cores.
- New API:
  - `extract_from_trace_records(records, instance_specific=False)`
  - `extract_from_trace_jsonl(path, instance_specific=False)`
- `scripts/extract_error_paradigms.py` now supports:
  - `--trace-jsonl <path>`
  - `--instance-specific`
- In the default non-instance-specific mode, mined templates do not store a
  concrete `source_clue` or `puzzle_id`. They store only the typed policy kind,
  for example:
  `{"kind": "directly_left_from_source_clue"}`.
- `GuidedSolver` now materializes these generic templates at repair time by:
  - reading the current UNSAT core variables,
  - matching the typed relation against the current puzzle text,
  - deriving the current puzzle's source clue and target constraint.
- This means one mined template can transfer across different variables and
  puzzles. Example:
  - mined bad shape: `Int('job_Chef') == Int('job_Pilot') + 1`
  - generic policy: `directly_left_from_source_clue`
  - current puzzle source clue: `The Cat pet is immediately left of the Fish pet.`
  - materialized target: `Int('pet_Cat') == Int('pet_Fish') - 1`

Execution:

```powershell
python scripts\extract_error_paradigms.py `
  --trace-jsonl results\controlled_repair_directly_left_hard_template_10.jsonl `
  --output paradigm_store\mined_relation_templates.db `
  --min-support 1

python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_small_eval_domain_explicit.jsonl `
  --model GPT-4o-mini --sizes 3x3,3x4 --max-records 10 --max-repair 1 `
  --perturbation-type directly_left --relation-hard-mode `
  --error-library paradigm_store\mined_relation_templates.db `
  --no-wrapper-target `
  --output results\controlled_repair_directly_left_mined_template_10.csv `
  --trace-output results\controlled_repair_directly_left_mined_template_10.jsonl
```

Artifacts:

- `paradigm_store/mined_relation_templates.db`
- `paradigm_store/mined_relation_templates.json`
- `results/controlled_repair_directly_left_mined_template_10.csv`
- `results/controlled_repair_directly_left_mined_template_10.jsonl`
- `results/controlled_repair_mined_template_summary.csv`
- `results/controlled_repair_mined_template_jsonl_summary.csv`

Result comparison:

| Setting | N | Accuracy | Error guidance | Exact target repairs |
| --- | ---: | ---: | ---: | ---: |
| Hard mode, no memory | 10 | 10/10 | 0 | 8/10 |
| Hard mode, benchmark-built typed template | 10 | 10/10 | 10 | 10/10 |
| Hard mode, trace-mined generic template | 10 | 10/10 | 10 | 10/10 |

Interpretation:

- This closes an important methodological gap. The memory can now be generated
  from previous repair traces and reused as a generic typed repair rule.
- The mined library contains one generic relation template with support count
  10. It does not memorize concrete targets, but the online solver reconstructs
  the current source clue and target constraint dynamically.
- This supports the claim that the core contribution is not prompt formatting:
  memory becomes a reusable solver-addressable repair template that constrains
  the LLM toward the correct formal relation.
- The evidence is still controlled repair-loop evidence. The next step is to
  collect full-pipeline failure traces and measure whether mined templates
  improve end-to-end repair behavior without synthetic perturbations.

Next execution plan:

- Run GPT-4o-mini full-pipeline traces with no error memory and save JSONL.
- Mine typed replacement templates from those traces.
- Re-run the same puzzle subset with the mined error library.
- Report three metrics separately:
  `validated_repair_success`, `exact_target_repair_pct`, and final benchmark
  accuracy.

## 20. Full-Pipeline Failure Boundary: Hidden Domains

Status: executed with GPT-4o-mini. This run clarifies the current end-to-end
bottleneck and should not be interpreted as a negative-memory result.

Execution:

```powershell
python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_3x_small_eval.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 3x3,3x4 `
  --max-repair 1 `
  --no-paradigm --no-memory `
  --schema-hint-mode puzzle `
  --output results\full_pipeline_hidden_domain_nomemory_gpt4omini_10.csv `
  --trace-output results\full_pipeline_hidden_domain_nomemory_gpt4omini_10.jsonl
```

Artifacts:

- `results/full_pipeline_hidden_domain_nomemory_gpt4omini_10.csv`
- `results/full_pipeline_hidden_domain_nomemory_gpt4omini_10.jsonl`
- `results/full_pipeline_hidden_domain_nomemory_gpt4omini_10_summary.csv`
- `results/full_pipeline_hidden_domain_nomemory_gpt4omini_10_trace_summary.csv`
- `paradigm_store/full_pipeline_hidden_domain_mined_templates.db`
- `paradigm_store/full_pipeline_hidden_domain_mined_templates.json`

Results:

| Setting | N | Accuracy | Memory eligible | Repair steps | Extracted templates |
| --- | ---: | ---: | ---: | ---: | ---: |
| Hidden-domain full pipeline, no memory | 10 | 0/10 | 0 | 0 | 0 |

Trace summary:

- Final failures are `KEY_MISMATCH=10`.
- The common action pattern is `validate_model` followed by
  `invalid_model_retranslate` or `misaligned_model_retranslate`.
- The solver state is often SAT, but the predicted key set omits hidden
  candidate values, for example `color_Blue` or `drink_Beer`.
- `extract_error_paradigms.py --trace-jsonl` extracts 0 typed repair templates.

Interpretation:

- This is a schema/candidate-completeness bottleneck, not a solver repair
  bottleneck. The memory system is not triggered because there is no UNSAT
  repair loop to mine or guide.
- This supports a clean experimental separation:
  - schema hints / model validation explain full-pipeline robustness,
  - typed error memory explains repair-loop behavior once the formula enters
    an UNSAT repair state.
- Do not claim that current mined error memory improves this hidden-domain
  end-to-end setting. The correct next step is either explicit candidate-domain
  recovery or a separate schema-completion memory.

## 21. LLM-Derived Base Repair: Schema-Completed Trace Collection

Status: implemented and run with GPT-4o-mini. This bridges the fully controlled
solution-derived repair benchmark and the full NL-to-Z3 pipeline.

Implementation changes:

- `scripts/run_controlled_repair_benchmark.py` now supports:
  - `--base-constraints solution` (default, previous behavior)
  - `--base-constraints llm_validated`
  - `--base-constraints llm_schema_completed`
  - `--prepared-output`
  - `--prepared-input`
- `llm_schema_completed` uses GPT-4o-mini for clue constraints, then
  deterministically adds domain bounds and `Distinct(...)` schema constraints
  before validation and controlled perturbation.
- Prepared JSONL files cache the exact controlled puzzles, so no-memory and
  memory runs use the same LLM-derived base constraints.
- Generic relation-template materialization now prioritizes the wrong-direction
  relation variables in multi-relation UNSAT cores. This prevents the template
  from selecting a different correct relation in the same core.

Execution:

```powershell
python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_small_eval_domain_explicit.jsonl `
  --model GPT-4o-mini `
  --sizes 3x3,3x4 `
  --max-records 30 `
  --max-repair 1 `
  --base-constraints llm_schema_completed `
  --perturbation-type directly_left `
  --prepared-output results\prepared_llm_schema_completed_directly_left_gpt4omini_30.jsonl `
  --no-wrapper-target `
  --output results\llm_base_repair_directly_left_nomemory_gpt4omini_30_initial.csv `
  --trace-output results\llm_base_repair_directly_left_nomemory_gpt4omini_30_initial.jsonl

python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_small_eval_domain_explicit.jsonl `
  --prepared-input results\prepared_llm_schema_completed_directly_left_gpt4omini_30.jsonl `
  --model GPT-4o-mini `
  --max-repair 1 `
  --no-wrapper-target `
  --output results\llm_base_prepared_directly_left_nomemory_gpt4omini.csv `
  --trace-output results\llm_base_prepared_directly_left_nomemory_gpt4omini.jsonl

python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_small_eval_domain_explicit.jsonl `
  --prepared-input results\prepared_llm_schema_completed_directly_left_gpt4omini_30.jsonl `
  --model GPT-4o-mini `
  --max-repair 1 `
  --error-library paradigm_store\mined_relation_templates.db `
  --no-wrapper-target `
  --output results\llm_base_prepared_directly_left_mined_memory_gpt4omini.csv `
  --trace-output results\llm_base_prepared_directly_left_mined_memory_gpt4omini.jsonl
```

Artifacts:

- `results/prepared_llm_schema_completed_directly_left_gpt4omini_30.jsonl`
- `results/llm_base_prepared_directly_left_nomemory_gpt4omini.csv`
- `results/llm_base_prepared_directly_left_nomemory_gpt4omini.jsonl`
- `results/llm_base_prepared_directly_left_mined_memory_gpt4omini.csv`
- `results/llm_base_prepared_directly_left_mined_memory_gpt4omini.jsonl`
- `results/llm_base_prepared_directly_left_nomemory_gpt4omini_trace_summary.csv`
- `results/llm_base_prepared_directly_left_mined_memory_gpt4omini_trace_summary.csv`

Fair prepared-subset comparison:

| Setting | N | Accuracy | Repair success | Error guidance | Exact target repairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| LLM-schema-completed base, no memory | 1 | 0/1 | 0/1 | 0 | 0/1 |
| LLM-schema-completed base, mined memory | 1 | 1/1 | 1/1 | 1 | 1/1 |

Observed failure/success:

- No memory repaired the core by returning
  `Int('hobby_Gardening') == Int('hobby_Reading') - 1`, which did not restore
  the perturbed source clue and kept the formula UNSAT.
- Mined memory materialized:
  `source_clue=1. The Music hobby is immediately left of the Reading hobby.`
  and returned the exact target
  `Int('hobby_Music') == Int('hobby_Reading') - 1`.

Interpretation:

- This is stronger than the pure solution-derived controlled run because the
  base clue constraints come from GPT-4o-mini, while schema completion remains a
  deterministic validator/normalizer.
- The current dataset has only 10 local records, and the exact validated
  LLM-derived subset contains only 1 directly-left sample. Treat this as a
  qualitative bridge experiment, not a statistically powered result.
- The next evidence upgrade is to generate or load a larger domain-explicit
  local set, then build a prepared LLM-schema-completed subset of at least
  30-50 memory-eligible relation repairs.

## 22. Scaled LLM-Derived Prepared Repair Evaluation

Status: implemented and validated with GPT-4o-mini on a generated 150-record
domain-explicit ZebraLogic set. This is currently the strongest evidence for
the memory effect.

Implementation changes:

- Added `scripts/generate_zebra_jsonl.py`.
- The script uses `PuzzleGenerator` and writes benchmark-compatible JSONL with:
  `id`, `size`, `puzzle`, `solution`, optional `difficulty`, and optional
  `conflict_count`.
- `--domain-explicit` inserts a `Candidate values:` section into the puzzle
  text, so the translator has visible candidate domains without oracle answer
  positions.

Data generation:

```powershell
python scripts\generate_zebra_jsonl.py `
  --specs 75:3x3:medium,75:3x4:medium `
  --seed 20260529 `
  --domain-explicit `
  --output data\hf\zebralogic\generated_3x_eval_domain_explicit_150.jsonl
```

Prepared LLM-derived repair subset:

```powershell
python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_eval_domain_explicit_150.jsonl `
  --model GPT-4o-mini `
  --sizes 3x3,3x4 `
  --max-records 150 `
  --max-repair 1 `
  --base-constraints llm_schema_completed `
  --perturbation-type directly_left `
  --prepared-output results\prepared_llm_schema_completed_directly_left_gpt4omini_generated150.jsonl `
  --no-wrapper-target `
  --output results\generated150_llm_base_directly_left_nomemory_initial.csv `
  --trace-output results\generated150_llm_base_directly_left_nomemory_initial.jsonl
```

Fair ablation on the exact same prepared subset:

```powershell
python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_eval_domain_explicit_150.jsonl `
  --prepared-input results\prepared_llm_schema_completed_directly_left_gpt4omini_generated150.jsonl `
  --model GPT-4o-mini `
  --max-repair 1 `
  --no-wrapper-target `
  --output results\generated150_prepared_directly_left_nomemory_gpt4omini.csv `
  --trace-output results\generated150_prepared_directly_left_nomemory_gpt4omini.jsonl

python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_3x_eval_domain_explicit_150.jsonl `
  --prepared-input results\prepared_llm_schema_completed_directly_left_gpt4omini_generated150.jsonl `
  --model GPT-4o-mini `
  --max-repair 1 `
  --error-library paradigm_store\mined_relation_templates.db `
  --no-wrapper-target `
  --output results\generated150_prepared_directly_left_mined_memory_gpt4omini.csv `
  --trace-output results\generated150_prepared_directly_left_mined_memory_gpt4omini.jsonl
```

Artifacts:

- `data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl`
- `results/prepared_llm_schema_completed_directly_left_gpt4omini_generated150.jsonl`
- `results/generated150_prepared_directly_left_nomemory_gpt4omini.csv`
- `results/generated150_prepared_directly_left_nomemory_gpt4omini.jsonl`
- `results/generated150_prepared_directly_left_mined_memory_gpt4omini.csv`
- `results/generated150_prepared_directly_left_mined_memory_gpt4omini.jsonl`
- `results/generated150_prepared_directly_left_nomemory_gpt4omini_trace_summary.csv`
- `results/generated150_prepared_directly_left_mined_memory_gpt4omini_trace_summary.csv`
- `results/generated150_prepared_directly_left_comparison_summary.csv`

Main result:

| Setting | N | Accuracy | Repair success | Exact target repairs | Error guidance |
| --- | ---: | ---: | ---: | ---: | ---: |
| LLM-schema-completed base, no memory | 43 | 26/43 | 33/43 | 20/43 | 0 |
| LLM-schema-completed base, mined memory | 43 | 43/43 | 43/43 | 43/43 | 43 |

Additional trace diagnostics:

- No-memory produced 10 repairs that stayed UNSAT.
- No-memory produced 7 SAT-but-wrong repairs, where Z3 became SAT but the final
  model did not match the benchmark solution.
- Mined memory produced 0 UNSAT repairs and 0 SAT-but-wrong repairs.
- Mined memory exact target repair rate is 100.0%; no-memory is 46.5%.

Interpretation:

- This experiment keeps the key methodological separation:
  - GPT-4o-mini translates natural-language clues into formal constraints.
  - deterministic schema completion supplies only bounds and all-different
    invariants.
  - the repair memory supplies a mined, generic, typed replacement template.
- The memory is not memorizing puzzle-specific variables. The mined template
  stores only `{"kind": "directly_left_from_source_clue"}` and materializes the
  current source clue from the current puzzle and UNSAT core.
- The result directly supports the core claim: solver-addressable memory
  constrains GPT-4o-mini away from plausible but wrong repairs and toward the
  exact formal relation needed by the current clue.
- This should be reported as an LLM-derived controlled repair benchmark, not as
  a full hidden-domain end-to-end result.

## 23. GPT-4o-mini on 5x5 / 6x5 with Experience Libraries

Status: executed. The result separates full-pipeline behavior from repair-loop
behavior.

Official local 5x5/6x5 smoke:

```powershell
python scripts\run_online.py `
  --data-dir data\hf\zebralogic\grid_mode_test.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --no-paradigm --no-memory `
  --schema-hint-mode puzzle `
  --output results\size_5x5_6x5_gpt4omini_baseline.csv `
  --trace-output results\size_5x5_6x5_gpt4omini_baseline.jsonl

python scripts\run_online.py `
  --data-dir data\hf\zebralogic\grid_mode_test.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --no-paradigm `
  --error-library paradigm_store\mined_relation_templates.db `
  --schema-hint-mode puzzle `
  --output results\size_5x5_6x5_gpt4omini_mined_error_memory.csv `
  --trace-output results\size_5x5_6x5_gpt4omini_mined_error_memory.jsonl
```

Official-smoke result:

| Setting | N | Accuracy | Memory eligible | Error guidance |
| --- | ---: | ---: | ---: | ---: |
| Full pipeline, no memory | 2 | 0/2 | 0 | 0 |
| Full pipeline, mined error memory | 2 | 0/2 | 0 | 0 |
| Full pipeline, oracle `solution_keys` schema | 2 | 1/2 | 0 | 0 |

Interpretation:

- The mined repair memory is not triggered on the official 5x5/6x5 smoke. The
  failures are validation/schema failures (`INVALID_MODEL`, `MISALIGNED_MODEL`,
  `KEY_MISMATCH`), not UNSAT repair-loop states.
- With oracle schema keys, GPT-4o-mini solves the 5x5 case but still fails the
  6x5 case by key mismatch. This points to variable canonicalization and
  schema completion as the full-pipeline bottleneck.

Generated flat-solution 5x5/6x5 full-pipeline test:

```powershell
python scripts\generate_zebra_jsonl.py `
  --specs 5:5x5:medium,5:6x5:medium `
  --seed 20260530 `
  --domain-explicit `
  --output data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl

python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --no-paradigm --no-memory `
  --schema-hint-mode puzzle `
  --output results\generated_5x5_6x5_gpt4omini_baseline.csv `
  --trace-output results\generated_5x5_6x5_gpt4omini_baseline.jsonl

python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --library paradigm_store\gpt4o_3x3_positive_fixed.db `
  --error-library paradigm_store\mined_relation_templates.db `
  --schema-hint-mode puzzle `
  --output results\generated_5x5_6x5_gpt4omini_memory.csv `
  --trace-output results\generated_5x5_6x5_gpt4omini_memory.jsonl
```

Generated full-pipeline result:

| Setting | N | Accuracy | Memory eligible | Error guidance |
| --- | ---: | ---: | ---: | ---: |
| Full pipeline, no memory | 10 | 8/10 | 0 | 0 |
| Full pipeline, positive + mined error memory | 10 | 7/10 | 0 | 0 |

Interpretation:

- The apparent 8/10 vs 7/10 difference is not a memory effect. There are no
  repair steps and no error-guidance steps in either run.
- Both runs end with SAT formulas; errors are final-answer mismatches after
  translation/retranslation, not repair-loop failures.

Controlled 5x5/6x5 repair-loop test:

```powershell
python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-records 10 `
  --max-repair 1 `
  --perturbation-type directly_left `
  --relation-hard-mode `
  --no-wrapper-target `
  --output results\generated_5x5_6x5_controlled_directly_left_nomemory.csv `
  --trace-output results\generated_5x5_6x5_controlled_directly_left_nomemory.jsonl

python scripts\run_controlled_repair_benchmark.py `
  --data data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-records 10 `
  --max-repair 1 `
  --perturbation-type directly_left `
  --relation-hard-mode `
  --error-library paradigm_store\mined_relation_templates.db `
  --no-wrapper-target `
  --output results\generated_5x5_6x5_controlled_directly_left_mined_memory.csv `
  --trace-output results\generated_5x5_6x5_controlled_directly_left_mined_memory.jsonl
```

Controlled repair-loop result:

| Setting | N | Accuracy | Repair success | Exact target repairs | Error guidance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Controlled directly-left, no memory | 10 | 10/10 | 10/10 | 9/10 | 0 |
| Controlled directly-left, mined memory | 10 | 10/10 | 10/10 | 10/10 | 10 |

Conclusion:

- On 5x5/6x5 full pipeline, current experience libraries do not help because
  they are not triggered. The bottleneck is still translation/schema/model
  validation, not repair memory.
- Once the problem is placed into a solver repair-loop state, the mined typed
  relation memory transfers across scale and improves exact repair-shape
  conformity from 9/10 to 10/10. Final accuracy is saturated in this controlled
  setting.
- The next optimization for 5x5/6x5 should target schema canonicalization and
  translation completeness first; repair memory should be evaluated on
  memory-eligible subsets, not on all full-pipeline attempts.

## 24. Protected GPT-4o-mini Translation Normalization

Question:

- Can we add a second cleanup stage where GPT-4o-mini first translates the
  puzzle, then GPT-4o-mini normalizes the generated constraints before Z3 and
  repair?

Implemented path:

- Added `--translation-normalize {none,initial,always}` to `scripts/run_online.py`.
- Added `LLMClient.normalize_translation(...)`.
- Added `NLToZ3Translator(..., normalize_mode=...)`.
- `initial` normalizes only the first translation.
- `always` normalizes both the first translation and later retranslation output.
- The final protected selector accepts normalized constraints only when:
  - their Z3/model-validation score is strictly better than the original; and
  - the normalized set preserves the semantic relation signatures already
    present in the original translation.
- The relation-preservation gate treats single-argument wrappers such as
  `And(Int('x') == 1)` as equivalent to `Int('x') == 1`, so formatting cleanup
  is allowed while relation reversal/weakening/strengthening is rejected.

Commands:

```powershell
python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --no-paradigm --no-memory `
  --schema-hint-mode puzzle `
  --translation-normalize initial `
  --output results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_v2.csv `
  --trace-output results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_v2.jsonl

python scripts\summarize_online_csvs.py `
  results\generated_5x5_6x5_gpt4omini_baseline.csv `
  results\generated_5x5_6x5_gpt4omini_normalize_initial_gated.csv `
  results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_v2.csv `
  --output results\generated_5x5_6x5_gpt4omini_protected_normalize_v2_comparison.csv
```

Result:

| Setting | N | Accuracy | Avg calls | Avg repair rounds | Initial SAT | Validation retranslate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline, no normalize | 10 | 8/10 | 1.70 | 0.70 | 3 | 7 |
| Unguarded/generic initial normalize | 10 | 8/10 | 2.50 | 0.50 | 5 | 5 |
| Protected initial normalize v2 | 10 | 9/10 | 2.00 | 0.00 | 10 | 0 |

Interpretation:

- The user's proposed "generate then clean up" stage is feasible and useful, but
  only when it is protected. On the generated 5x5/6x5 smoke set, protected
  initial normalization improves GPT-4o-mini from 8/10 to 9/10.
- The gain is a translation-level robustness effect. It is not evidence that
  experience memory improved this full-pipeline run, because the protected run
  uses `--no-paradigm --no-memory` and has no repair-loop activity.
- `always` normalization is not recommended: earlier run
  `results\generated_5x5_6x5_gpt4omini_normalize_always.csv` fell to 5/10,
  consistent with over-editing later recovery translations.
- `normalize + memory` is also not yet a positive result:
  `results\generated_5x5_6x5_gpt4omini_memory_normalize_initial_gated.csv`
  was 7/10. It can trigger memory, but the current mined relation template does
  not reliably help the full-pipeline failure states.
- A stricter category-permutation validator is useful as a diagnostic for fake
  SAT models with repeated house positions inside a category, but enabling it
  by default in this recovery pipeline dropped the smoke result to 7/10 because
  current recovery/retranslation can move some cases away from otherwise
  correct translations. Keep it as a diagnostic helper until recovery is
  improved.

Next optimization:

- Keep `--translation-normalize initial` as the recommended full-pipeline
  translation robustness option.
- Add deterministic clue-coverage diagnostics before using category-permutation
  failures as hard rejection.
- Evaluate experience memory only on memory-eligible or controlled repair-loop
  subsets; do not claim full-pipeline memory gains from this normalization
  result.

## 25. Making More SAT Failures Memory-Eligible

Question:

- How do we increase the measurable benefit of memory when many GPT-4o-mini
  failures are `SAT` formulas with wrong answers rather than `UNSAT` repair
  states?

Implemented mechanism:

- Added a deterministic clue-coverage checker for high-confidence relation
  mismatches:
  - direct house position clues;
  - directly-left/right clues;
  - somewhere-left/right clues;
  - adjacent clues.
- The checker compares explicit clue-derived target constraints with generated
  constraints. It can detect cases like:
  - clue says `A is immediately left of B`;
  - translation generated `Abs(A - B) == 1`, `A == B + 1`, or another relation
    over the same variable pair.
- The checker is memory-gated:
  - it does not alter accepted SAT results by itself;
  - it only creates `validate_clue_coverage` / `repair` steps when the error
    library can materialize a target replacement from the source clue.
- Coverage repair is batched. If one puzzle weakens eight `directly-left` clues
  to `Abs(...) == 1`, all eight memory-targeted replacements are applied in one
  solver rebuild instead of repairing only the first one.
- Error guidance is now target-aware for relation templates. Generic relation
  templates are injected only when they can materialize a concrete
  `target_constraint` from the current source clue/current core. This prevents
  broad templates from encouraging unrelated variable-pair repairs.

Commands:

```powershell
python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --library paradigm_store\gpt4o_3x3_positive_fixed.db `
  --error-library paradigm_store\mined_relation_templates.db `
  --schema-hint-mode puzzle `
  --translation-normalize initial `
  --output results\generated_5x5_6x5_gpt4omini_memory_normalize_initial_coverage_batch.csv `
  --trace-output results\generated_5x5_6x5_gpt4omini_memory_normalize_initial_coverage_batch.jsonl

python scripts\summarize_online_csvs.py `
  results\generated_5x5_6x5_gpt4omini_baseline.csv `
  results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_v2.csv `
  results\generated_5x5_6x5_gpt4omini_memory_normalize_initial_coverage_batch.csv `
  --output results\generated_5x5_6x5_memory_gain_coverage_batch_comparison.csv
```

Observed result:

| Setting | N | Accuracy | Memory eligible | Error guidance | Validated repair success |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline, no normalize | 10 | 8/10 | 0 | 0 | 0 |
| Protected initial normalize | 10 | 9/10 | 0 | 0 | 0 |
| Protected normalize + coverage memory | 10 | 9/10 | 2 | 2 | 1 |

Trace finding:

- The new coverage-memory path successfully identified a 5x5 case where
  GPT-4o-mini weakened eight `directly-left` clues into `Abs(...) == 1`.
  Memory materialized eight concrete target replacements from the source clues
  and applied them in one batch.
- The live 10-puzzle result did not exceed protected normalization overall
  because another 6x5 run entered a separate UNSAT repair path, and live
  GPT-4o-mini outputs vary across runs.

Interpretation:

- This is useful progress for the method: memory is no longer restricted to
  native UNSAT states. It can now operate on a subset of SAT-but-semantically
  suspicious translations.
- Do not yet claim an end-to-end full-pipeline accuracy gain from memory on
  5x5/6x5. The correct claim is narrower:
  "clue coverage routing increases memory eligibility and enables target-aware
  batch repairs for weak/incorrect relation translations."
- For a strong paper result, evaluate this on a fixed prepared/replay set where
  the same translated constraints are reused across ablations. Live API runs on
  10 puzzles are too noisy for fine-grained memory attribution.

Next optimization:

- Build a fixed `SAT_clue_mismatch` replay benchmark from trace JSONL:
  save puzzle id, original constraints, clue-coverage issues, and ground truth.
- Compare:
  - no coverage memory: accept original SAT model;
  - coverage memory: apply target-aware batch replacements;
  - optional repair loop after batch replacement if the batch becomes UNSAT.
- Report memory gain on this memory-eligible subset separately from the full
  all-puzzle accuracy.

Status: implemented first fixed replay benchmark.

Implementation:

- Added `scripts\run_clue_coverage_replay.py`.
- Online traces now record translated/retranslated constraint sets on steps that
  produce a candidate formula, so replay can reuse the exact same LLM-generated
  constraints.
- Replay mode supports two inputs:
  - existing `clue_coverage` repair steps already present in a trace;
  - arbitrary SAT trace steps with recorded constraints, plus the original
    ZebraLogic JSONL for puzzle text recovery.
- When `--error-library` is provided, replay keeps only coverage repairs whose
  expected target can be materialized by memory.

Commands:

```powershell
python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --no-paradigm --no-memory `
  --schema-hint-mode puzzle `
  --translation-normalize initial `
  --output results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_traceconstraints.csv `
  --trace-output results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_traceconstraints.jsonl

python scripts\run_clue_coverage_replay.py `
  --trace results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_traceconstraints.jsonl `
  --data data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_10.jsonl `
  --error-library paradigm_store\mined_relation_templates.db `
  --output results\generated_5x5_6x5_traceconstraints_clue_coverage_replay.csv `
  --trace-output results\generated_5x5_6x5_traceconstraints_clue_coverage_replay.jsonl
```

Fixed replay result:

| Replay subset | N | Before memory | After coverage memory | Improved | Regressed |
| --- | ---: | ---: | ---: | ---: | ---: |
| SAT clue-mismatch, memory-materialized | 2 | 0/2 | 1/2 | 1 | 0 |

Interpretation:

- This is the cleanest current evidence for increasing memory benefit: on the
  exact same GPT-4o-mini-generated constraint states, target-aware coverage
  memory improves one of two memory-eligible SAT clue-mismatch cases and causes
  no regression.
- The improved case contains nine relation repairs, mostly `directly-left`
  clues that GPT-4o-mini weakened to `Abs(...) == 1` or `<`.
- The remaining unimproved case shows that relation-memory repair can correct a
  large fraction of the formalization while other missing/incorrect constraints
  can still keep the final model wrong.

Next step:

- Enlarge the replay set by running protected normalization on more generated
  5x5/6x5 puzzles and extracting all SAT clue-mismatch states.
- Mine additional error templates beyond `directly_left`: especially weakened
  `somewhere_left/right`, same-house equality, and direct-position variants.

Expanded fixed replay, 50-puzzle run:

```powershell
python scripts\generate_zebra_jsonl.py `
  --specs 25:5x5:medium,25:6x5:medium `
  --seed 20260531 `
  --domain-explicit `
  --output data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_50.jsonl

python scripts\run_online.py `
  --data-dir data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_50.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --sizes 5x5,6x5 `
  --max-repair 3 `
  --no-paradigm --no-memory `
  --schema-hint-mode puzzle `
  --translation-normalize initial `
  --output results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_50.csv `
  --trace-output results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_50.jsonl

python scripts\run_clue_coverage_replay.py `
  --trace results\generated_5x5_6x5_gpt4omini_normalize_initial_protected_50.jsonl `
  --data data\hf\zebralogic\generated_5x5_6x5_eval_domain_explicit_50.jsonl `
  --error-library paradigm_store\mined_relation_templates.db `
  --output results\generated_5x5_6x5_clue_coverage_replay_50.csv `
  --trace-output results\generated_5x5_6x5_clue_coverage_replay_50.jsonl
```

Protected-normalize full run:

| Setting | N | Accuracy | 5x5 | 6x5 | Avg LLM calls | Avg repair rounds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-4o-mini, protected initial normalize, no memory | 50 | 27/50 | 13/25 | 14/25 | 2.20 | 0.20 |

Fixed replay result on memory-materialized SAT clue-mismatch states:

| Replay subset | N | Before memory | After coverage memory | Improved | Regressed |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5x5 | 10 | 1/10 | 5/10 | 4 | 0 |
| 6x5 | 8 | 0/8 | 2/8 | 2 | 0 |
| Total | 18 | 1/18 | 7/18 | 6 | 0 |

Repair pattern distribution in the replay subset:

| Clue relation | Generated relation | Count |
| --- | --- | ---: |
| `directly_left` | `adjacent` | 82 |
| `directly_left` | `directly_right` | 10 |
| `directly_left` | `somewhere_left` | 10 |

Interpretation:

- The enlarged fixed replay gives a stronger memory-benefit signal than the
  first 10-puzzle smoke: on identical GPT-4o-mini-generated constraint states,
  target-aware coverage memory improves 6 of 18 memory-materialized SAT
  clue-mismatch cases and causes no regression.
- This supports the core method claim for the current stage:
  experience memory is useful when it formalizes recurring wrong translation
  patterns into explicit target constraints and routes otherwise accepted SAT
  states through deterministic validation and batch repair.
- The evidence is still subset-level, not yet a full all-puzzle end-to-end
  memory gain claim. The all-puzzle protected-normalize run remains 27/50
  without live memory, while replay isolates the memory-eligible states.
- Most current gain comes from one dominant error family: GPT-4o-mini weakens
  `immediately left of` into adjacency, the opposite direction, or generic
  left-of. This is good for attribution, but the next expansion should add
  more families so the method is not only a `directly_left` correction system.

Next expansion:

- Mine and add templates for same-house equality, direct house positions,
  `somewhere_left/right`, and adjacent direction confusions.
- Add a replay report column for partial model improvement, because several
  unchanged-wrong cases move closer to ground truth after memory repair but
  still fail due to other missing or incorrect constraints.
- After the template library broadens, run a paired live memory-vs-no-memory
  experiment on the same 50-puzzle file to test whether the replay gain
  transfers to end-to-end accuracy.
