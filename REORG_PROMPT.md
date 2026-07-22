# 仓库整理提示词（PRISM + SPARC 双工作分离）

> 用途：把这份文件整段作为提示词交给一个编码 agent（或新会话的 Claude Code）执行。
> 目标：在**同一个仓库**内把两个研究工作（PRISM / SPARC-SBW）的**入口、文档、产物**按工作清晰分离，
> 归档明显废弃物，但**不拆成两个仓库、不改动核心代码包 `prism/` 的逻辑**。
> 生成时间：2026-07-22。执行前请先读完"红线规则"再动手。

---

## 0. 背景：这个仓库里有两个工作

| | **PRISM**（旧） | **SPARC / SBW**（新） |
|---|---|---|
| 全称 | Paradigm-guided Reasoning with Iterative Solver Memory | Satisfiable but Wrong: Solver-Decidable Abstention for LLM Constraint Formalization |
| 一句话 | 离线挖"求解范式库" + 在线引导求解 + 修复记忆 | LLM 形式化约束"可满足但错误(SBW)"→ 用求解器可判定的**弃权门控(π-gate)** 做选择性预测 |
| 目标会议 | AAAI-2026 草稿（已有编译 PDF） | AAAI-27（working target） |
| 主稿 | `docs/2026-AAAI-PRISM/` 与 `docs/paper_draft/aaai2026_prism/`（两份已分叉） | `docs/paper_draft/sparc_paper_zh.tex` + `ara/` 研究工件 |
| 状态 | 代码实现完整，实验有占位 | 三种子锁表完成，正在补去oracle/拒答baseline |

**两个工作后续都要继续做。** 因此本次整理的原则是"分清楚、留退路"，不是"二选一删掉"。

### 关键纠缠点（务必理解，否则会拆错）
- **不存在独立的 `sparc/` 代码包。** SPARC 的核心 π-gate 逻辑**内嵌在 PRISM 的
  `prism/online/guided_solver.py`** 里（`sparc=True` / `_sparc_gate` / `sparc_max_completions` /
  `sparc_repair_budget` / `sparc_blind_completion` / `sparc_no_invariant`，共约 26 处引用）。
  → 这个文件是**共享文件**，本次整理**只加边界注释、绝不物理拆分**。
- 两个工作共用底层：`prism/core/*`（solver / translator / llm_api / api_client / llm_client / types /
  model_validation）与 `prism/evaluation/benchmarks/*`（zebralogic / arlsat / …）。
  → `prism/` 包整体**原地不动**，本次只重组 `scripts/` `results/` `docs/`。

---

## 1. 精确文件地图（整理依据，执行时以此为准）

### 1.1 `prism/` 模块归属（**不移动**，仅供理解与注释）

| 模块 | 归属 |
|---|---|
| `prism/offline/*`（trajectory_collector, trajectory_clusterer, paradigm_abstractor, paradigm_verifier, kdp_identifier, error_paradigm_extractor） | **PRISM-only** |
| `prism/paradigm_library/*`（library, error_library, retriever, schema） | **PRISM-only** |
| `prism/online/repair_memory.py`, `strategy_switcher.py`, `candidate_pool.py`, `feature_extractor.py` | **PRISM-only** |
| `prism/online/guided_solver.py` | **共享**（PRISM 在线求解 + SPARC π-gate 同居一文件） |
| `prism/core/*`（solver, translator, llm_api, api_client, llm_client, generator, constraint_tags, model_validation, types） | **共享** |
| `prism/evaluation/benchmarks/*`, `metrics.py`, `transfer_rate.py` | **共享**（arlsat.py 含 SPARC 的 AR-LSAT 门控端口 WellDefinednessGate） |

### 1.2 `scripts/` 入口分类（**要移动**到 `scripts/{prism,sparc,shared}/`）

> 执行时：对每个脚本读 docstring + import 确认归属；下表是起始分类，遇到与实际不符以实际为准，
> 不确定的放 `scripts/shared/` 并在 `ENTRYPOINTS.md` 标注"待归类"。

