# fig:framework 框架图完整设计规格（v2）

> P0-2 条目的细化产物。目标：§3.2 跨双栏 `figure*`，替换现有 TikZ 图 1，吸收图 2 内容。
> 交付方式：本文档末尾附可直接发给 Gemini 的英文 prompt。
> 与 `fig_motivation_spec.md` 共用视觉语言（扁平矢量、Okabe–Ito、绿=已验证/成功、朱红=错误/UNSAT、橙=检测/强调）。
> **v2 变更**：v1 产出（`fig_framework.png` 第一版）布局与文字全部正确，但视觉单调——全是白底描边矩形+纯文字。v2 升级为 **illustrated technical** 风格：模块加线条图标与微型可视化、软色块填充、曲线箭头；并新增 §6b "基于现图重绘"短 prompt。

---

## 0. 已定决策（对应 P0-2 四个待细化点 + v2 风格决策）

| 决策点 | 结论 | 理由 |
|---|---|---|
| 泳道布局 | **横向双泳道**：上窄（离线 ~30% 高）下宽（在线 ~70% 高），流程一律从左到右；在线泳道内部再分主循环行 + 修复分支行 | 双栏宽 7.0 in、高度预算 ~3.3 in，横向泳道天然匹配宽扁画幅；修复分支是主贡献，给在线泳道 2 倍高度 |
| L1–L4 呈现 | **嵌入框架图**：修复分支末端画 4 级阶梯（staircase），每级只标"动作 + 代价"一行；触发路径用"检测器 → 阶梯"的橙色箭头表达 | 阶梯形状自带"渐进升级"语义，比独立小图省一个浮动体；**联动结论：P2-6 表取消**，各级触发条件从 `guided_solver.py` 核实后写进 §4.4 正文（遗留待办见 §8） |
| 微型示例 | **放 3 个，全部复用贯穿案例**：① 在线入口的 NL 约束标签（绿房/白房，与动机图同一句）；② 范式库下方的范式卡片（链式位置传播，吸收图 2 左半）；③ 修复记忆旁的修复记录卡（SEMANTIC_FLIP，吸收图 2 右半） | 图 2 独立浮动体取消（P1-5），内容不丢；三个示例分别锚定"输入—离线产物—在线产物"，且与 fig:motivation 用同一道谜题形成全文贯穿 |
| 数字标注 | **保留 3 个架构事实类数字**：`≈40:1 compression`（入库箭头）、`budget R = 5`（修复区标题）、`≤1×`（L4）；**不放** τ_snd/τ_p/τ_stag 等阈值数值 | 40:1 与 R=5 是框架属性、caption 已有；阈值属于实现细节，图内只写符号（如 `J ≥ τ_stag`） |
| **视觉风格（v2 新增）** | **illustrated technical**：每模块带 2.5px 线条图标 + 部分模块内嵌微型可视化（聚类散点、三层漏斗、迷你时间轴等）；软色块填充取代白底描边；曲线贝塞尔箭头取代直角折线 | v1 产出信息正确但"全是方框和文字"，不符合顶会 overview figure 惯例；微型可视化让每个模块"自己解释自己"，是 NeurIPS/ICML 高质量框架图的共同特征 |

---

## 1. 整体版式与风格

- **画幅**：跨双栏（AAAI `figure*` 7.0 in 宽），建议画布 **2100×980 px**（宽:高 ≈ 2.14:1，印刷约 7.0×3.3 in）。
- **结构**：两条横向泳道（同 v1）：
  - 上泳道（~30% 高）：**Offline: paradigm distillation**。
  - 下泳道（~70% 高）：**Online: guided inference & repair**，内部分主循环行 + 修复分支行。
- **跨泳道箭头仅 2 条**：范式库 ↓ 检索框（绿，`inject as suggestions`）；修复记忆 ↑ 三重筛选（绿虚线，`experience write-back`）。
- **v2 风格三要素**：
  1. **模块 = 软色块 + 图标 + 标题 + 副标签**：圆角 ~14px，无描边或极细描边，靠填充色区分泳道归属；标题左侧放单色线条图标（2.5px 描边，约 30×30px，简笔风格，禁 emoji/剪贴画）。
  2. **微型可视化**：约半数模块内嵌一个火柴盒大小的示意图（见 §2–§4 各表"图标/微型可视化"列），让读者不读字也能猜到模块干什么。
  3. **曲线箭头**：贝塞尔平滑曲线，源端小实心圆点、末端干净箭头；主流程 2.5px，次要 1.5px；语义配色（绿=成功流、朱红=错误流、橙=升级流、深灰=中性流）。
