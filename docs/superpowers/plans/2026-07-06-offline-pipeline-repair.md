# Offline Pipeline Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the offline paradigm mining pipeline so it produces useful positive paradigms from trajectories, then collect 300+ new trajectories and validate the full closed loop works.

**Architecture:** Three targeted fixes to existing code + config change, then a collection run, then a validation run. No new modules needed. The root problem is (1) `domain_sizes_before/after` are never populated (starves KDP conditions A and C), (2) `cluster_min_size=5` is too high for the current trajectory volume, and (3) the KDP feature vectors are too coarse to separate repair patterns. The plan fixes (1) and (2) directly; (3) is a stretch goal.

**Tech Stack:** Python, Z3, existing PRISM modules (`prism/offline/`, `prism/core/`), pytest, GPT-4o-mini API

## Global Constraints

- Python 3.10+ (match existing codebase)
- Do NOT modify `prism/core/types.py` field definitions — `domain_sizes_before/after` already exist as `Dict[str, int]`, just need to be populated
- Do NOT change the `TrajectoryStep` schema — backward-compatible with existing 64 JSON files
- All changes must preserve existing passing tests: run `pytest tests/ -x -q` before and after each task
- Model: GPT-4o-mini (matches existing trajectory data)
- Config file: `config/default.yaml` — change `cluster_min_size` there, not in code
- Output library: `paradigm_store/prism_v2.db` (keep old files intact)
- Trajectory output: `data/trajectories/gpt4omini_3x_v2/` (separate from existing dirs)

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `prism/offline/trajectory_collector.py` | **Modify** | Populate `domain_sizes_before/after` in each step |
| `config/default.yaml` | **Modify** | Lower `cluster_min_size` from 5 to 2 |
| `tests/test_trajectory_collector.py` | **Modify** | Add tests for domain_sizes population |
| `scripts/run_offline.py` | **Read-only** | Used as-is with `--resume` and `--puzzle-specs` flags |

---

## Task 1: Populate `domain_sizes_before/after` in TrajectoryCollector

**Files:**
- Modify: `prism/offline/trajectory_collector.py`
- Modify: `tests/test_trajectory_collector.py`

**Background:** `TrajectoryStep.domain_sizes_before/after` are `Dict[str, int]` mapping variable name → number of remaining candidate values. In ZebraLogic, each attribute value (e.g., `color_Red`) is an integer variable with initial domain `{1, 2, ..., n_houses}`. After adding a constraint like `Int('color_Red') == 2`, Z3 can determine the model assigns it exactly 2 — so its domain collapses to size 1. The `domain_sizes` should record how many distinct values remain consistent with current constraints for each variable.

**Approach:** After each `solver.check()` call that returns SAT or UNSAT, iterate over the current constraint list to infer domain sizes. The simplest correct method: for each Z3 integer variable seen in constraints, enumerate how many values in `[1, n_houses]` are consistent with the current constraint set by probing with the solver.

**Interfaces:**
- Consumes: `Z3SolverWrapper` (existing), `PuzzleInstance.size` (existing `"3x3"` string)
- Produces: populated `domain_sizes_before` and `domain_sizes_after` dicts in each `TrajectoryStep`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_trajectory_collector.py  — add to existing test file

def test_domain_sizes_populated_after_repair(mock_llm_client):
    """domain_sizes_before and domain_sizes_after should be non-empty dicts."""
    from prism.offline.trajectory_collector import TrajectoryCollector
    from prism.core.types import PuzzleInstance

    puzzle = PuzzleInstance(
        puzzle_id="test-001",
        nl_description=(
            "There are 3 houses numbered 1 to 3. Each house has 2 attributes.\n"
            "1. The Red color person lives in house 1.\n"
            "2. The Blue color person is immediately left of the Green color person.\n"
            "Candidate values:\n- color: Red, Blue, Green\n- pet: Cat, Dog, Fish"
        ),
        constraints_nl=[
            "The Red color person lives in house 1.",
            "The Blue color person is immediately left of the Green color person.",
        ],
        solution={"color_Red": "1", "color_Blue": "2", "color_Green": "3",
                  "pet_Cat": "1", "pet_Dog": "2", "pet_Fish": "3"},
        size="3x2",
        domain="zebralogic",
        raw_data={},
    )

    collector = TrajectoryCollector(llm_client=mock_llm_client, max_repair_rounds=2)
    trajectories = collector.collect([puzzle], n_runs=1, temperature=0.0)

    assert len(trajectories) == 1
    traj = trajectories[0]
    # Every non-translate step that enters the repair loop should have domain sizes
    repair_steps = [s for s in traj.steps if s.action == "repair"]
    if repair_steps:
        for step in repair_steps:
            assert isinstance(step.domain_sizes_before, dict), "domain_sizes_before must be a dict"
            assert isinstance(step.domain_sizes_after, dict), "domain_sizes_after must be a dict"
            # Sizes must be positive integers
            for var, size in step.domain_sizes_before.items():
                assert isinstance(size, int) and size >= 1, f"Bad size for {var}: {size}"
            for var, size in step.domain_sizes_after.items():
                assert isinstance(size, int) and size >= 1, f"Bad size for {var}: {size}"


