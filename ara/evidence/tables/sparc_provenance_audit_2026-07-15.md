# E05: Cached SPARC Provenance Audit

- **Date**: 2026-07-15
- **Provenance**: ai-executed
- **Command**: `python scripts/audit_sparc_evidence.py --output-dir <temporary directory>`
- **Scope**: Cached ZebraLogic, AR-LSAT, and component traces only. The audit made no LLM calls.

## Results

- The historical endpoint arms are not a frozen-input comparison. Exact pre-gate
  constraint-multiset matches are 175/600 (29.2%) for baseline versus
  baseline+SPARC and 199/600 (33.2%) for aggressive versus aggressive+SPARC.
  Post-hoc matched-subset SBW counts are 21 to 6 and 19 to 8, respectively.
- On frozen no-gate constraints, the uniqueness probe finds 72/78 baseline SBW
  outputs and 69/73 aggressive SBW outputs. It also classifies 6/62 and 15/63
  correct outputs as non-unique.
- The current code accepts discriminative completion candidates without an
  answer-variable whitelist. The audit found 1,336 accepted candidates and no
  previously unseen integer variable, but this observation does not enforce the
  premise required for projected-answer-space contraction.
- The AR-LSAT first-40 pilot is protocol-confounded: only 11/40 reconstructed
  backgrounds match, and the baseline includes 14 random fallback answers.

## Interpretation Boundary

This audit supports the fixed-state diagnostic claim and the manuscript's
evidence hierarchy. It does not establish a causal end-to-end SPARC effect,
semantic correctness of accepted completions, or cross-task generalization.

## Source Bindings

- `scripts/audit_sparc_evidence.py`
- `results/zebra_v2_s42`, `results/zebra_v2_s123`, `results/zebra_v2_s7`
- `results/arlsat_gate_probe`
- `results/zebra_ablation_s42`
