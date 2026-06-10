# PRISM Paper Rewrite Design Spec
**Date:** 2026-05-30  
**Target venue:** AAAI 2026  
**Strategy:** Plan A — Progressive Merge (原始版本技术细节 + _new版本结构/数据)

---

## 0. Technical Contradiction Resolution Table

Before any prose, all technical conflicts were resolved against source code and `config/default.yaml`.

### 0.1 KDP Conditions

| Conflict Point | Original version | _new version | **Code truth (kdp_identifier.py)** |
|---|---|---|---|
| **Condition A definition** | `|δ_{t-1}(x)| − |δ_t(x)| ≥ 2` (shrinks by ≥2) | `|δ_t(x)| ≤ 1` (uniquely determined) | **Original is correct.** `_DOMAIN_DROP_THRESHOLD = 2`; code: `size_before - size_after >= self._threshold` |
| **Condition B step types** | CHAIN\_PROPAGATION or CONTRADICTION\_ELIMINATION | CHAIN\_PROPAGATION or CONTRADICTION\_ELIMINATION | Both agree. Code: `StepType.CHAIN` or `StepType.CONTRADICTION` |
| **Condition C** | Present (aggregate log-ratio ≥ 1.0 bits) | Absent | **Original is correct.** Condition C exists in code with `_INFO_GAIN_BITS_THRESHOLD = 1.0` |
| **Condition D (repair)** | Not mentioned in either | Not mentioned in either | Code has Condition D (successful repair). **Add to paper.** |

**Resolution for paper:** Use original version's KDP definition with all conditions A, B, C, and add D.

### 0.2 Z3 Triple Verification — Effect Check

| Conflict Point | Original version | _new version | **Code truth (paradigm_verifier.py)** |
|---|---|---|---|
| **Effect check definition** | Non-contradiction (`φ_pre ∧ op` SAT) + Non-vacuousness (`φ_pre ∧ ¬op` SAT) | "net domain reduction ≥ 0.80 across 50 states" | **Original is correct.** `verify_effect()` checks non-contradiction + non-vacuousness via negated-operation probe. No domain-reduction counting in code. |

**Resolution for paper:** Use original version's effect check definition (two sub-conditions: non-contradiction + non-vacuousness).

### 0.3 Trigger Precision Check

| Conflict Point | Original version | _new version | **Code truth (paradigm_verifier.py)** |
|---|---|---|---|
| **Metric meaning** | Non-firing rate (fraction where trigger does NOT fire) | "Z3-UNSAT for states not satisfying trigger" | **Original is correct.** `verify_trigger_precision()` counts `non_matching` (trigger does not fire on sample). Returns non-firing fraction. |
| **Pool size** | "pool of 18 annotated constraints" | "20 random states not satisfying trigger" | **Original is correct.** `_REPRESENTATIVE_CONSTRAINT_POOL` has 18 entries. |
| **Sample size** | N_p = 50 | N = 20 | **Original is correct.** `_DEFAULT_N_SAMPLES = 50` |
| **Precision threshold** | ≥ 0.80 (as precision floor) | ≥ 0.80 | **Config truth:** `paradigm_precision_floor: 0.20` in default.yaml. **Neither version is correct.** The paper says ≥0.80, code rejects if `< 0.20`. The metric measures non-firing rate; a floor of 0.20 means at least 20% of random samples must NOT match — i.e., the trigger must not fire on everything. Use config value: **τ_p = 0.20 (non-firing floor)**. |

**Resolution for paper:** The trigger precision metric is the non-firing rate (structural set-intersection check). Threshold τ_p = 0.20. **⚠️ Both paper versions had wrong threshold (0.80). Use 0.20 from config.**

### 0.4 Repair Rounds and Max_repair_rounds

| Conflict Point | Original version | _new version / experiments | **Code truth (config/default.yaml)** |
|---|---|---|---|
| **max_repair_rounds** | R = 5 | K = 8 (used in experiments table) | **Config:** `max_repair_rounds: 5`. _new/experiments also says `K = 8` in hyperparams section. **⚠️ Inconsistency within _new itself.** |
| **L4 attempt threshold** | "L4 at most once per puzzle" | not specified | **Config:** `l4_attempt_threshold: 10`; code: L4 triggers when `n >= _L4_ATTEMPT_THRESHOLD (10)` and no SAT outcomes. Also: a second L4 attempt is not explicitly blocked by code (only by the attempt threshold). |
| **Termination bound** | R+2 per puzzle | not stated | **From code:** `max_repair_rounds: 5` = R = 5. Worst case: 1 (translate) + 5 (repair) + 1 (L4 retranslate) = 7. Formula is R+2 = 7. This is correct IF max_repair_rounds = 5. |

**⚠️ Critical: The experiments_new.tex hyperparameters table says `K = 8` while config says `max_repair_rounds: 5`.** This requires user clarification — experiments may have been run with a different config value.

**Provisional resolution:** Use R = 5 (from config). Note that experiments table K=8 may be a different parameter or was changed for experiments. **Flag for user.**

### 0.5 Stagnation / Loop Thresholds

