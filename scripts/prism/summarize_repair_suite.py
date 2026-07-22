"""Summarize and compare controlled repair benchmark suite results.

Reads per-condition CSV files produced by run_repair_benchmark_suite.py,
computes McNemar's test for each no-memory vs template-memory pair, and
generates a unified summary table.

Usage::

    python scripts/prism/summarize_repair_suite.py \
        --suite-dirs results/prism/repair_suite_3x_solution results/prism/repair_suite_5x_solution \
        --labels "3x3/3x4 (solution)" "5x5/6x5 (solution)" \
        --output results/prism/repair_suite_combined_summary.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

_PERTURBATION_ORDER = [
    "direct_position",
    "directly_left",
    "somewhere_left",
    "directly_right",
    "somewhere_right",
    "adjacent",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Summarize controlled repair benchmark suite results"
    )
    p.add_argument(
        "--suite-dirs",
        nargs="+",
        required=True,
        help="One or more suite output directories",
    )
    p.add_argument(
        "--labels",
        nargs="+",
        default=None,
        help="Labels for each suite dir (default: dir names)",
    )
    p.add_argument(
        "--output",
        default="results/prism/repair_suite_combined_summary.csv",
        help="Output CSV path",
    )
    p.add_argument(
        "--latex",
        action="store_true",
        help="Also print a LaTeX table",
    )
    return p.parse_args(argv)


def _read_suite_dir(
    suite_dir: Path,
) -> dict[str, dict[str, list[dict]]]:
    """Read all CSV result files in a suite directory.

    Returns:
        {perturbation_type: {condition: [rows]}}
    """
    results: dict[str, dict[str, list[dict]]] = {}
    for csv_path in sorted(suite_dir.glob("*.csv")):
        name = csv_path.stem
        if "summary" in name or "metadata" in name:
            continue
        # Parse filename: {perturbation_type}_{condition}.csv
        # Conditions: nomemory, template_memory
        parts = name.split("_")
        if "template_memory" in name:
            condition = "template_memory"
            pt = name.replace("_template_memory", "")
        elif "nomemory" in name:
            condition = "no_memory"
            pt = name.replace("_nomemory", "")
        else:
            continue
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        results.setdefault(pt, {})[condition] = rows
    return results


def _mcnemar_test(
    nomem_rows: list[dict],
    mem_rows: list[dict],
) -> tuple[float, float]:
    """Compute McNemar's test for paired binary outcomes.

    Matches rows by puzzle_id. Returns (chi2_statistic, p_value).
    Uses mid-p McNemar's test for small samples.
    """
    nomem_by_id = {r["puzzle_id"]: r.get("solved", "").lower() == "true" for r in nomem_rows}
    mem_by_id = {r["puzzle_id"]: r.get("solved", "").lower() == "true" for r in mem_rows}

    # Count discordant pairs
    ids = set(nomem_by_id) & set(mem_by_id)
    b = 0  # nomem wrong, mem correct
    c = 0  # nomem correct, mem wrong
    for pid in ids:
        n_ok = nomem_by_id[pid]
        m_ok = mem_by_id[pid]
        if not n_ok and m_ok:
            b += 1
        elif n_ok and not m_ok:
            c += 1

    # McNemar's exact mid-p
    n_disc = b + c
    if n_disc == 0:
        return 0.0, 1.0

    # Standard chi-squared with continuity correction for large samples
    if n_disc >= 25:
        chi2 = (abs(b - c) - 1) ** 2 / n_disc
        p = _chi2_sf(chi2, df=1)
    else:
        # Exact binomial mid-p
        p = _binomial_midp(b, n_disc)
        chi2 = float("nan")
    return chi2, p


def _chi2_sf(chi2: float, df: int = 1) -> float:
    """Survival function of chi-squared distribution (upper-tail p-value)."""
    # Simple approximation for df=1: p = erfc(sqrt(chi2/2))
    x = math.sqrt(chi2 / 2.0)
    return math.erfc(x)


def _binomial_midp(k: int, n: int) -> float:
    """Mid-p for two-sided binomial test with p=0.5."""
    # P(X <= k-1) + 0.5 * P(X = k), doubled for two-sided
    from math import comb, log, exp

    def binom_pmf(k_, n_, p=0.5):
        logpmf = comb(n_, k_) and (
            math.lgamma(n_ + 1) - math.lgamma(k_ + 1) - math.lgamma(n_ - k_ + 1)
            + k_ * math.log(p)
            + (n_ - k_) * math.log(1 - p)
        )
        return math.exp(logpmf) if n_ > 0 else (1.0 if k_ == 0 else 0.0)

    lo = min(k, n - k)
    # Two-sided: P(X <= lo - 1) * 2 + P(X = lo)
    cum = 0.0
    for i in range(lo):
        cum += binom_pmf(i, n)
    mid_p = 2 * cum + binom_pmf(lo, n)
    return min(1.0, mid_p)


def _significance_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return ""


def summarize(args: argparse.Namespace) -> None:
    suite_dirs = [Path(d) for d in args.suite_dirs]
    labels = args.labels or [d.name for d in suite_dirs]
    if len(labels) != len(suite_dirs):
        raise ValueError("--labels must match --suite-dirs count")

    all_rows: list[dict] = []

    print(f"\n{'='*80}")
    print("CONTROLLED REPAIR BENCHMARK SUITE — COMBINED RESULTS")
    print(f"{'='*80}")

    for label, suite_dir in zip(labels, suite_dirs):
        print(f"\n{'─'*40}")
        print(f"Suite: {label} ({suite_dir})")
        print(f"{'─'*40}")
        print(f"{'Perturbation':<22} {'N':>4} {'NoMem':>8} {'MemAcc':>8} {'Δpp':>6} {'p':>8} {'Sig':>4}")
        print("-" * 65)

        suite_results = _read_suite_dir(suite_dir)

        for pt in _PERTURBATION_ORDER:
            conditions = suite_results.get(pt, {})
            nomem = conditions.get("no_memory", [])
            tmem = conditions.get("template_memory", [])
            if not nomem or not tmem:
                continue

            n_nomem = len(nomem)
            n_tmem = len(tmem)
            n = min(n_nomem, n_tmem)

            solved_nomem = sum(1 for r in nomem if r.get("solved", "").lower() == "true")
            solved_tmem = sum(1 for r in tmem if r.get("solved", "").lower() == "true")

            acc_nomem = solved_nomem / n_nomem * 100 if n_nomem else 0
            acc_tmem = solved_tmem / n_tmem * 100 if n_tmem else 0
            delta = acc_tmem - acc_nomem

            chi2, p = _mcnemar_test(nomem, tmem)
            sig = _significance_stars(p)

            print(
                f"{pt:<22} {n:>4} "
                f"{solved_nomem}/{n_nomem:>3} ({acc_nomem:>4.1f}%) "
                f"{solved_tmem}/{n_tmem:>3} ({acc_tmem:>4.1f}%) "
                f"{delta:>+6.1f} "
                f"{p:>8.4f} "
                f"{sig:>4}"
            )

            all_rows.append({
                "suite": label,
                "perturbation_type": pt,
                "n": n,
                "n_nomem": n_nomem,
                "n_tmem": n_tmem,
                "solved_nomem": solved_nomem,
                "solved_tmem": solved_tmem,
                "acc_nomem_pct": round(acc_nomem, 1),
                "acc_tmem_pct": round(acc_tmem, 1),
                "delta_pp": round(delta, 1),
                "mcnemar_chi2": round(chi2, 3) if not math.isnan(chi2) else "exact",
                "mcnemar_p": round(p, 4),
                "significance": sig,
            })

    # Save CSV
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if all_rows:
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
            writer.writeheader()
            writer.writerows(all_rows)
        print(f"\nSaved to: {output_path}")

    # Optional LaTeX table
    if args.latex:
        _print_latex_table(all_rows)


def _print_latex_table(rows: list[dict]) -> None:
    print("\n% LaTeX table")
    print("\\begin{table}[t]")
    print("\\centering")
    print("\\small")
    print("\\begin{tabular}{llrrrrl}")
    print("\\toprule")
    print(
        "Suite & Perturbation & $N$ & No-Mem (\\%) & Template-Mem (\\%) "
        "& $\\Delta$pp & $p$\\\\"
    )
    print("\\midrule")
    current_suite = None
    for row in rows:
        suite = row["suite"]
        if suite != current_suite:
            if current_suite is not None:
                print("\\midrule")
            current_suite = suite
        pt = row["perturbation_type"].replace("_", "\\_")
        sig = row["significance"]
        star = f"$^{{{sig}}}$" if sig else ""
        print(
            f"\\multirow{{1}}{{*}}{{{suite if suite != current_suite else ''}}} "
            f"& {pt} & {row['n']} "
            f"& {row['acc_nomem_pct']:.1f} "
            f"& {row['acc_tmem_pct']:.1f}{star} "
            f"& {row['delta_pp']:+.1f} "
            f"& {row['mcnemar_p']:.4f}\\\\"
        )
    print("\\bottomrule")
    print("\\end{tabular}")
    print("\\caption{Controlled repair benchmark: no-memory vs.~template-memory accuracy. "
          "$^*p<0.05$, $^{**}p<0.01$, $^{***}p<0.001$ (McNemar's test).}")
    print("\\label{tab:controlled-repair}")
    print("\\end{table}")


def main() -> None:
    args = parse_args()
    summarize(args)


if __name__ == "__main__":
    main()