**PRISM 入口** → `scripts/prism/`
- `run_offline.py` — 离线范式蒸馏流水线（收集→聚类→抽象→验证→建库）→ `paradigm_store/*.db`
- `run_online.py` — ZebraLogic 在线引导求解评测
- `run_experiments.py` — 消融/泛化实验驱动（`config/experiments/*.yaml`）
- `run_arlsat.py` — AR-LSAT 在线评测
- `run_logical_deduction.py` — BBH LogicalDeduction 评测
- `run_controlled_repair_benchmark.py` — 受控修复回路基准
- `run_repair_benchmark_suite.py` — 修复基准扫全套扰动
- `extract_error_paradigms.py` — 从轨迹抽取错误范式库
- `quick_verify.py` — 实现完整性 smoke 自检
- `summarize_repair_suite.py`, `summarize_online_csvs.py` — PRISM 结果汇总
- `verify_arlsat_trajectories.py`, `audit_pipeline.py`, `test_5x6_puzzle.py`, `add_zebra_domains_to_puzzle_text.py`, `run_v3_validation.ps1/.sh`

**SPARC 入口** → `scripts/sparc/`
- `run_frozen_sparc.py` — 前瞻配对的冻结门控实验（prepare/run 各臂）→ `results/frozen_*.jsonl`
- `audit_sparc_evidence.py` — 无 LLM 的证据/溯源审计 → `results/sparc_evidence_audit/`
- `deoracle_q1.py` — 去 schema/key-set oracle 重跑 Q1 唯一性诊断（仅 stdout）
- `baseline_abstain_zebra.py` — Q2：结构 π-gate vs 自一致性弃权（风险-覆盖）
- `budget_sweep_zebra.py` — 补全预算 k 扫描 → 风险-覆盖曲线
- `rescore_zebra_results.py` — 用修正后的 answers_match 重打分 ZebraLogic CSV
- `multimodel_eval.py` — 多模型 RQ1/2/3 harness → `results/multimodel/`, `rq3_gpt4omini/`
- `b5_on_trace.py` — 在既有 trace 上只跑 B5 round-trip 基线（依赖 `multimodel_eval` 的函数）
- `sparc_runtime_stats.py` — SPARC 运行时统计（π-gate 分布/wall-clock）

**共享/数据准备** → `scripts/shared/`
- `download_datasets.py` — 从 HuggingFace 下官方基准 → `data/`
- `generate_zebra_jsonl.py` — 生成本地 Zebra JSONL
- `filter_trace_subset.py`, `summarize_trace_jsonl.py`, `run_clue_coverage_replay.py` — **待确认**（读 import 判定归 sparc 还是 shared）

### 1.3 `results/` 产物分类（**要移动**到 `results/{prism,sparc}/`）

> ⚠️ 移动前必读 §2 红线规则第 2 条——脚本里有硬编码默认路径。

**SPARC 产物** → `results/sparc/`
- `zebra_v2_s42/`, `zebra_v2_s123/`, `zebra_v2_s7/`, `zebra_v2_4o/` — 主 trace 语料
- `zebra_main_s42/`, `zebra_sparc_s42/`, `zebra_ablation_s42/`
- `sparc_evidence_audit/`, `sparc_evidence_audit_smoke/`
- `frozen_s42_baseline.jsonl`(+manifest), `frozen_gate_only.jsonl`, `frozen_sparc_k3.jsonl`, `frozen_pairing_s42/`
- `arlsat_gate_probe/`
- `multimodel_smoke/`, `rq3_gpt4omini/`, `b5_roundtrip.json`, `b5.log`

**PRISM 产物** → `results/prism/`
- `arlsat_half*/`, `arlsat_seed123/`, `arlsat_seed456/`, `probe_*/`
- `repair_suite_*/`, `controlled_repair_*`, `traj_verify/`
- `full_pipeline_*.jsonl`, `generated_*.jsonl`, `memory_*`, `schema_ablation_*`

> 边界模糊项（如 `arlsat_half` vs `arlsat_gate_probe`）：读目录内文件的生产脚本痕迹判定；
> 不确定就在 `RESULTS_INDEX.md` 记为"待确认"，**不要猜删**。

### 1.4 `docs/` 整理（去重 + 分工作 + 归档）

**PRISM 论文/笔记** → `docs/prism/`
- `2026-AAAI-PRISM/`（编译目录，有 PDF）与 `paper_draft/aaai2026_prism/`（自称 canonical 的源）
  → **两份已分叉，见 §2 红线第 4 条：只出 diff 报告，不自动合并**