| Parameter | Original | _new | **Config truth** |
|---|---|---|---|
| `τ_stag` (Jaccard) | 0.75 | 0.75 | `stagnation_jaccard: 0.75` ✓ Both correct |
| Stagnation window k | 3 | 3 | `stagnation_window: 3` ✓ Both correct |
| `τ_ℓ` (cosine loop) | 0.90 | 0.90 | `loop_cosine: 0.90` ✓ Both correct |
| Checkpoint stack | depth ≤ 5 | not stated | `checkpoint_stack_limit: 5` ✓ Original correct |
| Cluster distance θ | 0.25 | 0.25 | `cluster_distance: 0.25` ✓ Both correct |
| Cluster min size | 5 | 5 | `cluster_min_size: 5` ✓ Both correct |
| Soundness threshold | ≥ 0.90 | ≥ 0.90 | `paradigm_soundness: 0.90` ✓ Both correct |

### 0.6 Experiment Results Status

The `experiments_new.tex` table contains **specific numerical results with significance stars, 3 seeds, bootstrap resampling**. These appear to be real measured results. User must confirm before treating them as ground truth for the rewrite.

---

## 1. Paper Architecture (Final Structure)

The final paper in `sections_final/` will have the following files and approach:

### `abstract_final.tex`
**Source:** `abstract_new.tex` as base (cleaner narrative, no technical inaccuracies)  
**Changes:** Minor language polish; ensure numbers match experiments_new.tex data

### `introduction_final.tex`
**Source:** `introduction_new.tex` as base (better subsection structure)  
**Changes:**
- Tighten prose to AAAI style (remove over-elaborate subsection headers inside Introduction — AAAI convention is to avoid `\subsection` inside `\section{Introduction}`)
- Preserve the narrative structure (motivation → limitations → insight → PRISM → contributions)
- Update contribution list to match actual code (4 contributions, not misaligned numbering)

### `related_work_final.tex`
**Source:** `related_work.tex` original as base (has the EBL/clause-learning spectrum section that is academically stronger)  
**Changes:**
- Absorb `related_work_new.tex`'s "Summary: PRISM's Novelty" structure
- Polish citation format to `\citep{}` form throughout
- Remove the "Unsupervised Knowledge Extraction" subsection (too generic, not competitive)

### `methodology_final.tex`
**Source:** `methodology.tex` original as primary (technically correct)  
**Changes based on contradiction resolution:**
- **KDP Section:** Use original Condition A (≥2 drop), keep Condition C, add Condition D (successful repair — currently missing from both paper versions)
- **Effect Check:** Use original (non-contradiction + non-vacuousness) — NOT _new's domain-reduction version
- **Trigger Precision:** Use original's non-firing-rate framing, but update threshold to τ_p = 0.20 (from config)
- **max_repair_rounds:** Use R = 5 (config value); flag K=8 discrepancy for user
- Absorb `methodology_new.tex`'s cleaner PRISM Architecture Overview table format

### `experiments_final.tex`
**Source:** `experiments_new.tex` (has actual data)  
**Changes:**
- Fix hyperparameter table: use R = 5 (or clarify K = 8)
- Ensure all metric definitions are precise
- Confirm KnK citation accuracy

### `conclusion_final.tex`
**Source:** `conclusion_new.tex` (much better structure with Broader Implications)  
**Changes:** Minor polish, fill in acknowledgments placeholder note

---

## 2. Writing Style Guidelines (AAAI 2026 Standard)

- **Concise:** No sentence > 40 words without cause. Cut every hedge word ("basically", "essentially", "in a sense").
- **Claim-first:** Lead with the claim, follow with evidence/justification. Never bury the finding.
- **Active voice** preferred for contributions and results. Passive acceptable for describing the system.
- **No subsections inside Introduction** — AAAI style uses `\textbf{paragraph}` instead.
- **Citations:** `\citep{}` for parenthetical, `\citet{}` for inline. Never "(Author Year)" manually.
- **Tables:** All result tables must have `\toprule / \midrule / \bottomrule` (booktabs). All significance-starred results noted in caption.
- **Math notation:** Consistent throughout — use the original methodology.tex notation (which is more complete).

---

## 3. Unanswered Questions (Need User Clarification Before Writing Experiments)

1. **max_repair_rounds: Is it R=5 (config) or K=8 (experiments table)?** If K=8 was the actual experimental setting, config should be updated before paper describes it.
2. **Trigger precision threshold: τ_p = 0.20 (config) or 0.80 (as stated in both paper versions)?** These describe the same metric differently — 0.20 means "reject paradigms that fire on >80% of random samples." Are the two descriptions equivalent and was the paper just badly worded?
3. **Are the numbers in experiments_new.tex real measured results?**
4. **KnK dataset citation:** Is the 200-puzzle subset from ProntoQA `\citep{saparov2022pronto}` correct, or is this a different dataset?

---

## 4. Section Rewrite Order

1. methodology_final.tex (most technically sensitive — resolve first)  
2. experiments_final.tex (depends on #1 for hyperparameter consistency)  
3. abstract_final.tex (depends on final results)  
4. introduction_final.tex  
5. related_work_final.tex  
6. conclusion_final.tex  
7. main_final.tex (top-level file pointing to sections_final/)
