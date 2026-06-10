# PRISM 方案深度审查报告
> 论文组织 · 审稿人问题预测 · 范围重新定标

---

## 一、论文组织安排（逐节分析）

目标期刊：**ACL / EMNLP Long Paper**（正文 8 页 + 无限附录）

### §1 Introduction（~1.0 页）✓ 可行

**段落结构：**

- **Para 1** — LLM 在 CSP 上的系统性失败。引用 ZebraLogic 的数据：精度随约束数/规模急剧下降，即使最强的 frontier model 在 6×6 谜题上也低于 40%。
- **Para 2** — 现有两条路线各自的局限：神经符号方法（Logic-LM 系列）在翻译错误修复上停滞；Agent 记忆方法（ExpeL/ReasoningBank）记忆单元无形式验证，无法用于推理密集型任务。
- **Para 3** — 核心 insight：CSP 轨迹每一步都可被 Z3 形式验证——这是两条线融合的关键前提，也是与所有已有工作的根本区别。
- **Para 4** — PRISM 概述（两句话）：离线从轨迹提炼 solver-verified 范式；在线用范式引导推理 + 修复记忆防止停滞。
- **Para 5** — 实验结果一句话摘要 + 四条贡献列表。

> ⚠️ **关键要求**：Introduction 必须在贡献点中明确回答「为什么不直接用 few-shot」——用「verified + compressed + selective」三个词概括范式的优势，否则审稿人第一个问题就会击中你。

---

### §2 Background & Related Work（~1.5 页）✓ 可行

**§2.1 Neuro-Symbolic Reasoning**（0.5 页）

覆盖 Logic-LM / LINC / SAT-LM / Logic-LM++ / VERGE，重点不是介绍背景，而是明确指出三个共同局限：
1. 每道题独立求解，经验清零
2. 错误反馈粒度粗（原始报错字符串），未区分错误类型
3. 修复迭代停滞问题有记录但无解决方案

**§2.2 Agent Memory & Experience**（0.5 页）

覆盖 Reflexion / ExpeL / ReasoningBank / ProcMEM / ERL，重点对比：

| 工作 | 记忆单元 | 可验证？ | 域 |
|------|---------|---------|-----|
| Reflexion | 自由文本反思 | ✗ | 通用任务 |
| ExpeL | 自由文本 insight | ✗ | Web/ALF |
| ReasoningBank | 结构化策略 | ✗ | Web/SWE |
| **PRISM（本工作）** | **结构化范式** | **✓ Z3 验证** | **CSP** |

**§2.3 CSP Benchmarks**（0.5 页）

引用 ZebraLogic 和 GridPuzzle 的错误分析结论：「wrong reasoning step」和「elimination error」是主要失败原因，这是你研究 CSP 特定策略的实证基础，也证明 CSP 领域需要专门的经验积累机制。

---

### §3 Preliminaries（~0.5 页）✓ 可行

- 正式定义 CSP（变量、域、约束集、可行解）
- Zebra Puzzle 的形式化表示（作为 CSP 实例）
- Solving Trajectory 的符号定义：$\mathcal{T} = \langle (S_0, a_1, S_1), \ldots, (S_{T-1}, a_T, S_T) \rangle$
- Z3 的角色：SAT/UNSAT oracle + UNSAT core 提取（一句话说明 `assert_and_track` 的原理）

---

### §4 PRISM Framework（~3.0 页）⚠️ 较复杂，需精心组织

**§4.1 Overview**（0.3 页）

一张精心设计的系统图（必须是论文的 Figure 1，读者通过图就能理解主体流程），加两句话说明离线/在线分工。

**§4.2 Solving Paradigm Representation**（0.4 页）

定义四元组结构，给出一个完整的具体示例（P2 链式传播），展示触发条件 → 推断操作 → Z3 前后条件的完整格式。这是让审稿人「看到」范式是什么的关键。

**§4.3 Offline: Paradigm Distillation**（0.8 页）

用**流程图 + 关键算法伪代码**表达，不要平铺五步的文字描述：

