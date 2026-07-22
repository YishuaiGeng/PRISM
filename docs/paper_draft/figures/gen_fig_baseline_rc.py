#!/usr/bin/env python3
"""Risk--coverage: structural gate vs B0/B1/B4, all on the same GPT-4o-mini
no-gate outputs (78 gold puzzles across sizes; 30 answered SAT, 18 SBW).

Numbers from:
    python scripts/multimodel_eval.py --models GPT-4o-mini \
      --sizes 3x3,4x4,5x3,6x3,6x4 --scorable-only --baselines b1 --sc-samples 5
"""
import os

import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["SimSun", "Times New Roman", "DejaVu Serif"],
    "font.size": 10, "axes.labelsize": 10, "legend.fontsize": 7.5,
    "legend.frameon": False,
    "figure.dpi": 300, "savefig.dpi": 300, "savefig.bbox": "tight",
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.15, "grid.linestyle": "-",
    "lines.linewidth": 1.6, "lines.markersize": 5,
})

GATE = (15.4, 8.3)                                        # structural gate, 1 sample
B0 = (38.5, 60.0)                                         # SAT-accept (no abstention)
B1 = [(2.6, 50.0), (7.7, 66.7), (38.5, 60.0)]            # verbalized confidence sweep
B5 = [(2.6, 50.0), (6.4, 20.0), (38.5, 60.0)]            # round-trip faithfulness sweep
B4 = [(50.0, 64.1), (38.5, 53.3), (25.6, 40.0), (17.9, 28.6), (7.7, 0.0)]  # multi-formalization consistency, t=1..5
B4_T = [1, 2, 3, 4, 5]

fig, ax = plt.subplots(figsize=(3.3, 2.6))

cov = [c for c, _ in B4]; risk = [r for _, r in B4]
ax.plot(cov, risk, color="#2A9D8F", marker="s", linestyle="--", zorder=3,
        label="B4 多形式化一致性（$N{=}5$）")
for t, (x, y) in zip(B4_T, B4):
    ax.annotate(f"$t{{=}}{t}$", (x, y), textcoords="offset points",
                xytext=(4, -9), fontsize=6.5, color="#2A9D8F")

ax.scatter([c for c, _ in B1], [r for _, r in B1], color="#E76F51", marker="o",
           zorder=4, label="B1 置信度")
ax.scatter([c for c, _ in B5], [r for _, r in B5], color="#9467BD", marker="^",
           zorder=4, label="B5 往返一致性")
ax.scatter(*B0, color="#8C8C8C", marker="D", zorder=4, label="B0 SAT-接受")
ax.scatter(*GATE, marker="*", s=170, color="#0072B2", edgecolor="black",
           linewidth=0.5, zorder=5, label="结构门控（单样本）")

ax.set_xlabel("回答覆盖率（%）")
ax.set_ylabel("作答风险（%）")
ax.set_xlim(0, 55)
ax.set_ylim(0, 72)
ax.legend(loc="upper right", handlelength=1.5)

out = os.path.dirname(os.path.abspath(__file__))
fig.savefig(os.path.join(out, "fig_baseline_rc.pdf"))
fig.savefig(os.path.join(out, "fig_baseline_rc.png"), dpi=300)
print("saved fig_baseline_rc.{pdf,png}")
