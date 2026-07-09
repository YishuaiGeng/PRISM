# fig:motivation 动机图完整设计规格（v2）

> P0-1 条目的细化产物。目标：AAAI 第 1 页右栏顶部 teaser 图。
> 交付方式：本文档末尾附可直接发给 Gemini 的英文 prompt。
> v2 变更：回应四个疑问——数字取舍、GT 改 Correct、修复动作去夸张化、(c) 改为对照时间轴。

---

## 0. 已定决策

| 决策点 | 结论 | 理由 |
|---|---|---|
| 两联 vs 三联 | **三联**，(c) 为与 (b) 同构的对照时间轴 | 只有痛点没有解法钩子不完整；(c) 与 (b) 用相同视觉语言才能形成"5 轮卡死 vs 3 轮通关"的直接对比 |
| 案例选择 | (a)(b)(c) 用**同一道谜题**贯穿："The green house is immediately to the left of the white house" | (b) 的停滞由 (a) 的翻译错误引发，(c) 展示 PRISM 解同一道题；素材来自 §6.8 案例研究 |
| 错误类型 | **对称化错误**（E-002，Or 双向扩展） | 一行公式即可看懂，理解成本最低 |
| 图内数字 | **只放 baseline 行为观察类数字**（停滞率 41.3%、修复轮数对比 4.2→2.1、停滞率对比 41.3%→12.4%）；**撤掉 7/19** | 7/19 是 PRISM 自身挖掘产出，用方法的结果论证方法的动机有循环论证嫌疑，且"error paradigm"概念第 1 页尚未建立；改为定性表述，待有 baseline 日志统计后再补中性数字 |
| 正确译法标签 | 用 **`Correct ✓`**，不用 GT | 约束翻译没有"标注的标准翻译"，GT（ground truth）用词不当 |
| (b) 修复动作 | **各轮动作表面不同**（edit/relax/rewrite/restate），仅 UNSAT core 徽章完全一致 | 5 轮修同一动作过于夸张失真；真实且更有力的故事是"动作看似在变、矛盾源从未改变"，这正是反馈粒度粗的准确含义 |
| 图内语言 | 全英文 | AAAI 终稿英文，图只做一次 |
| 视觉形式 | Gemini 生成矢量风格图，TikZ 为回退 | 三联卡片+时间轴信息图 |

---

## 1. 整体版式

- **画幅**：单栏宽（AAAI 单栏 3.3 in），建议画布 990×1240 px（宽:高 ≈ 1:1.25，v2 因 (c) 变时间轴略增高）。
- **结构**：三个横向条带自上而下：
  - (a) 高度约 34%——跨题重复的系统性翻译错误
  - (b) 高度约 32%——baseline 修复停滞时间轴（红）
  - (c) 高度约 28%——PRISM 同题对照时间轴（绿）
  - 余量 6% 为条带间距
- **配色**（色盲安全，Okabe–Ito）：
  - 错误/失败：朱红 `#D55E00`
  - 正确/PRISM：蓝绿 `#009E73`
  - 强调标注：橙 `#E69F00`
  - 中性：深灰 `#333333` 文字，浅灰 `#F2F2F2` 卡片底
- **字体**：无衬线（Helvetica/Arial）标签，等宽（Courier/Menlo）代码与约束；缩放到 3.3 in 后最小字号 ≥ 6.5 pt。
- **风格**：扁平矢量、白底、无渐变无阴影。

---

## 2. 条带 (a)：Systematic translation errors recur across instances

**一句话**：没有跨题记忆，LLM 在不同题目上重复同一个翻译错误。

### 布局

- 左 70%：**堆叠卡片**——展开的主卡片（Puzzle #12）+ 身后两张幽灵卡露边（#47、#83）。
- 右 30%：竖排标注区。

### 主卡片内容（等宽字体）

```
Puzzle #12  (color attribute)
NL: "The green house is immediately
     to the left of the white house."

LLM ✗     Or(green = white − 1,
             green = white + 1)   ← symmetrized
Correct ✓ green = white − 1
```