```
Algorithm 1: Paradigm Distillation
Input:  Puzzle generator G, LLM M, Z3 solver S
Output: Paradigm Library L

1. Collect trajectories T = {T_i} using M+S on N puzzles from G
   (temperature=0.7, 3 runs per puzzle for diversity)
2. For each T_i, identify KDPs via:
   (A) domain size drops by ≥2 for some variable, OR
   (B) step_type ∈ {CHAIN, CONTRADICTION}
3. Cluster KDPs by constraint-type feature vector
   (agglomerative, cosine distance, threshold θ)
4. For each cluster C_k with support ≥ m:
   a. Sample up to 10 representative KDPs
   b. Prompt M to abstract paradigm P̂_k
   c. Verify P̂_k: soundness/effect/trigger precision
   d. If all checks pass: add P̂_k to L
Return L
```

> ⚠️ **页面压缩建议**：KDP 的详细识别条件、聚类特征向量的完整定义、Z3 三重验证的具体检验方法——这三部分移到附录。正文只保留核心逻辑。

**§4.4 Online: Paradigm-Guided Inference**（0.8 页）

重点写清楚两个关键设计：

1. **两层检索**：Layer 1（约束类型集合匹配，O(1)）→ Layer 2（LLM 语义判断，仅对 Layer 1 通过的候选）
2. **注入前一致性预检**：每个候选范式的推断都经过实时 Z3 检验，矛盾的不注入——这是防止范式误导 LLM 的第二道防线
3. **UNSAT 归因**：区分「新推断导致的 UNSAT」vs「已有翻译错误导致的 UNSAT」（通过检查新推断是否在 UNSAT core 中）

**§4.5 Repair Trajectory Memory**（0.7 页）

用一张 Table 呈现四级策略切换，节省文字描述空间：

| 级别 | 触发条件 | 响应动作 |
|------|---------|---------|
| L1 | 停滞检测触发（Jaccard ≥ τ_s） | 切换 UNSAT core 中的目标约束 |
| L2 | L1 后连续 2 次仍 UNSAT | 切换修复类型（relax→retranslate）|
| L3 | 循环检测触发（cosine ≥ τ_l） | 回退到最近 SAT 检查点 |
| L4 | 无可用检查点 / L3 失败 | 全量重新翻译（blank-slate） |

停滞检测公式（修正后版本）：

$$J_{\min} = \min_{i \neq j \in \{t-k,\ldots,t\}} \frac{|U_i \cap U_j|}{|U_i \cup U_j|} \geq \tau_s$$

---

### §5 Experiments（~2.5 页）⚠️ 最关键

**五个研究问题（RQ）：**

| RQ | 问题 | 对应实验 |
|----|------|---------|
| RQ1 | PRISM 整体性能优于所有基线？ | 主结果表（各规模谜题准确率） |
| RQ2 | 修复记忆是否减少停滞？ | 平均修复轮数、停滞率、LLM 调用次数 |
| RQ3 | 范式库质量如何？ | 覆盖率、置信度分布、触发频率 top-10 |
| RQ4 | 各模块独立贡献？ | 消融实验（移除 Paradigm / Memory / 策略切换） |
| RQ5 | 范式能跨规模迁移？ | L1 泛化（小谜题→大谜题），可选 L2 |

**基线设置（8 条，必须包含）：**

```
1. Plain LLM          — 纯 CoT，无符号求解器
2. Paper-1            — 你的论文一（LLM+Z3，无任何记忆）★最重要基线
3. Logic-LM           — 引用官方 ZebraLogic 报告数字
4. ExpeL-CSP          — ExpeL 适配到 CSP 域（同等轨迹，无 Z3 验证）
5. Verified Few-Shot  — Z3 验证过的步骤直接注入（无压缩，无抽象）
6. PRISM w/o Memory   — 只有范式库，无修复记忆
7. PRISM w/o Paradigm — 只有修复记忆，无范式库
8. PRISM Full         — 完整系统
```

> 📌 **ExpeL-CSP** 实现需要约 1 周额外工作，但对审稿人来说是「必要的公平对比」。如果时间紧，可降为优先级次高，在 Limitations 中说明「ExpeL-CSP 的完整实现作为 future work」。

