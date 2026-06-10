# PRISM Paper Draft Workspace

这个目录集中存放 PRISM 论文写作相关材料，包括中文梳理、AAAI LaTeX 草稿、修订评审笔记和通用中文论文模板。

## 目录结构

- `aaai2026_prism/`：PRISM 的 AAAI 2026 LaTeX 草稿工作区。
- `source_notes_zh/`：从 `docs/paper/` 复制过来的中文分节梳理材料。
- `review_notes/`：论文重写总结、审稿视角审查、实验设计和提交准备清单等辅助材料。
- `templates/`：原 `docs/paper_draft` 中的通用中文论文模板，保留为以后复用。

## 推荐入口

继续写 PRISM 英文主稿时，优先编辑：

```text
aaai2026_prism/main_final.tex
aaai2026_prism/sections_final/*.tex
```

补充材料入口：

```text
aaai2026_prism/supp_english.tex
aaai2026_prism/sections_supp/*.tex
```

中文内容参考：

```text
source_notes_zh/*.md
```

## 编译

进入 `aaai2026_prism/` 后编译主稿：

```bash
latexmk -pdf main_final.tex
```

编译补充材料：

```bash
latexmk -pdf supp_english.tex
```

已有 PDF 参考版本放在：

```text
aaai2026_prism/compiled_reference/
```

## 来源说明

- `source_notes_zh/` 来自 `docs/paper/`。
- `aaai2026_prism/` 来自 `docs/2026-AAAI-PRISM/` 中的论文源文件、章节、参考文献、AAAI 样式文件和图片。
- `review_notes/` 汇总了根目录和 `docs/` 下与论文修订、实验设计、投稿准备相关的 Markdown 笔记。
- 原通用中文模板移动到 `templates/`，没有和 PRISM 正文混合。

原始目录暂未删除，方便回溯和比对。
