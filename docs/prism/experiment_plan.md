# PRISM 待补实验完整方案

> 本文档是投稿前实验执行的指南。每个实验给出：目标、命令、预期产出、结果如何写入论文。
> 所有命令在项目根目录 `D:\Papers\PRISM` 下执行。

---

## 0. 前置准备

### 0.1 环境检查

```bash
# 确认依赖
pip install -e .
pytest tests/ -x -q          # 快速冒烟，确保核心模块没有回归

# 确认 API key 就绪
# OpenAI:  需要 OPENAI_API_KEY 环境变量（GPT-4o, o1-mini）
# Anthropic: 需要 ANTHROPIC_API_KEY 环境变量（如已有，用 Claude 也可）

# 确认数据集
ls data/hf/zebralogic/         # ZebraLogic JSONL 文件
ls data/hf/knights-and-knaves/ # KnK JSONL 文件
```

### 0.2 离线范式库确认

如果 `paradigm_store/prism.db` 已存在且有 34 个已验证范式，可复用。
如需重建：

```bash
python scripts/run_offline.py \
  --config config/default.yaml \
  --model "GPT-4o" \
  --n-puzzles 600 --n-runs 3 \
  --output paradigm_store/prism.db \
  --seed 42
```

预计耗时：~1800 次 LLM 调用 + Z3 验证 ≈ 2-4 小时（取决于 API 速率）。

### 0.3 种子与重复

所有实验使用 3 个随机种子：`42, 123, 456`。
报告均值 ± 标准差。

---

## P0-① 真实数据：主表全量实验

### 目标
替换主表（Table 2）所有占位数字。

### 执行

**A) 纯 LLM 基线（无 Z3，无范式）：**
```bash
# 纯 LLM 需要一个不走 Z3 验证的脚本路径，或用 run_online.py --no-paradigm --no-memory --max-repair 0
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-paradigm --no-memory --max-repair 0 \
    --seed $seed \
    --output results/P0/pure_llm_seed${seed}.csv
done
```

**B) LLM+Z3 基线（Paper-1，无范式无记忆）：**
```bash
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-paradigm --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P0/paper1_seed${seed}.csv
done
```

**C) ExpeL-CSP 基线：**
```bash
# ExpeL-CSP 需要适配脚本：从 1500 轨迹提取 NL 经验并注入
# 如需新建脚本，参考 prism/online/guided_solver.py 中 enable_paradigm=False + NL经验注入
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-paradigm --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P0/expel_csp_seed${seed}.csv
    # TODO: 需要增加 --expel-mode 或类似参数
done
```

**D) 验证少样本（Verified Few-Shot）：**
```bash
# VFS：检索经 Z3 验证的历史步骤 k=5 直接注入
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P0/vfs_seed${seed}.csv
    # TODO: 需要增加 --vfs-mode 或 --retrieval-only 参数
done
```

**E) PRISM 消融（无修复记忆）：**
```bash
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/prism.db \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P0/prism_wo_mem_seed${seed}.csv
done
```

**F) PRISM 消融（无范式库）：**
```bash
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-paradigm --max-repair 5 \
    --seed $seed \
    --output results/P0/prism_wo_par_seed${seed}.csv
done
```

**G) PRISM 完整系统：**
```bash
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/prism.db \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --max-repair 5 \
    --seed $seed \
    --output results/P0/prism_full_seed${seed}.csv \
    --trace-output results/P0/prism_full_trace_seed${seed}.jsonl
done
```

### 结果汇总脚本

```bash
python scripts/summarize_online_csvs.py results/P0/ --output results/P0/main_table.csv
```

### 写入论文位置
- Table 2（主表）：替换所有数值
- §6.1 分析文字：根据真实增益模式调整叙述

### 预计成本
- 900 题 × 10 个系统变体 × 3 种子 × ~5 调用/题 ≈ 135,000 次 LLM 调用
- GPT-4o 定价约 $2,700（按 $0.02/调用估算）
- 耗时约 3-5 天（并行运行可缩短）

