# PRISM 实验设计完整方案

---

## 0. 实验总览

### 五个研究问题（RQ）与对应实验

| RQ | 问题 | 实验编号 | 预计工作量 |
|----|------|---------|-----------|
| RQ1 | PRISM 整体性能是否优于所有基线？ | Exp-1 主结果 | Week 8-10 |
| RQ2 | 修复记忆是否有效减少停滞与修复代价？ | Exp-2 修复效率 | Week 2-3（可早出结果）|
| RQ3 | 范式库的质量与覆盖情况如何？ | Exp-3 范式分析 | Week 5-7 |
| RQ4 | 各模块的独立贡献是什么？ | Exp-4 消融 | Week 10 |
| RQ5 | 范式能否跨规模/跨类型迁移？ | Exp-5 泛化 | Week 10-11 |

### 附加分析

| 分析 | 目的 | 放正文/附录 |
|------|------|-----------|
| Exp-6 超参数敏感性 | 证明系统鲁棒性 | 附录 |
| Exp-7 注入方式对比 | 确定最优范式注入策略 | §6 Analysis |
| Exp-8 案例研究 | 定性展示系统工作过程 | §6 Analysis |
| Exp-9 LLM backbone 对比 | 证明框架不依赖特定模型 | 附录 |

---

## 1. 实验环境与基础设置

### 1.1 数据集

**训练数据（仅用于离线范式提炼，绝不用于测试）**

使用论文二的可控谜题生成器生成，与 ZebraLogic 完全独立：

```
训练集构成（共 600 道谜题）：
  - 3×5 谜题（3 个实体 × 5 种属性）：200 道，难度 easy/medium 各半
  - 4×5 谜题：200 道，难度 easy/medium/hard = 4:4:2
  - 5×5 谜题：200 道，难度 medium/hard = 5:5

每道谜题跑 3 次（temperature=0.7）收集多样性轨迹
轨迹总量：600 × 3 = 1800 条（去重后约 1500 条）
```

难度定义（使用 Z3 冲突数作为客观难度指标）：
- Easy：Z3 conflicts < 5
- Medium：5 ≤ conflicts < 15
- Hard：conflicts ≥ 15

**测试数据**

主评估集：**ZebraLogic**（官方 benchmark，不参与任何训练）

```
ZebraLogic 规模分布（共 1000 道）：
  - 2×4：100 道（热身，预期所有系统高精度）
  - 3×5：200 道
  - 4×5：200 道
  - 5×5：200 道
  - 5×6：200 道
  - 6×6：100 道（最难，关键区分点）
```

L2 泛化测试集：**Knights-and-Knaves**（KnK）

```
使用 ProntoQA 或 LogiQA 中的 KnK 子集
选取约 200 道（确保有足够数量做统计检验）
不用于任何训练或调参
```

**重要原则**：ZebraLogic 的 dev/test 切分

```
ZebraLogic 1000 道：
  - Dev set（10% = 100 道）：用于超参数搜索（Exp-6）
  - Test set（90% = 900 道）：用于所有主实验
  Dev set 和 Test set 在确定超参数后绝不混用
```

---

### 1.2 LLM Backbone

**主实验 backbone**：`GPT-4o`（2024-08-06 版本，固定版本号保证复现）

```python
# 统一 API 调用配置
client = openai.OpenAI()
response = client.chat.completions.create(
    model="gpt-4o-2024-08-06",
    messages=messages,
    temperature=0.0,     # 评估时确定性输出
    max_tokens=2048,
    seed=42              # 确保可复现（OpenAI seed 参数）
)
```

**备选 backbone**（附录 Exp-9）：`Qwen2.5-72B-Instruct`

原因：证明 PRISM 框架不依赖特定模型，同时验证 VERGE 提出的「formalization barrier（<20B 模型无法做语义修复）」在 PRISM 框架中是否仍然存在。

---

### 1.3 Z3 配置

```python
import z3

def create_solver_with_timeout():
    solver = z3.Solver()
    solver.set("timeout", 5000)   # 5 秒超时
    solver.set("unsat_core", True)
    return solver

# UNSAT core 提取必须使用 assert_and_track
def add_tracked_constraint(solver, expr, name: str):
    track_var = z3.Bool(name)
    solver.assert_and_track(expr, track_var)
    return track_var
```

Z3 超时处理：超时视为「求解失败」，不计入准确率，单独统计超时率。

---

### 1.4 评估指标定义

