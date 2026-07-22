# Claims

## C01: SAT alone is insufficient for task correctness
- **Statement**: In the evaluated LLM-to-solver pipelines, a SAT result can coexist with an incorrect task answer because satisfiability checks internal consistency rather than semantic faithfulness.
- **Status**: supported
- **Provenance**: ai-suggested
- **Falsification criteria**: A proof that the evaluated acceptance protocol makes SAT imply semantic equivalence, together with the absence of SAT-but-wrong runs under the audited outputs.
- **Proof**: [E01, E02]
- **Dependencies**: []
- **Tags**: SBW, satisfiability, semantic faithfulness

## C02: SPARC reduces observed SBW and answered-sample risk
- **Statement**: On 200 labeled ZebraLogic questions across three seeds, matched SPARC configurations reduce SBW from 78 to 13 and from 73 to 26, with answered-sample risk falling from 55.71% to 15.85% and from 53.68% to 27.66%.
- **Status**: supported
- **Provenance**: ai-suggested
- **Falsification criteria**: Recalculation from the recorded per-seed outputs fails to reproduce the four-outcome ledger or matched comparisons.
- **Proof**: [E01]
- **Dependencies**: [C01]
- **Tags**: ZebraLogic, risk, coverage

### 2026-07-15 scope amendment
- **Status**: weakened
- **Provenance**: ai-suggested
- **Reason**: The word "matched" describes configuration labels, not frozen inputs. Only 175/600 and 199/600 pre-gate constraint states exactly match, so the endpoint differences remain descriptive rather than causal. See C08 and E05.

## C03: Structural gating is necessary but not sufficient for semantic correctness
- **Statement**: The uniqueness gate detects multiple answer projections but does not detect unique-but-wrong formalizations.
- **Status**: supported
- **Provenance**: ai-suggested
- **Falsification criteria**: A proof that uniqueness entails semantic faithfulness for all admitted formalizations, or an audit showing no unique-but-wrong cases under the stated classification protocol.
- **Proof**: [E04]
- **Dependencies**: [C01]
- **Tags**: uniqueness, limitation, answer projection

## C04: Accuracy improvement is not established
- **Statement**: The observed accuracy point estimates do not support a statistically established improvement or a no-loss claim under the analyses currently available.
- **Status**: revised
- **Provenance**: ai-suggested
- **Falsification criteria**: A prespecified, adequately powered superiority or non-inferiority analysis supports the corresponding claim.
- **Proof**: [E01]
- **Dependencies**: [C02]
- **Tags**: statistics, accuracy, scope calibration

## C05: Accepted discriminative completion contracts a finite answer space
- **Statement**: If a completion constraint depends only on answer variables, excludes at least one of two current answer models, and preserves SAT, the projected answer space becomes a strict subset; finite-budget completion terminates.
- **Status**: revised
- **Provenance**: ai-suggested
- **Falsification criteria**: A counterexample satisfying all premises where the projected answer space does not strictly contract.
- **Proof**: [conditional projected-answer argument pending an explicit answer-variable-only proposition; E05 documents that the current implementation does not enforce the premise]
- **Dependencies**: [C03]
- **Tags**: contraction, termination, conditional guarantee

### 2026-07-15 implementation amendment
- **Status**: revised
- **Provenance**: ai-suggested
- **Reason**: The proposition remains conditional, but current code does not enforce its answer-variable-only premise. The manuscript now proves complete-model-space progress and records the projected-answer-space condition separately in C09 and E05.

## C06: Near-zero overhead is not supported
- **Statement**: The former near-zero-cost characterization is inconsistent with traces showing 0.86 to 1.07 additional LLM calls per question.
- **Status**: refuted
- **Provenance**: ai-suggested
- **Falsification criteria**: A corrected trace audit demonstrates negligible LLM-call and end-to-end overhead under the same configurations.
- **Proof**: [E03]
- **Dependencies**: []
- **Tags**: efficiency, LLM calls, withdrawn claim

## C07: The frozen-state uniqueness gate has bounded diagnostic value
- **Statement**: On the audited no-gate ZebraLogic constraint states, the uniqueness probe detects 72/78 baseline SBW outputs and 69/73 aggressive SBW outputs, while also rejecting 6/62 and 15/63 correct outputs as structurally non-unique.
- **Status**: supported
- **Provenance**: ai-suggested
- **Falsification criteria**: Reproducing the frozen-state audit from the cached traces yields materially different contingency counts under the stated answer-projection protocol.
- **Proof**: [E05]
- **Dependencies**: [C01, C03]
- **Tags**: ZebraLogic, uniqueness, diagnostic scope, selective answering

## C08: Historical endpoint differences do not identify a causal SPARC effect
- **Statement**: The lower endpoint SBW counts and answered-sample risk in the historical SPARC arms cannot be attributed to SPARC because only 175/600 and 199/600 pre-gate constraint states exactly match their nominal controls.
- **Status**: supported
- **Provenance**: ai-suggested
- **Falsification criteria**: A prospectively frozen-input paired rerun demonstrates that the historical arms were in fact paired, or independently estimates the component effect while controlling the initial constraint state.
- **Proof**: [E05]
- **Dependencies**: [C02]
- **Tags**: causal inference, provenance, experimental design, scope calibration

## C09: Current completion acceptance guarantees full-model progress, not projected-answer contraction
- **Statement**: Given a SAT candidate that excludes at least one current complete model, adding it strictly contracts the complete-model space. The implementation does not enforce the answer-variable-only premise needed to infer strict contraction of the projected answer space.
- **Status**: supported
- **Provenance**: ai-suggested
- **Falsification criteria**: A counterexample violates strict complete-model contraction under the stated condition, or the implementation is shown to mechanically restrict every candidate to the answer-variable whitelist.
- **Proof**: [E05, `docs/paper_draft/sparc_paper_zh.tex`, Proposition 3]
- **Dependencies**: [C05]
- **Tags**: completion, projection, theorem scope, implementation boundary

## C11: The current SPARC baseline comparison supports only reported operating-point ordering
- **Statement**: The 78-label risk--coverage comparison supports lower observed risk for structural gating than the listed confidence and multi-formalization operating points, but does not establish global Pareto dominance across thresholds, models, or tasks.
- **Status**: revised
- **Provenance**: ai-suggested
- **Falsification criteria**: A sufficiently powered, prespecified comparison across complete operating curves and matched conditions establishes dominance under a stated criterion.
- **Proof**: [`docs/paper_draft/sparc_paper_zh.tex`, Section 5.3]
- **Dependencies**: [C04, C08]
- **Tags**: SPARC, selective prediction, risk coverage, scope calibration

## C10: PRISM solver screening constrains encoded consistency, not language-to-logic semantic fidelity
- **Statement**: In PRISM, sampled Z3 checks can reject candidate paradigms that conflict with the current formal constraint state, but they cannot by themselves establish that the natural-language constraints were translated faithfully or that a paradigm is correct on all unseen states.
- **Status**: revised
- **Provenance**: ai-suggested
- **Falsification criteria**: A method specification and validation study establish semantic fidelity of the natural-language-to-Z3 mapping and universal paradigm correctness from the existing screening procedure alone.
- **Proof**: [`docs/paper_draft/PRISM_AAAI_chinese_polished.md`, `docs/paper_draft/source_notes_zh/PRISM_methodology_chinese.md`]
- **Dependencies**: []
- **Tags**: PRISM, solver screening, semantic fidelity, scope calibration