- `paper/`（中文分节笔记）与 `paper_draft/source_notes_zh/`（**是 paper/ 的重复拷贝**）→ 去重保一份
- `paper_draft/PRISM_AAAI_chinese_polished.md` 及 `_polishing_notes.md`
- `paper_draft/review_notes/` 中 PRISM-era 的：`PAPER_REVISION_SUMMARY.md`, `REVISION_GUIDE.md`,
  `PRISM_paper_review.md`, `experiment_design.md`, `PRISM_experiment_design.md`, `ablation_matrix.md`,
  `benchmark_extension_plan.md`, `figure_specs.md`, `AAAI-2026-PAPER-PREPARATION-GUIDE.md`
- 顶层散落 md 归位到此：`PAPER_PREPARATION_GUIDE.md`, `PAPER_REVISION_SUMMARY.md`, `QUICK_START.md`,
  `SOLVING_PROCESS.md`, `IMPLEMENTATION_CHECKLIST.md`, `TEST_5x6_RESULTS.md`, `analysis_report.md`

**SPARC 论文/笔记** → `docs/sparc/`
- `paper_draft/sparc_paper_zh.tex`（主稿）, `sbw_intro_related_zh.tex`（引言+相关工作重写）
- `paper_draft/review_notes/sbw_related_work_map.md`, `sparc_aaai_rewrite_audit_zh.md`
- `paper_draft/figures/`（fig_motivation / fig_baseline_rc / fig_risk_coverage + 生成脚本）
- `paper_draft/pending_experiments.md`
- 关联说明：`ara/`（SPARC 研究工件，**保留原位不动**，在 `docs/sparc/README.md` 里指过去即可）
  - ⚠️ `ara/PAPER.md` 引用的 `docs/paper_draft/sparc_summary_and_reviewer_defense.md` **当前不存在**，
    在 `docs/sparc/README.md` 记一条 TODO

**背景 survey**（8 个 html）→ `docs/surveys/`
- `agent_memory_trajectory_survey`, `neuro_symbolic_agent_landscape`, `neuro_symbolic_research_directions`,
  `neurosymbolic_agent_solver_survey`, `paradigm_memory_system_design`, `prism_detailed_review`,
  `work_background_innovation_feasibility`, `prism_naming_resources_framework`

**归档** → `docs/archive/`
- `docs/6a4cfb3ead8c02dc3f9d922b/`（第三份 hash 命名 LaTeX 拷贝，疑 Overleaf 导出）
- `docs/AuthorKit27/`（AAAI-2027 author kit 模板；若确定要用于 SPARC 投稿则移 `docs/sparc/authorkit/`，
  否则归档——执行时问用户或先归档）
- 去重后多余的那份 `paper/` 或 `source_notes_zh/`

### 1.5 顶层废弃 → `archive/`
- `api/`（2026-05 旧拷贝，已被 `prism/core/api_client.py` `prism/core/llm_api.py` 取代，
  配置已迁 `config/api/`）。**唯一引用**是 `tests/test_api_config_env.py` 里的
  `import api.llm_api as LegacyLLMAPI` 做回归对照 → 见 §2 红线第 3 条处理。
- `.playwright-mcp/`（浏览器日志，非工作产物，可归档或 gitignore）

### 1.6 SPARC 专属测试（保留在 `tests/`，若脚本移动需同步改 import）
- `test_sparc.py`, `test_run_frozen_sparc.py`, `test_audit_sparc_evidence.py`,
  `test_arlsat_gate.py`, `test_llm_seed.py`

---

## 2. 红线规则（违反会破坏可复现性或丢内容，执行前必读）

1. **先建安全网。** 动手前：`git add -A && git commit -m "chore: snapshot before reorg"`（或打 tag
   `pre-reorg`）。全程用 `git mv` 移动以保留历史，**禁止** `rm` 删除——废弃物一律 `git mv` 到
   `archive/` 或 `docs/archive/`。

2. **移动 `results/` 会撞硬编码默认路径。** 多个脚本把 `results/zebra_v2_*`、`results/zebra_ablation_s42`、
   `results/arlsat_gate_probe`、`results/sparc_evidence_audit`、`results/multimodel`、`results/rq3_gpt4omini`
   以及 `data/hf/zebralogic`、`data/hf/ar-lsat` 写成默认值。移动产物后必须：
   - `grep -rn "results/" scripts/ prism/`（同理 `paradigm_store/`）找出所有字符串字面量路径；
   - 同步更新脚本里的**默认值**为新路径（`results/sparc/...`）；保留 `--flag` 覆盖能力不变；
   - `data/` 是否移动：本次**建议 `data/` 原地不动**（两工作共用输入），只移 `results/`。