- **配色**（色盲安全，与 fig:motivation 一致并扩展）：
  - 离线泳道底色：极浅蓝 `#EAF4FB`；离线模块填充 `#DCEBF7`，图标深蓝 `#0072B2`
  - 在线主循环模块填充 `#E9F3EE`，图标蓝绿 `#009E73`；修复子区域底色 `#FBEFE9`，修复模块填充 `#FAE3D6`，图标朱红 `#D55E00`
  - 记忆/已验证/成功：蓝绿 `#009E73`；错误/UNSAT：朱红 `#D55E00`；检测/强调：橙 `#E69F00`
  - 中性：深灰 `#333333` 文字，浅灰 `#F2F2F2` 徽章/示例卡底
- **字体**：无衬线（Helvetica/Arial）标签，等宽（Courier/Menlo）代码、约束与卡片内容；缩放到 7.0 in 后最小字号 ≥ 6.5 pt。
- **风格底线**：扁平矢量、白底、无渐变无阴影无 3D、无照片级元素；图标全部为统一笔触的单色线条画。
- **图内语言**：全英文。

---

## 2. 上泳道：Offline paradigm distillation

流程框 5 个 + 库 1 个，从左到右。新增"图标/微型可视化"列：

| # | 主标签 | 副标签 | 图标/微型可视化 |
|---|---|---|---|
| 1 | `Training puzzles` | `with gold answers` | 图标：三张堆叠卡片；微型：3×3 小网格，几格涂色，旁一枚小 ✓ |
| 2 | `Trajectory collection` | `r = 3 samples, keep SAT ∧ correct` | 微型：迷你水平时间轴 4 个小节点，3 绿 ✓ 1 灰，末端小字 `SAT ✓` |
| 3 | `KDP identification & clustering` | `conditions A–D · hierarchical clustering` | 微型：约 12 个散点分成 3 个虚线圈聚类（蓝/青/灰），每簇 1 个星标关键点 |
| 4 | `LLM abstraction` | `cluster → candidate paradigm` | 微型：三个小点用细线汇聚成一张小卡片；图标：sparkle |
| 5 | `Triple filtering (Z3)` | `soundness · effect · trigger precision` | 微型：**三层筛网漏斗**，顶部落入 5 张小卡，底部漏出 2 张绿卡，3 张红卡带小 ✗ 被弹到侧面 |
| 6 | `Paradigm library 𝓛` | | 图标：绿色数据库圆柱 + 扇形展开的 3 张绿卡 |

- 5 → 6 的箭头上方徽章：**`≈ 40:1 compression`**（浅灰底徽章）。
- 微型示例 ②：范式卡片挂在库正下方（内容同 v1，等宽字体，标题行蓝绿）：

```
Chain position propagation
Q:    direct_position + relative_offset
O:    pos(B) ← pos(A) + d
pre:  1 ≤ pos(A) + d ≤ n
post: Z3-SAT(pos(B) = pos(A) + d)
soundness 0.94
```

---

## 3. 下泳道行 1：Online 主循环

| # | 主标签 | 副标签/细节 | 图标/微型可视化 |
|---|---|---|---|
| 1 | `New puzzle` | 下挂微型示例 ①：NL 标签 `"The green house is immediately to the left of the white house."` | 图标：带问号的拼图块 |
| 2 | `Retrieve by signature σ(S_t)` | `+ Z3 consistency pre-check`；接收库的绿色下行箭头 `inject as suggestions` | 图标：磁铁吸附两张小卡片 |
| 3 | `LLM guided inference` | | 图标：芯片/大脑，侧面插着一张小卡（表示范式建议已注入） |
| 4 | `Z3 verify` | `assert_and_track` | 图标：盾牌内嵌齿轮，标 `Z3`；框缘两枚小戳记：绿 ✓ / 红 ✗ |
| 5 | `Answer ✓` | 蓝绿实心终点框 | 微型：全部涂色的已解 3×3 小网格 + 大 ✓ |

- **SAT 出口**：框 4 上沿绿曲线回环到框 3，标签 `SAT: update domains, push checkpoint`；绿短箭头 4 → 5，标签 `SAT ∧ complete`。
- **UNSAT 出口**：框 4 下沿朱红粗曲线（3px）落入行 2，标签 `UNSAT`。

---

## 4. 下泳道行 2：修复分支（画细，主贡献）

