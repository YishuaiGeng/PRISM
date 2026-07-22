# results/ 产物索引（按工作分目录）

> `results/` 本身在 `.gitignore` 中（本地数据，不入库）；仅本索引文件被跟踪。
> 2026-07-22 整理：全部产物已物理拆分为 `results/prism/` 与 `results/sparc/`。
> 整理前的完整快照见 scratchpad `results_backup_prereorg.tar.gz`（12M）。

## results/sparc/ — SPARC / SBW 产物（23 项）

| 路径 | 生产脚本 | 说明 |
|---|---|---|
| `zebra_v2_s42/`, `zebra_v2_s123/`, `zebra_v2_s7/` | multimodel/在线 no-gate 跑批 | 主 trace 语料（各臂 baseline/basesparc/nopar/noparsparc/full） |
| `zebra_v2_4o/` | 同上，GPT-4o formalizer | |
| `zebra_ablation_s42/` | 组件消融跑批 | blind-completion / no-invariant 臂（audit `--ablation-dir`） |
| `zebra_main_s42/` | `rescore_zebra_results.py` | 被重打分的 ZebraLogic 主跑 |
| `zebra_sparc_s42/` | 早期 SPARC 臂 | 仅日志 |
| `sparc_evidence_audit/`, `sparc_evidence_audit_smoke/` | `audit_sparc_evidence.py` | audit.json/md, pairing_audit.csv, gate_diagnostic.csv 等 |
| `frozen_pairing_s42/`, `frozen_gate_only.*`, `frozen_s42_baseline.*`, `frozen_sparc_k3.*` | `run_frozen_sparc.py` | 冻结门控前瞻配对各臂 + manifest |
| `arlsat_gate_probe/` | AR-LSAT 良定性门控 pilot | audit `--arlsat-dir` |
| `multimodel_smoke/`, `rq3_gpt4omini/`, `rq3_gpt4omini.log` | `multimodel_eval.py` | 多模型 RQ1/2/3 |
| `b5_roundtrip.json`, `b5.log` | `b5_on_trace.py` | B5 round-trip 基线 |

## results/prism/ — PRISM 产物（342 项，家族归纳）

| 文件族 | 生产脚本 | 说明 |
|---|---|---|
| `arlsat_*`（half/seed/calib/smoke/probe/offline logs，**除** gate_probe） | `run_arlsat.py`, offline | AR-LSAT 评测/离线跑批 |
| `controlled_repair_*` | `run_controlled_repair_benchmark.py` | 受控修复回路基准 |
| `repair_suite_*` | `run_repair_benchmark_suite.py` | 修复基准全套扰动 |
| `generated_*`, `generated60_*`, `generated150_*` | 在线跑批（自生成谜题） | 各种 memory/normalize/coverage 变体 |
| `memory_*`, `schema_*`, `size_*`, `smoke_*`, `domain_explicit_*`, `prepared_*` | 在线消融/探针 | 记忆/schema/规模消融 |
| `full_pipeline_*` | 端到端流水线对比 | baseline vs prism |
| `llm_base_*` | LLM 基线跑批 | |
| `v3_*`, `logs/` | `run_v3_validation.{sh,ps1}` | v3 验证 |
| `gpt4o_*`, `pipeline_*`, `post_todo_*`, `probe_*`, `traj_verify/`, `zebra_mini_*`, `zebra_offline_*`, `zebra_probe_*` | 各类离线/在线探针与审计 | |

> 归属规则：SPARC = 上表白名单；其余一律 PRISM。边界存疑项（如 `zebra_offline_*` 离线日志、
> `probe_*`）归为 PRISM；若日后发现某项其实属 SPARC，从 `results/prism/` 移到 `results/sparc/`
> 并更新对应脚本默认路径即可。