3. **`api/` 归档要先处理它的唯一引用。** `tests/test_api_config_env.py` 里
   `import api.llm_api`。两种做法二选一（推荐前者）：
   - (a) 把该测试中对 `api/` 的旧对照断言删掉/skip，只保留对 `prism.core.llm_api` 的测试，再归档 `api/`；
   - (b) 若想留回归对照，把 `api/` 移到 `archive/legacy_api/` 后更新该测试的 import 路径并确保
     `archive/` 在 import 可达（加 `__init__` 或调 sys.path）。
   改完**必须** `pytest tests/test_api_config_env.py` 绿。

4. **两份 PRISM LaTeX 树：只 diff、不合并。** 生成 `docs/archive/prism_latex_fork_diff.md`，内容为
   `docs/2026-AAAI-PRISM/`（编译目录，有 PDF）与 `docs/paper_draft/aaai2026_prism/`（自称 canonical）
   逐文件 diff 概要（`main_final.tex`、`sections_final/*.tex` 已知不同；`main_english.tex` 已知相同）。
   **两份都先保留**（分别放 `docs/prism/latex_build/` 与 `docs/prism/latex_canonical/`），
   在报告末尾列出待用户决策项，**不要自动合并或删除任一份**。

5. **移动 `scripts/` 会撞跨脚本 import 与测试 import。**
   - `b5_on_trace.py` 从 `multimodel_eval.py` 导入函数（同目录假设）——两者都在 `scripts/sparc/` 则 OK；
     否则修 import。全面 `grep -rn "^from \|^import " scripts/` 找同目录相互依赖。
   - `tests/test_*.py` 里对脚本的 import（如 `test_run_frozen_sparc.py`）路径要随之更新。
   - 每个脚本子目录加 `__init__.py`（若测试以包方式 import）。
   - 移动后 **`pytest` 全绿是本阶段完成的硬标准**。

6. **不改 `prism/` 代码逻辑。** 本次只允许对 `prism/online/guided_solver.py` 加**注释区块**标出 SPARC
   π-gate 边界（`# === SPARC π-gate BEGIN/END ===`），不改任何行为。是否将 π-gate 抽成独立模块
   留作后续决策（见 §4）。

7. **`.gitignore` 已 tracked 的构建产物要 `git rm --cached`。** 很多 `.aux/.log/.fls/.fdb_latexmk/.bbl/.blg/`
   `.synctex.gz`、`tmp/pdfs/*.png`、`__pycache__/`、`.pytest_cache/` 已被 git 跟踪，只加 `.gitignore`
   不会取消跟踪，需 `git rm -r --cached` 后再提交。

---

## 3. 分阶段执行（每阶段结束 = 验证通过 + 一次 git commit）

**Phase 0 — 安全准备**
- 确认 `git status`；`git commit`/`git tag pre-reorg` 建快照。
- 建目录骨架：`scripts/{prism,sparc,shared}/`、`results/{prism,sparc}/`、
  `docs/{prism,sparc,surveys,archive}/`、`archive/`。

**Phase 1 — 文档整理（最低风险，先做）**
- 按 §1.4 用 `git mv` 归位 PRISM/SPARC/survey 文档；去重 `paper/` vs `source_notes_zh/`（保一份，另一份归档）。
- 生成 §2-4 的 LaTeX diff 报告；两份 LaTeX 树分别改放 `latex_build/` `latex_canonical/`。
- 顶层散落 md 归位（`README.md` / `SUBMISSION_TODO.md` 是否留根目录见下）。
- 验证：`git status` 干净、无悬空引用；commit。

**Phase 2 — 废弃归档**
- 按 §1.5 + §2-3 归档 `api/`（并处理 `test_api_config_env.py`）、`docs/6a4c…/`、`AuthorKit27`（或问用户）。
- 验证：`pytest tests/test_api_config_env.py` 绿；commit。

**Phase 3 — scripts 分目录**
- 按 §1.2 `git mv` 脚本到 `scripts/{prism,sparc,shared}/`；加 `__init__.py`（如需）。
- 修跨脚本 import 与 `tests/` 中脚本 import（§2-5）。
- 写 `scripts/ENTRYPOINTS.md`：两个工作各自的"从零复现命令序列"（PRISM: download → run_offline →
  run_online / run_experiments；SPARC: download → multimodel_eval / run_frozen_sparc → audit_sparc_evidence），
  标注每个脚本 输入→输出 路径，并记录 guided_solver.py 纠缠点。
