# PRISM Figure Specifications

Detailed spec for the two main paper figures. Use these to drive figure generation (matplotlib for plots, TikZ / draw.io for diagrams). Both figures must be PDF-vector and respect AAAI 2026 sizing.

---

## Figure 1: Motivation

**Goal:** Make two claims visually undeniable within 0.5 seconds of viewing:
1. Baseline accuracy collapses as puzzle complexity grows; PRISM does not.
2. Baseline repair loops stagnate (heavy long tail); PRISM cuts the tail via escalation.

**Size:** 3.5" × 2.5" total (AAAI single-column). Two side-by-side panels.

**Placement:** Top of Section 1 (Introduction), right after the "performance cliff" sentence.

### Panel A (left) — Complexity Cliff

- **Type:** grouped bar chart (or grouped line if more than 4 baselines).
- **X-axis:** puzzle scale ∈ {3×5, 4×4, 4×5, 5×5, 5×6, 6×6} (6 groups).
- **Y-axis:** solving accuracy %, range 0-100.
- **Series (with consistent colors throughout paper):**
  - CoT prompting — grey, hatched
  - Logic-LM — light blue
  - ExpeL (CSP-adapted) — yellow
  - Neural-symbolic baseline (LLM+Z3, no memory) — dark blue
  - **PRISM (ours) — red/orange, slightly thicker outline**
- **Annotation:** dashed horizontal line at random-baseline accuracy with label "random" on the right margin.
- **Annotation:** a curved arrow from "5×5" group to "6×6" group on the baseline bars labeled "all baselines → random"; matching arrow on PRISM showing maintained accuracy.

### Panel B (right) — Repair Loop Stagnation

- **Type:** ECDF (empirical cumulative distribution function) of repair rounds per puzzle. Or histogram if ECDF feels too sparse.
- **X-axis:** repair rounds per puzzle, 0 to 15+.
- **Y-axis:** cumulative fraction of puzzles, 0 to 1.
- **Series:**
  - Neural-symbolic baseline — solid blue, long flat tail past 10 rounds (stagnation regime).
  - **PRISM — solid red, climbs steeply, plateaus at R = 5 (the hard cap).**
- **Annotation:** vertical dashed line at x = 5 labeled "PRISM max R"; shaded "stagnation regime" zone past x = 8 on the baseline curve.
- **Caption hook:** "Baseline puzzles routinely drift past 10 repair rounds without resolution; PRISM's adaptive escalation forces termination within 5 rounds in over X% of cases."

### LaTeX placeholder

```latex
\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{figures/figure1.pdf}
\caption{\textbf{Two faces of the complexity curse.} (Left) Solving accuracy across six ZebraLogic complexity scales; baselines degrade toward random as scale grows, PRISM maintains accuracy. (Right) ECDF of repair-rounds per puzzle; baselines exhibit a long stagnation tail past 10 rounds, while PRISM's bounded escalation policy terminates within $R{=}5$.}
\label{fig:motivation}
\end{figure}
```

---

## Figure 2: PRISM Framework Overview

**Goal:** Make the two-stage architecture and the SMT feedback loop legible in one glance. Reader should be able to trace any data dependency in under 3 seconds.

**Size:** 7" × 3" (AAAI full text-width, double-column or two-column spanning).

**Placement:** Top of Section 3 (Methodology), right before §3.1.

### Layout

Two stacked horizontal bands separated by a thin vertical divider in the middle.

```
+--------------------------------------------------------------------------+
| OFFLINE (one-time)                  |       ONLINE (per puzzle)          |
|                                     |                                    |
|   training       KDP      cluster   |   new        Layer-1    Z3         |
|   puzzles ──→ identifier ──→ ─────┐ |   puzzle ───→ retrieval ─→ pre-    |
|   (NL+sol)                         │ |  (NL)              │     check    |
|                                    ▼ |                    ▼              |
|                       LLM abstract   |              Layer-2 (cost-gated) |
|                              │       |                    │              |
|                              ▼       |                    ▼              |
|              ╔═══ TRIPLE VERIFY (Z3) ═══╗                Z3 inference   |
|              ║ soundness | effect | precision ║─ ─ ─ ─ ─→ step           |
|              ╚════════════════════════════════╝                │         |
|                              │       |                         ▼         |
|                              ▼       |                    SAT? UNSAT?    |
|                      ┌──────────────┐                            │       |
|                      │ Paradigm     │←──── promotion ────────────│       |
|                      │ Library L    │                            ▼       |
|                      └──────┬───────┘                  Repair Memory M  |
|                             │       |                            │      |
|                             │       |                  stagnation/loop  |
|                             │       |                        detect     |
|                             │       |                            ▼      |
|                             │       |              4-level escalation   |
|                             │       |               (L1→L2→L3→L4)       |
|                             │       |                            │      |
|                             │  ═════╪═══ candidate pool L† ═════╪══════ |
|                             └───────┴── batched re-verify ──────┘      |
|                                     |                                  |
+--------------------------------------------------------------------------+
```

### Visual encoding rules

- **Boxes:** rounded rectangles; light blue fill for components (e.g., Layer-1, Layer-2), no fill for data stores (Library, Memory) with thicker outline.
- **Arrows:** solid for data flow, dashed for control flow, double-line for the SMT verification edge so it pops visually.
- **Z3 / SMT verification points:** highlighted with a small Z3 logo or a checkmark-in-circle glyph so the reader can count "where does SMT get called?" at a glance — answer: paradigm screening (offline), consistency precheck (online), inference verification (online), write-back re-screening (offline-side).
- **Stage divider:** vertical dashed line labelled "Offline (one-time)" and "Online (per puzzle)" at the top of each half.
- **Section anchors:** small grey labels under each component pointing to the paper subsection that defines it, e.g. "§3.3.2" under KDP identifier, "§3.5.4" under escalation.

### Caption draft

> **Figure 2: PRISM Framework.** The offline stage (left) distils paradigms from training trajectories via Key Decision Point identification, clustering, LLM abstraction, and Z3 triple verification (soundness, effect, trigger precision). The online stage (right) retrieves paradigms via two-layer matching, performs SMT-checked inference, and on UNSAT writes typed repair records into a memory that drives four-level adaptive escalation. Successful online patterns are staged in a candidate pool $\mathcal{L}^{\dagger}$ and re-screened by the same triple-verification protocol before promotion to the live library $\mathcal{L}$. Z3 verification points are marked with double-line edges; consult Section 3 subsection labels under each component for the formal definitions.

### LaTeX placeholder

```latex
\begin{figure*}[t]
\centering
\includegraphics[width=\textwidth]{figures/figure2.pdf}
\caption{<caption draft above>}
\label{fig:framework}
\end{figure*}
```

---

## Production checklist

- [ ] PDF vector output (no rasterized panels).
- [ ] Color palette consistent with paper accent color (red/orange for PRISM throughout).
- [ ] Font: Helvetica or Times to match AAAI body text.
- [ ] Figure 1 panels share a single y-axis label style and grid color.
- [ ] Figure 2 arrows snap to a 10-unit grid (cleaner rendering).
- [ ] Every component box in Figure 2 has a §-anchor footnote.
- [ ] Captions ≤ 100 words.
- [ ] Both figures pass colorblind safety check (red/blue is colorblind-safe; avoid red/green).