```
核心指标（正文表格）：
  Acc@size        — 各规模谜题的求解准确率（exact match with GT）
  Acc@avg         — 所有规模的平均准确率（weighted by size distribution）
  LLM-Calls       — 每道谜题平均 LLM API 调用次数
  Repair-Rounds   — 每道翻译失败谜题的平均修复迭代轮数
  Stagnation-Rate — 触发停滞检测的谜题占比（%）

范式相关指标（§6 Analysis 或附录）：
  Paradigm-Trigger-Rate  — 有范式被触发的推断步骤占总步骤比例
  Paradigm-Hit-Rate      — 触发范式后推断 Z3 验证为 SAT 的比例
  Paradigm-Coverage      — 测试集中有范式覆盖的 KDP 占总 KDP 比例

迁移指标（Exp-5）：
  L1-Transfer-Acc        — 在大规模谜题上使用小规模范式库的准确率
  L1-Delta               — L1 迁移准确率 vs 无范式基线的差值
  L2-Transfer-Rate       — Zebra 范式在 KnK 上的触发率
  L2-Hit-Rate            — 触发范式在 KnK 上的命中率
```

---

### 1.5 统计显著性

所有主要结论使用 **paired bootstrap test**（n=1000 重采样），显著性水平 p < 0.05。

对于多重比较（8 个 system × 6 个 size），使用 **Bonferroni 校正**。

每个实验重复 **3 次（不同随机种子）**，报告 mean ± std。

---

## 2. 八条基线的实现规范

### B1：Plain LLM（CoT）

```
设置：GPT-4o，zero-shot chain-of-thought
Prompt：直接给出谜题文本，要求逐步推理并输出解
无 Z3 求解器，无任何记忆机制
输出格式：要求输出结构化赋值（house: [attr1=val1, ...]）
```

### B2：Paper-1（LLM + Z3，无记忆）

```
设置：复用论文一的完整 pipeline
  NL → Z3 翻译 → Z3 求解 → 结果解释
  翻译失败时：把原始 Z3 报错直接返回给 LLM 修复（最多 5 轮）
  无任何跨题目经验积累
这是最重要的基线，证明 PRISM 相对于前序工作的增量
```

### B3：Logic-LM

```
设置：参考原始论文实现
  使用官方 ZebraLogic 报告的数字（如有）
  如没有官方数字，按原论文设置复现：
    LLM 翻译到 Prolog/Z3，Clingo/Z3 执行，LLM 自修复
评估说明：在论文中注明「引用官方报告数字」or「本文复现」
```

### B4：ExpeL-CSP

```
设置：把 ExpeL 适配到 CSP 求解域
  使用与 PRISM 相同的 1500 条训练轨迹
  ExpeL 原始流程：
    Step 1: 把成功/失败轨迹对提交给 LLM，提取 insight
    Step 2: 使用 ADD/UPVOTE/DOWNVOTE/EDIT 操作维护 insight 列表
    Step 3: 测试时把所有 insights 注入 prompt
  与 PRISM 的关键区别：
    - Insights 是自由文本，无 Z3 验证
    - 所有 insights 全量注入，非选择性检索
    - 无修复记忆机制
实现工作量：约 1 周
如果时间不够：在 Related Work 中说明「ExpeL 无直接 CSP 适配，实现细节见附录」
```

### B5：Verified Few-Shot

```
设置：直接回应「为什么不用 few-shot」
  从 1500 条训练轨迹中提取经过 Z3 验证为 SAT 的推断步骤
  按约束类型特征，检索与当前谜题最相关的 top-K 步骤（K=5）
  直接把这 K 个步骤的「[约束状态] → [推断结论]」对注入 prompt
  有选择性检索（与 PRISM 相同的检索机制），但无范式抽象
  无修复记忆
这个 baseline 隔离了「结构化范式抽象」的贡献
```

### B6：PRISM w/o Memory（仅范式库）

```
设置：完整 PRISM，但移除 RepairMemory 模块
  范式检索 + 引导推断 + Z3 验证 均保留
  翻译失败时：用原始 Z3 报错修复（最多 5 轮，与 B2 相同）
  无停滞检测，无循环检测，无策略切换
证明：修复记忆模块的独立贡献
```

### B7：PRISM w/o Paradigm（仅修复记忆）

```
设置：完整 PRISM，但移除 Paradigm Library
  无范式引导，LLM 自由推断
  RepairMemory 完整保留：停滞检测 + 循环检测 + 四级策略切换
  注入给 LLM 的是修复历史摘要，而非范式
证明：范式库模块的独立贡献
```

