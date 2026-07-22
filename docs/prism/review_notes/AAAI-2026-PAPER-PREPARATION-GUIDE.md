# AAAI 2026 PRISM Paper Preparation Guide

## Overview

This guide provides a comprehensive roadmap for completing, polishing, and submitting the PRISM paper to AAAI 2026. The paper is in advanced stages with solid Abstract, Introduction, Related Work, and Methodology sections. The primary focus now is completing the Experiments section with actual results and ensuring all AAAI formatting requirements are met.

**Current Status:**
- ✅ Abstract: Complete
- ✅ Introduction: Complete  
- ✅ Related Work: Complete
- ✅ Methodology: Complete
- 🔄 Experiments: Framework established, Results section needs content
- ✅ Conclusion: Complete

---

## Phase 1: Complete the Experiments Section (CRITICAL PATH)

### 1.1 Results Subsection Structure

The Results subsection needs to present empirical findings in a logical, evidence-driven sequence. Follow this structure:

```
Results
├── Main Accuracy Results
│   ├── Overall performance across puzzle sizes
│   ├── Comparison with baselines
│   └── Statistical significance/confidence intervals
│
├── Cost Analysis
│   ├── LLM calls comparison
│   ├── Token efficiency
│   └── Cost-accuracy trade-off
│
├── Repair Efficiency
│   ├── Stagnation reduction (core contribution)
│   ├── Paradigm trigger rates
│   └── Average repair rounds
│
├── Paradigm Transfer Analysis
│   ├── Paradigm hit rates
│   ├── Paradigm reusability patterns
│   └── Library growth dynamics
│
└── Ablation Studies
    ├── PRISM vs. memory-only variant
    ├── PRISM vs. paradigm-library-only variant
    └── Impact analysis of core components
```

### 1.2 Writing the Results Subsection

**Key Writing Principles:**
1. **Lead with strongest evidence**: Start with your most impressive results
2. **Use precise quantitative claims**: "PRISM achieved 89.3% accuracy" not "PRISM achieved high accuracy"
3. **Support claims with data**: Every major claim needs evidence (table, figure, or explicit numbers)
4. **Avoid interpretation in Results**: Save interpretation for discussion or analysis
5. **Be consistent with notation**: Use same names for baselines/methods throughout

**Template for Main Results:**

```latex
\paragraph{Main Results.}
PRISM achieved \textbf{X\%} accuracy on 4×4 puzzles, \textbf{Y\%} on 5×5, 
and \textbf{Z\%} on 6×6 puzzles, compared to baselines...

Table~\ref{tab:main_results} summarizes the performance across all 
baselines. PRISM achieved an average improvement of \textbf{V\%} over 
the next-best baseline...
```

### 1.3 Key Metrics to Report

For each experiment, ensure you report:

| Metric | Purpose | How to Present |
|--------|---------|-----------------|
| Solving Accuracy (%) | Success rate | Table by puzzle size, bar chart for visual comparison |
| LLM Calls per Puzzle | Cost efficiency | Box plot or mean ± std | 
| Repair Rounds | Algorithm efficiency | Histogram or box plot by puzzle size |
| Paradigm Trigger Rate (%) | Utility of library | Line plot showing how library grows |
| Paradigm Hit Rate (%) | Reusability | Table or scatter plot |
| Success + Confidence Intervals | Statistical rigor | Note sample sizes, mention if differences are significant |

### 1.4 Creating High-Quality Figures and Tables

**Table Best Practices:**
- Use clear column headers with metric definitions
- Include sample sizes (N) and confidence intervals where applicable
- Use `\textbf{}` for best results
- Add caption explaining what the table shows
- In caption, note if differences are statistically significant

