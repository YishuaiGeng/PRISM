"""Multi-model evaluation harness for RQ1/RQ2/RQ3.

For each formalizer it runs the no-gate pipeline once (temperature 0, schema
hints from the *puzzle text only* -- no gold keys), then derives:

  * RQ1  SAT-accept risk  (SBW rate among answered SAT outputs);
  * RQ2  uniqueness confusion matrix + detection / false-rejection;
  * RQ3  structural-gate risk--coverage point, and -- if ``--sc-samples K``>0 --
         a temperature-sampled self-consistency risk--coverage curve (t-of-K).

It re-uses the exact offline probe used by the paper's Q1/Q2 so the numbers are
directly comparable across models.

Paid: formalization calls the LLM.  Nothing runs until ``--execute-paid`` is
given; ``--dry-run`` loads data and builds the solver without any API call.

Example (small smoke test)::

    python scripts/sparc/multimodel_eval.py --models GPT-4o-mini --limit 5 \
      --sc-samples 0 --dry-run

    python scripts/sparc/multimodel_eval.py --models GPT-4o,DeepSeek-V3 \
      --sc-samples 5 --temperature 0.7 --out-dir results/sparc/multimodel --execute-paid
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.online.guided_solver import GuidedSolver
from prism.paradigm_library.library import ParadigmLibrary
from prism.evaluation.benchmarks.zebralogic import (
    _solution_to_str,
    answers_match,
    evaluate_zebralogic,
    is_scorable,
    load_zebralogic,
)
from scripts.sparc.audit_sparc_evidence import reconstruct_constraints, uniqueness_probe


def build_solver(model: str, temperature: float, seed: int) -> GuidedSolver:
    llm = LLMClient(model_name=model, temperature=temperature, seed=seed)
    library = ParadigmLibrary(":memory:", Z3SolverWrapper())
    return GuidedSolver(
        llm_client=llm,
        library=library,
        layer2_enabled=False,
        enable_paradigm=False,
        enable_memory=False,
        enable_writeback=False,
        sparc=False,               # no gate: this is the no-gate arm
        schema_hint_mode="puzzle",  # visible text only, no gold keys
    )


def rq1_rq2_gate(results: list[dict]) -> dict:
    scorable = [r for r in results if is_scorable(r.get("ground_truth"))]
    answered = [r for r in scorable if r.get("final_z3_result") == "SAT"]
    # RQ1: SAT-accept risk.
    sbw = [r for r in answered if not answers_match(r["ground_truth"], r.get("predicted"))]
    # RQ2 confusion + structural-gate operating point.
    conf: Counter = Counter()
    gate_answered = gate_wrong = 0
    for r in answered:
        probe = uniqueness_probe(reconstruct_constraints(r))
        if probe["base_verdict"] != "SAT" or probe["gate"] not in {"unique", "non_unique"}:
            continue
        correct = answers_match(r["ground_truth"], r.get("predicted"))
        conf[f"{'correct' if correct else 'wrong'}_{probe['gate']}"] += 1
        if probe["gate"] == "unique":
            gate_answered += 1
            gate_wrong += 0 if correct else 1
    sbw_uni, sbw_non = conf["wrong_unique"], conf["wrong_non_unique"]
    cor_uni, cor_non = conf["correct_unique"], conf["correct_non_unique"]
    total = len(scorable)
    return {
        "scorable": total,
        "answered_sat": len(answered),
        "sat_accept_risk_pct": 100 * len(sbw) / len(answered) if answered else None,
        "confusion": {"correct_unique": cor_uni, "correct_non_unique": cor_non,
                      "sbw_unique": sbw_uni, "sbw_non_unique": sbw_non},
        "detection_pct": 100 * sbw_non / (sbw_uni + sbw_non) if (sbw_uni + sbw_non) else None,
        "false_rejection_pct": 100 * cor_non / (cor_uni + cor_non) if (cor_uni + cor_non) else None,
        "gate_coverage_pct": 100 * gate_answered / total if total else None,
        "gate_risk_pct": 100 * gate_wrong / gate_answered if gate_answered else None,
    }


def self_consistency(sample_runs: list[list[dict]], t_values: Sequence[int]) -> list[dict]:
    by_pid: dict[str, list] = defaultdict(list)
    gt_of: dict[str, str] = {}
    for results in sample_runs:
        for r in results:
            if not is_scorable(r.get("ground_truth")):
                continue
            gt_of[r["puzzle_id"]] = r["ground_truth"]
            answered = r.get("final_z3_result") == "SAT"
            by_pid[r["puzzle_id"]].append(r.get("predicted") if answered else None)
    n = len(by_pid)
    out = []
    for t in t_values:
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
        out.append({
            "t": t, "puzzles": n, "answered": answered, "wrong": wrong,
            "coverage_pct": 100 * answered / n if n else None,
            "risk_pct": 100 * wrong / answered if answered else None,
        })
    return out


_CONF_PROMPT = """你是逻辑谜题求解的评审。给定谜题与一个候选完整答案，请只输出一个 0 到 100
的整数，表示该候选答案完全正确的置信度（100=确信全对，0=确信有错）。不要输出其他内容。

