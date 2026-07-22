# PRISM MVP Design

## Goal

Build a runnable PRISM MVP that supports four systems for early experiments:

- Paper-1 baseline: LLM + Z3 repair loop, no paradigm, no repair memory.
- PRISM w/o Memory: paradigm guidance enabled, repair memory disabled.
- PRISM w/o Paradigm: repair memory enabled, paradigm guidance disabled.
- PRISM Full: paradigm guidance and repair memory both enabled.

## Architecture

The existing package structure stays intact. The MVP tightens behavior in the online and evaluation layers instead of adding new subsystems.

`GuidedSolver` becomes configurable through explicit `enable_paradigm` and `enable_memory` flags. Paradigm guidance controls library retrieval, semantic matching, consistency pre-checks, and confidence write-back. Repair memory controls history summaries, loop/stagnation detection, and strategy switching. With both disabled, the solver behaves as the Paper-1 baseline.

Evaluation loaders remain responsible for converting datasets into `PuzzleInstance`. Evaluators must judge correctness by exact match against `PuzzleInstance.solution` when ground truth is present. A SAT solver result alone is not counted as solved for benchmark accuracy.

## Components

- `prism/online/guided_solver.py`: add feature flags and make memory/paradigm paths independently removable.
- `scripts/run_online.py`: wire CLI ablation flags into `GuidedSolver`.
- `scripts/run_experiments.py`: wire experiment variant flags into `GuidedSolver`.
- `prism/evaluation/benchmarks/*.py`: use exact-match correctness when ground truth exists.
- Tests: cover ablation behavior and exact-match evaluation.

## Data Flow

1. Translate puzzle text to Z3 constraints.
2. Check SAT/UNSAT.
3. If UNSAT, optionally retrieve safe paradigm hints.
4. Optionally inject repair history and strategy-switch prompts.
5. Ask LLM for a repair, rebuild solver, and repeat.
6. Return `SolveResult`.
7. Evaluator compares predicted solution to ground truth if available.

## Error Handling

The MVP keeps existing solver error behavior. Empty or invalid translations still produce a `SolveResult` rather than crashing. If memory is disabled, no stagnation or loop escalation is attempted. If paradigms are disabled, the library is never queried and no confidence write-back is performed.

## Testing

Tests must prove:

- Paper-1 mode does not retrieve paradigms or use repair-memory strategy switching.
- w/o Memory mode can still retrieve paradigms but does not set stagnation.
- w/o Paradigm mode never retrieves paradigms.
- Benchmark evaluators count a SAT result as incorrect when it does not match ground truth.
