"""Aggregate SPARC runtime statistics from zebra_v2 traces and logs.

Produces the numbers reported in the paper's efficiency and limitation
sections:
  1. pi-gate outcome distribution (unique / non_unique / unknown_timeout)
     and a global UNKNOWN scan across all runs (fail-open trigger count);
  2. diff-completion acceptance/rejection and protected conflict-repair
     trigger counts;
  3. wall-clock duration per run derived from err.log timestamps.

Usage:  python scripts/sparc/sparc_runtime_stats.py [results_glob]
Default results glob: results/zebra_v2_s*
"""

from __future__ import annotations

import collections
import datetime
import glob
import json
import os
import re
import sys

TS_PAT = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def run_key(path: str) -> tuple[str, str]:
    seed = re.search(r"zebra_v2_(s\w+)", path).group(1)
    system = os.path.basename(path).split(".")[0].rsplit("_g", 1)[0]
    return seed, system


def trace_stats(root_glob: str) -> dict:
    rows: dict = {}
    for f in sorted(glob.glob(f"{root_glob}/*.trace.jsonl")):
        r = rows.setdefault(run_key(f), collections.Counter())
        for line in open(f, encoding="utf-8"):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            r["puzzles"] += 1
            r["llm_calls"] += rec.get("llm_calls", 0)
            r["final_" + str(rec.get("final_z3_result"))] += 1
            if rec.get("initial_z3_result") == "UNKNOWN":
                r["unknown_any"] += 1
            for s in rec.get("steps") or []:
                a = s.get("action")
                if a == "pi_gate":
                    r["gate_solves"] += 1
                    r["gate_" + str(s.get("gate"))] += 1
                elif a == "diff_completion":
                    r["diff_accept"] += 1
                elif a == "diff_completion_rejected":
                    r["diff_reject"] += 1
                elif a == "sparc_conflict_repair":
                    r["conflict_repair"] += 1
                if s.get("z3_result") == "UNKNOWN" or s.get("raw_z3_result") == "UNKNOWN":
                    r["unknown_any"] += 1
    return rows


def wallclock_stats(root_glob: str) -> dict:
    agg: dict = collections.defaultdict(lambda: [0.0, 0])
    for f in sorted(glob.glob(f"{root_glob}/*.err.log")):
        first = last = None
        retries = 0
        for line in open(f, encoding="utf-8", errors="replace"):
            m = TS_PAT.match(line)
            if m:
                t = datetime.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if first is None:
                    first = t
                last = t
            if "503" in line or "retry" in line.lower():
                retries += 1
        if first and last:
            key = run_key(f)
            agg[key][0] += (last - first).total_seconds()
            agg[key][1] += retries
    return agg


def main() -> None:
    root_glob = sys.argv[1] if len(sys.argv) > 1 else "results/zebra_v2_s*"

    rows = trace_stats(root_glob)
    print("== pi-gate / completion / conflict-repair (SPARC arms) ==")
    total_gate = collections.Counter()
    for (seed, system), r in sorted(rows.items()):
        if "sparc" not in system:
            continue
        n = r["puzzles"]
        for k in ("gate_unique", "gate_non_unique", "gate_unknown_timeout"):
            total_gate[k] += r[k]
        total_gate["gate_solves"] += r["gate_solves"]
        total_gate["diff_accept"] += r["diff_accept"]
        total_gate["diff_reject"] += r["diff_reject"]
        total_gate["conflict_repair"] += r["conflict_repair"]
        print(
            f"{seed:5s} {system:12s} n={n} gate={r['gate_solves']} "
            f"(unique={r['gate_unique']}, non_unique={r['gate_non_unique']}, "
            f"unknown_timeout={r['gate_unknown_timeout']}) "
            f"diff_ok={r['diff_accept']} diff_rej={r['diff_reject']} "
            f"conflict_repair={r['conflict_repair']} "
            f"final_NONUNIQUE={r['final_SAT_NONUNIQUE']}"
        )
    acc = total_gate["diff_accept"]
    rej = total_gate["diff_reject"]
    print(
        f"TOTAL gate={total_gate['gate_solves']} unique={total_gate['gate_unique']} "
        f"non_unique={total_gate['gate_non_unique']} "
        f"unknown_timeout={total_gate['gate_unknown_timeout']}"
    )
    print(
        f"TOTAL diff candidates={acc + rej} accepted={acc} "
        f"rejected={rej} ({rej / (acc + rej):.1%}) "
        f"conflict_repair={total_gate['conflict_repair']}"
    )
    unknown_total = sum(r["unknown_any"] for r in rows.values())
    print(f"UNKNOWN anywhere across ALL runs (incl. baselines): {unknown_total}")

    print("\n== wall-clock from err.log timestamps ==")
    agg = wallclock_stats(root_glob)
    print(f"{'seed':6s}{'system':13s}{'total_min':>10s}{'sec/puzzle':>11s}{'retry_lines':>12s}")
    for (seed, system), (dur, retries) in sorted(agg.items()):
        n = rows.get((seed, system), {}).get("puzzles", 640) or 640
        print(f"{seed:6s}{system:13s}{dur / 60:10.1f}{dur / n:11.2f}{retries:12d}")


if __name__ == "__main__":
    main()