谜题：
{nl}

候选答案（变量=取值）：
{ans}

只输出一个整数："""


def _parse_conf(text: str | None) -> int | None:
    m = re.search(r"\d{1,3}", text or "")
    if not m:
        return None
    return max(0, min(100, int(m.group())))


def verbalized_confidence(model: str, base_results: list[dict], nl_of: dict[str, str],
                          seed: int, thresholds=(90, 75, 60, 50, 25, 0)) -> list[dict]:
    """B1: elicit a 0--100 confidence per answered SAT output; sweep threshold."""
    llm = LLMClient(model_name=model, temperature=0.0, seed=seed)
    scored: list[tuple[int, bool]] = []
    for r in base_results:
        if not is_scorable(r.get("ground_truth")) or r.get("final_z3_result") != "SAT":
            continue
        resp = llm.ask(_CONF_PROMPT.format(nl=nl_of.get(r["puzzle_id"], ""),
                                           ans=r.get("predicted")), max_tokens=8)
        conf = _parse_conf(resp)
        if conf is None:
            continue
        scored.append((conf, answers_match(r["ground_truth"], r.get("predicted"))))
    total = sum(1 for r in base_results if is_scorable(r.get("ground_truth")))
    return _threshold_sweep(scored, total, thresholds)


def _threshold_sweep(scored, total, thresholds):
    out = []
    for tau in thresholds:
        kept = [c for c in scored if c[0] >= tau]
        wrong = sum(1 for c in kept if not c[1])
        out.append({"threshold": tau, "answered": len(kept), "wrong": wrong,
                    "coverage_pct": 100 * len(kept) / total if total else None,
                    "risk_pct": 100 * wrong / len(kept) if kept else None})
    return out


_BACKTRANS_PROMPT = """把下列逻辑谜题的 Z3 约束翻译回自然语言线索，一行一条，只输出线索本身。

约束：
{constraints}
"""

_RT_JUDGE_PROMPT = """判断“复原线索”是否忠实且完整地覆盖了“原题”中的每一条线索（既不遗漏、
也不添加或弱化）。只输出一个 0 到 100 的整数（100=完全一致，0=严重不符）。

原题：
{nl}

复原线索：
{back}