### B8：PRISM Full

```
设置：完整 PRISM 系统
  离线范式库（600 道训练谜题提炼）
  在线范式检索（两层匹配 + 一致性预检）
  修复轨迹记忆（停滞 + 循环检测 + 四级策略切换）
  Z3 逐步验证 + UNSAT 归因
  经验写回机制
```

---

## 3. Exp-1：主结果实验（RQ1）

### 3.1 实验目标

证明 PRISM Full 在 ZebraLogic 各规模上显著优于所有 8 个基线，且提升随谜题规模增大而增大（说明经验积累对困难场景价值最高）。

### 3.2 实验设置

```
数据：ZebraLogic test set（900 道，按规模分层）
系统：8 个（B1-B8）
重复：3 次（seed = {42, 123, 456}）
评估：Acc@size × 6 + Acc@avg + LLM-Calls + Repair-Rounds
```

### 3.3 主结果表格设计

```
Table 2: Main Results on ZebraLogic

System          | 3×5  | 4×5  | 5×5  | 5×6  | 6×6  | Avg  | LLM↓ | Rep↓
----------------|------|------|------|------|------|------|------|------
Plain LLM       |      |      |      |      |      |      |      |
Paper-1 (ours)  |      |      |      |      |      |      |      |
Logic-LM        |      |      |      |      |      |      |      |
ExpeL-CSP       |      |      |      |      |      |      |      |
Verified FS     |      |      |      |      |      |      |      |
PRISM w/o Mem   |      |      |      |      |      |      |      |
PRISM w/o Par   |      |      |      |      |      |      |      |
PRISM Full      |      |      |      |      |      |      |      |

↑ higher is better, ↓ lower is better
Bold = best; * = significantly better than Paper-1 (p < 0.05)
```

### 3.4 预期结果与论文主张

**核心预期**：

```
PRISM Full vs Paper-1：
  - 3×5（简单）：提升约 5%（简单谜题提升空间小）
  - 4×5（中等）：提升约 10%
  - 5×5（中等偏难）：提升约 13%
  - 6×6（困难）：提升约 15-20%（越难提升越大是关键论点）

PRISM Full vs Verified Few-Shot：
  - 各规模均优于 Verified FS，证明范式抽象优于直接注入
  - 在 6×6 上差距最大（FS 因 context 过长性能下降）

PRISM Full vs ExpeL-CSP：
  - 显著优于 ExpeL-CSP，证明 Z3 验证的必要性
```

**如果实际数字与预期差异大的处理方式**：

- 提升 < 5%：扩大分析维度，聚焦于修复轮数和 LLM 调用次数的节省
- 提升 > 25%：检查是否有 data leakage，重新验证

### 3.5 额外分析：规模-性能曲线

画一张折线图，X 轴为谜题规模（约束数 × 变量数），Y 轴为 Acc：

```
Figure 2: Accuracy vs. Problem Scale
展示 4 条线：Plain LLM / Paper-1 / PRISM w/o Par / PRISM Full
预期：所有系统随规模增大精度下降，但 PRISM Full 下降最慢
论点：经验积累对困难问题的价值最大，体现为「性能下降斜率最小」
```

---

## 4. Exp-2：修复效率实验（RQ2）

### 4.1 实验目标

独立评估修复记忆的效果，证明：
1. 停滞检测准确率高（真正停滞时触发，未停滞时不误触发）
2. 修复轮数显著减少
3. 修复成功率提升

**这个实验可以在 Week 2-3 就跑出来**（基于 Paper-1 直接加 RepairMemory 模块），是整个论文最早出结果的实验。

### 4.2 实验设置

```
数据：ZebraLogic test set 中「第一次翻译 Z3 返回 UNSAT 或报错」的子集
  （即：只分析需要修复的困难谜题，排除一次性成功的简单谜题）
  预计约 40-60% 的谜题会进入修复流程

对比系统（聚焦 Memory 的贡献）：
  - Paper-1：无记忆，5 轮上限修复
  - PRISM w/o Par（= Paper-1 + Memory）：仅加修复记忆
  - PRISM Full：完整系统（作为参考）
```

### 4.3 评估指标

