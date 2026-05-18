"""Paradigm transfer metrics for cross-scale and cross-domain generalisation.

Provides two transfer scenarios defined in the PRISM experiment design:

- **L1 (within-domain, cross-scale)**: Paradigms learned on small puzzles are
  evaluated on larger puzzles of the same type.  A positive ``delta_accuracy``
  with a high ``hit_rate`` confirms that the paradigm library generalises across
  scales without needing to re-run the offline distillation phase.

- **L2 (cross-domain)**: Paradigms from Zebra puzzles are applied to
  Knights-and-Knaves puzzles.  A non-trivial ``trigger_rate`` on the target
  domain indicates that structurally similar constraint patterns exist across
  domains, even when surface-level formulations differ.

All functions accept the same ``List[dict]`` result format used by the rest of
``prism.evaluation.metrics`` (see that module's docstring for the full schema).
"""

from __future__ import annotations

from typing import Dict, List


# --------------------------------------------------------------------------- #
# Inline helpers (duplicated to avoid circular import with metrics.py)          #
# --------------------------------------------------------------------------- #

def _solve_accuracy(results: List[dict]) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.get("solved", False)) / len(results)


def _all_steps(results: List[dict]) -> List[dict]:
    steps: List[dict] = []
    for r in results:
        steps.extend(r.get("steps", []))
    return steps


def _paradigm_trigger_rate(results: List[dict]) -> float:
    steps = _all_steps(results)
    if not steps:
        return 0.0
    return sum(1 for s in steps if s.get("paradigm_triggered", False)) / len(steps)


def _paradigm_hit_rate(results: List[dict]) -> float:
    steps = _all_steps(results)
    triggered = [s for s in steps if s.get("paradigm_triggered", False)]
    if not triggered:
        return 0.0
    return sum(1 for s in triggered if s.get("paradigm_correct", False)) / len(triggered)


# Public aliases so callers can use canonical names.
solve_accuracy = _solve_accuracy
paradigm_trigger_rate = _paradigm_trigger_rate
paradigm_hit_rate = _paradigm_hit_rate


def paradigm_transfer_rate(
    source_results: List[dict],
    target_results: List[dict],
) -> Dict[str, float]:
    """Measure paradigm transfer from a source domain/scale to a target.

    Computes three metrics over the *target* result set:

    - **trigger_rate**: fraction of repair steps where a paradigm was retrieved.
      High values indicate the library's scope tags match the target domain.
    - **hit_rate**: fraction of paradigm-triggered steps that led to a correct
      repair.  High values indicate the paradigms' strategies generalise.
    - **delta_accuracy**: ``target_accuracy - source_accuracy``.  Positive means
      the system performs at least as well on the target as the source; near-zero
      or positive is the hoped-for L2 result.

    Args:
        source_results: Results from the source (training) domain or scale.
        target_results: Results from the evaluation (target) domain or scale.

    Returns:
        Dict with keys ``"trigger_rate"``, ``"hit_rate"``, and
        ``"delta_accuracy"`` (all floats in interpretable ranges).

    Example::

        >>> transfer = paradigm_transfer_rate(train_results, test_results)
        >>> transfer["delta_accuracy"]   # positive = no transfer loss
        0.04
    """
    return {
        "trigger_rate": paradigm_trigger_rate(target_results),
        "hit_rate": paradigm_hit_rate(target_results),
        "delta_accuracy": (
            solve_accuracy(target_results) - solve_accuracy(source_results)
        ),
    }


def l1_cross_scale_summary(
    configs: Dict[str, List[dict]],
    test_sizes: List[str],
) -> List[Dict[str, object]]:
    """Tabulate L1 cross-scale transfer across multiple training configurations.

    Args:
        configs: Mapping of config label (e.g. ``"Config-A (3x5)"``) to its
            corresponding result dicts.  Each result dict must include a
            ``"domain"`` field set to the puzzle size string (e.g. ``"4x5"``).
        test_sizes: Ordered list of puzzle size strings to report.

    Returns:
        List of row dicts, each with keys ``"config"`` and one key per entry in
        *test_sizes* containing the solve accuracy for that size.

    Example::

        >>> rows = l1_cross_scale_summary(
        ...     {"Config-A": config_a_results, "Config-C": config_c_results},
        ...     ["3x5", "4x5", "5x5", "6x6"],
        ... )
    """
    rows: List[Dict[str, object]] = []
    for config_label, results in configs.items():
        row: Dict[str, object] = {"config": config_label}
        by_size: Dict[str, List[dict]] = {}
        for r in results:
            size = r.get("domain", "unknown")
            by_size.setdefault(size, []).append(r)
        for size in test_sizes:
            size_results = by_size.get(size, [])
            row[size] = solve_accuracy(size_results) if size_results else None
        rows.append(row)
    return rows


def l2_cross_domain_summary(
    zebra_results: List[dict],
    knk_results: List[dict],
) -> Dict[str, float]:
    """Compute L2 Zebra→Knights-and-Knaves transfer summary.

    Args:
        zebra_results: Results from the Zebra (source) domain.
        knk_results: Results from the Knights-and-Knaves (target) domain,
            using paradigms learned solely from Zebra puzzles.

    Returns:
        Dict with keys ``"zebra_accuracy"``, ``"knk_accuracy"``,
        ``"knk_trigger_rate"``, ``"knk_hit_rate"``, and ``"delta_accuracy"``.
    """
    transfer = paradigm_transfer_rate(zebra_results, knk_results)
    return {
        "zebra_accuracy": solve_accuracy(zebra_results),
        "knk_accuracy": solve_accuracy(knk_results),
        "knk_trigger_rate": transfer["trigger_rate"],
        "knk_hit_rate": transfer["hit_rate"],
        "delta_accuracy": transfer["delta_accuracy"],
    }