---

## P0-② VERGE baseline

### 目标
在 ZebraLogic 上获取 VERGE 的对比数据。

### 方案选择

**方案 A（推荐）：引用原文数值**
- VERGE 论文 (arXiv:2601.20055) 中是否报告了 ZebraLogic 结果？
- 如果报告了：直接引用，标注 "Results from Singh et al. (2026)"
- 如果未报告 ZebraLogic：标注 "VERGE 未在 ZebraLogic 上评估，仅在其原始基准上报告"

**方案 B：复现**
- 检查 VERGE 是否开源：https://github.com/xxx/verge（查 arXiv 论文中的链接）
- 如果开源：克隆并在 ZebraLogic 上运行
- 如果未开源：联系作者或标注 "无法复现"

### 执行步骤
```bash
# 1. 检查论文中的数据
# 从 arXiv:2601.20055 的 PDF 中提取 ZebraLogic 相关表格

# 2. 如需复现
# git clone <verge-repo>
# pip install -r requirements.txt
# python run_verge.py --data allenai/ZebraLogicBench --sizes "3x5,4x5,5x5,5x6,6x6"
```

### 写入论文位置
- Table 2 中 VERGE† 行
- 如引用原文：脚注说明 "Results from original paper; evaluated on [their benchmark]"

---

## P0-③ Logic-LM++ baseline

### 目标
获取 Logic-LM++ 在 ZebraLogic 上的对比数据。

### 方案
同 VERGE。Logic-LM++ (arXiv:2407.02514) 论文中可能在 AR-LSAT 或 FOLIO 上报告结果。
ZebraLogic 上的结果可能需要复现。

### 执行
```bash
# 检查论文数据
# Logic-LM++ 开源于 https://github.com/xxx/logic-lm-pp（查论文）

# 如需复现
# git clone <logic-lm++-repo>
# 在 ZebraLogic 上运行其 pipeline
```

### 写入论文位置
- Table 2 中 Logic-LM++† 行

---

## P0-④ 多 LLM 实验

### 目标
验证 PRISM 增益不依赖于 GPT-4o。

### 模型列表
| 模型 | config 中名称 | API | 说明 |
|------|-------------|-----|------|
| GPT-4o | GPT-4o | OpenAI | 主实验（已有） |
| Llama-3-70B-Instruct | 需配置 | 第三方 API 或本地部署 | 开源大模型 |
| o1-mini | o1-mini | OpenAI | 推理增强模型 |

### 执行

**Llama-3-70B：**
```bash
# 选项1：通过兼容 OpenAI API 的服务（如 Together AI, Fireworks）
# 在 config/api/model_configs.json 中添加 Llama-3-70B 配置

for seed in 42 123 456; do
  # 基线
  python scripts/run_online.py \
    --model "Llama-3-70B" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-paradigm --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P0/llama70b_paper1_seed${seed}.csv

  # PRISM Full（需要用 Llama-3 重建离线范式库，或测试 GPT-4o 范式在 Llama 上的迁移）
  python scripts/run_online.py \
    --model "Llama-3-70B" \
    --library paradigm_store/prism.db \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --max-repair 5 \
    --seed $seed \
    --output results/P0/llama70b_prism_seed${seed}.csv
done
```

**o1-mini：**
```bash
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "o1-mini" \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --no-paradigm --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P0/o1mini_paper1_seed${seed}.csv

  python scripts/run_online.py \
    --model "o1-mini" \
    --library paradigm_store/prism.db \
    --sizes "3x5,4x5,5x5,5x6,6x6" \
    --max-repair 5 \
    --seed $seed \
    --output results/P0/o1mini_prism_seed${seed}.csv
done
```

### 注意事项
- Llama-3-70B 需要 API 接入（Together AI 约 $0.9/M tokens）或本地 A100 部署
- o1-mini 的 API 行为与 GPT-4o 不同（不支持 temperature=0.0，改用 seed 控制）
- 范式库跨模型复用：主实验用 GPT-4o 范式库在其他模型上测试；如效果差距大，需分别构建