**主结果表结构示例：**

| System | 3×4 | 4×5 | 5×5 | 5×6 | 6×6 | Avg LLM Calls | Avg Repair Rounds |
|--------|-----|-----|-----|-----|-----|--------------|------------------|
| Plain LLM | - | - | - | - | - | - | - |
| Paper-1 | - | - | - | - | - | - | - |
| Logic-LM | - | - | - | - | - | - | - |
| Verified FS | - | - | - | - | - | - | - |
| ExpeL-CSP | - | - | - | - | - | - | - |
| PRISM w/o Mem | - | - | - | - | - | - | - |
| PRISM w/o Par | - | - | - | - | - | - | - |
| **PRISM Full** | - | - | - | - | - | - | - |

---

### §6 Analysis（~1.0 页）✓ 可行

**§6.1 案例研究**：选一道 5×5 谜题，完整展示：
- 范式 P2 被触发的时刻（展示触发条件匹配 + 推断被 Z3 验证）
- 修复记忆在第 3 次循环时阻断重复修复的时刻
- 策略切换从 L1 升级到 L2 的过程

这是论文中最有说服力的定性证据，读者看完后应该「哦，原来是这样工作的」。

**§6.2 范式质量分析**：
- 置信度分布直方图（说明大多数范式置信度 ≥0.90）
- 触发频率 top-5 范式列表（说明哪些范式最常用）
- 范式覆盖率：有多少比例的 KDP 被库中某个范式覆盖

**§6.3 错误类型分析**：
- 修复记忆中各 ErrorType 的分布饼图
- 「停滞检测触发前后各类错误的修复成功率」对比

---

### §7 Conclusion + Limitations（~0.5 页）✓ 可行

**Limitations 必须诚实写出（审稿人会看）：**
1. 范式库与 CSP 域强耦合，新域需要重新运行离线阶段
2. 聚类阈值和停滞检测阈值需要在 dev set 上调优
3. L2 跨域迁移（Zebra → Knights-Knaves）是初步探索，尚无结论性结果
4. 范式抽象步骤依赖 LLM，引入不确定性（由 Z3 验证部分补偿）

**Future Work 指向：**
- 结合 RLVR 对范式库做端到端微调
- 将验证轨迹作为 PRM 训练数据
- 跨域范式迁移的自动化机制

---

### 总页数预算检查

| 章节 | 预算 | 是否可控 |
|------|------|---------|
| §1 Introduction | 1.0 页 | ✓ |
| §2 Related Work | 1.2 页（压缩后） | ✓ |
| §3 Preliminaries | 0.5 页 | ✓ |
| §4 PRISM Framework | 2.5 页（部分移附录） | ⚠️ 需精简 |
| §5 Experiments | 2.5 页 | ⚠️ 需精简 |
| §6 Analysis | 1.0 页 | ✓ |
| §7 Conclusion | 0.5 页 | ✓ |
| **合计** | **≈ 9.2 页** | **压附录后 ≈ 8 页** |

**移入附录的内容：**
- KDP 详细识别算法（伪代码）
- 聚类特征向量完整定义
- Z3 三重验证的具体步骤
- 超参数敏感性实验（grid search 结果）
- 完整的范式库列表（所有 ~35 个范式）

---

## 二、审稿人问题预测与回应策略

### Q1：「为什么不直接把成功轨迹的步骤作 few-shot？范式提炼增加了额外成本，收益是否值得？」

**这是最高频的质疑，必须用实验直接回答。**

回应策略：
- 设计 **Verified Few-Shot** baseline（表格中第 5 条）：把经过 Z3 验证的成功轨迹步骤直接注入 prompt，与 PRISM 对比
- 预期结果：few-shot 在小谜题上接近 PRISM，但在大谜题（5×6, 6×6）上因 context 过长（O(N) 增长）而显著下降；PRISM 始终保持 O(K) 常数 context
- 论文中用一句话定量说明：「PRISM 从 1500 条轨迹提炼为 35 个范式，40:1 压缩比；在 6×6 谜题上 Verified Few-Shot 因 context 超限而降级，PRISM 无此问题」

