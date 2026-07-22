"""No-key-oracle recomputation of the Q1 uniqueness diagnostic.

The published Q1 (``tab:gate-diagnostic``) replays the uniqueness probe on
no-gate outputs whose *final* result is SAT.  Those states have already passed
the historical pipeline's schema/key-set validation, which reads the expected
key names from ``puzzle.solution``.  This script quantifies the dependence on
that validation by folding back every state whose *underlying* solver reached
SAT but was relabelled by the schema/key check (``INVALID_MODEL`` /
``KEY_MISMATCH`` / ``MISALIGNED_MODEL``), and re-running the identical,
key-agnostic uniqueness probe.

Correctness is judged exactly as in the published diagnostic, i.e. with
``answers_match`` on the record's projected ``predicted``.  Because ZebraLogic
scoring itself aligns model variables to the gold key names, key-mismatched
states whose *values* are correct but whose attribute names differ are counted
as wrong here; the no-oracle detection rate is therefore a conservative lower
bound.

Running it reproduces the with-oracle numbers (a methodology check) and prints
the no-oracle numbers cited in the paper.

Usage::

    python scripts/sparc/deoracle_q1.py \
      results/sparc/zebra_v2_s42 results/sparc/zebra_v2_s123 results/sparc/zebra_v2_s7
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.sparc.audit_sparc_evidence import (
    load_records,
    reconstruct_constraints,
    uniqueness_probe,
)
from prism.evaluation.benchmarks.zebralogic import answers_match, is_scorable

# Underlying-SAT states: a model existed; the label may have been rewritten by
# the schema/key-set validation.
SAT_FAMILY = {"SAT", "INVALID_MODEL", "KEY_MISMATCH", "MISALIGNED_MODEL"}
NO_GATE_SYSTEMS = (("baseline", "baseline"), ("nopar", "aggressive"))
DEFAULT_DIRS = (
    Path("results/sparc/zebra_v2_s42"),
    Path("results/sparc/zebra_v2_s123"),
    Path("results/sparc/zebra_v2_s7"),
)


def confusion_matrix(records, *, no_key_oracle: bool) -> tuple[Counter, int]:
    counts: Counter = Counter()
    probed = 0
    for item in records:
        record = item.record
        if not is_scorable(record.get("ground_truth")):
            continue
        final = record.get("final_z3_result")
        if no_key_oracle:
            if final not in SAT_FAMILY:
                continue
        elif final != "SAT":
            continue
        probe = uniqueness_probe(reconstruct_constraints(record))
        if probe["base_verdict"] != "SAT" or probe["gate"] not in {"unique", "non_unique"}:
            continue
        probed += 1
        correct = answers_match(record.get("ground_truth"), record.get("predicted"))
        counts[f"{'correct' if correct else 'wrong'}_{probe['gate']}"] += 1
    return counts, probed


def summarise(counts: Counter) -> dict:
    cu, cn = counts["correct_unique"], counts["correct_non_unique"]
    wu, wn = counts["wrong_unique"], counts["wrong_non_unique"]
    sbw, correct = wu + wn, cu + cn
    return {
        "correct_unique": cu,
        "correct_non_unique": cn,
        "sbw_unique": wu,
        "sbw_non_unique": wn,
        "sbw": sbw,
        "correct": correct,
        "detection_pct": 100 * wn / sbw if sbw else float("nan"),
        "false_rejection_pct": 100 * cn / correct if correct else float("nan"),
    }


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dirs", nargs="*", type=Path)
    args = parser.parse_args(argv)
    dirs = args.result_dirs or list(DEFAULT_DIRS)

    for system, label in NO_GATE_SYSTEMS:
        records = load_records(dirs, system)
        print(f"\n===== {label} ({system}) — {len(records)} records =====")
        for no_oracle in (False, True):
            counts, probed = confusion_matrix(records, no_key_oracle=no_oracle)
            s = summarise(counts)
            tag = "no-key-oracle" if no_oracle else "with-oracle  "
            print(
                f"  {tag}: states={probed:4d} | "
                f"C_uniq={s['correct_unique']:3d} C_non={s['correct_non_unique']:3d} "
                f"SBW_uniq={s['sbw_unique']:3d} SBW_non={s['sbw_non_unique']:3d} | "
                f"detection={s['detection_pct']:.1f}%  "
                f"false_rejection={s['false_rejection_pct']:.1f}%"
            )


if __name__ == "__main__":
    main()
