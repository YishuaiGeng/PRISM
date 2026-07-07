# PRISM 离线管道修复与轨迹采集进度

> 最后更新：2026-07-07  
> 当前分支：main（最新 commit c835f02）

---

## 一、问题根因（已修复）

离线管道此前从未成功挖出有效正向范式，根因有三：

| 问题 | 根因 | 修复状态 |
|---|---|---|
| KDP 条件 A/C 从不触发 | `TrajectoryStep.domain_sizes_before/after` 始终是空字典，`TrajectoryCollector` 从未填充 | ✅ 已修复（commit d7c8410） |
| 聚类门槛过高 | `cluster_min_size=5`，而 64 条旧轨迹每类型 KDP < 5 | ✅ 已修复（commit 8044f30，降为 2） |
| 轨迹数量不足 | 原始轨迹仅 64 条，KDP 总计 43 个，无法支撑聚类 | ✅ 已新增采集（见第三节） |

---

## 二、代码修复记录

### commit d7c8410 — `feat: populate domain_sizes_before/after in TrajectoryCollector`

**修改文件：**
- `prism/core/solver.py`：新增 `get_constraints() -> list[str]` 和 `get_variables() -> list[str]`
- `prism/offline/trajectory_collector.py`：新增 `_compute_domain_sizes()` 模块函数和 `_puzzle_n_houses()` 静态方法；在 `_solve_once()` 修复循环中，每次 repair 前后各调用一次 `_compute_domain_sizes()` 填充字段
- `tests/conftest.py`：新增 `MockLLMClient` fixture
- `tests/test_trajectory_collector.py`：新增 2 个测试（`test_domain_sizes_populated_after_repair`、`test_domain_sizes_decrease_after_constraint`）

**原理：** 对当前 solver 中的每个 Z3 整型变量，枚举 `[1..n_houses]` 范围内有多少个值与当前约束集相容（一次小型 Z3 探测），���果存入 `domain_sizes_before`（LLM 调用前）和 `domain_sizes_after`（solver.check() 后）。

### commit 8044f30 — `config: lower cluster_min_size from 5 to 2`

**修改文件：** `config/default.yaml`

```yaml
# 修改前
cluster_min_size: 5
# 修改后
cluster_min_size: 2
```

---

## 三、轨迹采集现状

### 3.1 新采集批次（2026-07-07）

| 目录 | 谜题规格 | 计划轨迹 | 实际采集 | 完成度 | Solved率 | CONTRADICTION步骤 | domain_sizes已填充 |
|---|---|---|---|---|---|---|---|
| `batch_3x_v2` | 3x3/3x4，easy/medium，×3 runs | 1200 | **1200** | ✅ 100% | 23% | 976 | 1868步 |
| `batch_4x5x_v2` | 4x5/5x5，medium/hard，×3 runs | 960 | **758** | ⚠️ 79% | 23% | 867 | 1426步 |
| `batch_5x6x_v2` | 5x6/6x5，medium/hard，×3 runs | 600 | **453** | ⚠️ 75% | 21% | 564 | 901步 |
| `gpt4omini_3x_v2` | 3x3/3x4/4x5，medium，×3 runs | 300 | **300** | ✅ 100% | 23% | 253 | 483步 |
| **新批次合计** | — | **3060** | **2711** | **89%** | — | **2660** | **4678步** |

> **缺口说明：**  
> - `batch_4x5x_v2` 缺 202 条（API 中断）  
> - `batch_5x6x_v2` 缺 147 条（API 中断）  
> - 当前不补采集，直接用现有 2711 条开始挖掘

### 3.2 旧有轨迹（参考，不再使用）

| 目录 | 轨迹数 | Solved率 | 备注 |
|---|---|---|---|
| `gpt4o_3x3_valid_audit` | 20 | 60% | GPT-4o，无 domain_sizes |
| `gpt4o_easy_correct_audit` | 16 | 100% | GPT-4o，无 domain_sizes |
| `gpt4o_easy_valid_audit` | 16 | 31% | GPT-4o，无 domain_sizes |
| `gpt4o_mini_audit` | 4 | 75% | 无 domain_sizes |
| `gpt4o_mini_audit_v2` | 4 | 50% | 无 domain_sizes |

---

## 四、已有范式库现状

### 4.1 正向范式库（Positive Paradigm Library）

| 文件 | 范式数 | avg_confidence | avg_support | scope 分布 | 来源 |
|---|---|---|---|---|---|
| `prism_v2.db` | **4** | 1.0 | 65.25 | inclusion×3, exclusion, all_different, ordering, logical_implication | gpt4omini_3x_v2（300条） |
| `prism_v2_smoke.db` | 3 | 1.0 | 4.67 | inclusion×2, logical_implication×2 | gpt4o_3x3_valid_audit（20条，smoke test） |
| `prism_3x_v2.db` | **7** | 1.0 | 153.43 | inclusion×3, exclusion×4, ordering, logical_implication×2, all_different | batch_3x_v2（1200条） |
| `gpt4o_3x3_positive_fixed.db` | 2 | 1.0 | 6.0 | inclusion, logical_implication | 旧版，仅 schema 级平凡范式 |

> **注意：** 当前正向范式 scope 均为 schema 级约束（inclusion/all_different 等），尚未挖出关系型修复范式。`batch_4x5x_v2`/`batch_5x6x_v2` 尚未挖掘，预计会有更有意义的范式。

### 4.2 错误范式库（Error Paradigm Library）