子区域底色 `#FBEFE9`、朱红细描边，左上角标题：**`Repair loop (budget R = 5)`**，标题旁小扳手图标。

| # | 节点 | 细节 | 图标/微型可视化 |
|---|---|---|---|
| a | `UNSAT core extraction` | 下挂徽章 `core = {c7, c2}` | 微型：镊子从一排灰色小方片中夹出 2 片红色小方片（标 `c7` `c2`）——图标即语义 |
| b | `Attribution: a_t ∈ core?` | 菱形判定；出边 `yes → retract current inference` / `no → mark historical constraint as target` | 图标：分叉箭头 |
| c | `Typed repair memory 𝓜` | 蓝绿描边强调；下挂微型示例 ③ | 图标：带彩色索引标签的账本/笔记本 |
| d | `Stagnation / Loop detection` | 内两行等宽小字：`Jaccard(U_i, U_j) ≥ τ_stag`、`cos(α_new, α_hist) ≥ τ_loop` | 图标：雷达仪表盘 + 带斜杠的循环箭头 |
| e | **L1–L4 阶梯** | 4 级上升台阶，一条小箭头沿台阶向上爬；颜色 L1 浅橙 → L4 朱红 | 台阶本体即可视化：<br>`L1 switch target · O(1)`<br>`L2 switch repair type · O(m)`<br>`L3 rollback checkpoint · O(n)`<br>`L4 re-translate all · O(T) · ≤1×` |

- d → e 橙色曲线箭头，标签 `escalate`。
- e 顶部深灰曲线箭头回到行 1 `LLM guided inference`，标签 `repair action`。
- c 引出**绿色虚线**沿画布右缘向上接入 `Triple filtering (Z3)`，标签 `experience write-back: successful repairs → paradigm candidates`；贴边走线，不穿内容。
- 微型示例 ③：修复记录卡（同 v1）：

```
Repair record R_t
e:  SEMANTIC_FLIP
U:  {c7, c2}   fp: SHA-256(U)
α:  (switch_type, c7, re-translate direction)
o:  SAT ✓
```

---

## 5. Caption 文案

### 中文版（当前中文稿用）

> 图 X：\PRISM 框架总览。\textbf{离线泳道}（上）：成功求解轨迹经 KDP 识别（条件 A--D）、跨轨迹聚类、LLM 抽象与 \zthree 三重筛选（一致性、效果、触发精度）提炼为范式库（约 40:1 压缩）。\textbf{在线泳道}（下）：新谜题按约束类型签名检索范式，经一致性预检后以建议式注入引导 LLM 推断，\zthree 逐步验证；返回 \unsat 时进入修复循环——提取 UNSAT core 并归因（区分当前推断与历史翻译错误），记录至类型化修复记忆，当 Jaccard 停滞检测或余弦循环检测触发时沿 L1--L4 阶梯升级干预（切换目标 → 切换类型 → 回退检查点 → 全量重译）。成功修复经验回写离线筛选流程，形成闭环。

### 英文版（AAAI 终稿用）

> Figure X: Overview of \PRISM. \textbf{Offline lane} (top): successful solving trajectories are distilled into a paradigm library via KDP identification (conditions A--D), cross-trajectory clustering, LLM abstraction, and Z3 triple filtering (soundness, effect, trigger precision), at a $\approx$40:1 compression ratio. \textbf{Online lane} (bottom): for a new puzzle, paradigms retrieved by constraint-type signature pass a Z3 consistency pre-check and are injected as suggestions to guide LLM inference, with each step verified by Z3. On \unsat, the repair loop extracts the UNSAT core, attributes the contradiction (current inference vs.\ historical translation), and logs a typed repair record; when Jaccard-based stagnation or cosine-based loop detection fires, the system escalates along the L1--L4 ladder (switch target $\to$ switch repair type $\to$ rollback checkpoint $\to$ full re-translation). Successful repairs are written back to the offline filtering pipeline, closing the loop.

---

## 6. 交给 Gemini 的 Prompt（v2 全量重绘，直接复制使用）

