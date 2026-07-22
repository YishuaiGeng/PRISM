# 入口脚本索引（PRISM / SPARC 双工作）

> 脚本按工作分目录：`scripts/prism/`、`scripts/sparc/`、`scripts/shared/`。
> 所有脚本从**仓库根**运行（脚本内部 `sys.path` 已自动把根加入路径）：
> `python scripts/<group>/<name>.py ...`

## 关键纠缠点（务必知道）
- 不存在独立的 `sparc/` 代码包。**SPARC 的 π-gate 逻辑内嵌在 PRISM 的
  `prism/online/guided_solver.py`**（`sparc=True` / `_sparc_gate` / `sparc_max_completions`
  / `sparc_repair_budget` / `sparc_blind_completion` / `sparc_no_invariant`）。
  两个工作共用 `prism/core/*` 与 `prism/evaluation/benchmarks/*`。
- 因此本仓库是"一包两工作"，靠本目录的分组区分入口，而非物理拆分核心代码。

---

## PRISM（旧：范式库 + 求解器修复记忆，AAAI-2026）

论文/笔记见 `docs/prism/`。产物库 `paradigm_store/*.db`，评测产物 `results/prism/`（见 `results/RESULTS_INDEX.md`）。

复现主线：
```bash
# 1) 数据（共享）
python scripts/shared/download_datasets.py --datasets zebralogic arlsat

# 2) 离线：轨迹→KDP→聚类→抽象→Z3验证→建范式库
python scripts/prism/run_offline.py --config config/default.yaml --output paradigm_store/prism.db

# 3) 在线：加载范式库评测 ZebraLogic
python scripts/prism/run_online.py --config config/default.yaml --library paradigm_store/prism.db

# 4) 消融/泛化实验
python scripts/prism/run_experiments.py --experiment ablation      # config/experiments/ablation.yaml
python scripts/prism/run_experiments.py --experiment generalization
```

| 脚本 | 作用 |
|---|---|
| `prism/run_offline.py` | 离线范式蒸馏流水线 → `paradigm_store/*.db` |
| `prism/run_online.py` | ZebraLogic 在线引导求解评测 |
| `prism/run_experiments.py` | 消融/泛化实验驱动 |
| `prism/run_arlsat.py` | AR-LSAT 在线评测 |
| `prism/run_logical_deduction.py` | BBH LogicalDeduction 评测 |
| `prism/run_controlled_repair_benchmark.py` | 受控修复回路基准 |
| `prism/run_repair_benchmark_suite.py` | 修复基准扫全套扰动 |
| `prism/run_clue_coverage_replay.py` | 无 LLM 重放固定 SAT clue-coverage 修复状态 |
| `prism/extract_error_paradigms.py` | 从轨迹抽取错误范式库 |
| `prism/quick_verify.py` | 实现完整性 smoke 自检 |
| `prism/verify_arlsat_trajectories.py` | AR-LSAT 轨迹答案判定 |
| `prism/audit_pipeline.py` | 无 API 的流水线产物审计 |
| `prism/summarize_online_csvs.py` / `summarize_repair_suite.py` / `summarize_trace_jsonl.py` | 结果汇总 |
| `prism/test_5x6_puzzle.py` | 5×6 谜题手工验证 |
| `prism/run_v3_validation.ps1` / `.sh` | v3 验证批处理 |

---

## SPARC / SBW（新：可满足但错误 → 选择性弃权，AAAI-27）

论文/笔记见 `docs/sparc/`（主稿 `sparc_paper_zh.tex`）；研究工件见 `ara/`。
主 trace 语料 `results/sparc/zebra_v2_s{42,123,7}/`。多为 flag-driven，无专用 YAML。

复现主线：
```bash
python scripts/shared/download_datasets.py --datasets zebralogic

# 多模型 RQ1/2/3 harness（付费，需 --execute-paid）
python scripts/sparc/multimodel_eval.py --models GPT-4o-mini --limit 5 --execute-paid

# 前瞻配对的冻结门控实验（prepare 冻结无门控输入，run 回放各臂）
python scripts/sparc/run_frozen_sparc.py prepare --source-dir results/sparc/zebra_v2_s42 ...
python scripts/sparc/run_frozen_sparc.py run --arm sparc_k3 ...

# 无 LLM 的证据/溯源审计（读缓存 trace）
python scripts/sparc/audit_sparc_evidence.py --zebra-dir results/sparc/zebra_v2_s42 \
  --arlsat-dir results/sparc/arlsat_gate_probe --ablation-dir results/sparc/zebra_ablation_s42
```

| 脚本 | 作用 |
|---|---|
| `sparc/run_frozen_sparc.py` | 冻结门控前瞻配对实验（各臂 replay）→ `results/sparc/frozen_*` |
| `sparc/audit_sparc_evidence.py` | 无 LLM 证据/溯源审计 → `results/sparc/sparc_evidence_audit/`（被下列脚本 import） |
| `sparc/multimodel_eval.py` | 多模型 RQ1/2/3 harness → `results/sparc/multimodel/`, `rq3_gpt4omini/` |
| `sparc/b5_on_trace.py` | 在既有 trace 上跑 B5 round-trip 基线（import `multimodel_eval`） |
| `sparc/deoracle_q1.py` | 去 oracle 重跑 Q1 唯一性诊断（stdout） |
| `sparc/baseline_abstain_zebra.py` | Q2：结构 π-gate vs 自一致性弃权 |
| `sparc/budget_sweep_zebra.py` | 补全预算 k 扫描 → 风险-覆盖曲线 |
| `sparc/rescore_zebra_results.py` | 用修正 answers_match 重打分 ZebraLogic CSV |
| `sparc/sparc_runtime_stats.py` | SPARC 运行时统计（π-gate 分布 / wall-clock） |

内部依赖：`baseline_abstain_zebra` / `deoracle_q1` / `multimodel_eval` / `run_frozen_sparc`
均 `from scripts.sparc.audit_sparc_evidence import ...`；`b5_on_trace` `from scripts.sparc.multimodel_eval import ...`。

---

## shared（数据准备 / 通用工具）

| 脚本 | 作用 |
|---|---|
| `shared/download_datasets.py` | 从 HuggingFace 下官方基准 → `data/` |
| `shared/generate_zebra_jsonl.py` | 生成本地 Zebra JSONL（import `add_zebra_domains_to_puzzle_text`） |
| `shared/add_zebra_domains_to_puzzle_text.py` | 给 ZebraLogic JSONL 加显式候选值域 |
| `shared/filter_trace_subset.py` | 过滤在线 trace JSONL 成可复用评测子集 |
