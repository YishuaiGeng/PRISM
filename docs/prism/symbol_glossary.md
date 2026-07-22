# PRISM Symbol Glossary

Single source of truth for symbols and named thresholds used across the paper, supplementary, and code. When in doubt, defer to `config/default.yaml` for numerical defaults.

## Conventions

- **Paper symbol** column matches the LaTeX usage in `docs/2026-AAAI-PRISM/sections/*.tex` and `sections_supp/*.tex`.
- **Code identifier** column is the canonical name in the `prism/` package or in `config/default.yaml` (YAML key form).
- **Default** is the numeric / categorical value shipped in `config/default.yaml`.
- **Defined in** points to the methodology subsection that introduces the symbol.

## Thresholds and hyperparameters

| Paper symbol | Code identifier | Default | Defined in | Notes |
|---|---|---|---|---|
| `R` (max repair rounds) | `thresholds.max_repair_rounds` / `_DEFAULT_MAX_REPAIR_ROUNDS` | 5 | §3.5 | Bounds online LLM-call budget to `R+2` (Appendix B termination proof). |
| KDP domain drop | `thresholds.kdp_domain_drop` / `_DOMAIN_DROP_THRESHOLD` | 2 | §3.3.2 Condition A | Per-variable hard cutoff. |
| `τ_ig` (KDP info-gain, bits) | `thresholds.kdp_info_gain_bits` / `_INFO_GAIN_BITS_THRESHOLD` | 1.0 | §3.3.2 Condition C | Aggregate `Σ log₂(d_before/d_after)`. |
| `θ` (cluster distance) | `thresholds.cluster_distance` | 0.25 | §3.3.3 | Complete-linkage agglomerative threshold (cosine distance). |
| `m_min` (min cluster size) | `thresholds.cluster_min_size` / `thresholds.min_support` | 5 | §3.3.3 | Clusters below this are discarded. |
| `τ_s` (soundness) | `thresholds.paradigm_soundness` | 0.90 | §3.3.4 | Acceptance rate over `N_p` random subsets. |
| `τ_p` (precision floor) | `thresholds.paradigm_precision_floor` / `_DEFAULT_TRIGGER_PRECISION_FLOOR` | 0.20 | §3.3.4 | **Non-firing-rate floor**, not firing-rate ceiling. Earlier drafts mis-stated this as 0.80; the convention used throughout the current paper and code is the non-firing-rate floor. |
| `N_p` (verification trials) | `thresholds.verification_trials` / `_DEFAULT_N_SAMPLES` | 50 | §3.3.4 | Soundness and precision both sample this many trials. |
| Layer-1 top-K | `thresholds.paradigm_top_k` / `_DEFAULT_PARADIGM_TOP_K` | 3 | §3.4.1 | Paradigm candidates passed to Layer-2 / consistency check. |
| Min retrieval confidence | `thresholds.paradigm_confidence_floor` | 0.50 | §3.4.1 | Paradigms below this confidence are never retrieved. |
| Layer-2 policy | `thresholds.layer2_policy` | `complexity_gated` | §3.4.1 | One of `always`, `complexity_gated`, `stagnation_only`. |
| Layer-2 complexity floor | `thresholds.layer2_complexity_floor` / `_LAYER2_COMPLEXITY_VAR_FLOOR` | 25 constraints | §3.4.1 | Below this size, Layer-2 is skipped unless UNSAT has occurred. |
| `τ_stag` (stagnation Jaccard) | `thresholds.stagnation_jaccard` | 0.75 | §3.5.2 | MAX-over-pairs criterion on **canonicalised** UNSAT cores. |
| `k` (stagnation window) | `thresholds.stagnation_window` | 3 | §3.5.2 | Number of recent records considered. |
| `τ_ℓ` (loop cosine fallback) | `thresholds.loop_cosine` | 0.90 | §3.5.3 | Used only when structured `(τ, c, π)` triple match does not fire. |
| Checkpoint stack depth | `thresholds.checkpoint_stack_limit` / `_CHECKPOINT_STACK_LIMIT` | 5 | §3.5.4 | Multi-level L3 revert. |
| L4 attempt threshold | `thresholds.l4_attempt_threshold` / `_L4_ATTEMPT_THRESHOLD` | 10 | §3.5.4 | Fallback when no SAT outcome has been observed. |
| Re-verification batch `K` | `thresholds.writeback_batch_K` | 50 | §3.6 | Online write-back candidates re-screened every K solved puzzles. |

