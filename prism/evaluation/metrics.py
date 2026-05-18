"""Evaluation metrics for the PRISM repair pipeline.

All functions accept a ``List[dict]`` where each dict represents the outcome
of one puzzle run.  The expected schema for a **result dict** is:

.. code-block:: python

    {
        # ── identification ──────────────────────────────────────────────
        "puzzle_id":   str,          # unique puzzle / problem identifier
        "domain":      str,          # optional domain tag (e.g. "scheduling")

        # ── correctness ─────────────────────────────────────────────────
        "solved":      bool,         # True if final answer matches ground truth
        "ground_truth": str | None,  # expected SAT model string or "UNSAT"
        "predicted":    str | None,  # actual final answer produced by the solver

        # ── cost ────────────────────────────────────────────────────────
        "llm_calls":     int,        # total LLM API calls consumed
        "repair_rounds": int,        # number of constraint-repair iterations

        # ── per-iteration trace ──────────────────────────────────────────
        "steps": [
            {
                "iteration":          int,
                "paradigm_triggered": bool,  # a paradigm was retrieved & applied
                "paradigm_correct":   bool,  # that paradigm led to SAT outcome
                "stagnated":          bool,  # stagnation detector fired this step
            },
            ...
        ],
    }

``steps`` may be an empty list for runs that solved in zero repair iterations.
Missing keys default to safe sentinel values (0, False, empty list) inside each
metric function so that partially-instrumented result dicts are tolerated.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Internal helpers                                                              #
# --------------------------------------------------------------------------- #

def _safe_mean(values: List[float]) -> float:
    """Return the mean of *values*, or 0.0 if the list is empty."""
    return sum(values) / len(values) if values else 0.0


def _all_steps(results: List[dict]) -> List[dict]:
    """Flatten all per-iteration step dicts from a result list."""
    steps: List[dict] = []
    for r in results:
        steps.extend(r.get("steps", []))
    return steps


def _stagnation_rate(results: List[dict]) -> float:
    """Fraction of runs that contain at least one stagnated step."""
    if not results:
        return 0.0
    stagnated = sum(
        1 for r in results
        if any(s.get("stagnated", False) for s in r.get("steps", []))
    )
    return stagnated / len(results)


# --------------------------------------------------------------------------- #
# Core metrics                                                                  #
# --------------------------------------------------------------------------- #

def solve_accuracy(results: List[dict]) -> float:
    """Fraction of puzzle runs in which the solver produced the correct answer.

    A run is counted as correct when ``result["solved"] is True``.  Callers are
    responsible for populating that field (typically by comparing the solver's
    final ``SAT``/``UNSAT`` verdict and, when SAT, the variable assignments
    against the ground-truth model).

    Args:
        results: List of result dicts (see module docstring for schema).

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 for an empty list.

    Example::

        >>> solve_accuracy([{"solved": True}, {"solved": False}])
        0.5
    """
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("solved", False)) / len(results)


def avg_llm_calls(results: List[dict]) -> float:
    """Mean number of LLM API calls per puzzle run.

    Counts the ``"llm_calls"`` field in each result, defaulting to 0 when absent.
    Useful for estimating inference cost per benchmark instance.

    Args:
        results: List of result dicts.

    Returns:
        Float ≥ 0.0.  Returns 0.0 for an empty list.
    """
    return _safe_mean([float(r.get("llm_calls", 0)) for r in results])


def avg_repair_rounds(results: List[dict]) -> float:
    """Mean number of constraint-repair iterations per puzzle run.

    Counts the ``"repair_rounds"`` field in each result (equivalently,
    ``len(result["steps"])`` can be used when ``steps`` is fully populated).
    Repair rounds measure solver effort independently of LLM call granularity.

    Args:
        results: List of result dicts.

    Returns:
        Float ≥ 0.0.  Returns 0.0 for an empty list.
    """
    return _safe_mean([float(r.get("repair_rounds", 0)) for r in results])


def paradigm_trigger_rate(results: List[dict]) -> float:
    """Fraction of repair steps in which at least one paradigm was retrieved.

    Numerator: steps where ``step["paradigm_triggered"] is True``.
    Denominator: total steps across all runs.

    A high trigger rate indicates good paradigm coverage of the encountered
    constraint patterns; a low rate suggests the library needs more paradigms
    for the target domain.

    Args:
        results: List of result dicts.

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 when there are no steps.
    """
    steps = _all_steps(results)
    if not steps:
        return 0.0
    triggered = sum(1 for s in steps if s.get("paradigm_triggered", False))
    return triggered / len(steps)


def paradigm_hit_rate(results: List[dict]) -> float:
    """Fraction of paradigm-triggered steps that resulted in a correct repair.

    Numerator: steps where ``paradigm_triggered`` AND ``paradigm_correct``.
    Denominator: steps where ``paradigm_triggered``.

    This is a precision-like metric for the paradigm library: given that a
    paradigm fired, how often did it actually solve or advance the repair?

    Args:
        results: List of result dicts.

    Returns:
        Float in [0.0, 1.0].  Returns 0.0 when no paradigm-triggered step exists.
    """
    steps = _all_steps(results)
    triggered = [s for s in steps if s.get("paradigm_triggered", False)]
    if not triggered:
        return 0.0
    correct = sum(1 for s in triggered if s.get("paradigm_correct", False))
    return correct / len(triggered)



def stagnation_reduction(
    baseline_results: List[dict],
    prism_results: List[dict],
) -> float:
    """Relative reduction in the stagnation rate achieved by PRISM vs. baseline.

    Stagnation rate of a result set = fraction of runs that contain at least one
    step where ``step["stagnated"] is True``.

    Formula::

        reduction = (baseline_stagnation - prism_stagnation) / baseline_stagnation

    A positive value means PRISM stagnated on fewer runs.  Returns 0.0 when
    ``baseline_results`` is empty or the baseline stagnation rate is zero
    (no improvement can be attributed to PRISM in either case).

    Args:
        baseline_results: Results from a system without the paradigm-guided
            strategy switcher (e.g., vanilla LLM repair loop).
        prism_results: Results from the full PRISM pipeline.

    Returns:
        Float.  Positive means improvement, negative means regression,
        0.0 means no baseline stagnation to compare against.

    Example::

        >>> stagnation_reduction(baseline, prism)
        0.32   # PRISM reduced stagnation rate by 32 %
    """
    b_rate = _stagnation_rate(baseline_results)
    if b_rate == 0.0:
        return 0.0
    p_rate = _stagnation_rate(prism_results)
    return (b_rate - p_rate) / b_rate


# --------------------------------------------------------------------------- #
# Report generation                                                             #
# --------------------------------------------------------------------------- #

def generate_report(
    results: List[dict],
    library_stats: dict,
    baseline_results: Optional[List[dict]] = None,
    title: str = "PRISM Evaluation Report",
) -> str:
    """Generate a Markdown-formatted experiment report.

    Combines all core metrics into a single human-readable document suitable
    for inclusion in a paper appendix, wandb artifact, or experiment log.

    Args:
        results: PRISM experiment results (see module docstring for schema).
        library_stats: Dict returned by ``ParadigmLibrary.stats()``, expected
            to contain ``"total"``, ``"avg_confidence"``, ``"avg_support"``,
            and ``"scope_distribution"``.
        baseline_results: Optional baseline result list for comparative sections.
            When supplied, the report includes a comparison table and the
            stagnation reduction metric.
        title: Report title shown as the top-level Markdown heading.

    Returns:
        A multi-line Markdown string.
    """
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    n = len(results)

    acc = solve_accuracy(results)
    calls = avg_llm_calls(results)
    rounds = avg_repair_rounds(results)
    trig = paradigm_trigger_rate(results)
    hit = paradigm_hit_rate(results)
    stag_rate = _stagnation_rate(results)

    lines: List[str] = [
        f"# {title}",
        "",
        f"*Generated: {ts}*",
        "",
        "---",
        "",
        "## 1. Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Puzzles evaluated | {n} |",
        f"| Solve accuracy | {acc:.1%} |",
        f"| Avg LLM calls / puzzle | {calls:.2f} |",
        f"| Avg repair rounds / puzzle | {rounds:.2f} |",
        f"| Paradigm trigger rate | {trig:.1%} |",
        f"| Paradigm hit rate | {hit:.1%} |",
        f"| Stagnation rate | {stag_rate:.1%} |",
        "",
    ]

    # ── Paradigm library stats ──────────────────────────────────────────
    lines += [
        "## 2. Paradigm Library",
        "",
        f"| Statistic | Value |",
        f"|-----------|-------|",
        f"| Total paradigms | {library_stats.get('total', 0)} |",
        f"| Avg confidence | {library_stats.get('avg_confidence', 0.0):.4f} |",
        f"| Avg support count | {library_stats.get('avg_support', 0.0):.1f} |",
        "",
    ]

    scope_dist: Dict[str, int] = library_stats.get("scope_distribution", {})
    if scope_dist:
        lines += [
            "### Scope distribution",
            "",
            "| Scope tag | Count |",
            "|-----------|-------|",
        ]
        for tag, count in sorted(scope_dist.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{tag}` | {count} |")
        lines.append("")

    # ── Baseline comparison (optional) ─────────────────────────────────
    if baseline_results:
        b_acc = solve_accuracy(baseline_results)
        b_calls = avg_llm_calls(baseline_results)
        b_rounds = avg_repair_rounds(baseline_results)
        b_stag = _stagnation_rate(baseline_results)
        stag_red = stagnation_reduction(baseline_results, results)

        acc_delta = acc - b_acc
        calls_delta = calls - b_calls
        rounds_delta = rounds - b_rounds

        lines += [
            "## 3. Comparison vs. Baseline",
            "",
            "| Metric | Baseline | PRISM | Delta |",
            "|--------|----------|-------|-------|",
            f"| Solve accuracy | {b_acc:.1%} | {acc:.1%} | "
            f"{acc_delta:+.1%} |",
            f"| Avg LLM calls | {b_calls:.2f} | {calls:.2f} | "
            f"{calls_delta:+.2f} |",
            f"| Avg repair rounds | {b_rounds:.2f} | {rounds:.2f} | "
            f"{rounds_delta:+.2f} |",
            f"| Stagnation rate | {b_stag:.1%} | {stag_rate:.1%} | "
            f"{stag_red:+.1%} reduction |",
            "",
        ]

    # ── Per-domain breakdown (if "domain" keys present) ─────────────────
    domains: Dict[str, List[dict]] = {}
    for r in results:
        d = r.get("domain")
        if d:
            domains.setdefault(d, []).append(r)

    if domains:
        lines += [
            "## 4. Per-domain Breakdown",
            "",
            "| Domain | N | Accuracy | Trigger rate | Hit rate |",
            "|--------|---|----------|--------------|----------|",
        ]
        for domain, dr in sorted(domains.items()):
            lines.append(
                f"| {domain} | {len(dr)} "
                f"| {solve_accuracy(dr):.1%} "
                f"| {paradigm_trigger_rate(dr):.1%} "
                f"| {paradigm_hit_rate(dr):.1%} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "*End of report.*",
        "",
    ]

    return "\n".join(lines)