```
主要指标：
  Repair-Success-Rate   — 经过修复后最终求解成功的比例
  Avg-Repair-Rounds     — 平均修复轮数（成功和失败均计入）
  Stagnation-Rate       — 停滞检测触发的谜题占修复集合比例
  Post-Stagnation-Acc   — 停滞检测触发后（策略切换后）的最终成功率

停滞检测评估指标（需要人工标注小样本验证）：
  Stagnation-Precision  — 触发停滞检测时，确实处于停滞状态的比例
  Stagnation-Recall     — 真实停滞状态被检测到的比例
  F1-Stagnation         — 综合指标
```

**停滞检测的真实标签获取**：

人工标注 100 道修复案例，判断「第 k 轮修复时是否处于真实停滞状态」（判断标准：第 k+1 到 k+3 轮修复均失败且 UNSAT core 未变化）。用于计算 Stagnation-Precision / Recall。

### 4.4 结果表格设计

```
Table 3: Repair Efficiency Analysis

System          | Repair-Rate | Avg-Rounds↓ | Stagnation↓ | Post-Stag-Acc
----------------|-------------|-------------|-------------|---------------
Paper-1         |    XX%      |    X.X      |    XX%      |     XX%
PRISM w/o Par   |    XX%      |    X.X      |    XX%      |     XX%
PRISM Full      |    XX%      |    X.X      |    XX%      |     XX%

子分析（按错误类型分解）：
ErrorType       | Count | Paper-1 Fix% | PRISM Fix%  | Delta
SYNTAX          |       |              |             |
OVER_CONSTRAINT |       |              |             |
UNDER_CONSTRAINT|       |              |             |
SEMANTIC_FLIP   |       |              |             |
SCOPE_ERROR     |       |              |             |
LEGACY          |       |              |             |
```

---

## 5. Exp-3：范式库质量分析（RQ3）

### 5.1 实验目标

回答「范式库里有什么，质量如何，覆盖了多少场景」。

这是论文 §6 Analysis 的重要内容，让读者能够理解 PRISM 的内部工作状态。

### 5.2 分析维度

**A. 范式库统计**

```python
# 运行离线提炼后统计以下数据：
paradigm_stats = {
    "total_paradigms": len(library),
    "by_type": Counter([p.inferred_type for p in library]),
    "confidence_distribution": [p.confidence for p in library],
    "support_distribution": [p.support_count for p in library],
    "compression_ratio": len(trajectories) / len(library),
    "scope_distribution": Counter([s for p in library for s in p.scope])
}
```

目标输出（Figure 3 的内容）：
- 置信度分布直方图（期望：大多数 ≥ 0.90）
- 按范式类型（P1/P2/P3）的分布饼图
- 支持轨迹数（support_count）分布

**B. 范式触发分析（在测试集上运行）**

```
对 ZebraLogic test set 的所有推断步骤进行统计：

  Paradigm-Trigger-Rate = 有范式被 Layer 1 检索到的步骤 / 总步骤
  Paradigm-Match-Rate   = Layer 2 语义匹配通过的步骤 / Layer 1 通过的步骤
  Paradigm-Hit-Rate     = Z3 验证为 SAT 的触发步骤 / 语义匹配通过的步骤

触发频率 Top-10 范式列表（表格形式，展示最有用的范式）
```

**C. 覆盖率分析**

```
对于测试集上「没有范式覆盖」的推断步骤，分析其特征：
  - 约束类型分布（哪类约束最难被范式覆盖？）
  - 这些步骤的 LLM 错误率是否更高？
  - 作为未来工作的方向：哪些场景需要更多范式？
```

### 5.3 呈现方式

在论文 §6.2 中用 2 个 Figure + 1 个 Table：

```
Figure 3a：范式置信度分布直方图
Figure 3b：Top-10 触发范式的频率条形图
Table 4：范式库摘要统计
  Total | P1-type | P2-type | P3-type | Avg-Conf | Compression-Ratio
```

---

## 6. Exp-4：消融实验（RQ4）

### 6.1 实验目标

系统性地验证 PRISM 各个模块的独立贡献，回答「哪个模块最关键」。

### 6.2 消融设计（2×2 + 细粒度）

**主消融（2×2 因子设计）**：

```
                    | With Memory | Without Memory
--------------------|-------------|----------------
With Paradigm       | PRISM Full  | PRISM w/o Mem (B6)
Without Paradigm    | PRISM w/o Par (B7) | Paper-1 (B2)
```

**细粒度消融**（在 PRISM Full 基础上逐一移除）：