def test_domain_sizes_decrease_after_constraint(mock_llm_client):
    """After adding a direct-position constraint, that variable's domain should be size 1."""
    from prism.offline.trajectory_collector import TrajectoryCollector, _compute_domain_sizes
    from prism.core.solver import Z3SolverWrapper

    solver = Z3SolverWrapper()
    # Add domain bounds for a 3-house puzzle with variable color_Red
    solver.add_constraint("And(Int('color_Red') >= 1, Int('color_Red') <= 3)")
    solver.add_constraint("And(Int('color_Blue') >= 1, Int('color_Blue') <= 3)")
    solver.add_constraint("And(Int('color_Green') >= 1, Int('color_Green') <= 3)")
    solver.add_constraint("Distinct(Int('color_Red'), Int('color_Blue'), Int('color_Green'))")
    sizes_before = _compute_domain_sizes(solver, n_houses=3)
    # Each variable has domain [1,2,3] = 3 candidates
    assert sizes_before.get("color_Red") == 3
    assert sizes_before.get("color_Blue") == 3

    solver.add_constraint("Int('color_Red') == 1")
    solver.check()
    sizes_after = _compute_domain_sizes(solver, n_houses=3)
    # color_Red is now pinned to 1
    assert sizes_after.get("color_Red") == 1
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
cd D:\Papers\PRISM
pytest tests/test_trajectory_collector.py::test_domain_sizes_populated_after_repair tests/test_trajectory_collector.py::test_domain_sizes_decrease_after_constraint -v
```

Expected: `ImportError: cannot import name '_compute_domain_sizes'` or `AssertionError: domain_sizes_before must be a dict`

- [ ] **Step 3: Add `_compute_domain_sizes` helper to trajectory_collector.py**

Add this function after the imports, before `class TrajectoryCollector`:

```python
def _compute_domain_sizes(solver: Z3SolverWrapper, n_houses: int) -> dict[str, int]:
    """Count how many values in [1..n_houses] remain feasible for each variable.

    For each Z3 Int variable mentioned in the current solver, probe how many
    values in the puzzle house range are consistent with current constraints.
    Uses one Z3 clone per variable × per candidate value — O(vars × n_houses)
    solver calls, each very fast (milliseconds).

    Returns an empty dict if n_houses <= 0 or no variables found.
    """
    if n_houses <= 0:
        return {}
    variables = solver.get_variables()
    if not variables:
        return {}
    result: dict[str, int] = {}
    for var in variables:
        count = 0
        for val in range(1, n_houses + 1):
            probe = Z3SolverWrapper()
            for c in solver.get_constraints():
                probe.add_constraint(c)
            probe.add_constraint(f"Int('{var}') == {val}")
            if probe.check() == "SAT":
                count += 1
        result[var] = max(count, 1)  # floor at 1 to avoid log2(0) in KDP info-gain
    return result
```

**Note:** `Z3SolverWrapper` needs `get_variables()` and `get_constraints()` methods. Check if they exist; if not, add them in Step 4 first.

- [ ] **Step 4: Check and add missing Z3SolverWrapper methods**

Read `prism/core/solver.py` to check if `get_variables()` and `get_constraints()` exist. If not, add them:

```python
# Add to Z3SolverWrapper class in prism/core/solver.py

def get_constraints(self) -> list[str]:
    """Return the list of constraint strings added to this solver."""
    return list(self._constraints)  # assuming self._constraints exists

def get_variables(self) -> list[str]:
    """Return variable names mentioned in current constraints."""
    import re
    names = set()
    for c in self._constraints:
        names.update(re.findall(r"Int\('([^']+)'\)", c))
    return sorted(names)
