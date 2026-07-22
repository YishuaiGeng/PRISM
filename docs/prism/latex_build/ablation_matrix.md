# PRISM Ablation Experiment Matrix

Pre-execution checklist of every ablation we plan to report. Each row is a self-contained run that should be reproducible by editing only one knob away from `PRISM Full`. Run them on the ZebraLogic dev set (100 puzzles) first, then promote to the full test set (300 puzzles) for the ones that show signal.

## A. Paradigm-side ablations (validates C1)

| ID | Variant | Diff from Full | Key metric to report | Hypothesis to confirm/falsify |
|---|---|---|---|---|
| A0 | **PRISM Full** | — (reference) | accuracy, repair rounds, LLM calls | — |
| A1 | w/o paradigm library | `enable_paradigm = False`; pure LLM+Z3 | accuracy drop attributed to paradigm | Library carries non-trivial accuracy lift |
| A2 | w/o triple verification | admit every LLM-abstracted paradigm without soundness/effect/precision filter | accuracy + paradigm-misfire rate | Filter is the discriminator, not just the LLM abstraction |
| A3 | w/o soundness check | `τ_s = 0.0`, keep effect + precision | accuracy + over-application rate | Soundness contributes meaningfully |
| A4 | w/o effect check | drop both non-contradiction and non-vacuousness | vacuous paradigms admitted (count) | Effect prevents trivially-true paradigms |
| A5 | w/o precision check | `τ_p = 0.0`, accept any selectivity | trigger over-fire rate | Precision is needed for selectivity |
| A6 | w/o relational predicates (Layer-1) | retriever ignores `relational_predicates` in trigger | trigger over-fire rate, accuracy on 6×6 | Relational predicates lift Layer-1 above pure type-set match |
| A7 | w/o Layer-2 (always-off) | `layer2_enabled = False` | accuracy + per-step LLM calls | Layer-2 helps when Layer-1 is ambiguous |
| A8 | Layer-2 always-on | `layer2_policy = always` | accuracy + per-step LLM calls | Default `complexity_gated` policy preserves most accuracy at lower cost |
| A9 | Paradigm library size scaling | use {10, 20, 35, 50, 100} top-confidence paradigms | accuracy curve over library size | Diminishing returns past ~35; absolute lift over A1 |
| A10 | w/o online write-back | freeze `L`, no candidate staging | accuracy delta over A0 | Online write-back is a measurable gain, not just plumbing |

## B. Repair-memory-side ablations (validates C2)

| ID | Variant | Diff from Full | Key metric to report | Hypothesis to confirm/falsify |
|---|---|---|---|---|
| B0 | **PRISM Full** (same as A0) | — | — | — |
| B1 | w/o repair memory | `enable_memory = False` (paradigm library kept) | accuracy + repair rounds | Memory is required even with paradigms |
| B2 | w/o stagnation detection | always-False stagnation detector | repair rounds long tail | Stagnation detection cuts the tail |
| B3 | w/o loop detection | always-False loop detector | duplicate repair rate | Loop detection prevents oscillation |
| B4 | w/o ErrorType secondary classification | force `OVER_CONSTRAINT` for all NEW_ASSERTION | repair success rate per error type | Secondary classification routes repairs better |
| B5 | w/o L1 | escalation skips L1, goes straight to L2 | accuracy + repair rounds | L1 is the cheap fix that catches most |
| B6 | w/o L2 | escalation skips L2, goes L1 → L3 | accuracy + repair rounds | L2 covers the medium-difficulty regime |
| B7 | w/o L3 | escalation skips L3, goes L2 → L4 | accuracy + L4 trigger rate | L3 saves puzzles that would otherwise hit L4 |
| B8 | w/o L4 | L4 never triggered; declare unsolved | accuracy ceiling | L4 is the last-resort recovery; non-zero contribution |
| B9 | single-level checkpoint (no stack) | `checkpoint_stack_limit = 1` | L3 success rate | Multi-level stack catches more recoverable states |
| B10 | NL-only loop detection | revert `detect_loop` to embedding-only | undetected loops on dev set | Structured triple match catches paraphrase loops the embedding misses |
| B11 | Raw UNSAT cores (no canonicalisation) | revert `detect_stagnation` to raw `unsat_core` | stagnation detection precision/recall | Canonicalisation matters |

## C. Cross-cutting / end-to-end

| ID | Variant | Diff from Full | Key metric |
|---|---|---|---|
| C1 | PRISM Full vs each baseline on 4×4 / 5×5 / 6×6 | side-by-side | accuracy × scale matrix |
| C2 | PRISM Full vs A1 vs B1 on 4×4 / 5×5 / 6×6 | three-way | which component drives gains at which scale |
| C3 | Amortised cost analysis | record offline cost + online cost on test set, compute total per puzzle | $ per puzzle vs baselines |
| C4 | Robustness to LLM choice | swap GPT-4o / Claude / open-weight model in offline distillation | library diversity & coverage |

## Execution notes

- **Dev set first**: run A1-A10 and B1-B11 on the 100-puzzle dev split. Only promote variants whose dev-set delta is > 2pp accuracy or > 0.5 repair rounds to full test-set runs.
- **Single-knob discipline**: every ablation must differ from Full by exactly one configuration line. Avoid combined ablations until the singles are reported.
- **Reproducibility**: each row should have a `config/experiments/ablation_<ID>.yaml` that inherits from `config/default.yaml` and overrides only the necessary knob.
- **Statistical reporting**: 3 seeds per variant on dev set; full test set with 1 seed (budget permitting). Report mean and seed-stdev where applicable.
