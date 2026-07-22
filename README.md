# PRISM + SPARC 单仓双工作

本仓库承载**两个研究工作**，共用同一套底层代码包 `prism/`（LLM 翻译 + Z3 求解 + 基准评测）：

| | **PRISM**（旧） | **SPARC / SBW**（新） |
|---|---|---|
| 全称 | Paradigm-guided Reasoning with Iterative Solver Memory | Satisfiable but Wrong: Solver-Decidable Abstention for LLM Constraint Formalization |
| 一句话 | 离线挖"求解范式库" + 在线引导求解 + 修复记忆 | LLM 形式化"可满足但错误(SBW)" → 求解器可判定的弃权门控(π-gate) 做选择性预测 |
| 目标会议 | AAAI-2026 草稿 | AAAI-27（working target） |
| 论文/笔记 | [`docs/prism/`](docs/prism/) | [`docs/sparc/`](docs/sparc/)（主稿 `sparc_paper_zh.tex`）+ 研究工件 [`ara/`](ara/) |
| 入口脚本 | [`scripts/prism/`](scripts/prism/) | [`scripts/sparc/`](scripts/sparc/) |
| 结果产物 | `results/prism/` | `results/sparc/` |
| 产物库 | `paradigm_store/*.db` | — |

> **关键纠缠点**：不存在独立的 `sparc/` 代码包。SPARC 的 π-gate 逻辑内嵌在 PRISM 的
> `prism/online/guided_solver.py` 尾部（`# === SPARC π-gate BEGIN ===`，`sparc=True` 时激活），
> 两个工作共用 `prism/core/*` 与 `prism/evaluation/benchmarks/*`。这是"一包两工作"，
> 靠 `scripts/` 与 `docs/`、`results/` 的分组区分，而非物理拆分核心代码。

## 导航

- **入口与复现命令**：[`scripts/ENTRYPOINTS.md`](scripts/ENTRYPOINTS.md) — 两个工作各自的 从零复现命令序列 + 每个脚本的输入/输出
- **结果产物索引**：[`results/RESULTS_INDEX.md`](results/RESULTS_INDEX.md) — 每个产物目录/文件族的归属与生产脚本
- **本次整理方案**：[`REORG_PROMPT.md`](REORG_PROMPT.md) — 目录重组的完整规则与分阶段计划
- **归档**：[`archive/`](archive/)（退休的 `legacy_api/`）、[`docs/archive/`](docs/archive/)（第三份 LaTeX 拷贝、LaTeX 分叉对比报告）

## 目录结构

```
prism/                      # 共享代码包（两工作共用；guided_solver.py 尾部含 SPARC π-gate）
├── core/                   # 共享：solver / translator / llm_api / api_client / llm_client / types
├── evaluation/benchmarks/  # 共享：zebralogic / arlsat / logical_deduction / knights_knaves
├── offline/                # PRISM-only：轨迹→KDP→聚类→抽象→Z3验证
├── paradigm_library/       # PRISM-only：范式库存储/检索
└── online/                 # guided_solver.py(共享) + repair_memory/strategy_switcher(PRISM-only)
scripts/{prism,sparc,shared}/   # 按工作分组的入口脚本（见 ENTRYPOINTS.md）
docs/{prism,sparc,surveys,archive}/
results/{prism,sparc}/      # gitignored；仅 RESULTS_INDEX.md 入库
ara/                        # SPARC 研究工件（claims/trace/evidence）
config/                     # 共享；experiments/*.yaml 属 PRISM
tests/                      # 486 tests
```

## 快速开始

```bash
pip install -e .

# 数据准备（共享）
python scripts/shared/download_datasets.py --datasets zebralogic arlsat

# PRISM 复现主线
python scripts/prism/run_offline.py --config config/default.yaml --output paradigm_store/prism.db
python scripts/prism/run_online.py  --config config/default.yaml --library paradigm_store/prism.db

# SPARC 复现主线（详见 scripts/ENTRYPOINTS.md）
python scripts/sparc/multimodel_eval.py --models GPT-4o-mini --limit 5 --execute-paid
python scripts/sparc/audit_sparc_evidence.py   # 无 LLM，读 results/sparc/ 缓存 trace

# 测试
pytest -q
```

## 配置

- `config/default.yaml` / `config/quick_test.yaml` — PRISM 离线/在线
- `config/experiments/{ablation,generalization}.yaml` — PRISM 实验（`run_experiments.py`）
- `config/api/*.json` — API/模型配置（两工作共享；`api_configs.json` 在 gitignore 中，参 `.example`）
- SPARC 脚本多为 flag-driven，无专用 YAML