- 验证：**`pytest` 全绿**；`python scripts/prism/quick_verify.py --mode full` 通过；commit。

**Phase 4 — results 分目录**
- 按 §1.3 `git mv` 产物到 `results/{prism,sparc}/`。
- 按 §2-2 grep 并更新所有脚本硬编码默认路径；边界模糊目录记入 `RESULTS_INDEX.md`。
- 写 `results/RESULTS_INDEX.md`：每个产物目录 → 生产脚本 + 所属工作 + 一句话说明。
- 验证：抽一条无需 API 的 SPARC 审计做冒烟（如 `python scripts/sparc/audit_sparc_evidence.py
  --zebra-dir results/sparc/zebra_v2_s42 ...` 的 dry/cached 路径能读到数据）；`pytest` 全绿；commit。

**Phase 5 — 代码边界注释 + README 重写**
- 在 `prism/online/guided_solver.py` 给 SPARC π-gate 相关方法/分支加 `# === SPARC π-gate ... ===`
  区块注释（不改逻辑）。
- 重写根 `README.md` 为**双工作导航页**：两个工作各一节（简介 / 主稿位置 / 入口脚本目录 /
  复现命令 / 产物位置 / 论文状态），并链接 `scripts/ENTRYPOINTS.md`、`results/RESULTS_INDEX.md`、
  `docs/prism/`、`docs/sparc/`、`ara/`。
- 验证：README 链接可达；commit。

**Phase 6 — 收尾**
- 更新 `.gitignore` + `git rm --cached` 取消跟踪构建产物（§2-7）。
- 全量 `pytest`；`git log --oneline` 复核；生成一页《整理报告》列出：移动清单、归档清单、
  改过默认路径的脚本、待用户决策项（§4）。commit。

---

## 4. 留给用户决策的开放项（提示词执行者遇到时先记录、不自作主张）

1. **是否把 SPARC π-gate 从 `guided_solver.py` 抽成独立模块**（如 `prism/online/sparc_gate.py`）。
   本次只加注释边界，不抽。抽离是后续重构，需专门跑回归。
2. **`results/` 约 200MB+ 且部分应否移出 git**（大 trace 目录是否 gitignore / 迁到外部存储 / git-lfs）。
   本次默认保留在仓库内、仅分目录。
3. **`docs/AuthorKit27/`（AAAI-2027 模板）归 SPARC 还是归档**——取决于 SPARC 是否投 AAAI-27。
4. **两份 PRISM LaTeX 树最终以哪份为准**（Phase 1 只出 diff 报告，合并由用户拍板）。
5. **是否给 SPARC 建 `config/sparc/*.yaml`**——当前 SPARC 脚本是 flag-driven，无 YAML 配置。
6. **根目录保留哪些 md**：建议只留 `README.md`（导航）+ 各工作的当前 TODO（`SUBMISSION_TODO.md` 归
   `docs/prism/` 还是留根，用户定）。

---

## 5. 目标结构一览（整理后）

```
PRISM/
├── prism/                     # 共享代码包（不动；guided_solver.py 为 PRISM+SPARC 共享）
├── scripts/
│   ├── prism/                 # PRISM 入口
│   ├── sparc/                 # SPARC 入口
│   ├── shared/                # 数据准备/通用工具
│   └── ENTRYPOINTS.md         # 两工作复现命令序列 + 纠缠点说明
├── results/
│   ├── prism/  ├── sparc/     # 按工作分产物
│   └── RESULTS_INDEX.md
├── docs/
│   ├── prism/                 # PRISM 论文(latex_build/ + latex_canonical/) + 笔记
│   ├── sparc/                 # SPARC 主稿 + 笔记 + figures（ara/ 在根，此处指过去）
│   ├── surveys/               # 背景 survey html
│   └── archive/               # 第三份 latex、LaTeX diff 报告等
├── ara/                       # SPARC 研究工件（原位保留）
├── config/                    # 共享；experiments/*.yaml 属 PRISM
├── paradigm_store/            # PRISM 产物库
├── archive/                   # api/ 旧拷贝等顶层废弃
├── tests/                     # 保留；脚本移动后同步 import
└── README.md                  # 双工作导航页
```
