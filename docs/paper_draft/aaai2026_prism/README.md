# AAAI 2026 PRISM Draft

这是 PRISM 的 AAAI 2026 LaTeX 草稿目录。

## 推荐编辑入口

- `main_final.tex`：当前推荐主稿入口，使用 `sections_final/`。
- `sections_final/`：当前整理后的主稿分节。
- `supp_english.tex`：补充材料入口。
- `sections_supp/`：补充材料分节。

## 历史/中间稿

- `main_english.tex`：较早的英文主稿入口，使用 `sections/`。
- `sections/`：早期分节和 `_new.tex` 重写版本，保留用于比对。
- `compiled_reference/`：从原草稿目录复制的 PDF 参考版本。

## 编译命令

```bash
latexmk -pdf main_final.tex
latexmk -pdf supp_english.tex
```

如果只想清理主稿编译产物：

```bash
latexmk -C main_final.tex
```

## 文件说明

- `aaai2026.sty`、`aaai2026.bst`：AAAI 2026 样式文件。
- `aaai2026_english.bib`：当前推荐主稿使用的参考文献文件。
- `aaai2026.bib`：早期主稿使用的参考文献文件。
- `figures/`：论文图和图说明。