```
PRISM Full 的 8 个可移除组件：
  A1: 移除 Z3 离线验证（范式无需通过 Z3 验证即可入库）
  A2: 移除在线一致性预检（不检验范式推断与当前约束是否相容）
  A3: 移除停滞检测
  A4: 移除循环检测
  A5: 移除策略切换（检测到停滞/循环后不切换，直接继续修复）
  A6: 移除经验写回（成功修复不更新范式库）
  A7: 移除两层检索的 Layer 2（只用约束类型集合匹配）
  A8: 移除 UNSAT 归因（不区分「新推断导致」vs「已有翻译错误导致」）
```

### 6.3 评估设置

```
数据：ZebraLogic test set（900 道）
关注规模：4×5 + 5×5 + 6×6（中等到困难，消融效果更明显）
重复：3 次
指标：Acc@avg + Repair-Rounds + Stagnation-Rate
```

### 6.4 消融结果表格

```
Table 5: Ablation Study

System / Variant       | Acc@4×5 | Acc@5×5 | Acc@6×6 | Avg   | ΔAcc
-----------------------|---------|---------|---------|-------|------
PRISM Full             |         |         |         |       | —
  - w/o Z3 verify (A1) |         |         |         |       | -X.X
  - w/o online check(A2)|        |         |         |       | -X.X
  - w/o stagnation (A3)|         |         |         |       | -X.X
  - w/o loop detect(A4)|         |         |         |       | -X.X
  - w/o strategy sw(A5)|         |         |         |       | -X.X
  - w/o write-back (A6)|         |         |         |       | -X.X
  - w/o Layer 2 (A7)   |         |         |         |       | -X.X
  - w/o attribution(A8)|         |         |         |       | -X.X
Paper-1                |         |         |         |       | -X.X

每行的 ΔAcc = 该变体 Acc - PRISM Full Acc（负值说明该组件有贡献）
```

---

## 7. Exp-5：泛化实验（RQ5）

### 7.1 L1 泛化实验：跨规模迁移

**实验目标**：验证在小规模谜题上学到的范式能否有效用于更大规模谜题。

**实验设计**：

```
三种训练配置（用不同规模的训练数据运行离线提炼）：
  Config-A：只用 3×5 谜题训练（200道）→ 提炼「小规模范式库」
  Config-B：只用 4×5 谜题训练（200道）→ 提炼「中规模范式库」
  Config-C：混合训练（600道，默认配置）→ 提炼「完整范式库」

在 ZebraLogic 各规模上分别评估三种配置：
  测试：3×5, 4×5, 5×5, 5×6, 6×6

关键对比：
  Config-A（小规模范式）在 5×5 和 6×6 上的表现
  vs Config-C（混合范式）在 5×5 和 6×6 上的表现
  → 差距说明「跨规模迁移损失」
  → 如果差距小（< 5%），证明范式泛化能力强
```

**L1 迁移率计算**：

```python
def l1_transfer_rate(source_lib, target_puzzles, solver):
    """
    source_lib: 在小规模数据上训练的范式库
    target_puzzles: 大规模测试谜题
    """
    triggered = 0
    total_steps = 0
    hits = 0
    for puzzle in target_puzzles:
        for step in get_inference_steps(puzzle):
            total_steps += 1
            matched = source_lib.retrieve(step.constraint_types)
            if matched:
                triggered += 1
                # 检查范式推断是否 SAT
                if solver.check_with(matched[0].operation) == "SAT":
                    hits += 1
    return {
        "trigger_rate": triggered / total_steps,
        "hit_rate": hits / triggered if triggered > 0 else 0,
        "effective_transfer": hits / total_steps
    }
```

**L1 结果表格**：

```
Table 6: L1 Cross-Scale Generalization

Training Config | Test: 3×5 | Test: 4×5 | Test: 5×5 | Test: 5×6 | Test: 6×6
----------------|-----------|-----------|-----------|-----------|----------
Config-A (3×5)  | (in-dist) |           |           |           |
Config-B (4×5)  |           | (in-dist) |           |           |
Config-C (mix)  |           |           |           |           |
No Paradigm     |           |           |           |           |

Transfer Rate（触发率）：
Config-A on 6×6 →  XX%（能触发多少范式）
Config-C on 6×6 →  XX%（参考）
```

### 7.2 L2 泛化实验：跨谜题类型迁移（可选）

**实验目标**：探索 Zebra 谜题范式在 Knights-and-Knaves（KnK）谜题上的迁移情况。

**为什么 KnK 是合理的 L2 目标**：