### 写入论文位置
- Table 9（多基础模型表）：替换占位值
- §6.6 分析文字

### 预计成本
- 2 个额外模型 × 2 个系统 × 900 题 × 3 种子 × ~5 调用 ≈ 54,000 次调用
- 约 $1,000-1,500

---

## P1-⑤ 手工规则基线（Hand-crafted Rules）

### 目标
隔离 LLM 归纳范式相对于人工编码规则的增量价值。

### 实现

需要新建一个手工规则范式库 `paradigm_store/handcrafted.db`，包含 3 类硬编码范式：

**规则 1 — 直接赋值传播：**
- 触发条件：存在 `direct_assignment(X, V)` 约束且 `|δ(X)| > 1`
- 操作：`δ(X) ← {V}`；对同属性其他变量 Y，`δ(Y) ← δ(Y) \ {V}`
- Z3 前条件：`X ∈ D_X ∧ V ∈ D_X`
- Z3 后条件：`X == V`

**规则 2 — 链式位置传播：**
- 触发条件：存在 `position(A) == k`（已确定）且 `position(B) == position(A) + d`
- 操作：`position(B) ← k + d`
- Z3 前条件：`1 ≤ k + d ≤ n`
- Z3 后条件：`position(B) == k + d`

**规则 3 — 矛盾消去（试探）：**
- 触发条件：某变量 X 域大小 = 2 且直接传播无法继续
- 操作：试探 `X = v`，若 Z3 返回 UNSAT 且 core 包含试探约束，则删除 v
- Z3 前条件：`|δ(X)| == 2`
- Z3 后条件：Z3-UNSAT(C ∪ {X == v})

### 实现步骤

```python
# 新建脚本：scripts/build_handcrafted_library.py
# 直接构造 ParadigmLibrary 并写入 SQLite
# 不经过 LLM 抽象和聚类，直接硬编码 3 条范式

from prism.paradigm_library.library import ParadigmLibrary
from prism.paradigm_library.schema import Paradigm

lib = ParadigmLibrary("paradigm_store/handcrafted.db")

# 构造 3 条手工范式（具体格式参照 prism/paradigm_library/schema.py）
# ...
lib.save()
```

### 执行
```bash
# 1. 构建手工规则库
python scripts/build_handcrafted_library.py

# 2. 运行 HR baseline
for seed in 42 123 456; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/handcrafted.db \
    --sizes "5x5" \
    --no-memory --max-repair 5 \
    --seed $seed \
    --output results/P1/handcrafted_seed${seed}.csv
done
```

### 写入论文位置
- Table 8（手工规则对比表）：替换占位值
- §7 讨论中"LLM 归纳 vs 手工规则"段落

### 预计成本
- 1 个系统 × ~180 题(5×5) × 3 种子 × ~5 调用 ≈ 2,700 次调用
- 约 $50

---

## P1-⑥ 错误类型分布直方图

### 目标
展示各错误类型在不同规模上的分布。

### 数据来源
从 P0-① G) 的 JSONL trace 文件中提取。

### 提取脚本

```python
# scripts/plot_error_distribution.py
import json, pandas as pd, matplotlib.pyplot as plt
from collections import Counter

error_counts = {}  # {scale: Counter}
for scale in ["4x5", "5x5", "6x6"]:
    counts = Counter()
    for seed in [42, 123, 456]:
        with open(f"results/P0/prism_full_trace_seed{seed}.jsonl") as f:
            for line in f:
                record = json.loads(line)
                if record["domain"] != scale:
                    continue
                for step in record.get("steps", []):
                    if step.get("error_type"):
                        counts[step["error_type"]] += 1
    error_counts[scale] = counts

# 转 DataFrame 并绘制分组直方图
df = pd.DataFrame(error_counts).fillna(0)
df = df.div(df.sum()) * 100  # 转为百分比
df.plot(kind="bar", figsize=(8, 4))
plt.ylabel("Proportion (%)")
plt.title("Error Type Distribution by Scale")
plt.tight_layout()
plt.savefig("figures/error_distribution.pdf", dpi=300)
```

