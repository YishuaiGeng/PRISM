#!/usr/bin/env python3
"""Motivation schematic for SPARC's post-SAT structural gate."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = [
    "SimSun",
    "Microsoft YaHei",
    "Arial",
    "DejaVu Sans",
]
plt.rcParams["svg.fonttype"] = "none"
plt.rcParams["pdf.fonttype"] = 42
plt.rcParams["font.size"] = 8

BLUE = "#0F4D92"
BLUE_SOFT = "#E5EEF8"
GREEN = "#DDF3DE"
RED = "#B64342"
RED_SOFT = "#F9E4E1"
NEUTRAL = "#4D4D4D"
NEUTRAL_SOFT = "#F4F5F7"
PANEL = "#FAFAFA"


def add_box(ax, x, y, w, h, text, facecolor, edgecolor=NEUTRAL,
            fontsize=7.4, textcolor="#272727", linewidth=1.0, bold=False):
    patch = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        linewidth=linewidth,
        edgecolor=edgecolor,
        facecolor=facecolor,
        transform=ax.transAxes,
    )
    ax.add_patch(patch)
    ax.text(
        x + w / 2,
        y + h / 2,
        text,
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=textcolor,
        fontsize=fontsize,
        fontweight="bold" if bold else "normal",
        linespacing=1.15,
    )
    return patch


def add_arrow(ax, start, end, color=NEUTRAL, label=None, offset=(0.0, 0.0)):
    arrow = FancyArrowPatch(
        start,
        end,
        transform=ax.transAxes,
        arrowstyle="-|>",
        mutation_scale=10,
        linewidth=1.1,
        color=color,
        shrinkA=2,
        shrinkB=2,
    )
    ax.add_patch(arrow)
    if label:
        ax.text(
            (start[0] + end[0]) / 2 + offset[0],
            (start[1] + end[1]) / 2 + offset[1],
            label,
            transform=ax.transAxes,
            ha="center",
            va="center",
            color=color,
            fontsize=6.4,
        )


def main():
    # Single-column portrait layout: panel a stacked above panel b.
    fig, ax = plt.subplots(figsize=(3.35, 4.35))
    fig.patch.set_facecolor("white")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # Panel a background (top).
    ax.add_patch(FancyBboxPatch(
        (0.02, 0.545), 0.96, 0.44,
        boxstyle="round,pad=0.008,rounding_size=0.02",
        linewidth=0.7, edgecolor="#D8D8D8", facecolor=PANEL,
        transform=ax.transAxes,
    ))
    # Panel b background (bottom).
    ax.add_patch(FancyBboxPatch(
        (0.02, 0.02), 0.96, 0.475,
        boxstyle="round,pad=0.008,rounding_size=0.02",
        linewidth=0.7, edgecolor="#C9D9ED", facecolor="#FBFDFF",
        transform=ax.transAxes,
    ))

    ax.text(0.05, 0.965, "a", transform=ax.transAxes, fontsize=9,
            fontweight="bold", va="top")
    ax.text(0.11, 0.963, "SAT 直接接受", transform=ax.transAxes,
            fontsize=7.6, fontweight="bold", va="top", color=NEUTRAL)
    ax.text(0.05, 0.475, "b", transform=ax.transAxes, fontsize=9,
            fontweight="bold", va="top")
    ax.text(0.11, 0.473, "SPARC 的 SAT 后决策", transform=ax.transAxes,
            fontsize=7.6, fontweight="bold", va="top", color=BLUE)

    # Panel a: a satisfiable encoding can still be incomplete.
    add_box(ax, 0.05, 0.775, 0.17, 0.11, "题面\n$P$", NEUTRAL_SOFT, fontsize=7)
    add_box(ax, 0.29, 0.775, 0.20, 0.11, "LLM\n形式化", NEUTRAL_SOFT, fontsize=7)
    add_box(ax, 0.56, 0.775, 0.19, 0.11, "约束\n$C$", RED_SOFT,
            edgecolor=RED, fontsize=7)
    add_box(ax, 0.83, 0.775, 0.11, 0.11, "SAT", GREEN,
            edgecolor="#6FAF70", fontsize=6.6, bold=True)
    add_arrow(ax, (0.22, 0.83), (0.29, 0.83))
    add_arrow(ax, (0.49, 0.83), (0.56, 0.83))
    add_arrow(ax, (0.75, 0.83), (0.83, 0.83))
    add_box(ax, 0.79, 0.595, 0.15, 0.10, "直接\n作答", NEUTRAL_SOFT, fontsize=6.8)
    add_arrow(ax, (0.885, 0.775), (0.87, 0.695), color=NEUTRAL)
    ax.text(0.61, 0.66, "线索可能\n遗漏或弱化", transform=ax.transAxes,
            ha="center", va="center", fontsize=6.0, color=RED, linespacing=1.1)
    ax.text(0.5, 0.575, "SAT 只证明当前 $C$ 内部一致", transform=ax.transAxes,
            ha="center", va="center", fontsize=6.8, color=RED, fontweight="bold")

    # Panel b: SPARC applies a task-defined structural predicate after SAT.
    add_box(ax, 0.05, 0.315, 0.16, 0.11, "SAT\n状态", GREEN,
            edgecolor="#6FAF70", fontsize=6.8, bold=True)
    add_box(ax, 0.28, 0.315, 0.21, 0.11, "SPARC\n结构门控", BLUE_SOFT,
            edgecolor=BLUE, textcolor=BLUE, fontsize=6.8, bold=True)
    add_box(ax, 0.555, 0.29, 0.21, 0.16, "答案投影\n满足任务\n结构条件？", "#FFFFFF",
            edgecolor=BLUE, fontsize=6.3, textcolor=BLUE, linewidth=1.2)
    add_box(ax, 0.80, 0.40, 0.17, 0.085, "结构通过\n作答", GREEN,
            edgecolor="#6FAF70", fontsize=6.2, bold=True)
    add_box(ax, 0.80, 0.155, 0.17, 0.085, "结构性\n拒答", RED_SOFT,
            edgecolor=RED, textcolor=RED, fontsize=6.2, bold=True)
    add_arrow(ax, (0.21, 0.37), (0.28, 0.37), color=BLUE)
    add_arrow(ax, (0.49, 0.37), (0.555, 0.37), color=BLUE)
    add_arrow(ax, (0.765, 0.40), (0.80, 0.44), color=BLUE)
    add_arrow(ax, (0.765, 0.335), (0.80, 0.20), color=RED)
    ax.text(0.42, 0.105, "唯一答案任务：检查答案投影唯一性", transform=ax.transAxes,
            ha="center", va="center", fontsize=6.2, color=BLUE)
    ax.text(0.5, 0.05, "结构条件是接受的必要条件，不等价于语义验证", transform=ax.transAxes,
            ha="center", va="center", fontsize=6.0, color=NEUTRAL)

    out = Path(__file__).resolve().parent / "fig_motivation"
    fig.savefig(out.with_suffix(".svg"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(out.with_suffix(".pdf"), bbox_inches="tight", pad_inches=0.02)
    fig.savefig(out.with_suffix(".png"), dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    print("saved fig_motivation.{svg,pdf,png}")


if __name__ == "__main__":
    main()