---

### Q2：「范式的 Z3 验证只在 20 个随机样本上，soundness ≥90% 意味着 10% 情况下会给错建议——这会不会比没有范式更差？」

回应策略：

**两道防线的设计保证安全性：**

1. **离线防线**：增大验证样本量到 50（成本可接受，Z3 极快），并加入 trigger precision 检验防止过度触发
2. **在线防线**：注入前的一致性预检（每个候选范式的推断实时经 Z3 验证），矛盾的直接过滤——这道防线保证「注入给 LLM 的范式建议绝对与当前约束不矛盾」

**消融实验设计**：
- `PRISM w/o online-check`（去掉在线一致性预检）对比 `PRISM full`
- `PRISM w/o Z3-verify`（离线不做验证，直接存入所有提炼的范式）对比 `PRISM full`
- 证明两道防线各有独立贡献

---

### Q3：「聚类阈值 θ=0.25 和停滞检测阈值 τ=0.75 如何确定？对超参数敏感吗？」

回应策略：

用 ZebraLogic dev set（10% 数据）做超参数搜索：
- θ ∈ {0.15, 0.20, 0.25, 0.30}
- τ_s ∈ {0.65, 0.70, 0.75, 0.80}
- τ_l ∈ {0.85, 0.90, 0.92, 0.95}

在附录中报告 9 格热力图，展示性能对超参数变化不敏感（预期结果：在合理范围内 ±1% 以内波动）。

正文一句话：「PRISM 对阈值超参数不敏感，在合理范围内性能变化 < 1%（详见附录）。」

---

### Q4：「只在 Zebra 谜题上实验。对新的 CSP 场景需要从零重新运行离线阶段吗？如果是，泛化性太弱。」

**这是最难完全回答的问题，需要诚实面对。**

回应策略（三层）：

1. **实验证据**：L2 实验测试 Zebra 范式在 Knights-Knaves 上的迁移率。即使只有 40-50% 的范式能迁移，这也证明「共享结构可以跨域」，是有意义的发现。
2. **正面论证**：离线阶段是一次性成本，可以分摊到该域所有未来任务上。类比：人类学数独需要一段时间掌握消去法，但掌握后每道题都受益。
3. **诚实的 Limitations**：在 §7 明确写出「域特定的离线阶段是当前局限，跨域自动范式迁移是未来工作方向」。

**不要过度主张跨域泛化——审稿人对这类主张非常警惕。**

---

### Q5：「论文三和论文一的增量贡献是否足够大？会不会被认为是工程扩展？」

回应策略：

**在 Introduction 第一段就说清楚本质区别：**

> 「论文一建立了静态的求解能力（static capability）——给一道谜题，输出一个解。论文三解决的是动态学习问题（dynamic learning）——Agent 如何从解谜经验中积累可迁移的推理策略，越解越好。这是从工具（tool）到 Agent 的本质跨越，而非性能优化。」

**实验数字是最强证明**：确保 PRISM 在困难谜题（5×5、6×6）上比 Paper-1 提升 ≥10%，且提升随难度增大——说明经验积累对困难场景价值最大，这是工程优化做不到的。

---

### Q6：「LLM 抽象范式时引入不确定性。Z3 验证真的能拦截所有错误范式吗？」

回应策略：

**诚实承认局限，但说明缓解机制：**

1. Z3 soundness 检验是充分不充要条件——确实可能有范式在 50 个测试样本上通过但在更多情况下失败
2. 在线一致性预检提供第二道防线：即使一个范式通过了离线验证，在线使用时如果其推断与当前约束矛盾，仍会被 Z3 实时拦截
3. 写回机制的质量保证：只有「在完整谜题求解成功后、经过完整 Z3 验证」的修复经验才能写回范式库，比离线提炼的范式有更强的实证支持
4. 长期使用中，低质量范式会因触发后 Z3 失败而逐渐降低 confidence score，最终被筛选出库

---

## 三、范围重新定标

### 核心主张（必须成立，所有实验设计围绕它）