```
KnK 和 Zebra 谜题的结构相似性：
  - 共同点：约束满足问题，Z3 可验证，有确定的 ground truth
  - 约束类型重叠：
    * 排除约束（「骑士不说谎」→ exclusion）
    * 绑定约束（「A 和 B 一致」→ binding）
  - 不重叠：
    * 位置/顺序约束（Zebra 特有）
    * 逻辑蕴含约束（KnK 特有）
```

**实验设置**：

```
数据：KnK 测试集 200 道
范式库：使用 Config-C（完整 Zebra 范式库，不在 KnK 上训练任何范式）

评估：
  1. Paradigm-Trigger-Rate on KnK：有多少推断步骤能找到匹配范式？
  2. Paradigm-Hit-Rate on KnK：触发范式后推断的准确率？
  3. Acc on KnK with/without Zebra paradigms：范式对 KnK 准确率的影响

期望结果（诚实的预期）：
  触发率较低（20-40%，因为 KnK 特有约束类型不在范式库中）
  但对于触发的步骤，命中率仍然较高（>70%）
  → 结论：部分范式可跨域迁移，「相邻/排除」类约束的范式最通用
```

**重要说明**：L2 实验在论文中定位为「探索性实验」，报告发现而不做过强的结论性主张。如果结果不理想（触发率 < 10%），诚实地在 Limitations 中说明。

---

## 8. Exp-6：超参数敏感性分析（附录）

### 8.1 超参数列表与搜索范围

```python
hyperparameter_grid = {
    "theta":      [0.15, 0.20, 0.25, 0.30],   # 聚类距离阈值
    "tau_s":      [0.60, 0.70, 0.75, 0.80],   # 停滞检测 Jaccard 阈值
    "tau_l":      [0.85, 0.88, 0.90, 0.92],   # 循环检测余弦阈值
    "min_support":[3, 5, 8, 10],              # 范式最小轨迹支持数
    "top_k":      [1, 2, 3, 5],               # 范式检索数量
}
```

### 8.2 搜索策略

使用 ZebraLogic **dev set**（100 道）做 grid search：

```python
# 先固定其他参数，对每个超参数单独扫描
# 找到敏感性最高的超参数后，对敏感参数做联合搜索
# 最终选定配置在 dev set 上确定后，锁定参数，不再调整

best_config = {
    "theta": 0.25,
    "tau_s": 0.75,
    "tau_l": 0.90,
    "min_support": 5,
    "top_k": 3
}
```

### 8.3 呈现方式

附录中的「超参数敏感性热力图」：

```
Figure A1: Hyperparameter Sensitivity
X 轴：tau_s 值
Y 轴：tau_l 值
颜色：Acc@avg on dev set
预期：在合理范围（tau_s ∈ [0.65, 0.85], tau_l ∈ [0.85, 0.92]）内性能变化 < 2%
结论（正文一句话）：「PRISM 对阈值超参数不敏感，合理范围内性能变化 < 2%（见附录）」
```

---

## 9. Exp-7：范式注入方式对比（§6 Analysis）

### 9.1 实验目标

确定范式注入给 LLM 的最优格式，同时验证「注入方式本身对性能的影响」。

### 9.2 注入格式变体

```
Inject-Hard：强制指令格式
  「你必须使用以下策略推断下一步：[P2: 链式传播] 根据 pos(Norwegian)=1
   和 pos(BlueHouse)=pos(Norwegian)+1，推断 pos(BlueHouse)=2。
   直接输出这个赋值，不要做其他推断。」

Inject-Soft：建议格式（推荐，与论文描述一致）
  「以下策略已在类似情境中验证有效，供参考：
   [P2] 链式传播：当某实体的位置已知且存在相对位置约束时，
   传播推导出相关实体的位置。」

Inject-Example：样例格式
  「类似情境的成功推断例子：
   [例1] pos(Norwegian)=1, pos(BlueHouse)=pos(Norwegian)+1
         → 推断 pos(BlueHouse)=2（已验证 SAT）」

No-Inject：不注入范式（基线，= PRISM w/o Paradigm）
```

### 9.3 对比实验

在 ZebraLogic 5×5 上对比四种注入方式（只改注入格式，其他完全相同）：

```
Table 7: Paradigm Injection Style Comparison

Inject Style  | Acc@5×5 | LLM-Calls | Follow-Rate*
--------------|---------|-----------|-------------
Hard          |         |           |
Soft          |         |           |
Example       |         |           |
No-Inject     |         |           |

* Follow-Rate = LLM 实际采用了范式建议的步骤比例（通过对比输出分析）
```

