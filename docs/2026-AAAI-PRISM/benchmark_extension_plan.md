# Second Benchmark: Knights & Knaves (cross-problem-type validation for C4)

## Why K&K and not Sudoku / N-Queens

We need a benchmark that:
1. Has a different constraint-type taxonomy than ZebraLogic (to validate L2 cross-problem-type paradigm transfer).
2. Is solvable by Z3 (so the SMT-grounded screening pipeline still applies).
3. Has data already locally available (no extra acquisition cost).
4. Has a difficulty axis comparable to ZebraLogic (so cross-scale claims port over).

K&K satisfies all four: 7 scales `test_people{2..8}.jsonl` already in `data/hf/knights-and-knaves/`, structured `statements` field (Lisp-like AST) shortcuts the LLM translation step, constraint types are propositional logic with self-referential statements (`telling-truth`, `lying`, `<=>`, `not`) — totally disjoint from ZebraLogic's `position`, `binding`, `adjacency`, `distinct` taxonomy.

Sudoku / N-Queens would require building a dataset; K&K is plug-and-play.

## Workplan

### Phase 1: Data loader (~0.5 day)

- Add `prism/data/knights_knaves_loader.py` reading `test_people{2..8}.jsonl`.
- Each record becomes a `PuzzleInstance`:
  - `nl_description` ← `quiz`
  - `solution` ← `solution`
  - `variables` ← `names`
  - `size` ← f"people_{N}"
  - `domain` ← "knights_knaves"
- Train/dev/test split: take 70% / 10% / 20% per scale, fixed seed.

### Phase 2: Translation prompts (~1 day)

- New prompt template that maps NL statements to Z3 propositional formulae:
  - Each `name` → `Bool('<name>')` where `True` = knight, `False` = knave.
  - "A says 'X'" → `Implies(A, X) ∧ Implies(Not(A), Not(X))` (knight tells truth, knave lies).
  - Built-in templates for `<=>`, `not`, `and`, `or`.
- Validate translation correctness on the structured `statements` field: parse it directly into Z3 as ground-truth comparison baseline.

### Phase 3: Paradigm reusability evaluation (~1 day)

- Run **PRISM with the ZebraLogic-trained paradigm library** (no K&K-specific training) on K&K dev/test.
- Report two transfer metrics:
  - **L2 raw hit rate**: fraction of K&K solving steps where any ZebraLogic-trained paradigm fired. Expect this to be *low* (constraint types differ).
  - **L2 conditional benefit**: when a paradigm did fire, did it help (vs PRISM-no-paradigm on the same puzzle)?
- This is direct evidence for the C4 (paradigm transferability) claim: if hit rate is low but conditional benefit is positive, paradigms transfer non-trivially across problem types.

### Phase 4: K&K-trained library (optional, ~1 day)

- Run the offline distillation pipeline on K&K training split to produce a K&K-specific library.
- Report:
  - Library overlap with ZebraLogic library (any paradigms that are essentially equivalent up to renaming?)
  - Cross-direction L2 transfer: K&K-trained paradigms applied to ZebraLogic.

## What to report in the paper

A new subsection in Section 5 (Experiments): "Cross-Problem-Type Transfer (K&K)".

Three numbers to report explicitly:
1. PRISM Full vs neuro-symbolic baseline on K&K dev/test, accuracy + repair rounds.
2. ZebraLogic-trained paradigm L2 hit rate and conditional benefit on K&K.
3. (Optional) K&K-trained paradigm L2 transfer to ZebraLogic.

## Honesty considerations

- We must NOT report a paradigm "hit" as success when the paradigm only fired but did not contribute. The hit rate and the conditional benefit are separate numbers; conflating them is the kind of issue a reviewer will catch.
- If L2 hit rate is essentially zero, that is fine — the report becomes "ZebraLogic paradigms do not transfer to K&K out of the box; cross-domain transfer is left to future work". This is a legitimate negative result that strengthens credibility.

## Decision needed

- Do we want to commit to running K&K? Confirmed `data/` already has the dataset. Cost: ~3 person-days + LLM call budget for ~700 puzzles.
- If yes, this becomes the empirical anchor for C4 (paradigm transferability) and saves the contribution from being purely conceptual.
- If no, C4 must be downgraded to "future work" in the conclusion, and the related "paradigm transferability" evaluation contribution must be re-scoped to L1 (cross-scale within ZebraLogic) only.