```
Create a richly illustrated, flat vector-style academic system-overview figure for a double-column AAAI paper, in the visual tradition of the best NeurIPS/ICML framework figures: NOT a plain flowchart of outlined rectangles, but soft color-filled modules, each with a small meaningful line-art icon and, where specified, a tiny schematic mini-visualization inside. White background, no gradients, no shadows, no 3D, no emoji, no clip art. Canvas 2100x980 px (width:height ≈ 2.14:1). Sans-serif font (Helvetica-like) for labels, monospace font for all code, constraints, and example cards. All text in English.

GLOBAL STYLE RULES:
- Modules are rounded rectangles (corner radius ~14px) with SOFT COLOR FILLS and no visible border (or a hairline border at most). Never plain white boxes.
- Every module has: a single-color line-art icon (uniform 2.5px stroke, ~30x30px, minimal and geometric) at the top-left or left of its title, a bold title, and a smaller gray sub-label.
- Mini-visualizations (specified per module below) are matchbox-sized schematic drawings INSIDE the module, drawn in the same 2px line-art style with small color accents. They are the key to making the figure feel alive.
- Arrows are SMOOTH CURVED bezier paths (never right-angle elbows), with a small filled dot at the source and a clean arrowhead at the target. Primary flows 2.5px, secondary 1.5px. Arrow colors carry meaning: bluish-green #009E73 for success/verified flows, vermilion #D55E00 for error flows, orange #E69F00 for escalation, dark gray #333333 for neutral flows.
- Color palette (colorblind-safe): deep blue #0072B2 (offline icons), bluish-green #009E73 (memory/verified/success), vermilion #D55E00 (errors/UNSAT), orange #E69F00 (detection/emphasis), dark gray #333333 (text), light gray #F2F2F2 (badges/example cards). Lane backgrounds: very light blue #EAF4FB (top lane), very light gray #F7F7F5 (bottom lane), very light vermilion #FBEFE9 (repair sub-region). Module fills: #DCEBF7 (offline modules), #E9F3EE (online main-loop modules), #FAE3D6 (repair modules).

The figure has TWO horizontal swim lanes, each with a vertical title along its far left edge.

TOP LANE — "Offline: paradigm distillation", ~30% of canvas height, background #EAF4FB.
A left-to-right pipeline of six modules (fill #DCEBF7, icons in deep blue #0072B2) connected by curved dark-gray arrows:
  1. "Training puzzles" / sub-label "with gold answers". Icon: three stacked cards. Mini-viz: a tiny 3x3 grid with a few colored cells and a small green check beside it.
  2. "Trajectory collection" / "r = 3 samples, keep SAT ∧ correct". Mini-viz: a miniature horizontal timeline of 4 small nodes — three with green checks, one gray — ending in tiny text "SAT ✓".
  3. "KDP identification & clustering" / "conditions A–D · hierarchical clustering". Mini-viz: about 12 scattered dots grouped into 3 dashed-outline clusters (blue, teal, gray), with one starred key dot per cluster.
  4. "LLM abstraction" / "cluster → candidate paradigm". Icon: a sparkle. Mini-viz: three small dots converging via thin lines into one small card.
  5. "Triple filtering (Z3)" / "soundness · effect · trigger precision". Mini-viz: a FUNNEL with three sieve layers; five tiny cards drop in at the top, two green cards exit at the bottom, three red cards with tiny crosses are deflected to the side.
  6. "Paradigm library 𝓛". Icon: a green database cylinder with three green cards fanning out of it. Give this module a slightly stronger bluish-green presence — it is the offline lane's product.
On the arrow from module 5 to module 6, a small light-gray badge: "≈ 40:1 compression".
Hanging below module 6, connected by a thin line, a light-gray monospace example card with a bluish-green title line and a tiny corner tag "paradigm":
  "Chain position propagation"
  "Q:    direct_position + relative_offset"
  "O:    pos(B) ← pos(A) + d"
  "pre:  1 ≤ pos(A) + d ≤ n"
  "post: Z3-SAT(pos(B) = pos(A) + d)"
  "soundness 0.94"

BOTTOM LANE — "Online: guided inference & repair", ~70% of canvas height, background #F7F7F5, with TWO internal rows.

ROW 1 (main loop, upper part of the lane), modules filled #E9F3EE with bluish-green icons, left to right:
  1. "New puzzle". Icon: a puzzle piece with a question mark. Hanging below: a small monospace tag "The green house is immediately to the left of the white house."
  2. "Retrieve by signature σ(S_t)" / sub-label "+ Z3 consistency pre-check". Icon: a magnet attracting two small cards.
  3. "LLM guided inference". Icon: a chip/brain outline with a small card plugged into its side (the injected paradigm suggestion).
  4. "Z3 verify" / sub-label "assert_and_track". Icon: a shield containing a gear, labeled "Z3". At the module's edge, two tiny stamp marks: a green check and a red cross.
  5. "Answer ✓" — a solid bluish-green terminal module with white text at the far right. Mini-viz: a fully colored solved 3x3 grid with a large white check.
A bluish-green curved arrow comes DOWN from "Paradigm library 𝓛" in the top lane into module 2, labeled "inject as suggestions".
From module 4, a bluish-green curved arrow loops back over the row into module 3, labeled "SAT: update domains, push checkpoint". A short bluish-green arrow from module 4 to module 5 labeled "SAT ∧ complete". A THICK (3px) vermilion curved arrow sweeps down from module 4 into row 2, labeled "UNSAT".

ROW 2 (repair branch): a rounded sub-region filled #FBEFE9 with a hairline vermilion border; title at its top-left: "Repair loop (budget R = 5)" with a small wrench icon. Modules inside filled #FAE3D6 with vermilion icons, left to right:
  a. "UNSAT core extraction". Mini-viz INSIDE the module: tweezers picking two red chips labeled "c7" and "c2" out of a row of gray chips. Hanging below: a light-gray badge in vermilion monospace "core = {c7, c2}".
  b. A diamond "Attribution: a_t ∈ core?" with two short labeled exits in small text: "yes → retract current inference" and "no → mark historical constraint as target"; both exits merge and continue right.
  c. "Typed repair memory 𝓜" — bluish-green accent (it is a memory component). Icon: a ledger/notebook with small colored index tabs. Hanging below, a light-gray monospace example card with a bluish-green title line and a tiny corner tag "repair record":
     "Repair record R_t"
     "e:  SEMANTIC_FLIP"
     "U:  {c7, c2}   fp: SHA-256(U)"
     "α:  (switch_type, c7, re-translate direction)"
     "o:  SAT ✓"
  d. "Stagnation / Loop detection" — orange accent. Icon: a radar gauge plus a looping arrow with a slash through it. Two monospace lines inside: "Jaccard(U_i, U_j) ≥ τ_stag" and "cos(α_new, α_hist) ≥ τ_loop".
  e. A four-step ascending STAIRCASE drawn as actual stairs (each step a rounded slab, colors grading from light orange at the bottom step to vermilion at the top step), with a small arrow climbing up along the steps. One label per step, bottom to top:
     "L1 switch target · O(1)"
     "L2 switch repair type · O(m)"
     "L3 rollback checkpoint · O(n)"
     "L4 re-translate all · O(T) · ≤1×"
An orange curved arrow from module d to the staircase labeled "escalate". From the top of the staircase, a dark-gray curved arrow rises back into "LLM guided inference" in row 1, labeled "repair action". From module c, a DASHED bluish-green curve runs along the right edge of the canvas UP into "Triple filtering (Z3)" in the top lane, labeled "experience write-back: successful repairs → paradigm candidates" — routed along the edge, never across other content.

CONSTRAINTS: Spell every label EXACTLY as written above, including σ(S_t), a_t, 𝓛, 𝓜, τ_stag, τ_loop and the symbols ∧, ←, ≤, ≥, ≈, →, ✓. Keep the two example cards and the core badge letter-for-letter as specified. All icons share one consistent line-art style — if an icon cannot be drawn cleanly, omit it rather than substituting clip art or emoji. Only two arrows may cross between lanes (library→retrieve, memory→filtering). Generous white space; text legible when scaled to 7.0 inches wide (minimum font ≈ 6.5 pt). Flat vector style only.
```