只输出一个整数："""


def roundtrip_consistency(model: str, base_results: list[dict], nl_of: dict[str, str],
                         seed: int, thresholds=(90, 75, 60, 50, 25, 0)) -> list[dict]:
    """B5: back-translate constraints to NL, judge faithfulness vs the puzzle; sweep threshold."""
    llm = LLMClient(model_name=model, temperature=0.0, seed=seed)
    scored: list[tuple[int, bool]] = []
    for r in base_results:
        if not is_scorable(r.get("ground_truth")) or r.get("final_z3_result") != "SAT":
            continue
        constraints = reconstruct_constraints(r)
        if not constraints:
            continue
        back = llm.ask(_BACKTRANS_PROMPT.format(constraints="\n".join(constraints)),
                       max_tokens=512)
        score = _parse_conf(llm.ask(
            _RT_JUDGE_PROMPT.format(nl=nl_of.get(r["puzzle_id"], ""), back=back), max_tokens=8))
        if score is None:
            continue
        scored.append((score, answers_match(r["ground_truth"], r.get("predicted"))))
    total = sum(1 for r in base_results if is_scorable(r.get("ground_truth")))
    return _threshold_sweep(scored, total, thresholds)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", required=True, help="Comma-separated formalizer aliases")
    p.add_argument("--data-dir", default="allenai/ZebraLogicBench")
    p.add_argument("--data-source", default="auto", choices=["auto", "hf", "local"])
    p.add_argument("--data-subset", default="grid_mode")
    p.add_argument("--sizes", default=None, help="Comma-separated sizes, e.g. '4x5,5x5'")
    p.add_argument("--limit", type=int, default=None, help="Cap puzzles (smoke test)")
    p.add_argument("--scorable-only", action="store_true",
                   help="Keep only gold-annotated puzzles (saves API budget)")
    p.add_argument("--sc-samples", type=int, default=0,
                   help="B4 multi-formalization consistency samples K")
    p.add_argument("--baselines", default="b4",
                   help="Comma list of extra baselines: b1 (verbalized confidence), "
                        "b5 (round-trip faithfulness). b0/B* always computed; b4 via "
                        "--sc-samples. b2 (logprob) unsupported by the text-only endpoint.")
    p.add_argument("--temperature", type=float, default=0.7, help="Temp for SC samples")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out-dir", type=Path, default=Path("results/sparc/multimodel"))
    p.add_argument("--execute-paid", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    sizes = args.sizes.split(",") if args.sizes else None
    puzzles = load_zebralogic(args.data_dir, sizes=sizes,
                              source=args.data_source, subset=args.data_subset)
    if args.scorable_only:
        puzzles = [p for p in puzzles if is_scorable(_solution_to_str(p.solution))]
    if args.limit:
        puzzles = puzzles[: args.limit]
    scorable_n = sum(1 for p in puzzles if is_scorable(_solution_to_str(p.solution)))
    passes = 1 + max(0, args.sc_samples)
    print(f"models={models} puzzles={len(puzzles)} (scorable~{scorable_n}) "
          f"passes/model={passes} (1 no-gate + {args.sc_samples} SC)")

    if args.dry_run:
        build_solver(models[0], 0.0, args.seed)  # construct only, no API
        print("[dry-run] data loaded and solver constructed; no API calls made.")
        return
    if not args.execute_paid:
        raise SystemExit("Refusing to spend API budget. Re-run with --execute-paid "
                         f"(≈{len(puzzles) * passes * len(models)} formalizations).")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    baselines = {b.strip().lower() for b in args.baselines.split(",") if b.strip()}
    nl_of = {p.puzzle_id: getattr(p, "nl_description", "") for p in puzzles}
    summary = {}
    for model in models:
        print(f"\n=== {model}: no-gate pass ===")
        base = evaluate_zebralogic(build_solver(model, 0.0, args.seed), puzzles)
        (args.out_dir / f"{model}_nogate.trace.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in base),
            encoding="utf-8")
        row = rq1_rq2_gate(base)
        if "b1" in baselines:
            row["confidence_b1"] = verbalized_confidence(model, base, nl_of, args.seed)
        if "b5" in baselines:
            row["roundtrip_b5"] = roundtrip_consistency(model, base, nl_of, args.seed)
        if args.sc_samples > 0:
            sc_runs = [evaluate_zebralogic(
                build_solver(model, args.temperature, args.seed + 1 + k), puzzles)
                for k in range(args.sc_samples)]
            row["self_consistency"] = self_consistency(
                sc_runs, t_values=range(1, args.sc_samples + 1))
        summary[model] = row
        print(json.dumps(row, ensure_ascii=False, indent=2))

    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSummary written to {args.out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
