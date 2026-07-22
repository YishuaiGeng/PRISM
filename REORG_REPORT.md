# 仓库整理完成报告（PRISM / SPARC 分离）

> 执行日期：2026-07-22 ｜ 分支：`chore/repo-reorg`（`main` 未动）
> 还原点：tag `pre-reorg`（含整理前 WIP+未跟踪文件快照）；
> `results/` 整理前 tar 快照见 scratchpad `results_backup_prereorg.tar.gz`。
> 验证：全程 **486 tests passed**；关键脚本 CLI + SPARC 审计读新路径均实测通过。

## 已完成（按提交）

| 提交 | 阶段 | 内容 |
|---|---|---|
| `2f322b1` | P0 | 快照 WIP+未跟踪文件（还原点）；tag `pre-reorg` |
| `37584f2` `e9ccb7c` | P1 | 文档按工作分 `docs/{prism,sparc,surveys,archive}`；第三份 LaTeX 归档 |
| `f00cbe1` | P2 | 退休 `api/` → `archive/legacy_api/`；删 legacy 对照测试 |
| `e8e767b` | P3 | 脚本分 `scripts/{prism,sparc,shared}`；修 sys.path/跨import/测试import |
| `72ea9c5` | P4 | 结果分 `results/{prism,sparc}`；改脚本默认路径；`RESULTS_INDEX.md` |
| `f3aad7f` | P5 | 双工作 README；`guided_solver.py` 标 SPARC π-gate 边界 |
| （本提交） | P6 | gitignore 构建产物 + 取消跟踪；本报告 |

## 关键改动明细

- **docs/**：PRISM 稿/笔记 → `docs/prism/`（`latex_build/` + `latex_canonical/` 两树均保留）；
  SPARC 稿/笔记 → `docs/sparc/`（含 `authorkit/`=AAAI-27 模板、`paper_A_method_definition.md`）；
  8 个 survey html → `docs/surveys/`；第三份 LaTeX + 分叉报告 → `docs/archive/`。
  **重要发现**：两份 PRISM LaTeX 树的"分叉"纯属 CRLF vs LF，正文逐字节相同
  （详见 `docs/archive/prism_latex_fork_diff.md`）。
- **scripts/**：29 脚本 + 2 shell 按工作分组；`scripts/ENTRYPOINTS.md` 为复现索引。
  修复：21 处 `sys.path` 深度 +1、2 处 `project_root`、6 处跨脚本 import、13 处测试 import。
- **results/**：SPARC 白名单目录 → `results/sparc/`（23 项），其余 → `results/prism/`（342 项）；
  按组批量更新脚本读/写默认路径（`results/prism/` 与 `results/sparc/`）。
- **api/** 退休：`prism/core/{api_client,llm_api}.py` + `config/api/` 为唯一现役实现。
- **代码**：`prism/online/guided_solver.py` 尾部（`_sparc_gate` 等 8 方法）已用
  `# === SPARC π-gate BEGIN/END ===` 标注为 SPARC 专属，**逻辑零改动**。

## 留给你决策的开放项（本次未动）

1. **两份 PRISM LaTeX 树去重**：内容相同（仅行尾差异），建议保 `latex_build/`、归档
   `latex_canonical/`，并加 `.gitattributes`（`*.tex text eol=lf`）。等你拍板。
2. **SPARC π-gate 是否从 `guided_solver.py` 抽独立模块**：本次只加注释边界，未抽。
3. **`SUBMISSION_TODO.md`** 仍在根目录（PRISM 投稿路线图）——是否移入 `docs/prism/`，你定。
4. **`docs/sparc/authorkit/`（AAAI-27 模板）**：已按"SPARC 目标=AAAI-27"归入 SPARC，
   若并非用于此投稿请改归 `docs/archive/`。
5. **合并回 main**：当前全部工作在 `chore/repo-reorg` 分支。确认无误后
   `git checkout main && git merge chore/repo-reorg`。
6. **`results/prism/` 边界存疑项**（`zebra_offline_*`、`probe_*` 等）若实为 SPARC，按
   `RESULTS_INDEX.md` 末尾说明迁移即可。

## 如何回滚

- 整体回滚：`git checkout main`（main 停在整理前 `a781cc2`）。
- 回到"整理前含 WIP"状态：`git checkout pre-reorg`。
- 仅恢复 results 原始布局：解压 scratchpad 的 `results_backup_prereorg.tar.gz`。