## 6b. 备选：基于现图重绘的短 Prompt（把 `fig_framework.png` 一并发给 Gemini）

> 现图布局、文字、箭头拓扑已全部正确，只需风格化重绘。图生图方式保真度更高，建议优先尝试；若 Gemini 借机改坏了布局或文字，再退回 §6 全量 prompt。

```
Redraw this exact academic system diagram with the SAME layout, the SAME two swim lanes, the SAME boxes in the SAME positions, and EVERY text label letter-for-letter identical — but upgrade the visual style from a plain flowchart to a richly illustrated NeurIPS/ICML-quality overview figure:
1. Replace all white outlined boxes with soft color-filled rounded modules (no borders): fill #DCEBF7 for the top-lane modules, #E9F3EE for the bottom main-row modules, #FAE3D6 for the modules inside the repair region.
2. Add a small single-color line-art icon (uniform 2.5px stroke, ~30px, minimal geometric style, NO emoji, NO clip art) beside each module title: stacked cards (Training puzzles), a mini timeline with green checks (Trajectory collection), clustered dots in dashed circles (KDP identification & clustering), a sparkle (LLM abstraction), a three-layer funnel with cards passing/rejected (Triple filtering), a green database cylinder with fanned cards (Paradigm library), a puzzle piece with a question mark (New puzzle), a magnet attracting cards (Retrieve), a chip with a small card plugged in (LLM guided inference), a shield with a gear (Z3 verify), a solved colored mini-grid (Answer), tweezers picking two red chips from gray chips (UNSAT core extraction), a fork arrow (Attribution), a ledger with colored tabs (Typed repair memory), a radar gauge with a slashed loop arrow (Stagnation / Loop detection).
3. Redraw the L1–L4 stack as an actual ascending STAIRCASE with a small arrow climbing the steps, colors grading light orange (L1) to vermilion (L4).
4. Replace all right-angle elbow arrows with smooth curved bezier paths, small filled dot at the source, clean arrowhead at the target; keep the existing arrow colors and labels.
5. Keep the two gray monospace example cards and the "core = {c7, c2}" badge exactly as they are.
Flat vector style, white background, no gradients, no shadows, no 3D. Colorblind-safe palette unchanged: #0072B2, #009E73, #D55E00, #E69F00, #333333.
```

