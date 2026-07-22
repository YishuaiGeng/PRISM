# SPARC 论文待跑实验记录

> 更新于 2026-07-18。记录**尚未跑**的实验、命令、成本、结果去向。
> 已跑并写入论文的：RQ1 普遍性 + SBW×能力×难度（3 模型）、RQ2 检出+去键名、
> RQ3 门控 Pareto 占优 B1/B4/B5（GPT-4o-mini）、RQ4 受控配对补全消融、AR-LSAT 诊断佐证。

## 2026-07-18 审稿修复（已完成的免实验部分）
- 论文文本：去键名口径升为主报告口径（摘要/结论 81.3/82.3 主数字）；摘要/结论范围
  收窄为"唯一答案任务的答案投影唯一性"；§5.3 补绝对计数（门控 12 作答 1 错等）+
  "个位数波动"统计限定；§3.4 候选补全压缩，式(5)+命题3+证明下沉新附录 app:completion；
  B3 从"超出范围"改为明确后续对比项。
- 代码：$V_A$ 答案变量白名单已机械实现（`guided_solver` 新参数 `sparc_va_mode`，
  默认 whitelist，从 `visible_schema_keys` 题面推导、不读金标，无匹配回退 all_int 并
  在 trace 记 `va_mode`；`run_online.py --sparc-va-mode`；`audit_sparc_evidence.uniqueness_probe`
  加 `answer_keys` 参数供离线重放）。**论文所有已报告数字仍是 all_int 口径**，白名单
  重放见下方待做实验 0b。

## 通用注意事项
- 跑任何脚本前**确保工作目录在 repo 根** `D:/Papers/PRISM`（Bash cwd 曾漂移到 figures 导致 redirect 失败、python 没执行）。
- 前置 `HF_HUB_OFFLINE=1` 读本地缓存，避免 HF 网络重试。
- 付费脚本必须显式 `--execute-paid`。
- API 端点（api2.aigcbest.top）**偶发 SSL 断连**，付费任务**串行**跑、失败重试；大任务放后台。
- 论文里所有 `\TODO{...}`（红字加粗）= 待填占位，投稿前必须清零。

---

## 待做实验 0a：主对比扩样（审稿 W1，最高优先）

**目的**：把 §5.3 风险-覆盖率对比从 78 金标（30 作答 SAT、18 SBW）扩到
**全部 200 金标 × 3 次重复**的冻结门控前状态，目标主对比 SBW ≥ 100，并给所有
操作点加 bootstrap 区间。消掉"18 个 SBW 撑不起'优于基线'"这一最大硬伤，同时修复
表3（200×3）与表5（78）样本量不对称。
**就绪度**：🟢 冻结协议 `run_frozen_sparc.py` + `baseline_abstain_zebra.py`/
`multimodel_eval.py` 均在位；门控与 B0 免费（离线重放），B1/B4/B5 付费
（B4 最贵：+5 次形式化 × 新增题）。
**结果去向**：表5 重做 + 图4 重生成；§5.3"说明"段的样本量限定随之改写；摘要
"78 题金标子集"措辞放宽。

## 待做实验 0b：V_A 白名单敏感性（免费，离线）

**目的**：用新实现的 `answer_keys` 白名单口径重放 `tab:gate-diagnostic` 的全部
冻结 SAT 状态，报告 whitelist vs all_int 的检出/误伤差异（论文 §6"接口边界"已
承诺该敏感性分析）。
**就绪度**：🟢 `audit_sparc_evidence.uniqueness_probe(constraints, answer_keys=...)`
已支持；调用侧把 `visible_schema_keys(puzzle)` 归一化后传入即可（参照
`prism.core.model_validation.normalise_schema_key`）。零成本。
**结果去向**：§5.2 加一行敏感性结论；若差异显著，需在 §6 相应改口径描述。

## 待做实验 0c：B3 直接作答自一致性基线（审稿 W4，便宜）

**目的**：补上与门控"零额外调用"卖点竞争最直接的免训练信号：同题集 N=5 次
**直接作答**（不经形式化）投票，t-of-N 扫描，进表5/图4 同一坐标系。
**成本**：5 次直接作答 × 对比题集（78 或扩样后 200）。比 B4 便宜（无形式化+求解）。
**就绪度**：🟡 需小脚本（可仿 `baseline_abstain_zebra.py` 加直接 QA 提示词）。
**结果去向**：表5 加 B3 行；§5.1 基线家族表 tab:baseline-props 的 B3 行由
"超出范围"改为实测。

---

## 待做实验 1：E4 — AR-LSAT 方法评测（最贵，约 2800 调用）

**目的**：把 AR-LSAT 从"仅诊断佐证"升级为**第二个基准上的方法评测**，直接消掉审稿人"单基准"质疑。
**验证**：结构门控（选项良定 / could-be-true 实例化）在不同任务形式（选择题）上是否成立。
**就绪度**：🟢 `scripts/run_arlsat.py --pi-gate` 已实现门控 + 右/错/弃答三值账本；数据 `data/hf/ar-lsat/{dev,test,train}.jsonl` 在位。**无需建代码。**

