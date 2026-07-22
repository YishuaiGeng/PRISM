# Hugging Face Dataset Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download and integrate `allenai/ZebraLogicBench` and `K-and-K/knights-and-knaves` into the PRISM pipeline.

**Architecture:** Add Hugging Face dataset adapters beside the existing local JSON loaders. A download script writes reproducible JSONL snapshots under `data/hf/`, while runtime loaders can read either HF directly or local snapshots. Pipeline scripts default to HF dataset identifiers and keep local JSON compatibility.

**Tech Stack:** Python, Hugging Face `datasets`, pytest, existing `PuzzleInstance` model and benchmark evaluators.

---

### Task 1: Add HF Record Adapters

**Files:**
- Modify: `prism/evaluation/benchmarks/zebralogic.py`
- Modify: `prism/evaluation/benchmarks/knights_knaves.py`
- Test: `tests/test_hf_dataset_adapters.py`

- [ ] Write tests for Zebra records with `size="5*6"`, `puzzle`, and `solution`.
- [ ] Write tests for KnK records with `quiz`, `names`, `solution`, `solution_text`, and `statements`.
- [ ] Verify tests fail because adapter functions do not exist.
- [ ] Implement `zebralogic_record_to_puzzle()` and `knk_record_to_puzzle()`.
- [ ] Verify tests pass.

### Task 2: Add HF Loading Mode

**Files:**
- Modify: `prism/evaluation/benchmarks/zebralogic.py`
- Modify: `prism/evaluation/benchmarks/knights_knaves.py`
- Test: `tests/test_hf_dataset_adapters.py`

- [ ] Write tests that monkeypatch dataset loading and call `load_zebralogic(source="hf")`.
- [ ] Write tests that monkeypatch dataset loading and call `load_knights_knaves(source="hf")`.
- [ ] Verify tests fail because the `source` option is not implemented.
- [ ] Implement lazy import of `datasets.load_dataset`.
- [ ] Add source dispatch for `local`, `hf`, and `auto`.
- [ ] Verify tests pass.

### Task 3: Add Download Script and Defaults

**Files:**
- Create: `scripts/download_datasets.py`
- Modify: `scripts/run_online.py`
- Modify: `scripts/run_experiments.py`
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Test: `tests/test_download_datasets.py`

- [ ] Write tests for JSONL writing using monkeypatched loaders.
- [ ] Verify tests fail because the script does not exist.
- [ ] Implement `download_zebralogic()`, `download_knights_knaves()`, and CLI.
- [ ] Set pipeline defaults to HF identifiers.
- [ ] Add `datasets` to requirements and ignore `data/hf/`.
- [ ] Verify tests pass.

### Task 4: Download and Verify

**Files:**
- Runtime output: `data/hf/` ignored by git.

- [ ] Run `python scripts/download_datasets.py --max-rows 10` as a smoke test.
- [ ] Run `pytest -q`.
- [ ] Commit the integration changes.
