# Problem

LLM-to-solver pipelines commonly accept an executable, satisfiable constraint set as a successful formalization. Satisfiability establishes internal consistency, but not faithfulness to the natural-language task. Missing or weakened constraints can enlarge the projected answer space while remaining SAT, allowing a solver to return a formally valid but task-incorrect answer.

The paper studies this run-level outcome as satisfiable-but-wrong (SBW). SPARC adds task-specified answer-space structure as a necessary acceptance condition, uses a second answer model to guide constraint completion, and abstains when the structural condition cannot be recovered within budget.

The core scope boundary is that answer-space structure is not a proof of semantic correctness. Unique-but-wrong formalizations can pass the gate.