### 写入论文位置
- 正文 Figure（错误类型分布）：替换当前占位表格
- 替换为 `\includegraphics{figures/error_distribution.pdf}`

---

## P1-⑦ 超参数敏感性曲线

### 目标
为 4 个关键超参数绘制连续敏感性曲线。

### 执行
需要对每个超参数值运行完整 5×5 评估。

```bash
# τ_stag 敏感性
for tau in 0.60 0.65 0.70 0.75 0.80; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/prism.db \
    --sizes "5x5" --seed 42 \
    --output results/P1/sensitivity_stag_${tau}.csv
    # TODO: 需要命令行参数覆盖 stagnation_jaccard
    # 或修改 config 文件后运行
done

# θ 敏感性（需要重建离线范式库）
for theta in 0.15 0.20 0.25 0.30 0.35; do
  python scripts/run_offline.py \
    --config config/default.yaml \
    --model "GPT-4o" \
    --n-puzzles 600 --n-runs 3 \
    --output paradigm_store/prism_theta${theta}.db \
    --resume  # 复用轨迹，仅重新聚类
    # TODO: 需要命令行参数覆盖 cluster_distance
  
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/prism_theta${theta}.db \
    --sizes "5x5" --seed 42 \
    --output results/P1/sensitivity_theta_${theta}.csv
done

# K_top 敏感性
for k in 1 2 3 4 5; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/prism.db \
    --sizes "5x5" --seed 42 \
    --output results/P1/sensitivity_ktop_${k}.csv
    # TODO: 需要命令行参数覆盖 paradigm_top_k
done

# R 敏感性
for r in 3 4 5 6 8; do
  python scripts/run_online.py \
    --model "GPT-4o" \
    --library paradigm_store/prism.db \
    --sizes "5x5" --seed 42 \
    --max-repair $r \
    --output results/P1/sensitivity_R_${r}.csv
done
```

### 绘图脚本

```python
# scripts/plot_sensitivity.py
import matplotlib.pyplot as plt
import pandas as pd

fig, axes = plt.subplots(2, 2, figsize=(10, 8))

# 读取并绘制每组超参数的结果
# ... (读取 CSV，提取准确率)

for ax, param, vals in zip(axes.flat, 
    [r"$\tau_{stag}$", r"$\theta$", r"$K_{top}$", "$R$"],
    [stag_results, theta_results, ktop_results, R_results]):
    ax.plot(vals["param"], vals["accuracy"], "o-")
    ax.set_xlabel(param)
    ax.set_ylabel("Accuracy (%)")
    ax.axvline(x=default_val, color="red", linestyle="--", alpha=0.5)

plt.tight_layout()
plt.savefig("figures/sensitivity.pdf", dpi=300)
```

### 写入论文位置
- 附录 B（超参数敏感性详细分析）：替换占位表格为真实曲线图

### 预计成本
- τ_stag: 5 个值 × 180 题 × ~5 调用 = 4,500 次
- θ: 5 个值需重建范式库（复用轨迹）+ 评估 = 4,500 + 离线验证
- K_top: 5 × 180 × 5 = 4,500
- R: 5 × 180 × 5 = 4,500
- 总计约 18,000 次调用 ≈ $360

---

## P2-⑧ 案例研究时序图

### 目标
从真实 trace 中选取一个典型案例，绘制修复时序图。

### 执行

