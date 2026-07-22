"""Run the B5 round-trip faithfulness baseline on an existing no-gate trace.

Avoids re-formalization: reuses the SAT outputs already in the trace and only
adds the round-trip calls (back-translate + faithfulness judge) per answered
puzzle.  Paid; nothing runs without --execute-paid.

    python scripts/sparc/b5_on_trace.py \
      --trace results/sparc/rq3_gpt4omini/GPT-4o-mini_nogate.trace.jsonl \
      --model GPT-4o-mini --execute-paid
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.sparc.multimodel_eval import roundtrip_consistency
from prism.evaluation.benchmarks.zebralogic import load_zebralogic


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--model", default="GPT-4o-mini")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data-dir", default="allenai/ZebraLogicBench")
    ap.add_argument("--execute-paid", action="store_true")
    args = ap.parse_args()

    base = [json.loads(l) for l in open(args.trace, encoding="utf-8") if l.strip()]
    answered = sum(1 for r in base if r.get("final_z3_result") == "SAT")
    print(f"trace={args.trace} records={len(base)} answered_SAT={answered} "
          f"(~{2 * answered} round-trip calls)")
    if not args.execute_paid:
        raise SystemExit("Re-run with --execute-paid to spend the API budget.")

    puzzles = load_zebralogic(args.data_dir, source="auto", subset="grid_mode")
    nl_of = {p.puzzle_id: getattr(p, "nl_description", "") for p in puzzles}
    points = roundtrip_consistency(args.model, base, nl_of, args.seed)
    print("B5 round-trip risk--coverage:")
    for p in points:
        if p["answered"]:
            print(f"  tau={p['threshold']:>3}: cov={p['coverage_pct']:.1f}% "
                  f"risk={p['risk_pct']:.1f}% (ans={p['answered']})")
    Path("results/sparc/b5_roundtrip.json").write_text(
        json.dumps(points, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved results/sparc/b5_roundtrip.json")


if __name__ == "__main__":
    main()