## Five-tuple paradigm

| Paper symbol | Code field on `Paradigm` schema |
|---|---|
| `Q` (trigger conditions) | `trigger: dict` — keys `constraint_types: List[str]`, optional `relational_predicates: List[dict]` |
| `O` (inference operation) | `operation: str` |
| `φ_pre` (pre-condition) | `pre_condition: str` (SMT-LIB / Z3 Python form) |
| `φ_post` (post-condition) | `post_condition: str` |
| `S` (applicable scope) | `scope: List[str]` |
| (provenance) | `id`, `name`, `confidence`, `support_count`, `source_cluster`, `created_at` |

## Repair record six-tuple

| Paper symbol | Code field on `RepairRecord` schema |
|---|---|
| `e_t` (error type) | `error_type: ErrorType` |
| `U_t` (UNSAT core) | `unsat_core: List[str]` |
| `Û_t` (core fingerprint) | `core_fingerprint: str` — SHA-256 of canonicalised core |
| `α_t` (repair action) | `repair_action: RepairAction` — fields `type`, `target_constraint`, `summary`, `parameter_signature` (new), `embedding` |
| `o_t` (outcome) | `outcome: Outcome` (SAT / UNSAT) |
| `U'_t` (new core) | `new_core: Optional[List[str]]` |

## ErrorType enum

Paper text uses the names without the `_` prefix; code uses the enum members below.

| Paper text | Code enum |
|---|---|
| `LegacyError` | `ErrorType.LEGACY` |
| `OverConstraint` | `ErrorType.OVER_CONSTRAINT` |
| `UnderConstraint` | `ErrorType.UNDER_CONSTRAINT` |
| `SemanticFlip` | `ErrorType.SEMANTIC_FLIP` |
| `ScopeError` | `ErrorType.SCOPE_ERROR` |
| `SyntaxError` | `ErrorType.SYNTAX` (note: code uses `SYNTAX`, not `SYNTAX_ERROR`) |

## Escalation levels

| Paper text | Code enum (`SwitchLevel`) |
|---|---|
| L1 — Switch Target | `L1_SWITCH_TARGET` |
| L2 — Switch Type | `L2_SWITCH_TYPE` |
| L3 — Revert Checkpoint | `L3_REVERT_CHECKPOINT` |
| L4 — Full Retranslate | `L4_FULL_RETRANSLATE` |

## Constraint kinds (used by trigger precision)

Defined in `prism/offline/paradigm_verifier.py::_CONSTRAINT_KINDS`. Trigger precision matches a paradigm's `trigger.constraint_types` against the kinds annotated on each pool entry by **set intersection**.

`position_arithmetic`, `position_equality`, `position_inequality`, `attribute_binding`, `distinct`, `quantified_exclusion`, `integer_bound`, `integer_equality`, `integer_inequality`, `integer_arithmetic`.

## Relational predicates (Layer-1)

Optional under `Paradigm.trigger["relational_predicates"]`. Each entry is `{"kind": ..., ...}`:

- `count_atleast` — `{"kind": "count_atleast", "type": <t>, "n": <int>}`
- `count_atmost` — `{"kind": "count_atmost", "type": <t>, "n": <int>}`
- `cooccur` — `{"kind": "cooccur", "types": [<t1>, <t2>, ...]}`

Unknown kinds soft-pass (do not filter).