---

## 7. 验收清单（拿到 Gemini 产出后逐项检查）

- [ ] 缩放到 7.0 in 宽后所有文字可读（重点：两张示例卡、检测器框内公式、阶梯标签）
- [ ] 双泳道结构清晰，泳道标题在左缘；在线泳道明显高于离线泳道
- [ ] **v2 风格落地**：模块为软色块填充（无白底描边框）；每模块有统一笔触的线条图标；至少 5 处微型可视化（网格、时间轴、聚类散点、漏斗、镊子夹片）清晰可辨
- [ ] **图标风格统一**：全部单色线条画、笔触粗细一致；无 emoji、无剪贴画、无 3D 图标混入
- [ ] 箭头为平滑曲线（无直角折线），源端圆点、末端箭头，语义配色正确
- [ ] 离线流程 6 框顺序与拼写正确，`≈ 40:1 compression` 徽章在 5→6 箭头上
- [ ] Z3 verify 三个出口齐全且颜色正确：绿回环（SAT）、绿短箭头（complete）、朱红粗箭头（UNSAT）
- [ ] 修复子区域含 5 个节点，归因菱形的 yes/no 两出边标注正确
- [ ] `core = {c7, c2}` 徽章与动机图 (b) 逐字一致（贯穿案例呼应）
- [ ] L1–L4 画成真实台阶且有爬升小箭头，4 级自下而上、颜色渐进，`≤1×` 只出现在 L4
- [ ] 跨泳道箭头恰好 2 条且贴边走线：库→检索（绿实线）、记忆→筛选（绿虚线）
- [ ] 图中不出现 τ 阈值数值、准确率等实验结果数字（只允许 40:1、R=5、r=3、≤1×、0.94）
- [ ] 公式/符号无乱码：σ(S_t)、a_t、𝓛、𝓜、τ_stag、τ_loop、∧、←（若花体 𝓛𝓜 渲染失败，可接受退化为 L、M）
- [ ] 无渐变、无阴影、白底；导出 SVG/PDF 矢量（位图则 ≥300 dpi）

## 8. 遗留待办

- [ ] 从 `prism/online/guided_solver.py` 核实 L1–L4 各级确切触发条件，补写进 §4.4 正文（P2-6 表已决定取消，触发规则必须在正文交代）
- [ ] 正文改动：图 2（`fig:example`）独立浮动体删除，caption 中相应引用指向本图的两张示例卡（P1-5）
- [ ] TikZ 现图 1 替换后，caption 换用本规格 §5 文案
- [ ] 若最终 fig:motivation 的贯穿案例谜题/约束句有改动，同步更新本图的 NL 标签与 `core = {c7, c2}` 徽章
- [ ] v2 定稿后，评估是否需要把 fig:motivation 也补图标（保持两图风格密度一致）

## 9. 回退方案

若 Gemini 产出质量不达标（泳道结构混乱、示例卡文字乱码、图标风格杂乱、阶梯画成流程框），降级路径：
1. 先试 §6b 图生图（以 v1 产出为底，只做风格化）；
2. 仍不行则接受 v1 版式，仅用 §6b 中的第 1、4 条（色块填充 + 曲线箭头）做最小风格升级；
3. 最终回退 TikZ 手绘：双泳道用两个 `fit` 背景层，图标用 `fontawesome5` 宏包近似；预计工作量约一天。