> 「从 CSP 求解轨迹中提炼的 solver-verified 范式，结合类型化修复记忆，能够显著提升 LLM 在复杂 CSP 上的求解准确率并减少修复停滞。这种改进在同域不同规模的谜题上可以迁移。」

这个主张精确、可证伪、范围明确——是一个好的学术主张。

---

### 两个支撑性发现

**支撑性发现 1（第 1-3 周可出结果）**

修复记忆单独就能减少平均修复轮数 X%，且停滞检测准确率 ≥ Y%。这个结论不依赖范式库，可以直接在 Paper-1 的 pipeline 上加修复记忆模块跑出来。是整个论文最稳固的结论。

**支撑性发现 2（第 4-7 周可出结果）**

范式库的内容分析：提炼出的范式类型分布（P1/P2/P3 各占多少比例），置信度分布，以及「有范式覆盖的步骤」vs「无范式覆盖的步骤」的准确率对比——后者单独就能证明范式有效。

---

### 按风险排序的实验推进顺序

**Week 1-2：最低风险实验先跑**
- 在 Paper-1 pipeline 上直接加 RepairMemory 模块
- 跑 ZebraLogic 4×5 和 5×5，对比 Paper-1 基线
- 预期：修复轮数下降，这是最容易成功的实验

**Week 3-5：离线提炼 pipeline**
- 用生成器生成 500 道训练谜题（easy/medium/hard 各比例）
- 收集轨迹（temperature=0.7，每题 3 次），KDP 识别，聚类
- 第 5 周末目标：有第一版范式库（哪怕只有 10-15 个范式）

**Week 6-8：端到端集成与调优**
- 接通离线范式库和在线推理模块
- 在 ZebraLogic dev set 上迭代调参（θ, τ_s, τ_l）
- **关键节点**：第 8 周末如果 PRISM Full 比 Paper-1 提升 ≥5%，论文核心主张成立，后续实验都是锦上添花

**Week 9-10：完整实验**
- 跑全部 8 个基线（ExpeL-CSP 优先级次高）
- 消融实验（移除各模块）
- L1 泛化实验（3×4→6×6 跨规模）

**Week 11：可选实验**
- L2 跨域实验（Knights-Knaves）：仅在 L1 结果好时投入精力
- 超参数敏感性实验（附录）

**Week 12：写作收尾**

---

### MVP 的精确定义（4 个必须满足的条件）

满足以下全部 4 项 → ACL/EMNLP long paper 投稿充分，不需要 L2 实验也成立：

1. ✅ PRISM Full 在 ZebraLogic 4×5 和 5×5 上比 Paper-1 基线提升 **≥8%**
2. ✅ 修复停滞率（连续 3 轮 UNSAT core 未变化）比 Paper-1 下降 **≥20%**
3. ✅ 消融实验证明 Paradigm 模块和 Memory 模块各有独立贡献（单独移除均下降 ≥3%）
4. ✅ 范式库分析展示合理的触发率（≥30% 的推断步骤有范式覆盖）和置信度分布

---

### 两种极端情形的应对

**最坏情形（PRISM 比 Paper-1 提升 < 3%）**

Pivot 到「分析型论文」：
- 核心内容变为：用修复轨迹记忆系统性地分析为什么 CSP 求解的神经符号修复会停滞
- 定量分析 ErrorType 分布、UNSAT core 的演化轨迹、停滞发生的约束规模阈值
- 结论：提出改进建议（但不一定全部实现），建立 CSP 修复行为的分类学
- 贡献级别保守但有价值，可投 EMNLP Findings 或相关 Workshop

**最乐观情形（PRISM 在 6×6 上提升 ≥15% 且 L2 有正向结果）**

- 论文主张可以扩展到「范式迁移」，加强泛化性论述
- 贡献级别提升，可以冲击 AAAI 2027 或 NeurIPS 2026 主会
- 此时把 L2 从「exploratory experiment」升格为主要实验之一

---

*文档生成时间：基于 PRISM 框架深度审查，涵盖论文组织、审稿人预测与范围定标三部分。*