**命令**（GPT-4o-mini，baseline 臂 vs 门控臂）：
```bash
# 先小样验证（--max-puzzles 20，几毛钱）确认管线通
HF_HUB_OFFLINE=1 python scripts/run_arlsat.py --model GPT-4o-mini --max-puzzles 20 \
  --output results/arlsat_gate_test.csv --trace-output results/arlsat_gate_test.trace.jsonl --pi-gate

# 全量两臂
HF_HUB_OFFLINE=1 python scripts/run_arlsat.py --model GPT-4o-mini \
  --output results/arlsat_baseline.csv --trace-output results/arlsat_baseline.trace.jsonl
HF_HUB_OFFLINE=1 python scripts/run_arlsat.py --model GPT-4o-mini --pi-gate \
  --output results/arlsat_gate.csv --trace-output results/arlsat_gate.trace.jsonl
```
**成本**：AR-LSAT 每题需 passage 形式化 + 5 个选项形式化（≈6+ 调用），×测试集（~230 题）×2 臂 ≈ **2800+ 调用**。最贵项。
**结果去向**：
- §5.2（RQ2）里 AR-LSAT 选项门控的检出/误伤 → 替换该段的 `\TODO`。
- 可在 §5.3（RQ3）加一行 AR-LSAT 的门控 vs baseline 风险-覆盖率。
- AR-LSAT 从"诊断"升格后，§5.1"AR-LSAT 用于跨任务诊断"措辞相应放宽。
**caveat**：良定门控是 could-be-true 判定模式（非唯一性），与 ZebraLogic 的 g_π 不同，写清楚。

---

## 待做实验 2：全量多模型 RQ1/RQ2/RQ3（贵，可用 --sizes 砍成本）

**目的**：填 GPT-4o、DeepSeek-V3.2 在**全集**上的 SBW 率 / 检出 / 基线对比，把当前"仅 GPT-4o-mini 主证据 + 难格探针"扩成完整多模型评测。
**验证**：RQ1/RQ2/RQ3 结论跨形式化器稳健（消"单模型"）。
**就绪度**：🟢 `scripts/multimodel_eval.py` 全就绪（B0/B1/B4/B5/B★ + 结构门控，`--schema-hint-mode puzzle` 无金标）。

**命令**：
```bash
HF_HUB_OFFLINE=1 python scripts/multimodel_eval.py \
  --models GPT-4o,DeepSeek-V3.2 --scorable-only --baselines b1,b5 --sc-samples 5 \
  --out-dir results/multimodel_full --execute-paid
```
**成本**：~434 金标 ×(1 无门控 + 5 自一致性)×~3.5 ×2 模型 ≈ **18k+ 调用**。很贵。
砍法：`--sizes 3x3,4x4,5x3,6x3,6x4`（78 金标）或 `--sc-samples 3` 降样本。
**结果去向**（跑完后一键扩）：
- `tab:prevalence`（RQ1）的 GPT-4o/DeepSeek 行（现为 `\TODO`）。
- `tab:gate-diagnostic`（RQ2）扩多模型行 + §5.2 RQ2 的 `\TODO`。
- §5.3（RQ3）的 `\TODO`：在 GPT-4o、DeepSeek 上重复 B1/B4/B5 对比。
- **填完后把摘要/贡献3/结论的"ZebraLogic + GPT-4o-mini"口径放宽到"2 基准 × N 模型"**（现在故意窄写、诚实）。

---

## 其余小 TODO（论文内 `\TODO`，多数免费/低成本）
- **去 oracle 全集口径**：当前 §5.2 去键名 81.3/82.3% 是难格/历史态；若要全集口径，用 `scripts/deoracle_q1.py`（免费，离线）。
- **V_A / 超时敏感性**（§5.5 RQ4 尾）：离线扫，免费。
- **数据配置差异待统一**⚠️：论文写 640/200/16规模，但当前 `load_zebralogic` 是 **1000/434/25规模**（历史 GPT-4o-mini 跑的是旧 640/200）。新全量跑会用新配置 → 决定"统一到旧 16 规模"还是"全部重基线到新配置"，影响所有数字口径。**整理文章时先定这个。**

## 已跑实验的复现入口
- 去键名 Q1：`scripts/deoracle_q1.py`
- 拒答基线（结构门控 vs 自一致性）：`scripts/baseline_abstain_zebra.py`
- 难格×能力探针：`results/probe_hard_cap/`（GPT-4o、DeepSeek-V3.2 trace）
- RQ3 多基线：`results/rq3_gpt4omini/summary.json`（gate+B0+B1+B4）
- B5 往返：`scripts/b5_on_trace.py` → `results/b5_roundtrip.json`
- E5 受控配对消融：`results/frozen_gate_only.jsonl`（k=0）vs `results/frozen_sparc_k3.jsonl`（k=3）
- 图：`docs/paper_draft/figures/gen_fig_baseline_rc.py`、`gen_fig_risk_coverage.py`