- `LLM ✗` 行朱红；`Correct ✓` 行蓝绿；`← symmetrized` 朱红小字斜体。
- 幽灵卡各露一行朱红小字：`Puzzle #47 (nationality) — same error`、`Puzzle #83 (job) — same error`。

### 右侧标注区

- 循环箭头图标（↻）+ 文字：`No cross-instance memory → the same error repeats across attribute types`
- **不放 7/19**。预留位置：若后续从 baseline 失败日志统计出中性数字（如 "found in X% of failed puzzles"），可补在此处（见 §8 待办）。

### 面板标签

- `(a) Same mis-translation, every puzzle`

---

## 3. 条带 (b)：Baseline — coarse feedback, repair stagnation

**一句话**：修复动作表面在变，UNSAT core 从未改变——这就是反馈粒度粗的后果。

### 布局

- 水平时间轴，5 个节点（Round 1–5），红色调。
- 每节点：上方动作标签，节点本体红 ✗ UNSAT，下方 core 徽章。

### 节点内容（动作各不相同，core 完全一致）

| 节点 | 上方动作标签 | 状态 | 下方 core 徽章 |
|---|---|---|---|
| Round 1 | `edit c7` | ✗ UNSAT | `core = {c7, c2}` |
| Round 2 | `relax c7` | ✗ UNSAT | `core = {c7, c2}` |
| Round 3 | `rewrite c7` | ✗ UNSAT | `core = {c7, c2}` |
| Round 4 | `restate c7` | ✗ UNSAT | `core = {c7, c2}` |
| Round 5 | `edit c7 again` | ✗ UNSAT | `core = {c7, c2}` |

- 5 个 core 徽章逐字一致（浅灰底、朱红等宽字），一眼看出"没变"。
- 相邻徽章间浅橙弧线，标 1–2 处 `J = 1.0`。
- 时间轴上方跨节点加一条横向注释（橙色）：`superficially different repairs — same contradiction`。
- 末端：大朱红 ✗ + `repair budget exhausted (R = 5)`。

### 数据钩子（条带右下橙色强调框）

```
41.3% of baseline repairs stagnate
```

（仅这一条；恢复率等对比数字移至 (c) 做前后对照。）

### 面板标签

- `(b) Baseline: raw solver feedback → stuck on the same UNSAT core`

### 与 (a) 的衔接

- (a) 的 `LLM ✗` 行引细虚线箭头到 Round 1，小字 `this mis-translation triggers…`。

---

## 4. 条带 (c)：PRISM — same puzzle, 3 rounds to SAT

**一句话**：同一道题，PRISM 的两类记忆分别拦截和脱困，3 轮到 SAT。

### 布局（与 (b) 同构的时间轴，绿色调，形成直接对比）

- 水平时间轴，**3 个节点**，与 (b) 的节点/徽章视觉语言完全一致，仅配色换蓝绿。
- 时间轴比 (b) 短，右侧留出的空间放前后对照数字块。

### 节点内容

| 节点 | 上方标签 | 状态 | 下方徽章 |
|---|---|---|---|
| Round 1 | `error paradigm E-002 injected` | ✓ blocked | `symmetrization avoided` |
| Round 2 | `new inference` | ✗ UNSAT | `core = {c7, c2} → signature matched` |
| Round 3 | `L1: switch repair target` | ✓ SAT | `escaped in 1 switch` |

- Round 1 徽章蓝绿：表示已知失败模式在发生前被拦截（对应痛点 a）。
- Round 2 徽章：core 签名被类型化记忆识别，立即触发升级，不等 5 轮（对应痛点 b）。
- 末端：大蓝绿 ✓ + `SAT`。

### 前后对照数字块（时间轴右侧，两行，箭头式）

```
repair rounds   4.2 → 2.1
stagnation     41.3% → 12.4%
```

