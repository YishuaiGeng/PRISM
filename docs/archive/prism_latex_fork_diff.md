# PRISM LaTeX 两树对比报告（不自动合并，待用户决策）

> 生成：2026-07-22，整理 Phase 1 期间。
> 对比对象：
> - `docs/prism/latex_build/`（原 `docs/2026-AAAI-PRISM/`）——编译工作目录
> - `docs/prism/latex_canonical/`（原 `docs/paper_draft/aaai2026_prism/`，其 README 自称推荐入口）

## 结论（重要）

**两份 LaTeX 源在正文上逐字节相同——所谓"分叉"完全是 CRLF vs LF 行尾差异造成的假象。**
之前的自动对比（含 `git`/`diff` 原始比较）把每一行都报成"不同"，实为行尾符不同：
- `latex_build/` 用 LF；`latex_canonical/` 用 CRLF。
- 用 `diff --strip-trailing-cr -b` 复核，所有共有 `.tex/.bib/.sty/.bst` 的**真实差异行数 = 0**。

验证样本（strip-CR 后真实改动行数）：

| 文件 | 原始diff行 | 真实改动行(strip-CR) |
|---|---|---|
| `main_final.tex` | 148 | **0** |
| `sections/methodology.tex` | 508 | **0** |
| `sections_final/methodology.tex` | 392 | **0** |
| `sections_final/experiments.tex` | 266 | **0** |
| `sections_supp/appendix_a_algorithms.tex` | 190 | **0** |
| `aaai2026.bib / .sty / .bst` | 多 | **0** |

## 两树真正的（非行尾）区别 = 各自多出的文件

**只有 `latex_build/` 有：**
- 备用入口与其构建产物：`main.tex`、`main_english.*`、`supp.tex`、`supp_english.*`
  （`.aux/.bbl/.blg/.fls/.fdb_latexmk/.log/.synctex.gz`）
- 已编译 PDF：`main_english.pdf`、`main_final.pdf`、`supp_english.pdf`
- `tmp/`（构建临时目录，含 pdf 转 png）
- 3 个散落 md：`ablation_matrix.md`、`benchmark_extension_plan.md`、`experiment_design.md`
  —— 经核对是 `docs/prism/review_notes/` 同名文件的**精确副本**（可删）

**只有 `latex_canonical/` 有：**
- `README.md`（自称推荐入口：`main_final.tex` + `sections_final/`）
- `compiled_reference/`（从原草稿目录复制来的 PDF 参考版）

两树都含相同的 `sections/`（含早期 `_new.tex` 重写版）、`sections_final/`、`sections_supp/`（附录 A–G）、`figures/`。

## 建议（留给用户拍板，本次不执行）

既然正文完全一致，无需"合并"，只需二选一去重：

1. **推荐：保留 `latex_build/` 为唯一 PRISM LaTeX 目录**——它含完整入口（main_final + main_english + supp）
   和最新编译 PDF；把 `latex_canonical/` 归档（或只保留其 `README.md` 说明并入 latex_build）。
   顺手删掉 latex_build 内 3 个与 review_notes 重复的 md。
2. 备选：反过来以 `latex_canonical/` 为准（它更"干净"、无构建产物），但需从 latex_build 补回
   `main_english/supp` 入口与已编译 PDF。
3. 统一行尾：给该目录加 `.gitattributes`（`*.tex text eol=lf`）避免以后再被 CRLF 制造假分叉。

> 决策前两树均原样保留在 `docs/prism/latex_build/` 与 `docs/prism/latex_canonical/`。