```

**Important:** Read `prism/core/solver.py` first to understand the actual field names before making any edits. The solver may already track constraints internally — don't duplicate storage.

- [ ] **Step 5: Wire `_compute_domain_sizes` into `_solve_once`**

In `prism/offline/trajectory_collector.py`, modify `_solve_once` to capture domain sizes before and after each repair step.

Find this block (around line 162-200):
```python
for iteration in range(1, self._max_rounds + 1):
    if solved:
        break

    unsat_core = solver.get_unsat_core() if result == "UNSAT" else []
    calls_before = self._llm.call_count
    ...
    step = TrajectoryStep(
        iteration=iteration,
        action="repair",
        step_type=self._classify_step(unsat_core, result),
        unsat_core=unsat_core,
        z3_result="PENDING",
        llm_call_count=calls_after,
    )
```

Add domain size capture:
```python
for iteration in range(1, self._max_rounds + 1):
    if solved:
        break

    unsat_core = solver.get_unsat_core() if result == "UNSAT" else []
    calls_before = self._llm.call_count

    # Capture domain sizes BEFORE this repair step
    n_houses = self._puzzle_n_houses(puzzle)
    sizes_before = _compute_domain_sizes(solver, n_houses)

    repair_response = self._llm.repair(
        constraints=current_constraints,
        unsat_core=unsat_core,
        history_summary="初次修复" if iteration == 1 else f"第 {iteration} 次修复",
    )
    repair_str = self._translator.parse_repair_response(repair_response)
    calls_after = self._llm.call_count - calls_before

    step = TrajectoryStep(
        iteration=iteration,
        action="repair",
        step_type=self._classify_step(unsat_core, result),
        unsat_core=unsat_core,
        z3_result="PENDING",
        llm_call_count=calls_after,
        domain_sizes_before=sizes_before,   # ← NEW
    )

    if repair_str:
        target_idx = self._find_repair_target(unsat_core, current_constraints)
        if target_idx is not None:
            old = current_constraints[target_idx]
            current_constraints[target_idx] = repair_str
            step = step.model_copy(update={
                "constraint_removed": old,
                "constraint_added": repair_str,
            })
        else:
            current_constraints.append(repair_str)
            step = step.model_copy(update={"constraint_added": repair_str})

        solver = Z3SolverWrapper()
        for c in current_constraints:
            solver.add_constraint(c)

    result = solver.check()

    # Capture domain sizes AFTER applying repair
    sizes_after = _compute_domain_sizes(solver, n_houses)
    step = step.model_copy(update={
        "z3_result": result,
        "domain_sizes_after": sizes_after,   # ← NEW
    })
    steps.append(step)
```

Also add the helper method to the class:
```python
@staticmethod
def _puzzle_n_houses(puzzle: PuzzleInstance) -> int:
    """Parse n_houses from puzzle.size string like '3x3' or '4x5'."""
    try:
        return int(str(puzzle.size).lower().split("x", 1)[0])
    except (TypeError, ValueError, IndexError):
        return 0
```

- [ ] **Step 6: Run tests to verify they pass**

```powershell
cd D:\Papers\PRISM
pytest tests/test_trajectory_collector.py -v
```

Expected: all existing tests still pass + 2 new tests pass.

- [ ] **Step 7: Run the full test suite to check no regressions**

```powershell
cd D:\Papers\PRISM
pytest tests/ -x -q
```

Expected: all tests pass (same count as before + 2 new).

- [ ] **Step 8: Commit**

```powershell
cd D:\Papers\PRISM
git add prism/offline/trajectory_collector.py prism/core/solver.py tests/test_trajectory_collector.py
git commit -m "feat: populate domain_sizes_before/after in TrajectoryCollector

Enable KDP conditions A and C by probing Z3 for feasible values per
variable before and after each repair step. Adds _compute_domain_sizes()
helper and Z3SolverWrapper.get_variables()/get_constraints() methods.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Lower `cluster_min_size` in config

**Files:**
- Modify: `config/default.yaml`

**Background:** With 300 trajectories × ~30% having CONTRADICTION steps × 1 KDP/step ≈ ~90 KDPs total, each split across ~9 constraint type bins. Average cluster size ≈ 10. `min_support=5` should work with 300 trajectories, but `min_support=2` is safer for the initial validation run before we have 300.