| 文件 | 范式数 | avg_support | scope | 来源 |
|---|---|---|---|---|
| `mined_relation_templates.db` | 1 | 10.0 | directly_left, directly_right | controlled repair 10条小集 |
| `mined_somewhere_left.db` | 1 | 4.0 | somewhere_left, somewhere_right | controlled repair 小集 |
| `mined_direct_position.db` | 1 | 10.0 | direct_position | controlled repair 小集 |
| `gpt4o_mini_error_audit_v2.db` | 5 | 1.2 | inclusion, logical_implication | 旧轨迹，无 replacement_policy |
| `gpt4o_mini_error_audit.db` | 3 | 1.0 | direct_position, inclusion | 旧轨迹，无 replacement_policy |

> **待挖掘：** `batch_3x_v2`/`batch_4x5x_v2`/`batch_5x6x_v2` 的错误范式库尚未建立。

---

## 五、Full Pipeline 实验结果

| 实验 | 数据 | 准确率 | pos_guidance | err_guidance | 备注 |
|---|---|---|---|---|---|
| LLM+Z3 baseline（旧） | 3x eval 150 | 88.7% (133/150) | 0 | 0 | 无范式库 |
| PRISM（空库） | 3x eval 150 | 91.3% (137/150) | 0 | 8 | mined_relation_templates 触发 8 次 |
| LLM+Z3 baseline（新） | 3x eval 150 | 94.0% (141/150) | 0 | 0 | API 不确定性导致与旧结果有差异 |
| PRISM v2（prism_v2.db） | 3x eval 150 | 93.3% (140/150) | **1** | 6 | 首次确认正向范式触发 ✅ |

> **结论：** `prism_v2.db` 的 4 个范式（schema 级）有触发信号，但未带来准确率提升。需要挖掘 batch_4x5x/5x6x 获得更有意义的修复型范式。

---

## 六、受控修复实验结果（已完成，最强证据）

| 规模 | Perturbation | No-Memory | Mined-Memory | Δpp | p值 |
|---|---|---|---|---|---|
| 3x3/3x4 | direct_position | 32.7% (49/150) | 80.7% (121/150) | +48.0 | <0.001*** |
| 3x3/3x4 | directly_left | 91.5% (130/142) | 100% (142/142) | +8.5 | <0.001*** |
| 3x3/3x4 | somewhere_left | 86.4% (51/59) | 100% (59/59) | +13.6 | <0.01** |
| 5x5/6x5 | direct_position | 36.0% (36/100) | 67.0% (67/100) | +31.0 | <0.001*** |
| 5x5/6x5 | directly_left | 94.0% (94/100) | 100% (100/100) | +6.0 | <0.05* |
| 5x5/6x5 | somewhere_left | 85.6% (77/90) | 100% (90/90) | +14.4 | <0.001*** |

> 使用 McNemar's test（精确或卡方）。Mined library 从 10 条 disjoint 小集挖掘，与评估集无重叠。

---

## 七、下一步计划

### 立即可做（不需要更多采集）

```powershell
# 1. 挖掘 batch_4x5x_v2 正向范式
python scripts/run_offline.py --config config/default.yaml --model GPT-4o-mini --resume --trajectories data/trajectories/batch_4x5x_v2 --output paradigm_store/prism_4x5x_v2.db

# 2. 挖掘 batch_5x6x_v2 正向范式
python scripts/run_offline.py --config config/default.yaml --model GPT-4o-mini --resume --trajectories data/trajectories/batch_5x6x_v2 --output paradigm_store/prism_5x6x_v2.db

# 3. 挖掘各批次错误范式
python scripts/extract_error_paradigms.py --trajectories data/trajectories/batch_3x_v2 --output paradigm_store/error_3x_v2.db --min-support 3
python scripts/extract_error_paradigms.py --trajectories data/trajectories/batch_4x5x_v2 --output paradigm_store/error_4x5x_v2.db --min-support 2
python scripts/extract_error_paradigms.py --trajectories data/trajectories/batch_5x6x_v2 --output paradigm_store/error_5x6x_v2.db --min-support 2

# 4. 验证新库效果
python scripts/run_online.py --data-dir data/hf/zebralogic/generated_3x_eval_domain_explicit_150.jsonl --data-source local --model GPT-4o-mini --library paradigm_store/prism_4x5x_v2.db --error-library paradigm_store/error_4x5x_v2.db --max-repair 3 --sizes 3x3,3x4 --schema-hint-mode puzzle --output results/full_pipeline_4x5x_prism.csv
```

### 待补齐（可选）

- `batch_4x5x_v2` 缺 202 条，`batch_5x6x_v2` 缺 147 条，可补采集：
  ```powershell
  # 补采 batch_4x5x（接续已有数据，需修改脚本跳过已生成 puzzle）
  # 或直接用现有 758/453 条，已足够支撑挖掘
  ```

---

## 八、文件位置速查

| 内容 | 路径 |
|---|---|
| 离线管道脚本 | `scripts/run_offline.py` |
| 错误范式挖掘脚本 | `scripts/extract_error_paradigms.py` |
| 在线推理脚本 | `scripts/run_online.py` |
| 受控修复脚本 | `scripts/run_controlled_repair_benchmark.py` |
| 实验汇总脚本 | `scripts/summarize_repair_suite.py` |
| 范式库（gitignored） | `paradigm_store/*.db` |
| 轨迹数据（gitignored） | `data/trajectories/batch_*/` |
| 实验结果 CSV | `results/` |
| 本文档 | `docs/OFFLINE_PIPELINE_PROGRESS.md` |
| 实验计划 | `docs/superpowers/plans/2026-07-06-offline-pipeline-repair.md` |