- 红色数字 → 绿色数字，中间箭头。
- 来源：`tab:main-results`（修复轮数 4.21→2.14 待复核）、`tab:repair-results`（停滞率 41.3→12.4）。

### 面板标签

- `(c) PRISM: solver-gated memory — same puzzle, solved`

### 视觉对应关系

- (a) → (c) Round 1 一条蓝绿细箭头（错误范式拦截对应痛点 a）；
- (b) 的 core 徽章区 → (c) Round 2 一条蓝绿细箭头（签名识别对应痛点 b）；
- 箭头贴条带边缘走，不穿过内容。

---

## 5. Caption 文案

### 中文版（当前中文稿用）

> 图 1：\PRISM 动机。(a) 缺乏跨题记忆时，LLM 在不同谜题上重复同一系统性翻译错误（图示为将有向邻接约束对称化为双向 Or）；(b) 原始求解器反馈下，表面不同的修复动作使 UNSAT core 始终不变（Jaccard $=1.0$），基线 41.3\% 的修复陷入停滞；(c) 在同一道谜题上，\PRISM 以求解器筛选的错误范式在错误发生前将其拦截，以类型化修复记忆识别 core 签名并切换修复目标，平均修复轮数由 4.2 降至 2.1。

### 英文版（AAAI 终稿用）

> Figure 1: Motivation for \PRISM. (a) Without cross-instance memory, an LLM repeats the same systematic mis-translation across puzzles (symmetrizing a directed adjacency constraint into a bidirectional Or). (b) With raw solver feedback, superficially different repairs leave the UNSAT core unchanged (Jaccard $=1.0$); 41.3\% of baseline repairs stagnate. (c) On the same puzzle, \PRISM blocks the known mis-translation with a solver-vetted error paradigm and escapes the repair loop via typed repair memory and target switching, cutting average repair rounds from 4.2 to 2.1.

---

## 6. 交给 Gemini 的 Prompt（v2，直接复制使用）

```
Create a clean, flat, vector-style academic figure (white background, no gradients, no shadows) for the first page of an AAAI paper. Single-column teaser, canvas 990x1240 px (width:height ≈ 1:1.25). Sans-serif font (Helvetica-like) for labels, monospace font for code/constraints. All text in English. Color palette (colorblind-safe): vermilion #D55E00 for errors/failures, bluish-green #009E73 for correct/solution elements, orange #E69F00 for emphasis callouts, dark gray #333333 for neutral text, light gray #F2F2F2 for card/badge backgrounds.

The figure has THREE horizontal bands stacked vertically. Bands (b) and (c) are two timelines drawn with the SAME visual vocabulary (same node shapes, same badge style) so readers can directly compare them: (b) is red and long, (c) is green and short.

BAND (a) — top, ~34% of height. Bold panel label at top-left: "(a) Same mis-translation, every puzzle".
Left 70%: a stack of three overlapping cards; the front card fully visible, two cards behind peeking out at offset edges. Front card content (monospace):
  Title: "Puzzle #12  (color attribute)"
  Line 1: NL: "The green house is immediately to the left of the white house."
  Line 2 (vermilion, prefixed with a red cross): LLM ✗   Or(green = white − 1, green = white + 1)   with a small italic vermilion note "← symmetrized"
  Line 3 (bluish-green, prefixed with a green check): Correct ✓   green = white − 1
The two peeking cards each show one small vermilion line: "Puzzle #47 (nationality) — same error" and "Puzzle #83 (job) — same error".
Right 30%: a circular-arrows icon (↻) with text: "No cross-instance memory → the same error repeats across attribute types".

BAND (b) — middle, ~32% of height, red-toned. Bold panel label: "(b) Baseline: raw solver feedback → stuck on the same UNSAT core".
A horizontal timeline with 5 nodes labeled Round 1..Round 5, connected by arrows. Above the nodes, action labels IN THIS ORDER (each one different): "edit c7", "relax c7", "rewrite c7", "restate c7", "edit c7 again". Each node shows a red cross and "UNSAT". Below each node hangs an IDENTICAL badge (light gray background, vermilion monospace text): "core = {c7, c2}" — all five badges must be letter-for-letter identical. Light-orange arcs connect adjacent badges; label one or two arcs "J = 1.0". Spanning above the action labels, an orange annotation: "superficially different repairs — same contradiction". At the right end: a large vermilion cross with "repair budget exhausted (R = 5)". In an orange emphasis box at bottom-right: "41.3% of baseline repairs stagnate".
Draw a thin dashed arrow from the vermilion "LLM ✗" line in band (a) down to Round 1 of band (b), tiny label: "this mis-translation triggers…".

BAND (c) — bottom, ~28% of height, green-toned, SAME node/badge visual style as band (b) but bluish-green. Bold panel label: "(c) PRISM: solver-gated memory — same puzzle, solved".
A horizontal timeline with only 3 nodes, visibly shorter than band (b)'s:
  Round 1 — label above: "error paradigm E-002 injected"; node: green check + "blocked"; badge below (bluish-green text): "symmetrization avoided".
  Round 2 — label above: "new inference"; node: red cross + "UNSAT"; badge below: "core = {c7, c2} → signature matched".
  Round 3 — label above: "L1: switch repair target"; node: green check + "SAT"; badge below: "escaped in 1 switch".
At the right end: a large bluish-green check mark with "SAT". To the right of the timeline, a small before/after stats block with arrows, baseline value in vermilion, PRISM value in bluish-green:
  "repair rounds  4.2 → 2.1"
  "stagnation  41.3% → 12.4%"
Draw one thin bluish-green arrow from band (a) into Round 1 of band (c), and one from the badge row of band (b) into Round 2 of band (c); route both arrows along the band edges, never across content.

Keep generous white space between bands. Text must remain legible when scaled to 3.3 inches wide (final minimum font ≈ 6.5 pt). Output as clean vector-style artwork suitable for an academic paper.
```