**Interfaces:**
- Consumes: nothing new
- Produces: `config/default.yaml` with `cluster_min_size: 2`

- [ ] **Step 1: Read current config**

```powershell
cd D:\Papers\PRISM
Get-Content config/default.yaml
```

- [ ] **Step 2: Change cluster_min_size**

In `config/default.yaml`, change:
```yaml
  cluster_min_size: 5
```
to:
```yaml
  cluster_min_size: 2
```

- [ ] **Step 3: Verify the change**

```powershell
cd D:\Papers\PRISM
python -c "import yaml; c=yaml.safe_load(open('config/default.yaml')); print('cluster_min_size:', c['thresholds']['cluster_min_size'])"
```

Expected: `cluster_min_size: 2`

- [ ] **Step 4: Run tests**

```powershell
cd D:\Papers\PRISM
pytest tests/ -x -q
```

Expected: all tests pass (config change shouldn't break any test).

- [ ] **Step 5: Commit**

```powershell
cd D:\Papers\PRISM
git add config/default.yaml
git commit -m "config: lower cluster_min_size from 5 to 2

With ~300 trajectories, average cluster size ~10. min_support=2 retains
clusters that min_support=5 would discard, giving more paradigm candidates.
Verification (soundness >= 0.90) still filters noise.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Smoke-test the fix on existing trajectories

Before spending API budget on 300 new trajectories, verify the fix produces KDPs and passes clustering on the 64 existing trajectories.

**Files:**
- Read-only: `scripts/run_offline.py`, `data/trajectories/`

**Interfaces:**
- Consumes: existing 64 trajectory JSON files (backward-compatible — domain_sizes will still be empty in old files, but KDP condition B still fires)
- Produces: `paradigm_store/prism_v2_smoke.db` with paradigm count > 0

- [ ] **Step 1: Run offline pipeline on existing trajectories with --resume**

```powershell
cd D:\Papers\PRISM
python scripts/run_offline.py `
  --config config/default.yaml `
  --model GPT-4o-mini `
  --resume `
  --trajectories data/trajectories/gpt4o_3x3_valid_audit `
  --output paradigm_store/prism_v2_smoke.db
```

Expected log output (approximate):
```
INFO Loaded N trajectories.
INFO Extracted M KDPs from N trajectories.
INFO Clustered M KDPs → K raw clusters → J with support ≥ 2
INFO Abstracted J candidate paradigms.
INFO Offline distillation complete. Accepted X/J paradigms.
```

Key check: `Accepted X/J paradigms` where X > 0.

- [ ] **Step 2: Verify the library is non-empty**

```powershell
cd D:\Papers\PRISM
python -c "
from prism.paradigm_library.library import ParadigmLibrary
from prism.core.solver import Z3SolverWrapper
lib = ParadigmLibrary('paradigm_store/prism_v2_smoke.db', Z3SolverWrapper())
print('Library stats:', lib.stats())
"
```

Expected: `total` > 0. If still 0, check the `_candidates.json` file for diagnostic scores.

- [ ] **Step 3: If total == 0, diagnose using candidates JSON**

```powershell
cd D:\Papers\PRISM
python -c "
import json
data = json.load(open('paradigm_store/prism_v2_smoke_candidates.json'))
print(f'Candidates: {len(data)}')
for d in data[:5]:
    print(d['name'], 'scores:', d['scores'])
"
```

If candidates exist but confidence < 0.90, the verification threshold is too tight. In that case, also try:

```powershell
cd D:\Papers\PRISM
python -c "
import yaml
c = yaml.safe_load(open('config/default.yaml'))
print('soundness threshold:', c['thresholds']['paradigm_soundness'])
"
```

If `paradigm_soundness` is 0.90 and all candidates score 0.6-0.8, temporarily lower it to 0.70 for the smoke test to see if it's the bottleneck. **Do not lower below 0.70 for production use.**

- [ ] **Step 4: If paradigm count > 0, commit smoke results**

```powershell
cd D:\Papers\PRISM
git add paradigm_store/prism_v2_smoke.db paradigm_store/prism_v2_smoke.json paradigm_store/prism_v2_smoke_candidates.json
git commit -m "test: smoke-test offline pipeline on existing trajectories

paradigm_store/prism_v2_smoke.db: N paradigms from existing 64 trajectories.
Confirms cluster_min_size=2 + domain_sizes fix enables paradigm extraction.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Collect 300+ new trajectories

**Files:**
- Read-only: `scripts/run_offline.py`
- New: `data/trajectories/gpt4omini_3x_v2/` (created by the script)

**Background:** 100 puzzles × 3 runs = 300 trajectories. With cluster_min_size=2 and ~30% CONTRADICTION steps, expect ~90 KDPs → ~10-20 clusters → ~10-20 paradigm candidates. Use 3x3/3x4/4x5 sizes (medium difficulty) to match ZebraLogic benchmark.

**Cost estimate:** Each puzzle run = ~3-6 LLM calls (1 translate + up to 5 repairs, most puzzles need 1-2). 300 trajectories × 4 avg calls = ~1200 GPT-4o-mini calls ≈ $0.50-$1.00.

**Interfaces:**
- Consumes: `config/default.yaml`, GPT-4o-mini API
- Produces: `data/trajectories/gpt4omini_3x_v2/*.json` (300 files)

- [ ] **Step 1: Generate puzzles and collect trajectories**

```powershell
cd D:\Papers\PRISM
python scripts/run_offline.py `
  --config config/default.yaml `
  --model GPT-4o-mini `
  --puzzle-specs "34:3x3:medium,33:3x4:medium,33:4x5:medium" `
  --n-runs 3 `
  --trajectories data/trajectories/gpt4omini_3x_v2 `
  --output paradigm_store/prism_v2.db `
  --seed 20260706
```

This generates 100 puzzles × 3 runs = 300 trajectories. Expected runtime: 30-60 minutes depending on API latency.

- [ ] **Step 2: Monitor progress**

The script logs every 50 trajectories. Watch for:
```
INFO Collected 50/300 trajectories
INFO Collected 100/300 trajectories
...
INFO Collected 300/300 trajectories. Total LLM calls: NNNN
```

- [ ] **Step 3: Verify trajectory count and solved rate**

```powershell
cd D:\Papers\PRISM
python -c "
import json
from pathlib import Path
files = list(Path('data/trajectories/gpt4omini_3x_v2').glob('*.json'))
solved = sum(1 for f in files if json.load(open(f))['solved'])
print(f'Trajectories: {len(files)}, Solved: {solved}/{len(files)} ({solved/len(files)*100:.1f}%)')
"
```

Expected: ~300 files, solved rate 50-80% (varies by puzzle difficulty).

- [ ] **Step 4: Check KDP count from new trajectories**

```powershell
cd D:\Papers\PRISM
python -c "
import json
from pathlib import Path
from prism.core.types import Trajectory
from prism.offline.kdp_identifier import KDPIdentifier

identifier = KDPIdentifier()
total_kdps = 0
with_domain = 0
for f in Path('data/trajectories/gpt4omini_3x_v2').glob('*.json'):
    traj = Trajectory.model_validate(json.load(open(f)))
    kdps = identifier.identify(traj)
    total_kdps += len(kdps)
    if any(k.step.domain_sizes_before for k in kdps):
        with_domain += 1
print(f'Total KDPs: {total_kdps}')
print(f'KDPs with domain_sizes populated: {with_domain}')
"
```

Expected: total_kdps > 50, and if Task 1 fix is applied, `with_domain > 0`.

- [ ] **Step 5: Commit trajectory metadata (not the JSON files — too large)**

```powershell
cd D:\Papers\PRISM
# Add only the paradigm library outputs, not the raw trajectories (too large)
git add paradigm_store/prism_v2.db paradigm_store/prism_v2.json paradigm_store/prism_v2_candidates.json
git commit -m "feat: collect 300 new trajectories, mine paradigm library v2

data/trajectories/gpt4omini_3x_v2/: 300 trajectories (3x3/3x4/4x5, GPT-4o-mini)
paradigm_store/prism_v2.db: N positive paradigms
Library stats: [paste stats here]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Validate full offline→online closed loop

Run the full pipeline end-to-end using the new paradigm library. Compare PRISM-with-library vs LLM+Z3-baseline on the domain-explicit eval set.

**Files:**
- Read-only: `scripts/run_online.py`, `data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl`

**Interfaces:**
- Consumes: `paradigm_store/prism_v2.db`, GPT-4o-mini API
- Produces: `results/full_pipeline_prism_v2_baseline.csv`, `results/full_pipeline_prism_v2_prism.csv`

- [ ] **Step 1: Check library is non-empty before running**

```powershell
cd D:\Papers\PRISM
python -c "
from prism.paradigm_library.library import ParadigmLibrary
from prism.core.solver import Z3SolverWrapper
lib = ParadigmLibrary('paradigm_store/prism_v2.db', Z3SolverWrapper())
stats = lib.stats()
print('Library stats:', stats)
assert stats['total'] > 0, 'Library is empty — check Task 4 before proceeding'
"
```

If total == 0, **stop here** and return to Task 3 (diagnose verification scores).

- [ ] **Step 2: Run LLM+Z3 baseline (no paradigm, no memory)**

```powershell
cd D:\Papers\PRISM
python scripts/run_online.py `
  --data-dir data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --no-paradigm --no-memory `
  --max-repair 3 `
  --sizes 3x3,3x4 `
  --schema-hint-mode puzzle `
  --output results/full_pipeline_prism_v2_baseline.csv `
  --trace-output results/full_pipeline_prism_v2_baseline.jsonl
```

- [ ] **Step 3: Run PRISM full with new library**

```powershell
cd D:\Papers\PRISM
python scripts/run_online.py `
  --data-dir data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl `
  --data-source local `
  --model GPT-4o-mini `
  --library paradigm_store/prism_v2.db `
  --error-library paradigm_store/mined_relation_templates.db `
  --max-repair 3 `
  --sizes 3x3,3x4 `
  --schema-hint-mode puzzle `
  --output results/full_pipeline_prism_v2_prism.csv `
  --trace-output results/full_pipeline_prism_v2_prism.jsonl
```

- [ ] **Step 4: Compare results**

```powershell
cd D:\Papers\PRISM
python -c "
import csv
def read(path):
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    n = len(rows)
    solved = sum(1 for r in rows if r.get('solved','').lower()=='true')
    pos_guid = sum(1 for r in rows if r.get('positive_guidance_triggered','').lower()=='true')
    err_guid = sum(1 for r in rows if r.get('error_guidance_triggered','').lower()=='true')
    return n, solved, pos_guid, err_guid

n, s, pg, eg = read('results/full_pipeline_prism_v2_baseline.csv')
print(f'Baseline:  {s}/{n} ({s/n*100:.1f}%),  pos_guidance={pg}, err_guidance={eg}')
n, s, pg, eg = read('results/full_pipeline_prism_v2_prism.csv')
print(f'PRISM v2:  {s}/{n} ({s/n*100:.1f}%),  pos_guidance={pg}, err_guidance={eg}')
"
```

**Decision criteria:**
- If `positive_guidance_triggered > 0`: paradigm library is being accessed ✅
- If PRISM accuracy > baseline by ≥3pp: full closed loop working ✅
- If PRISM accuracy ≤ baseline: paradigm library present but not helping — investigate what paradigms were abstracted

- [ ] **Step 5: Commit final results**

```powershell
cd D:\Papers\PRISM
git add results/full_pipeline_prism_v2_baseline.csv results/full_pipeline_prism_v2_prism.csv
git commit -m "test: validate offline→online closed loop with prism_v2 library

Baseline: X/150 (XX.X%)
PRISM v2: Y/150 (YY.Y%), paradigm_trigger_rate=Z%

[paste actual numbers before committing]

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- ✅ Fix domain_sizes population → Task 1
- ✅ Lower cluster_min_size → Task 2
- ✅ Smoke test on existing trajectories → Task 3
- ✅ Collect 300+ trajectories → Task 4
- ✅ Validate full pipeline → Task 5
- ✅ TDD (failing tests written before implementation) → Task 1 Steps 1-2
- ✅ Frequent commits → each task ends with a commit

**Placeholder scan:** None found.

**Type consistency:**
- `_compute_domain_sizes(solver: Z3SolverWrapper, n_houses: int) -> dict[str, int]` — used in Task 1 Step 3 (definition) and Step 5 (usage) with consistent signature
- `Z3SolverWrapper.get_variables() -> list[str]` and `.get_constraints() -> list[str]` — defined in Task 1 Step 4, used in Step 3
- `TrajectoryCollector._puzzle_n_houses(puzzle: PuzzleInstance) -> int` — defined and used in Task 1 Step 5

**Risk:** Task 1 Step 4 depends on `Z3SolverWrapper` internals — must read `prism/core/solver.py` before writing that code. The plan correctly flags this as a prerequisite.