**预期结果**：Soft 注入在准确率和 LLM 接受度上取得最佳平衡；Hard 注入可能导致 LLM 在范式不完全适用时仍强制执行错误推断。

---

## 10. Exp-8：案例研究（§6 Analysis）

### 10.1 案例选取标准

```python
# 选取满足以下条件的案例：
def select_case_study(results):
    good_cases = [r for r in results if (
        r['prism_success'] == True and         # PRISM 求解成功
        r['paper1_success'] == False and       # Paper-1 求解失败
        r['paradigm_triggered'] == True and    # 有范式被触发
        r['stagnation_detected'] == True and   # 修复记忆介入了
        r['puzzle_size'] in ['4×5', '5×5']     # 中等规模，可读性好
    )]
    return sorted(good_cases, key=lambda x: x['repair_rounds'])[0]
    # 选修复轮数适中（3-5轮）的案例，展示停滞检测和策略切换的完整过程
```

### 10.2 案例展示结构

在论文 §6.1 中，一道谜题占约 0.5 页：

```
Step 1: 初始翻译
  [NL约束] → [Z3代码] → Z3: UNSAT
  UNSAT core: {C3, C7}，类型: OVER_CONSTRAINT

Step 2: 修复轮 1
  LLM 修复 C7 → Z3: UNSAT（core 仍为 {C3, C7}）
  RepairRecord 1: {error=OVER, core={C3,C7}, action=relax C7, outcome=UNSAT}

Step 3: 修复轮 2
  LLM 修复 C3 → Z3: UNSAT（core 变为 {C3, C7, C9}）
  RepairRecord 2: {error=OVER, core={C3,C7,C9}, action=relax C3, outcome=UNSAT}

Step 4: 修复轮 3（触发停滞检测）
  J({C3,C7}, {C3,C7,C9}) = 2/3 = 0.67 < 0.75 → 未停滞（继续）
  LLM 修复 C7 再次 → 循环检测：余弦相似度 0.94 > 0.90 → 触发！
  策略切换 L2：「已尝试 relax，切换为 retranslate C7」
  LLM 重新翻译 C7 → Z3: SAT ✓

Step 5: 范式引导的推断（SAT 状态后）
  当前状态触发 P2（链式传播）
  Layer 1：约束类型 {adjacent, direct_position} ⊆ 当前约束类型 ✓
  在线一致性预检：P2 推断 → Z3 SAT ✓
  注入 P2 → LLM 正确推断 pos(BlueHouse)=2
  最终 Z3 SAT，ground truth 匹配 ✓
```

---

## 11. Exp-9：LLM Backbone 对比（附录）

### 11.1 实验目标

证明 PRISM 框架不依赖特定 LLM，在不同 backbone 上均有效。同时检验「formalization barrier」（VERGE 发现的 <20B 模型无法做语义修复）在 PRISM 中是否依然存在。

### 11.2 实验设置

```
测试 backbone：
  - GPT-4o（主实验）
  - Qwen2.5-72B-Instruct（开源大模型）
  - Qwen2.5-7B-Instruct（开源小模型，测试 formalization barrier）
  - Claude-3.5-Sonnet（可选）

测试数据：ZebraLogic 4×5（200道，选中等规模，计算资源可控）
系统：PRISM Full vs Paper-1（各 backbone）
```

### 11.3 结果表格

```
Table A2: Results Across LLM Backbones (4×5 Puzzles)

Backbone        | Paper-1 | PRISM Full | Δ(PRISM-Paper1) | PRISM LLM-Calls
----------------|---------|------------|-----------------|----------------
GPT-4o          |         |            |                 |
Qwen2.5-72B     |         |            |                 |
Qwen2.5-7B      |         |            |                 |
Claude-3.5-S    |         |            |                 |

观察点：
1. Δ(PRISM-Paper1) 在各 backbone 上是否稳定正值（框架通用性）
2. Qwen2.5-7B 的绝对精度是否远低于 72B（formalization barrier 验证）
3. PRISM 对小模型的提升比例是否更大（小模型更需要范式引导）
```

---

## 12. 实验执行计划

### 12.1 按周进度安排