---

## 7. 验收清单（拿到 Gemini 产出后逐项检查）

- [ ] 缩放到 3.3 in 宽后所有文字可读（重点：core 徽章、对照数字块）
- [ ] (b)(c) 两条时间轴视觉语言一致（节点形状、徽章样式相同，仅配色和长度不同），对比关系一眼可见
- [ ] (b) 5 个动作标签**各不相同**，5 个 core 徽章**逐字一致**（Gemini 常在重复元素上出变体）
- [ ] (c) 只有 3 个节点且明显短于 (b)
- [ ] 正确译法标签是 `Correct ✓` 而非 GT
- [ ] 图中不出现 7/19 或 "error paradigms mined" 类自指数字
- [ ] 公式正确：`Or(green = white − 1, green = white + 1)` 与 `green = white − 1`
- [ ] 三条跨条带箭头齐全且不穿过内容：(a)→(b) 虚线、(a)→(c) Round 1、(b)→(c) Round 2
- [ ] 前后对照数字块红→绿方向正确（4.2→2.1、41.3%→12.4%）
- [ ] 无渐变、无阴影、白底；导出 SVG/PDF 矢量（位图则 ≥300 dpi 并考虑 TikZ 重绘）

## 8. 数字复核与待办（camera-ready 前）

- [ ] 停滞率 41.3% → 12.4%（`tab:repair-results`，最终实验后复核）
- [ ] 修复轮数 4.2 → 2.1（`tab:main-results` 4.21/2.14，复核）
- [ ] **待办**：从 baseline 失败日志统计"含方向/对称翻转错误的失败题目占比"，作为 (a) 右侧标注的中性数字补入（替代已撤掉的 7/19）
- [ ] Puzzle 编号 #12/#47/#83 为示意，若与正文案例研究题号不一致需统一

## 9. 回退方案

若 Gemini 产出质量不达标（文字乱码、重复元素不一致、两条时间轴风格不统一），改用 TikZ 手绘：(b)(c) 共用同一组节点/徽章样式宏定义，天然保证视觉一致；预计工作量约半天。
