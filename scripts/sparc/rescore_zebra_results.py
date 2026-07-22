"""Re-score saved ZebraLogic result CSVs with the fixed answer comparison.

The original scoring had two bugs: (i) puzzles whose official answers are
blanked ('___') fell back to "reached validated SAT counts as solved";
(ii) real ground truth never matched predictions due to naming-convention
differences (``BookGenre_fantasy=house2`` vs ``bookGenre_Fantasy=2``).
This script recomputes correctness offline from the stored ground_truth /
predicted strings using :func:`answers_match`, restricted to scorable
puzzles, and prints per-system accuracy plus the SBW ledger.

Usage::

    python scripts/sparc/rescore_zebra_results.py results/zebra_main_s42
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.evaluation.benchmarks.zebralogic import answers_match, is_scorable


def rescore_dir(result_dir: Path) -> None:
    by_system: dict[str, list[dict]] = defaultdict(list)
    for csv_path in sorted(result_dir.glob("*.csv")):
        system = csv_path.stem.rsplit("_g", 1)[0]
        with open(csv_path, encoding="utf-8") as fh:
            by_system[system].extend(list(csv.DictReader(fh)))

    header = (
        f"{'system':<12} {'scorable':>8} {'true_acc':>9} {'SAT_right':>9} "
        f"{'SAT_wrong':>9} {'nonSAT':>7} {'unscorable':>10}"
    )
    print(header)
    print("-" * len(header))
    for system, rows in sorted(by_system.items()):
        scorable = [r for r in rows if is_scorable(r.get("ground_truth"))]
        unscorable = len(rows) - len(scorable)
        correct = [
            r for r in scorable
            if answers_match(r.get("ground_truth"), r.get("predicted"))
        ]
        sat_right = sum(
            1 for r in correct if r.get("final_z3_result") == "SAT"
        )
        sat_wrong = sum(
            1 for r in scorable
            if r.get("final_z3_result") == "SAT"
            and not answers_match(r.get("ground_truth"), r.get("predicted"))
        )
        non_sat = sum(
            1 for r in scorable if r.get("final_z3_result") != "SAT"
        )
        acc = len(correct) / len(scorable) * 100 if scorable else 0.0
        print(
            f"{system:<12} {len(scorable):>8} {acc:>8.1f}% {sat_right:>9} "
            f"{sat_wrong:>9} {non_sat:>7} {unscorable:>10}"
        )


if __name__ == "__main__":
    rescore_dir(Path(sys.argv[1] if len(sys.argv) > 1 else "results/zebra_main_s42"))
