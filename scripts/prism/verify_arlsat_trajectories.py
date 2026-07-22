"""Verify AR-LSAT training trajectories against ground-truth answers.

Trajectory collection marks a run "solved" when the formalization is SAT,
but on AR-LSAT an erroneous translation is often under-constrained-SAT, so
SAT alone is a weak success signal and paradigm mining can pick up
SAT-optimising pseudo-paradigms. This script upgrades the success signal:
it replays each SAT trajectory's stored Z3 model against the five answer
options and issues a three-valued verdict per trajectory:

    correct        the model's option pattern entails the ground-truth answer
    incorrect      the pattern contradicts the answer or the question's
                   well-posedness (e.g. two options hold on a could-be-true)
    indeterminate  a single model cannot decide (option undecided, formula
                   unparseable, or pattern consistent with several answers)

Verdict logic exploits well-posedness (exactly one correct option):

    could_be_true    wrong options CANNOT hold in any model. One holder ->
                     it must be the answer; >=2 holders -> formalization
                     wrong; 0 holders -> indeterminate.
    must_be_true     the answer holds in EVERY model. Ground-truth failing
                     in this model -> wrong; only ground-truth holding ->
                     correct; several holding -> indeterminate.
    cannot_be_true   the answer fails in every model. Ground-truth holding
                     -> wrong; ground-truth failing while all others hold ->
                     correct; otherwise indeterminate.
    EXCEPT variants  mirror the base type on the complement set.

Output: JSON {trajectory_id: verdict} plus a summary, consumed by
``run_offline.py --trajectory-verdicts``.

Usage::

    python scripts/prism/verify_arlsat_trajectories.py \
        --trajectories data/trajectories/arlsat_train_full \
        --model GPT-4o --offset 0 --max-trajectories 500 \
        --output results/prism/arlsat_traj_verdicts_s0.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from prism.core.llm_client import LLMClient
from prism.core.solver import Z3SolverWrapper
from prism.core.types import Trajectory
from prism.evaluation.benchmarks.arlsat import LETTERS, load_arlsat, parse_option_block

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"Int\('([^']+)'\)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify AR-LSAT trajectories against answers")
    p.add_argument("--trajectories", default="data/trajectories/arlsat_train_full")
    p.add_argument("--data-dir", default="data/hf/ar-lsat")
    p.add_argument("--split", default="train")
    p.add_argument("--model", default="GPT-4o")
    p.add_argument("--offset", type=int, default=0, help="Skip first N trajectory files")
    p.add_argument("--max-trajectories", type=int, default=None)
    p.add_argument("--output", default="results/prism/arlsat_traj_verdicts.json")
    return p.parse_args()


def model_holds(model_constraints: list[str], formula: str) -> str | None:
    """Whether *formula* holds under the fixed model; None if undecidable."""
    model_vars = {m for c in model_constraints for m in _VAR_RE.findall(c)}
    formula_vars = set(_VAR_RE.findall(formula))
    if not formula_vars or not formula_vars <= model_vars:
        return None  # free variables would make the SAT check vacuous
    solver = Z3SolverWrapper()
    try:
        for c in model_constraints:
            if not solver.add_constraint(c):
                return None
        if not solver.add_constraint(formula):
            return None
    except Exception:
        return None
    verdict = solver.check()
    if verdict == "SAT":
        return "holds"
    if verdict == "UNSAT":
        return "fails"
    return None


def judge(
    holds: dict[str, str | None],
    answer: str,
    question_type: str,
    is_except: bool,
) -> str:
    """Three-valued trajectory verdict from per-option model outcomes."""
    letters = sorted(holds)
    holders = [l for l in letters if holds[l] == "holds"]
    failers = [l for l in letters if holds[l] == "fails"]
    decided_all = len(holders) + len(failers) == len(letters)

    if is_except:
        # Mirror: e.g. could-be-true EXCEPT == exactly one cannot-be-true.
        if question_type in ("could_be_true", "unknown"):
            question_type, answer_side = "cannot_be_true", answer
        elif question_type == "must_be_true":
            question_type = "could_be_false_unique"
        # cannot_be_true EXCEPT (rare) falls through to indeterminate below.

    if question_type in ("could_be_true", "unknown"):
        if len(holders) >= 2:
            return "incorrect"  # two "possible" options break well-posedness
        if len(holders) == 1:
            return "correct" if holders[0] == answer else "incorrect"
        return "indeterminate"

    if question_type == "must_be_true":
        if holds.get(answer) == "fails":
            return "incorrect"  # a must-be-true answer failed in a model
        if holds.get(answer) == "holds" and len(holders) == 1:
            return "correct"
        return "indeterminate"

    if question_type == "cannot_be_true":
        if holds.get(answer) == "holds":
            return "incorrect"  # an impossible option held in a model
        if holds.get(answer) == "fails" and decided_all and len(failers) == 1:
            return "correct"
        return "indeterminate"

    return "indeterminate"


def main() -> None:
    args = parse_args()
    puzzles = {p.puzzle_id: p for p in load_arlsat(args.data_dir, split=args.split)}
    files = sorted(Path(args.trajectories).glob("*.json"))[args.offset:]
    if args.max_trajectories:
        files = files[: args.max_trajectories]
    llm = LLMClient(model_name=args.model, temperature=0.0)

    verdicts: dict[str, str] = {}
    counts = {"correct": 0, "incorrect": 0, "indeterminate": 0, "skipped": 0}
    for i, path in enumerate(files):
        traj = Trajectory.model_validate(json.loads(path.read_text(encoding="utf-8")))
        puzzle = puzzles.get(traj.puzzle_id)
        if puzzle is None or not traj.solved or not traj.solution:
            verdicts[traj.trajectory_id] = "skipped"
            counts["skipped"] += 1
            continue
        raw = puzzle.raw_data or {}
        model_constraints = [
            f"Int('{k}') == {v}"
            for k, v in traj.solution.items()
            if not str(k).startswith("_prism_track_") and str(v).lstrip("-").isdigit()
        ]
        options = list(raw.get("options") or [])
        response = llm.translate_arlsat_options(
            passage_nl=str(raw.get("passage", "")),
            question=str(raw.get("question", "")),
            options=options,
            background_constraints=model_constraints,
        )
        formulas = parse_option_block(response, n_options=len(options))
        holds = {
            LETTERS[j]: (
                model_holds(model_constraints, formulas.get(LETTERS[j]) or "")
                if formulas.get(LETTERS[j])
                else None
            )
            for j in range(len(options))
        }
        verdict = judge(
            holds,
            str(raw.get("answer")),
            str(raw.get("question_type", "unknown")),
            bool(raw.get("is_except", False)),
        )
        verdicts[traj.trajectory_id] = verdict
        counts[verdict] += 1
        if (i + 1) % 50 == 0:
            logger.info("Verified %d/%d | %s", i + 1, len(files), counts)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(verdicts, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("Verdicts: %s", counts)
    logger.info("Saved %d verdicts to %s", len(verdicts), output)


if __name__ == "__main__":
    main()
