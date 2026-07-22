#!/usr/bin/env python3
"""Risk--coverage curve swept over SPARC completion budget (k=0..3).

Data source: scripts/budget_sweep_zebra.py over results/zebra_v2_{s42,s123,s7}
(three-seed merged, n=600 scorable). No-gate systems appear as single points
since they have no budget knob. Regenerate the numbers with:

    python scripts/budget_sweep_zebra.py results/zebra_v2_s42 results/zebra_v2_s123 results/zebra_v2_s7
"""
import os

import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["SimSun", "Times New Roman", "DejaVu Serif"],
    "font.size": 10, "axes.labelsize": 10, "legend.fontsize": 8,
    "legend.frameon": False,
    "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.15, "grid.linestyle": "-",
    "lines.linewidth": 1.8, "lines.markersize": 5,
})

N = 600
# (answered, wrong) per completion budget k = 0..3, three-seed merged.
BASESPARC = [(62, 4), (75, 7), (81, 12), (82, 13)]
NOPARSPARC = [(75, 11), (82, 16), (90, 22), (94, 26)]
BASELINE = (140, 78)      # no gate, no budget knob
AGGRESSIVE = (136, 73)


def cov_risk(points):
    cov = [a / N * 100 for a, _ in points]
    risk = [w / a * 100 for a, w in points]
    return cov, risk


fig, ax = plt.subplots(figsize=(3.3, 2.6))

OFFSETS = {
    "#0072B2": [(3, -12), (3, -12), (7, -7), (4, 3)],
    "#2A9D8F": [(-10, 7), (-10, 7), (3, -12), (3, -12)],
}
for pts, label, color, marker in [
    (BASESPARC, "基线 + SPARC ($k{=}0..3$)", "#0072B2", "o"),
    (NOPARSPARC, "激进修复 + SPARC ($k{=}0..3$)", "#2A9D8F", "s"),
]:
    cov, risk = cov_risk(pts)
    ax.plot(cov, risk, color=color, marker=marker, zorder=3, label=label)
    for k, (x, y) in enumerate(zip(cov, risk)):
        ax.annotate(f"$k{{=}}{k}$", (x, y), textcoords="offset points",
                    xytext=OFFSETS[color][k], fontsize=7, color=color)

for (a, w), label, marker in [
    (BASELINE, "基线（无门控）", "X"),
    (AGGRESSIVE, "激进修复（无门控）", "P"),
]:
    ax.scatter(a / N * 100, w / a * 100, marker=marker, s=45,
               color="#E76F51", zorder=4, label=label)

ax.set_xlabel("回答覆盖率（%）")
ax.set_ylabel("作答风险（%）")
ax.set_xlim(8, 26)
ax.set_ylim(0, 62)
ax.legend(loc="upper left", handlelength=1.6)

out = os.path.dirname(os.path.abspath(__file__))
fig.savefig(os.path.join(out, "fig_risk_coverage.pdf"))
fig.savefig(os.path.join(out, "fig_risk_coverage.png"), dpi=300)
print("saved fig_risk_coverage.{pdf,png}")