```
Week 1-2：实验基础设施
  □ 建立 ConstraintRegistry（UNSAT core 回译基础）
  □ 实现 RepairMemory 模块（停滞+循环检测）
  □ 复现 Paper-1 pipeline，确认与原始结果一致
  □ 跑 Paper-1 在 ZebraLogic 的基线数字（所有规模）
  □ 【先出结果】PRISM w/o Par vs Paper-1（Exp-2 初步结果）

Week 3-4：离线提炼 pipeline
  □ 轨迹收集（600 × 3 次，1800条）
  □ KDP 识别（简化版判定条件）
  □ 特征向量提取 + 聚类
  □ 第一版范式库（目标 ≥10 个验证通过的范式）

Week 5-6：在线推理模块
  □ 两层检索（Layer 1 集合匹配 + Layer 2 LLM 语义判断）
  □ 注入前一致性预检
  □ 四级策略切换状态机
  □ 经验写回机制

Week 7-8：端到端集成与调参
  □ 接通所有模块，端到端跑通一道谜题
  □ 在 ZebraLogic dev set 上调参（Exp-6 超参数搜索）
  □ 确定最终超参数配置，锁定
  □ 【关键节点】PRISM Full vs Paper-1 在 dev set 的对比

Week 9-10：主实验
  □ Exp-1：全 8 个系统 × 全 6 个规模（重复 3 次）
  □ Exp-4：消融实验（8个组件 × 3个关键规模）
  □ Exp-5 L1：三种训练配置 × 全规模
  □ 开始整理 Exp-3 范式库统计

Week 11：补充实验与写作准备
  □ Exp-5 L2：KnK 迁移实验（如果 L1 结果好）
  □ Exp-7：注入方式对比
  □ Exp-8：案例研究选取与整理
  □ 附录：Exp-6 完整超参数热力图 + Exp-9 backbone 对比

Week 12：写作
  □ 按节完成初稿
  □ 重点打磨 §4 系统图和 §5 主结果讨论
  □ Limitations 诚实撰写
  □ 内部 peer review（至少一位导师审阅）
```

### 12.2 实验资源预算

```
LLM API 成本估算（GPT-4o @ ~$5/M tokens）：

  轨迹收集：1800 条 × 平均 8 步 × 500 tokens = 7.2M tokens ≈ $36
  范式抽象：35 个范式 × 3000 tokens = 105K tokens ≈ $0.5
  主实验 B1-B8：900 谜题 × 8 系统 × 平均 10 调用 × 1500 tokens
               = 108M tokens ≈ $540
  消融实验：900 × 8变体 × 0.5倍（只跑关键规模） ≈ $200
  其他实验（L1/L2/超参数等） ≈ $150

  总计：约 $930（约 6700 元）

如果预算有限的优化策略：
  - 主实验只用 3 次重复中的 1 次，在 revision 阶段补全
  - 消融实验只跑 5×5 和 6×6（最有区分度的规模）
  - 使用 Qwen2.5-72B-Instruct 替代 GPT-4o 降低约 10 倍成本（开源免费推理）
  最低成本方案（Qwen2.5）：约 $0（本地推理）+ GPU 时间
```

---

## 13. 数据管理与复现规范

### 13.1 实验记录规范

```python
# 每次实验运行的完整记录格式
experiment_log = {
    "exp_id": "exp1_prism_full_seed42_20250901",
    "config": {
        "system": "PRISM Full",
        "backbone": "gpt-4o-2024-08-06",
        "seed": 42,
        "hyperparams": best_config,
        "paradigm_library_version": "v1.2",  # 版本化管理
    },
    "results": {
        "per_puzzle": [...],  # 每道谜题的详细结果
        "aggregated": {
            "acc_3x5": 0.XX, "acc_4x5": 0.XX, ...
        }
    },
    "timestamp": "2025-09-01T14:30:00",
    "git_commit": "abc123"  # 代码版本
}
# 所有日志存储为 JSON，用 wandb 追踪
```

### 13.2 复现包清单（论文提交时附上）

```
prism_reproduce/
├── paradigm_library_v_final.db   # 最终范式库（SQLite）
├── paradigm_library_v_final.json # 人可读版本（所有范式明文）
├── results/
│   ├── exp1_main_results.csv
│   ├── exp2_repair_efficiency.csv
│   ├── exp4_ablation.csv
│   └── exp5_generalization.csv
├── configs/
│   └── best_config.yaml          # 最终超参数
├── scripts/
│   └── reproduce_all.sh          # 一键复现脚本
└── README_reproduce.md           # 复现说明
```

---

*实验设计版本：v1.0，基于 PRISM 框架深度审查后制定*
*预计总 GPU/API 成本：约 $900（GPT-4o）或接近零成本（Qwen2.5 本地推理）*
