"""Offline completion-budget sweep over SPARC trace files.

Derives, without re-running any LLM calls, the outcome of SPARC variants
whose diff-completion budget is truncated to k rounds: a puzzle whose full
trajectory passed the pi-gate after c accepted completions answers
identically when k >= c and abstains (SAT_NONUNIQUE at the gate) when
k < c.  Budget k = 0 is exactly the "gate-only" ablation arm (detect ->
abstain, no completion).  The full sweep yields the risk--coverage curve.

Validity rests on trajectory-prefix determinism: the trace up to the
(k+1)-th accepted completion is identical between the full run and the
budget-k run, so truncation is an exact replay, not a simulation.

Usage::

    python scripts/sparc/budget_sweep_zebra.py results/zebra_v2_s42 results/zebra_v2_s123 results/zebra_v2_s7
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.evaluation.benchmarks.zebralogic import answers_match, is_scorable

SPARC_SYSTEMS = ("basesparc", "noparsparc")


def load_traces(result_dir: Path, system: str) -> list[dict]:
    rows: list[dict] = []
    for path in sorted(result_dir.glob(f"{system}_g*.trace.jsonl")):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def completions_used(trace: dict) -> int:
    return sum(1 for s in trace.get("steps", []) if s.get("action") == "diff_completion")


def sweep(traces: list[dict], max_budget: int) -> list[dict]:
    """Three-value ledger at each completion budget k, scorable puzzles only."""
    scorable = [t for t in traces if is_scorable(t.get("ground_truth"))]
    out = []
    for k in range(max_budget + 1):
        sat_right = sat_wrong = abstain = 0
        for t in scorable:
            answered = t.get("final_z3_result") == "SAT" and completions_used(t) <= k
            if not answered:
                abstain += 1
            elif answers_match(t.get("ground_truth"), t.get("predicted")):
                sat_right += 1
            else:
                sat_wrong += 1
        n_answered = sat_right + sat_wrong
        out.append({
            "budget": k,
            "scorable": len(scorable),
            "sat_right": sat_right,
            "sat_wrong": sat_wrong,
            "non_answer": abstain,
            "coverage": n_answered / len(scorable) if scorable else 0.0,
            "risk": sat_wrong / n_answered if n_answered else 0.0,
            "accuracy": sat_right / len(scorable) if scorable else 0.0,
        })
    return out


def main(dirs: list[Path]) -> None:
    for system in SPARC_SYSTEMS:
        merged: list[dict] = []
        per_seed: dict[str, list[dict]] = {}
        for d in dirs:
            traces = load_traces(d, system)
            if traces:
                per_seed[d.name] = traces
                merged.extend(traces)
        if not merged:
            continue
        max_budget = max(completions_used(t) for t in merged)

        print(f"\n===== {system} (max completions observed: {max_budget}) =====")
        header = (f"{'budget':>6} {'scorable':>8} {'SAT_right':>9} {'SAT_wrong':>9} "
                  f"{'non_ans':>8} {'coverage':>9} {'risk':>7} {'acc':>7}")
        for label, traces in [*per_seed.items(), ("MERGED", merged)]:
            print(f"\n-- {label} --")
            print(header)
            for row in sweep(traces, max_budget):
                print(f"{row['budget']:>6} {row['scorable']:>8} {row['sat_right']:>9} "
                      f"{row['sat_wrong']:>9} {row['non_answer']:>8} "
                      f"{row['coverage']:>8.1%} {row['risk']:>6.1%} {row['accuracy']:>6.1%}")


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]] or [Path("results/zebra_v2_s42")]
    main(args)
