"""Q2: structural-gate vs heuristic self-consistency abstention baseline.

Both abstention rules are applied to the SAME no-gate outputs so the comparison
isolates the abstention *signal* (it does not re-run the formalizer).

Structural gate (single formalization, per-run over all scorable runs):
    answer iff the run is SAT and its answer projection is unique; score with
    answers_match.  This is the uniqueness signal of Q1 read as risk--coverage.

Self-consistency (three no-gate repetitions as N=3 samples, per annotated
puzzle): the consensus is the most frequent answered `predicted`; answer iff at
least t of the three runs emit that exact prediction (t = 1, 2, 3).

Confidence-threshold abstention is not computed: the historical traces do not
record a self-reported confidence score.

Usage::

    python scripts/baseline_abstain_zebra.py \
      results/zebra_v2_s42 results/zebra_v2_s123 results/zebra_v2_s7
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.audit_sparc_evidence import (
    load_records,
    reconstruct_constraints,
    uniqueness_probe,
)
from prism.evaluation.benchmarks.zebralogic import answers_match, is_scorable

NO_GATE_SYSTEMS = (("baseline", "baseline"), ("nopar", "aggressive"))
DEFAULT_DIRS = (
    Path("results/zebra_v2_s42"),
    Path("results/zebra_v2_s123"),
    Path("results/zebra_v2_s7"),
)


def structural_gate(records) -> tuple[int, int, int]:
    """(scorable_runs, answered, wrong) for the uniqueness gate on no-gate runs."""
    runs = answered = wrong = 0
    for item in records:
        r = item.record
        if not is_scorable(r.get("ground_truth")):
            continue
        runs += 1
        if r.get("final_z3_result") != "SAT":
            continue
        probe = uniqueness_probe(reconstruct_constraints(r))
        if probe["base_verdict"] != "SAT" or probe["gate"] != "unique":
            continue
        answered += 1
        if not answers_match(r.get("ground_truth"), r.get("predicted")):
            wrong += 1
    return runs, answered, wrong


def self_consistency(records, t: int) -> tuple[int, int, int]:
    """(puzzles, answered, wrong) requiring >= t of 3 runs to share an answer."""
    by_pid: dict[str, list] = defaultdict(list)
    gt_of: dict[str, str] = {}
    for item in records:
        r = item.record
        if not is_scorable(r.get("ground_truth")):
            continue
        gt_of[item.puzzle_id] = r.get("ground_truth")
        answered_run = r.get("final_z3_result") == "SAT"
        by_pid[item.puzzle_id].append(r.get("predicted") if answered_run else None)
    answered = wrong = 0
    for pid, preds in by_pid.items():
        answers = [p for p in preds if p]
        if not answers:
            continue
        consensus, count = Counter(answers).most_common(1)[0]
        if count >= t:
            answered += 1
            if not answers_match(gt_of[pid], consensus):
                wrong += 1
    return len(by_pid), answered, wrong


def _rc(total: int, answered: int, wrong: int) -> tuple[float, float]:
    cov = 100 * answered / total if total else 0.0
    risk = 100 * wrong / answered if answered else 0.0
    return cov, risk


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dirs", nargs="*", type=Path)
    args = parser.parse_args(argv)
    dirs = args.result_dirs or list(DEFAULT_DIRS)

    for system, label in NO_GATE_SYSTEMS:
        records = load_records(dirs, system)
        runs, ga, gw = structural_gate(records)
        gcov, grisk = _rc(runs, ga, gw)
        print(f"\n===== {label} ({system}) =====")
        print(f"  structural gate (1 sample, /{runs} runs): "
              f"answered={ga} wrong={gw} | coverage={gcov:.2f}% risk={grisk:.2f}%")
        for t in (3, 2, 1):
            n, a, w = self_consistency(records, t)
            cov, risk = _rc(n, a, w)
            print(f"  self-consistency t={t} (3 samples, /{n} puzzles): "
                  f"answered={a} wrong={w} | coverage={cov:.2f}% risk={risk:.2f}%")


if __name__ == "__main__":
    main()