```python
# scripts/plot_repair_timeline.py
# 从 JSONL trace 中选取一个包含停滞→策略切换→成功的典型案例

import json

# 找到包含 stagnation + successful repair 的案例
with open("results/P0/prism_full_trace_seed42.jsonl") as f:
    for line in f:
        record = json.loads(line)
        steps = record.get("steps", [])
        has_stagnation = any(s.get("stagnated") for s in steps)
        solved = record.get("solved", False)
        if has_stagnation and solved and record["domain"] == "4x5":
            # 输出时序表
            print(f"Puzzle: {record['puzzle_id']}")
            for i, step in enumerate(steps):
                print(f"Step {i}: action={step.get('action')}, "
                      f"z3={step.get('z3_result')}, "
                      f"core_size={len(step.get('unsat_core', []))}, "
                      f"stagnated={step.get('stagnated', False)}")
            break
```

### 绘图
用 TikZ 或 pgfplots 绘制时序图，横轴为步骤，纵轴标注事件。

### 写入论文位置
- 附录 C（案例研究可视化）：替换占位表格

---

## P2-⑨ 跨模型范式库差异分析

### 目标
比较不同 LLM 产生的范式库在覆盖度和风格上的差异。

### 执行

```bash
# 用 Llama-3-70B 重建离线��式库
python scripts/run_offline.py \
  --model "Llama-3-70B" \
  --n-puzzles 600 --n-runs 3 \
  --output paradigm_store/prism_llama70b.db

# 对比两个范式库
python -c "
from prism.paradigm_library.library import ParadigmLibrary
gpt_lib = ParadigmLibrary('paradigm_store/prism.db')
llama_lib = ParadigmLibrary('paradigm_store/prism_llama70b.db')
# 比较范式数量、类型分布、平均置信度等
"
```

### 写入论文位置
- 附录或讨论部分补充一段分析

---

## 执行优先级与时间表

| 优先级 | 实验 | 预计成本 | 预计耗时 | 依赖 |
|--------|------|---------|---------|------|
| **P0** | ① 主表全量实验 | ~$2,700 | 3-5 天 | 范式库就绪 |
| **P0** | ② VERGE baseline | $0-500 | 1-2 天 | 论文/代码获取 |
| **P0** | ③ Logic-LM++ baseline | $0-500 | 1-2 天 | 论文/代码获取 |
| **P0** | ④ 多 LLM 实验 | ~$1,500 | 2-3 天 | API 配置 |
| **P1** | ⑤ 手工规则基线 | ~$50 | 0.5 天 | 脚本开发 |
| **P1** | ⑥ 错误类型直方图 | $0 | 0.5 天 | ①的 trace 数据 |
| **P1** | ⑦ 超参数曲线 | ~$360 | 1-2 天 | 范式库就绪 |
| **P2** | ⑧ 案例时序图 | $0 | 0.5 天 | ①的 trace 数据 |
| **P2** | ⑨ 跨模型范式差异 | ~$500 | 1 天 | ④完成 |

**总预计成本**：约 $5,000-6,000（GPT-4o 定价）
**总预计耗时**：约 10-15 天（P0 与 P1 部分可并行）

---

## 结果写入论文的检查清单

完成实验后，依次替换以下位置的占位数字：

- [ ] Table 2（主表）：所有行所有列
- [ ] Table 3（修复效率 5×5）：所有行
- [ ] Table 4（多规模修复效率）：所有斜体数值
- [ ] Figure（错误类型分布）：替换为真实直方图
- [ ] Table 5（范式库统计）：成功轨迹数、KDP 数、压缩比、验证分数
- [ ] Table 6（消融 5×5）：所有行
- [ ] Table 8（手工规则对比）：HR 行
- [ ] Table 9（多 LLM）：Llama-3 和 o1-mini 行
- [ ] Table 7（跨规模迁移）：所有行
- [ ] Table（跨域迁移）：所有指标
- [ ] §6.1 分析文字：根据真实增益模式调整叙述
- [ ] 摘要末尾：更新最亮数字
- [ ] 附录 B（超参数敏感性）：替换为真实曲线
- [ ] 附录 C（案例时序）：选取真实案例
- [ ] 附录 D（计算成本）：替换为真实测量值