**Example Table Structure:**
```latex
\begin{table}[t]
\centering
\caption{Accuracy (\%) and Cost Comparison Across Puzzle Sizes}
\begin{tabular}{lcccccc}
\hline
\textbf{Method} & \textbf{4×4} & \textbf{5×5} & \textbf{6×6} & 
\textbf{Avg.} & \textbf{LLM Calls} & \textbf{Repairs} \\
\hline
CoT & 75.0 & 45.2 & 12.5 & 44.2 & 5.2 & 0.3 \\
Logic-LM & 82.1 & 58.3 & 28.7 & 56.4 & 8.1 & 2.1 \\
\ldots \\
PRISM & \textbf{94.3} & \textbf{87.2} & \textbf{71.5} & 
\textbf{84.3} & \textbf{6.8} & \textbf{0.8} \\
\hline
\end{tabular}
\label{tab:main_results}
\end{table}
```

**Figure Best Practices:**
- Use clear axis labels with units
- Include legends distinguishing methods
- Use consistent colors across all figures
- Ensure text is readable at paper size (not too small)
- Add error bars for variability

### 1.5 Ablation Study Guidance

Ablation studies validate that each component contributes meaningfully:

**PRISM (Full):** Memory + Paradigm Library + Repair
**Ablation 1 (Memory Only):** Correct memory traces, no paradigm library  
**Ablation 2 (Library Only):** Paradigm library, no memory management

Show:
- How each ablation performs vs. full PRISM
- Which components are most critical
- Whether components are complementary or redundant

Example: "Memory alone improves over baseline by 12%, library alone by 8%, but together achieve 31% improvement (PRISM), indicating strong complementarity."

### 1.6 Analysis Subsection

After Results, add brief interpretation:

```latex
\subsection{Analysis}

\paragraph{Key Findings.}
[Synthesize main results - 2-3 sentences maximum]

\paragraph{Why PRISM Works.}
[Explain the mechanism - reference methodology and results]

\paragraph{Limitations.}
[Acknowledge trade-offs or constraints]
```

---

## Phase 2: Cross-Section Polish and Coherence

### 2.1 Internal Reference Audit

Run through these checks:

- [ ] All figures/tables cited before introduction (e.g., "see Table 1")
- [ ] All acronyms defined on first use (PRISM, CSP, etc.)
- [ ] Consistent terminology throughout (don't switch between "puzzle" and "instance")
- [ ] All citation formats consistent (author-year style)
- [ ] Section cross-references are accurate

**Command to Find Undefined References:**
```bash
grep -n "ref{" main.tex | grep -v "^[#%]"
```

### 2.2 Narrative Flow

Read the paper section by section and verify:

1. **Abstract → Introduction**: Does introduction expand on abstract promises?
2. **Introduction → Related Work**: Does intro properly motivate the gap related work fills?
3. **Related Work → Methodology**: Does methodology clearly address the gap identified in related work?
4. **Methodology → Experiments**: Does experimental setup match methodology claims?
5. **Experiments → Conclusion**: Do results support conclusion's claims?

### 2.3 Conclusion Strengthening

The conclusion should:
- Summarize main contributions (mirror abstract)
- Highlight key empirical findings  
- Discuss broader impact/applications
- Mention limitations and future work
- End with memorable insight

**Review Checklist for Conclusion:**
- [ ] Restates the problem in one sentence
- [ ] Summarizes PRISM's novelty (3-4 points)
- [ ] Points to key empirical evidence (reference results)
- [ ] Discusses why this matters (impact)
- [ ] Acknowledges limitations
- [ ] Suggests 2-3 concrete future directions

---

## Phase 3: AAAI-Specific Formatting and Requirements

### 3.1 Critical AAAI Rules (2026 Template)

✅ **MUST DO:**
- Use `\documentclass[letterpaper]{article}` with `aaai2026` package
- Format: 8.5" × 11" page size (already set in main.tex)
- Use `natbib` for citations (already configured)
- Include algorithms/listings if needed (packages provided)
- Ensure no page breaks in final version
- Submit as PDF generated from LaTeX

❌ **ABSOLUTELY FORBIDDEN:**
- `\usepackage{hyperref}` or `\usepackage{geometry}`
- `\usepackage{authblk}` - Use "Author 1, Author 2" format directly
- `\usepackage{balance}`, `\usepackage{multicol}`, `\usepackage{setspace}`
- Commands: `\newpage`, `\pagebreak`, `\clearpage`, `\nocopyright`
- Negative `\vspace` values near captions/sections
- Font: `\tiny` (use `\footnotesize` minimum)
- Color in text (only in figures/diagrams)

### 3.2 Precise Page Layout Requirements

**AAAI 2026 Constraints:**
- Anonymous submission: NO author names, affiliations, or identifying information
- Page limit: Check current AAAI guidelines (typically 8-9 pages + references)
- Margins: Must use aaai2026.sty defaults (do NOT adjust)
- Font: Times/Helvetica/Courier as specified in template (already set)
- Spacing: Single column, no column balancing

**Check Page Count:**
```bash
# After PDF generation, check page count
pdfinfo main.pdf | grep Pages
```

If exceeding limit, compress content:
1. Move non-essential details to appendix (if allowed)
2. Shorten Related Work: Keep only highly relevant work
3. Condense methodology if possible: Algorithmic clarity > narrative prose
4. Merge tables/figures where possible

### 3.3 Bibliography and Citation Format

**AAAI uses natbib author-year format:**

✅ Correct:
```latex
\cite{Smith2020}  % → Smith (2020)
\citep{Smith2020} % → (Smith, 2020)
\citet{Smith2020} % → Smith (2020)
```

**BibTeX Entry Checklist:**
- [ ] All referenced works in `.bib` file
- [ ] All `.bib` entries have: author, year, title, journal/conference
- [ ] No "to appear" or "in submission" citations (not allowed)
- [ ] URLs use `\url{}` command
- [ ] Capitalization follows sentence case for titles

**Verify Bibliography:**
```bash
# Check for missing citations in PDF
grep "CITATION" main.pdf  # Should be empty
```

### 3.4 Theorem/Lemma/Proof Formatting

If PRISM paper includes formal results:

```latex
\begin{theorem}
\label{thm:example}
[Statement here]
\end{theorem}

\begin{proof}
[Proof here]
\end{proof}
```

### 3.5 Algorithm Formatting

If including algorithms (recommended for methodology clarity):

```latex
\begin{algorithm}
\caption{PRISM Algorithm}
\label{alg:prism}
\begin{algorithmic}
\STATE Input: puzzle $P$, memory $M$, library $L$
\STATE Output: solution or \textit{failure}
\FOR{round $t = 1$ to $T$}
  \IF{memory suggests paradigm}
    \STATE retrieve paradigm from $L$
  \ELSE
    \STATE generate new paradigm
  \ENDIF
\ENDFOR
\end{algorithmic}
\end{algorithm}
```

---

## Phase 4: Pre-Submission Quality Checklist

### 4.1 Content Verification (15 min)

- [ ] **Abstract** (150-250 words): Clearly states problem, novelty, key results
- [ ] **Introduction** (1-2 pages): Motivates problem, positions PRISM, outlines contributions  
- [ ] **Related Work** (1 page): Covers LLM reasoning, logic, CSP, memory in AI
- [ ] **Methodology** (2 pages): Clear algorithmic description, understandable to readers unfamiliar with area
- [ ] **Experiments** (2 pages): Complete results, proper baselines, statistical rigor
- [ ] **Conclusion** (0.5 pages): Summarizes contributions and future directions
- [ ] **References** (1 page): All cited works present, no broken citations

### 4.2 Technical Correctness (30 min)

- [ ] **No technical errors**: Verify all claims in methodology have supporting evidence
- [ ] **Notation consistent**: Same symbols mean same things throughout
- [ ] **Baselines fairly compared**: Same computational budget/constraints for all methods
- [ ] **Results reproducible**: Hyperparameters, random seeds, dataset splits clearly specified
- [ ] **Statistical claims valid**: Use confidence intervals, mention sample sizes, avoid over-claiming

### 4.3 Writing Quality (30 min)

- [ ] **Clarity**: Every sentence is understandable on first read
- [ ] **Conciseness**: No unnecessary words; cut verbose explanations
- [ ] **Grammar**: Run spellchecker, check common mistakes (its/it's, than/then)
- [ ] **Consistency**: 
  - Same capitalization for method names (PRISM, not Prism or prism)
  - Same terminology throughout (don't switch between "puzzle" and "instance")
  - Consistent use of tenses (present for permanent facts, past for what was done)

**Grammar Check Tools:**
```bash
# Install Aspell and LanguageTool for LaTeX checking
# Use in your editor: many support grammar checking
```

### 4.4 Formatting Verification (20 min)

- [ ] **No forbidden packages**: Search main.tex for disallowed packages
- [ ] **No page breaks**: No `\newpage`, `\pagebreak`, or `\clearpage`
- [ ] **No negative spacing**: No `\vspace{-...}` near captions
- [ ] **Figures/Tables**: All have captions, are referenced in text
- [ ] **Margins**: Use defaults from aaai2026.sty (don't modify geometry)
- [ ] **Font sizes**: Minimum `\footnotesize` (no `\tiny`)
- [ ] **Bibliography compiles**: No missing citations when you run `bibtex`

**Verify No Forbidden Commands:**
```bash
grep -E "\\\\(newpage|pagebreak|clearpage|nocopyright)" main.tex
```
Should return empty.

### 4.5 PDF Generation and Inspection (20 min)

```bash
cd /Users/ysgeng/Documents/Papers/PRISM/docs/2026-AAAI-PRISM
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex
```

After PDF generation, manually check:
- [ ] Title appears centered, no author names
- [ ] Page layout matches expected (8.5" × 11")
- [ ] No overfull hbox warnings (text exceeding margins)
- [ ] Figure/table placement is reasonable
- [ ] Bibliography has correct format
- [ ] Hyperlinks are disabled (should be plain text)

### 4.6 Final Proofreading (Slow Read - 1 hour)

Read the PDF slowly, section by section, checking:

**Introduction (3 min):**
- Does it grab attention?
- Is the research gap crystal clear?
- Are contributions explicitly listed?

**Related Work (3 min):**
- Does it systematically cover the landscape?
- Is it clear how PRISM differs from each category?
- Does it avoid "strawman" characterizations of prior work?

**Methodology (5 min):**
- Could someone reimplement PRISM from this description?
- Are key design choices justified?
- Are parameters clearly specified?

**Experiments (5 min):**
- Do results clearly support methodology claims?
- Are comparisons fair (same resources, computation)?
- Does ablation clearly validate component importance?
- Are limitations/failure cases discussed?

**Conclusion (2 min):**
- Does it wrap up without introducing new ideas?
- Are future directions concrete and actionable?

---

## Phase 5: Day-Before-Submission Checklist

### 5.1 Final Compilation (15 min)

```bash
# Clean previous builds
rm -f main.pdf main.log main.aux main.bbl main.blg

# Fresh compile
pdflatex main.tex
bibtex main
pdflatex main.tex
pdflatex main.tex

# Verify PDF exists and is valid
file main.pdf  # Should show "PDF document, version ..."
pdfinfo main.pdf  # Check pages, title, etc.
```

### 5.2 Anonymous Submission Audit (10 min)

Before submitting, ensure complete anonymity:

```bash
# Search for potential identifying info in PDF
pdftotext main.pdf - | grep -i -E "author|name|affiliation|university|lab"
```

✅ Should find:
- References to "(Author et al., Year)"
- Acknowledgments mentioning "anonymous reviewers"

❌ Should NOT find:
- Your name
- Institution name
- Author bios

If you find identifying information:
1. Check all section files for author comments
2. Remove any acknowledgment sections that reveal identity
3. Check bibliography for self-citations that reveal identity (cite as "Author (2023)")
4. Recompile and recheck

### 5.3 Submission Platform Test (5 min)

1. Go to AAAI OpenReview/submission site
2. Create test account (or use existing)
3. Check:
   - [ ] File upload accepts your PDF
   - [ ] PDF renders correctly in preview
   - [ ] No corrupted pages
   - [ ] All text is extractable
4. Do NOT submit this test upload

### 5.4 Final Paper Statistics (5 min)

Document for your records:

```
Paper: PRISM for Logical Puzzle Solving
Total Pages: [X]
Word Count: ~[Y]
References: [Z]
Figures: [F]
Tables: [T]
Ablation Variants: [V]

Submission Date: [DATE]
Deadline: [DEADLINE]
Days Early: [N]
```

---

## Common AAAI Pitfalls to Avoid

### Critical Mistakes That Get Papers Desk-Rejected:

1. **Author information visible** → Use anonymous template properly
2. **Page limit exceeded** → Count includes references, check AAAI rules
3. **Forbidden packages used** → double-check against list
4. **Broken bibliography** → All citations must be in .bib file
5. **Overfull text boxes** → Text extends beyond margins (check PDF)
6. **Self-citations too obvious** → Cite anonymously if recent work
7. **Figures/tables not referenced** → Every figure must be mentioned before display
8. **Results claimed but not shown** → "We achieved 95% accuracy" needs supporting evidence

### Common Presentation Mistakes:

1. **Jargon without definition** → Define all technical terms first use
2. **Too many related works** → Focus on most relevant, consolidate others
3. **Methodology hard to follow** → Should be understandable to non-experts in the specific domain
4. **Results buried in text** → Use tables/figures for quantitative results
5. **No discussion of limitations** → Acknowledge what PRISM cannot do
6. **Conclusion introduces new ideas** → Conclusion should summarize, not introduce new claims

---

## Timeline Recommendations

### 4 Weeks Before Deadline
- [ ] Complete experiments section with all results
- [ ] Create final figures and tables
- [ ] Write initial draft of analysis/ablations

### 3 Weeks Before Deadline
- [ ] Circulate draft to collaborators for review
- [ ] Incorporate feedback, refine results presentation
- [ ] Verify all claims have supporting evidence

### 2 Weeks Before Deadline  
- [ ] Final writing pass (clarity, grammar, flow)
- [ ] Update related work if new papers published
- [ ] Check AAAI website for any updates to requirements

### 1 Week Before Deadline
- [ ] Full formatting audit against AAAI checklist
- [ ] PDF generation and manual inspection
- [ ] Anonymous submission verification
- [ ] Final proofreading pass

### 48 Hours Before Deadline
- [ ] One more full PDF check
- [ ] Verify PDF uploading to platform works
- [ ] Prepare submission metadata/information

### Day of Deadline
- [ ] Submit 6+ hours before deadline (platform issues happen!)
- [ ] Verify submission was received (check confirmation email)

---

## Specific PRISM Paper Recommendations

### Experiments Section Expansion

Based on the current structure, here's what needs completion:

**Current State:**
```
✓ Benchmark description (ZebraLogic, puzzle sizes)
✓ Baselines listed (6 baselines including ablations)
✓ Metrics defined (6 key metrics)
✗ Results presentation missing
✗ Analysis of results missing
```

**Priority order for completion:**

1. **Main Accuracy Table** (highest impact)
   - Accuracy (%) across all puzzle sizes
   - All 6 baseline methods + PRISM
   - Include avg. performance

2. **Cost-Accuracy Trade-off** (shows efficiency)
   - LLM calls per puzzle by method
   - Demonstrate PRISM's efficiency over baselines

3. **Repair Efficiency Analysis** (core novelty)
   - Average repair rounds by puzzle size
   - Show stagnation reduction mechanism working
   - This is your strongest differentiator!

4. **Ablation Studies** (validates design)
   - Memory-only vs. Library-only vs. Full PRISM
   - Show complementarity of components

5. **Paradigm Transfer Analysis** (novel finding)
   - How library grows with more puzzles
   - Paradigm reusability across puzzle types
   - This could be a strong secondary finding

### Visualization Strategy

```
Figure 1: Accuracy comparison (bar chart, puzzle size on x-axis)
Figure 2: LLM calls efficiency (box plot or line)
Figure 3: Repair stagnation curves (line plot, rounds on x-axis)
Figure 4: Ablation comparison (grouped bar chart)
[Table 1: Comprehensive results table with all metrics]
```

### Expected Narrative

Your paper should tell this story in Experiments section:

> "PRISM achieved [X]% accuracy on 4×4 puzzles, outperforming 
> [baseline] by [Y] percentage points (Table 1). Importantly, this 
> improvement comes with substantially lower computational cost, 
> requiring only [Z] LLM calls compared to [baseline's] [W] calls. 
> The key to PRISM's efficiency is its repair mechanism: 
> [mechanism description] reduces stagnation rounds from [A] to [B] 
> on average (Figure 3). Ablation studies reveal that both memory 
> and paradigm library contribute significantly..."

---

## Resources and References

### AAAI 2026 Official Resources
- AAAI 2026 Website: https://aaai.org/aaai-conference/
- Author Kit Download: Check AAAI website for latest template
- Submission Guidelines: AAAI 2026 Call for Papers

### LaTeX and Bibliography
- AAAI 2026 LaTeX Template: `aaai2026.sty`
- natbib Documentation: `texdoc natbib`
- BibTeX Guide: http://www.ctan.org/pkg/bibtex

### Writing and Presentation
- Scientific Writing Checklist: Ensure clarity > cleverness
- Figure Design: Use consistent colors, readable fonts
- Statistical Reporting: Always include confidence intervals

### Tools for Quality Assurance
- **Spelling/Grammar**: Aspell, LanguageTool
- **PDF Validation**: pdfinfo, pdftotext
- **LaTeX Error Checking**: grep for forbidden packages/commands

---

## Questions to Ask Yourself Before Submitting

1. **Contribution clarity**: If I read only the title and abstract, would I understand what PRISM does differently from existing work?

2. **Evidence completeness**: For each claim in the paper, can I point to a specific figure, table, or reference that supports it?

3. **Methodology reproducibility**: Could someone reimplement PRISM from my methodology section?

4. **Result interpretation**: Do my results clearly support the claims I make about PRISM's advantages?

5. **Novelty justification**: What would I say if a reviewer asks "How is this different from [related work]?"

6. **Ablation sufficiency**: If a reviewer questions whether component X is necessary, can I point to the ablation study?

7. **Limitation acknowledgment**: What doesn't PRISM do well, and have I acknowledged this?

8. **Impact articulation**: Why should AAAI audience care about PRISM? Who benefits?

If you can confidently answer all 8, your paper is ready for submission. If not, focus on the questions where you're uncertain.

---

## Next Steps

1. **Complete Results subsection** (1-2 days)
   - Collect all empirical results
   - Create tables and figures
   - Write result paragraphs with interpretation

2. **Add Analysis subsection** (0.5 days)
   - Synthesize findings
   - Explain why PRISM works
   - Discuss trade-offs

3. **Polish and review** (2-3 days)
   - Circulate draft to collaborators
   - Incorporate feedback
   - Refine writing

4. **AAAI formatting audit** (1 day)
   - Check all formatting rules
   - Verify no forbidden packages/commands
   - Ensure anonymity

5. **Final proofreading** (1 day)
   - Slow read of full paper
   - Check for clarity and flow
   - Final PDF inspection

6. **Submit** (before deadline!)

Good luck with AAAI 2026 submission! 🎯
