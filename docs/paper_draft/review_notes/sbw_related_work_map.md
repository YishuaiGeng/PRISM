# SBW 论文相关工作地图（按技术机制组织）

**论文**: Satisfiable but Wrong: Solver-Decidable Abstention for LLM Constraint Formalization
**调研日期**: 2026-07-21
**方法**: 7 个并行检索方向，全部引用经 DBLP / OpenAlex / Semantic Scholar / ACL Anthology / 出版方官网 / arXiv 至少一源核验；SatLM 另经源码逐行核对。arXiv-only 预印本单独标注，不作为确定事实。

---

## 0. 执行摘要与新颖性判决

**判决：组合层面可辩护，构件层面无一为新，且存在三个必须正面处理的近邻。**

- **机制（blocking-clause 第二解查询）不新**：VCSearch (EMNLP 2025) 已逐字实现"Z3 求一解→加为约束→仍 SAT 则判多解并 reject"；SatLM (NeurIPS 2023) 源码中对标量答案变量做了同型查询（`gsm_solver.py` L105-112: `solver.add(ans != final_val); if solver.check() == sat: return "AMBIG"`）。
- **"求解器多解信号→弃答→selective accuracy"的管线级主张不新**：SatLM 已在正文声明（p.3: "SatLM can abstain from making uncertain predictions if it parses a problem into an unsatisfiable or ambiguous specification, giving it even higher accuracy in the selective prediction setting"）。
- **可辩护的增量**（须以此为贡献声明的全部）：
  1. **命名并系统量化 SBW 失败模式**（"satisfiable but wrong" 短语经 4 轮精确检索未见先例，命名权安全）；
  2. **把 ad-hoc 检查提炼为一等原语**：一般答案变量集 V_A 上的投影阻塞子句、单次增量查询、三值语义（结构通过 / SBW 弃答 / UNKNOWN≠通过）、成本分析——SatLM 四者皆无；
  3. **理论刻画**（未见先例，是最强差异化资产，建议前置）：纯欠约束（未排除真实答案）⇒ 答案投影必然非唯一 ⇒ 必被捕获的单侧保证 + "unique-but-wrong 会通过"的诚实定界（信号是必要条件检查，不是语义正确性证明）；
  4. **系统的 risk-coverage 评测**：在 ZebraLogic / AR-LSAT 上与置信度、self-consistency、SatLM 式 AMBIG 基线受控对比。

**最高风险**：不是机制撞车而是**叙事撞车**——SSV (IJCAI 2025) 已在 AR-LSAT 上卖 "gold-free solver 验证信号 + precision@coverage"（21.7% coverage、100% precision）。必须正面对比或至少深入讨论，否则敌意审稿人会说增量只剩"换了个更便宜的信号"。

---

## 1. 机制 A：LLM→形式化管线与"SAT 即接受"惯例

现有管线的错误处理几乎全部锚定在**可见失败**（语法错误、执行异常、UNSAT）；求解器一旦成功返回即接受答案，faithfulness 声明一律以"形式化正确"为未验证前提。

| 论文 | 引用（已核验） | 求解器返回 SAT 时的行为 | 是否讨论"仍可满足的形式化错误" |
|---|---|---|---|
| Logic-LM | Pan, Albalak, Wang, Wang. "Logic-LM: Empowering Large Language Models with Symbolic Solvers for Faithful Logical Reasoning". **Findings of EMNLP 2023**. DOI 10.18653/v1/2023.findings-emnlp.248 [DBLP] | 直接接受；self-refinement 仅由报错触发 | ✔ §4.4 承认 "a valid symbolic representation does not necessarily equate to a 'correct' problem formulation"，但无机制 |
| SatLM ⭐ | Ye, Chen, Dillig, Durrett. "SatLM: Satisfiability-Aided Language Models Using Declarative Prompting". **NeurIPS 2023**. arXiv:2305.09656 [DBLP+源码] | **UNSAT/AMBIG 时拒答**（最近邻，见 §7 切割） | ✔ Appendix G 给出 solver 正常返回但答案错误的实例 |
| LINC | Olausson, Gu, Lipkin, et al. "LINC: A Neurosymbolic Approach for Logical Reasoning by Combining Language Models with First-Order Logic Provers". **EMNLP 2023 main**. DOI 10.18653/v1/2023.emnlp-main.313 [DBLP] | K=10 采样多数投票 | ✔ L1/L2 信息丢失失败模式（有损但可执行的翻译） |
| LoGiPT | Feng, Xu, Hao, et al. "Language Models can be Deductive Solvers". **Findings of NAACL 2024**. DOI 10.18653/v1/2024.findings-naacl.254 [DBLP] | 无求解器（内化推理） | ✘ 只针对解析崩溃 |
| CLOVER | Ryu, Kim, Lee, Yang. "Divide and Translate: Compositional First-Order Logic Translation and Verification for Complex Logical Reasoning". **ICLR 2025**. arXiv:2410.08047 [DBLP+OpenReview] | 翻译期用 SAT 求解器做候选间择优 | ✔ 整篇动机即翻译语义错误；但是翻译期相对择优，无 post-SAT 检查，候选共享系统性遗漏时失效 |
| LLM+ASP | Yang, Ishay, Lee. "Coupling Large Language Models with Logic Programming for Robust and General Reasoning from Text". **Findings of ACL 2023**. DOI 10.18653/v1/2023.findings-acl.321 [ACL Anthology] | answer set 存在即取答案 | ✘ |
| LLM→ASP 谜题 | Ishay, Yang, Lee. "Leveraging Large Language Models to Generate Answer Set Programs". **KR 2023** [KR proceedings] | 接受；错误靠人工检查 | ✔ 记录"程序能跑但解错"的语义错误实例；未利用唯一解谓词自动检测——正是 SBW 的空档 |
| GenCP | Régin, De Maria, Bonlarron. "Combining Constraint Programming Reasoning with Large Language Model Predictions". **CP 2024**. DOI 10.4230/LIPIcs.CP.2024.25 [LIPIcs] | （反向集成：CP 内调 LLM 生成域）| 不适用——约束是人写的，无 SBW 现象；引用时防混淆 |
| StreamLLM | Voboril, Peruvemba Ramaswamy, Szeider. "StreamLLM: Enhancing Constraint Programming with Large Language Model-Generated Streamliners". **NSE@ICSE 2025** [IEEE Xplore] | streamliner 有意收窄，原模型保底 | 与 SBW 呈对偶：遗漏约束**扩大**解空间且无保底 |
| Autoformalization 锚点 | Wu, Jiang, Li, et al. "Autoformalization with Large Language Models". **NeurIPS 2022** [NeurIPS proc.] | 人工评估忠实性 | ✔ "可编译≠语义正确"是该域共识 |
| ZebraLogic（基准） | Lin, Le Bras, Richardson, et al. "ZebraLogic: On the Scaling Limits of LLMs for Logical Reasoning". **ICML 2025**, PMLR 267:37889-37905 [PMLR] | —— | 谜题**按构造唯一解**：结构谓词的任务来源，应显式引用 |
| AR-LSAT（基准） | Zhong, Wang, Tang, et al. "AR-LSAT: Investigating Analytical Reasoning of Text". arXiv:2104.06598 (2021)；正式版 "Analytical Reasoning of Text". **Findings of NAACL 2022** [ACL Anthology] | —— | 多选题设定下"唯一答案"谓词的表述需在论文写清（见风险 §9.4） |

**外围（按需引用）**：Holy Grail 2.0 (Tsouros, Verhaeghe, Kadıoğlu, Guns, arXiv:2308.01589, **预印本未评审**——但作者自认"生成模型的验证与调试尚无方案"，是动机好引文)；Michailidis, Tsouros, Guns. "Constraint Modelling with LLMs Using In-Context Learning". **CP 2024**, DOI 10.4230/LIPIcs.CP.2024.20（自修复循环只修可执行性错误）；LOGIC-LM++ (Kirtania, Gupta, Radhakrishna, **ACL 2024 NLRSE workshop**, DOI 10.18653/v1/2024.nlrse-1.6——注意是 workshop)。

---

## 2. 机制 B：显式故障触发的修复与 UNSAT 诊断（盲区证据链）

**触发器普查结论**：主流修复循环的触发信号穷举为语法/执行错误（Logic-LM；Chen, Lin, Schärli, Zhou. "Teaching Large Language Models to Self-Debug". **ICLR 2024**）、UNSAT/unsat core（Hao, Chen, Zhang, Fan. "Large Language Models Can Solve Real-World Planning Rigorously with Formal Verification Tools". **NAACL 2025**, DOI 10.18653/v1/2025.naacl-long.176——SAT 即接受的典型样本；Fazelnia, Mirakhorli, Bagheri. "Translation Titans, Reasoning Challenges: ...Detecting Conflicting Requirements". **ASE 2024**, DOI 10.1145/3691620.3695302——只抓过约束/冲突）、测试失败。**没有一个以"SAT 但答案投影非唯一"为触发器。**

**UNSAT-core/MUS 谱系是 SBW 的对偶**（诊断过约束极成熟，欠约束零工具）：
- Liffiton, Sakallah. "Algorithms for Computing Minimal Unsatisfiable Subsets of Constraints". **JAR 40(1), 2008**. DOI 10.1007/s10817-007-9084-z
- Liffiton, Previti, Malik, Marques-Silva. "Fast, Flexible MUS Enumeration". **Constraints 21(2), 2016**. DOI 10.1007/s10601-015-9183-0（MARCO；增量二次查询做诊断的范例——与 SBW gate 同类机制、历来服务 UNSAT 侧）

**"点名但未解决"的直接证据（Related Work 弹药，按强度排序）**：
1. Logic-LM §4.4 原文（见上表）；
2. LOGIC-LM++："since the code is syntactically correct and there is no proof-check on the refinement"（refinement 会接受语义错误的公式，如 "No young person teaches"→"all young people teach"）；
3. SatLM Appendix G.2：solver 正常返回但答案错误的案例类别；
4. Endres, Fakhoury, Chakraborty, Lahiri. "Can Large Language Models Transform Natural Language Intent into Formal Method Postconditions?" **FSE 2024** (PACMSE). DOI 10.1145/3660791——`true` 空洞满足一切实现却判 correct；correctness/completeness 二维术语可直接借用，"太弱的形式化对一切都满足"与欠约束保持 SAT 同构；
5. Dai, Yan, Lin. "The Signal-Coverage Matrix: Stratifying Type and Semantic Errors in Statement Autoformalization". arXiv:2606.28013 (2026-06), **预印本未评审**——把 "type-correct but semantically incorrect" 单列为 2×2 矩阵一格；
6. FormalRx (Wang, Huang, Wan, et al. arXiv:2607.04655, 标注 "Accepted at **ICML 2026**", to appear 待终核)——2026 风向：修复触发器扩展到语义失败，但语义判定仍靠模型/oracle。

**语义验证正面强攻派**（对照：不可判定或依赖 oracle）：Sun, Sheng, Padon, Barrett. "Clover: Closed-Loop Verifiable Code Generation". **SAIV 2024**, LNCS 14846, DOI 10.1007/978-3-031-65112-0_7（三制品闭环一致性，需 LLM 参与判定）。

**规格工程对照**（验证=人在环）：Cosler, Hahn, Mendoza, Schmitt, Trippel. "nl2spec: ...". **CAV 2023**, DOI 10.1007/978-3-031-37703-7_18；Fuggitti, Chakraborti. "NL2LTL...". **AAAI 2023 Demo**, DOI 10.1609/aaai.v37i13.27068。

**定位句（可直接用）**：Prior repair loops fire only on explicit failures (syntax, execution, UNSAT), and prior semantic validation is undecidable or oracle-dependent; we identify a decidable middle ground — a structural necessary condition checkable by one incremental solver query.

---

## 3. 机制 C：语义对齐（资源需求 × 保证类型）

| 机制 | 代表（已核验） | 额外模型 | 文本比较 | k 采样 | 金标参照 | 信号性质 |
|---|---|---|---|---|---|---|
| 学习式打分 | Lu, Wan, Huang, et al. "FormalAlign: Automated Alignment Evaluation for Autoformalization". **ICLR 2025** [OpenReview B5RrIFMqbe] | ✔ 专训打分器 | ✔ | ✘ | 训练期✔ | 连续分数，启发式，需调阈值 |
| 符号等价 | Li, Wu, Li, et al. "Autoformalize Mathematical Statements by Symbolic Equivalence and Semantic Consistency". **NeurIPS 2024**；Liu, Zheng, Lu, Cao, Yan. "Rethinking and Improving Autoformalization..." (BEq). **ICLR 2025** [OpenReview hUb2At2DsQ]；Poiroux, Weiss, Kunčak, Bosselut. "Reliable Evaluation and Benchmarks for Statement Autoformalization" (BEq+). **EMNLP 2025 main** [ACL Anthology 2025.emnlp-main.907]；Murphy, Yang, Sun, Li, Anandkumar, Si. "Autoformalizing Euclidean Geometry". **ICML 2024** [PMLR v235] | ✘（要证明器） | ✘ | 候选间用法需 k | 评估用法需✔ | 半可判定："找到证明⇒可靠"；**BEq+ 确定性化后 recall 仅 48.3%**（precision 98.0%）——NL↔formal 等价本质不可判定的定量证据 |
| 回译一致 | Azerbayev, Piotrowski, Schoelkopf, et al. "ProofNet...". arXiv:2302.12433, **预印本**；Ying, Wu, Geng, Yuan, Lin, Chen. "Lean Workbook...". **NeurIPS 2024 D&B** | ✔ 回译+NLI | ✔ | ✘ | ✘ | 软一致；**对 omission 系统性盲**（遗漏约束在回译文本中不可见）——可直接引证 SBW 论点 |
| 自一致投票 | Wang, Wei, Schuurmans, et al. "Self-Consistency Improves Chain of Thought Reasoning in Language Models". **ICLR 2023** [DBLP]；Zhou, Staats, Li, Szegedy, Weinberger, Wu. "Don't Trust: Verify — Grounding LLM Quantitative Reasoning with Autoformalization" (DTV). **ICLR 2024** [OpenReview V5tdi14ple] | ✘ | ✘ | ✔ ×K | ✘ | 统计共识；同源偏差下**一致地错**；DTV 是必须重点区分的先行（见 §7） |
| 测试/性质验证 | Chen, Zhang, Nguyen, et al. "CodeT: Code Generation with Generated Tests". **ICLR 2023** [OpenReview ktrw68Cmu9c]；nl2postcond（见 §2） | 测试亦 LLM 生成 | ✘ | ✔/✘ | CodeT✘ | 执行可靠但测试覆盖启发式；**验证器与被验证对象同源**（回应"为何不让 LLM 生成检查约束"） |
| **SBW 门（本文）** | — | **✘** | **✘** | **✘** | **✘** | **有限域可判定：一次 blocking-clause 查询给出确定二值答案** |

**边界声明（论文须主动写）**：SBW 门检测欠约束导致的非唯一性，对"约束错但恰好仍唯一"无信号——该情形恰是学习式打分/回译类方法的适用域。定位为**正交/互补**，不是替代。

---

## 4. 机制 D：弃答信号谱系（证据强度递增、适用面递减）

1. **Learned/heuristic**：Chow. "On Optimum Recognition Error and Reject Tradeoff". **IEEE TIT 16(1), 1970**；Geifman, El-Yaniv. "Selective Classification for Deep Neural Networks". **NeurIPS 2017**；Kamath, Jia, Liang. "Selective Question Answering under Domain Shift". **ACL 2020**（置信度在 OOD 下失准——对照论点：结构谓词不随分布偏移失效）；Jiang, Araki, Ding, Neubig. "How Can We Know When Language Models Know?..." **TACL 9, 2021**；Kadavath et al. "Language Models (Mostly) Know What They Know". arXiv:2207.05221, **预印本**（P(True)/P(IK)）；Zhang, Diao, Lin, et al. "R-Tuning: Instructing Large Language Models to Say 'I Don't Know'". **NAACL 2024** (Outstanding Paper)；Xiong, Hu, Lu, et al. "Can LLMs Express Their Uncertainty?..." **ICLR 2024**（verbalized confidence 普遍过自信——置信度基线的权威负面证据）。
2. **Sampling-based**：Self-Consistency (ICLR 2023)；Farquhar, Kossen, Kuhn, Gal. "Detecting Hallucinations in Large Language Models Using Semantic Entropy". **Nature 630, 2024**. DOI 10.1038/s41586-024-07421-0——只度量输出分布离散度，对"分布集中在错误形式化上"原理性失明，可点名对比。
3. **Statistical**：Quach, Fisch, Schuster, et al. "Conformal Language Modeling". **ICLR 2024**；Yadkori, Kuzborskij, Stutz, et al. "Mitigating LLM Hallucinations via Conformal Abstention". arXiv:2405.01563, **预印本**——保证属于分布不属于实例。对照句式：conformal 给"以 1−α 概率对"；solver certificate 给"对这个实例，唯一性成立/不成立，证据在此"。
4. **Deterministic/certificate-based**：**该象限非空——SatLM 已占位**（AMBIG 弃答 + selective accuracy，逐字证据见 §7）；DTV（确定性验证器过滤 + 统计投票的杂交，验证内部一致性而非唯一性）。
- 理论词汇来源：El-Yaniv, Wiener. "On the Foundations of Noise-free Selective Classification". **JMLR 11, 2010**（risk-coverage；SatLM 引的正是它）。
- 分类学锚点：Wen, Yao, Feng, et al. "Know Your Limits: A Survey of Abstention in Large Language Models". **TACL 13, 2025**. DOI 10.1162/tacl_a_00754——综述覆盖的推理时方法几乎全为 1/2 类，确定性外部信号在其分类学中缺位（引证空隙的综述级证据）。

---

## 5. 机制 E：求解器原语（"原语标准、再利用新"的证据与复杂度事实）

**原语是标准件**：
- McMillan. "Applying SAT Methods in Unbounded Symbolic Model Checking". **CAV 2002**（blocking clause 经典出处）
- Eén, Sörensson. "An Extensible SAT-solver". **SAT 2003**；"Temporal Induction by Incremental SAT Solving". **ENTCS 89(4), 2003**（增量接口——"一次增量查询几乎免费"的标准引文）
- Toda, Soh. "Implementing Efficient All Solutions SAT Solvers". **ACM JEA 21, 2016**（综述定性 blocking-clause 为标准技术；同时说明穷尽枚举很贵——反衬只查第 2 个投影的设计）
- Morgado, Marques-Silva. "Good Learning and Implicit Model Enumeration". **ICTAI 2005**（blocking 子句空间开销指数级）
- Gebser, Kaufmann, Schaub. "Solution Enumeration for Projected Boolean Search Problems". **CPAIOR 2009**（**投影变量上的阻塞子句**已有成熟实现——最接近的机制先驱，但目的是完整枚举）

**投影与计数**：Aziz, Chu, Muise, Stuckey. "#∃SAT: Projected Model Counting". **SAT 2015**；Lagniez, Marquis. "A Recursive Algorithm for Projected Model Counting". **AAAI 2019**；Sharma, Roy, Soos, Meel. "GANAK: A Scalable Probabilistic Exact Model Counter". **IJCAI 2019**——SBW 只消费计数问题最便宜的一比特（"≥2?"）。

**唯一性理论**：Valiant, Vazirani. "NP is as easy as detecting unique solutions". **TCS 47, 1986**；Blass, Gurevich. "On the unique satisfiability problem". **Information and Control 55, 1982**（UNIQUE-SAT US-完全、coNP-难）；Yato, Seta. "Complexity and Completeness of Finding Another Solution and Its Application to Puzzles". **IEICE Trans. E86-A(5), 2003**（ASP-完全性；第二解查询的正统出处，动机就是谜题唯一解检验）。

**唯一性作质量门控的先例**：De Kegel, Haahr. "Procedural Puzzle Generation: A Survey". **IEEE ToG 12(1), 2020**——生成流水线"生成→查唯一性→不唯一则拒"与 SBW 结构同构；差别：被门控的是谜题实例（约束可信），SBW 门控的是约束本身（约束不可信）。

**CSP 多解结构**：Freuder. "Eliminating Interchangeable Values in Constraint Satisfaction Problems". **AAAI 1991**（互换性——论证**必须投影到 V_A** 而非全模型比较的理论弹药：辅助变量互换不构成答案歧义）；Hebrard, Hnich, O'Sullivan, Walsh. "Finding Diverse and Similar Solutions in Constraint Programming". **AAAI 2005**（diversity 文献把多解视为资源，SBW 反转符号视为缺陷证据）。

**可引用的复杂度事实清单**：
1. 给定一个模型，判定"是否存在 V_A 上不同的第二模型" = 一次 SAT 调用（NP 查询；增量接口下学习子句复用）。
2. "恰有唯一解"整体 US-完全、coNP-难；承诺版多项式可解 ⇒ NP=RP——所以 SBW 只做"证伪唯一性"的廉价方向，用 UNKNOWN 承接预算耗尽，设计与复杂度下界自洽。
3. 找第二解对数独等谜题 NP-完全（Yato–Seta）——第二解查询不保证便宜，预算与 UNKNOWN 必不可少。
4. 完整投影计数远难于单次查询（#∃SAT）。

---

## 6. 机制 F：约束获取 / CEGIS / oracle 依赖

**核心对照**：这些方法能收敛到正确约束，因为每个候选都由可信 oracle 裁决；LLM NL 形式化场景中 OGIS 意义下的任何 oracle 接口都不可用。SBW gate 只继承机器的"查询"一半（solver-decidable distinguishing query），不继承"裁决"一半：检测欠约束，不获取缺失约束。

- **交互/被动获取**：Bessiere, Koriche, Lazaar, O'Sullivan. "Constraint acquisition". **AIJ 244, 2017**（CONACQ；只引期刊版）；Bessiere, Coletta, Hebrard, et al. "Constraint Acquisition via Partial Queries" (QuAcq). **IJCAI 2013**（其查询生成 = 与 blocking-clause 查询最近的机械亲属之一）；Beldiceanu, Simonis. "A Model Seeker...". **CP 2012**（被动获取也要可信正例——堵"那就用被动获取"的反问）；Tsouros, Stergiou. "Efficient multiple constraint acquisition". **Constraints 25, 2020**；Tsouros, Berden, Guns. "Learning to Learn in Interactive Constraint Acquisition". **AAAI 2024**（2024 年该线仍以可信查询为轴——oracle 是构成性前提的反证）；De Raedt, Passerini, Teso. "Learning Constraints from Examples". **AAAI 2018**（总括引文）。
- **CEGIS/OGIS**：Solar-Lezama, Tancau, Bodik, Seshia, Saraswat. "Combinatorial Sketching for Finite Programs". **ASPLOS 2006**（终止即正确性来自验证 oracle 手握完整 spec——"exploratory completion ≠ verified repair"的理论锚点）；**Jha, Gulwani, Seshia, Tiwari. "Oracle-Guided Component-Based Program Synthesis". ICSE 2010**（distinguishing input——**结构上最同源的机制**："是否存在第二个行为不同的对象"；找到后可问 I/O oracle 继续收敛，SBW 无 oracle 只能弃答。Related Work 应显式做 "same query, no oracle to consult" 对仗）；Jha, Seshia. "A Theory of Formal Synthesis via Inductive Learning". **Acta Informatica 54, 2017**（OGIS 统一语言："In OGIS terms, no admissible oracle interface exists in our setting"）；Alur et al. "Syntax-Guided Synthesis". **FMCAD 2013**（一句带过）。
- **LLM 建模评测**（benchmark-time oracle ≠ deployment-time oracle）：Ramamonjison et al. "NL4Opt Competition...". **PMLR 220, 2023**；Dakle et al. "Ner4Opt...". **CPAIOR 2023** / Constraints 2024。
- **无 spec 时的两条旁路**（都不可用于自治评测）：CodeT（自造噪声 oracle——同源偏差不可消除）；Fakhoury, Naik, Sakkas, Chakraborty, Lahiri. "LLM-Based Test-Driven Interactive Code Generation..." (TiCoder). **IEEE TSE 2024**（把人拉回环内当 oracle）。SBW 选第三条路：selective prediction。

**措辞纪律**：不要说"acquisition/CEGIS 不适用于 NL"（TiCoder 证明拉人进环可行），只说"在无用户在环的自治设定下 oracle 接口不可用"。

---

## 7. 最近先例排名与切割方案

| # | 先例 | 重叠 | 切割 |
|---|---|---|---|
| 1 | **SatLM** (NeurIPS 2023) | AMBIG（多可行解）+ UNSAT 弃答；selective accuracy 报告；gold-free；源码含标量版阻塞-重解查询 | (i) AMBIG 是附带异常信号非贡献主体、只针对单标量答案变量（AR-LSAT 路径用逐选项 `is_valid` 蕴含检查，机制完全不同）；(ii) 无一般 V_A 投影阻塞子句原语、无理论、无成本分析；(iii) 无 UNKNOWN≠通过三值区分（超时归异常）；(iv) selective 表在 GSM-Sys/GSM/Clutrr 非逻辑题、无 risk-coverage 曲线。**必须逐字引用其弃答声明并做三点切割；建议复现其 AMBIG 作为基线** |
| 2 | **VCSearch** (Tian, Zhou, Yu, et al. "Bridging the Gap Between Well-Defined and Ill-Defined Problems in Mathematical Reasoning". **EMNLP 2025 main**, DOI 10.18653/v1/2025.emnlp-main.642) | **逐字同机制**：Z3 求一解→加为约束→仍 SAT 判多解→reject（"Multi" 类别） | 用途不同：检测**病题**（NL 题目缺条件/矛盾）vs 本文检测**好题的坏形式化**；数学应用题域；迭代 variable-constraint 搜索多次 LLM 调用 vs 单次查询；无 selective prediction/risk-coverage 框架。承认机制同源，主张用途+理论+评测新 |
| 3 | **SSV** (Raza, Milic-Frayling. "Instantiation-based Formalization of Logical Reasoning Tasks using Language Models and Logical Solvers". **IJCAI 2025**) | gold-free solver 验证信号；**AR-LSAT 上 precision@coverage**（21.7% coverage、100% precision）——评测框架撞车 | 信号是具体实例化可满足性检验（需 LLM 生成实例、多次调用）非解唯一性；失败先修复重试非纯弃答。应对：成本对比 + 信号正交性（可叠加）实验 |
| 4 | **Solver-in-the-Loop ASP** (Schrader, Lange, Kaminski, et al. **AAAI 2026**, DOI 10.1609/aaai.v40i30.39714) | answer set 数量入 reward（过多=欠约束、零=矛盾）；logic grid puzzles 域 | 信号用于迭代修复/回溯**非弃答**；无 selective 评测；ASP 非 SAT/SMT 增量查询 |
| 5 | **Vacuity detection**（Kupferman, Vardi. "Vacuity Detection in Temporal Model Checking". **STTT 2003**；Beer, Ben-David, Eisner, Rodeh. "Efficient Detection of Vacuity...". **FMSD 2001**（工业观察 ~20% 规约平凡通过）；Kupferman. "Sanity Checks in Formal Verification". **CONCUR 2006**；Chockler, Kupferman, Vardi. "Coverage Metrics for Temporal Logic Model Checking". **TACAS 2001**） | "验证通过但通过方式暴露规约有病"——概念同构的形式方法先祖 | 无 LLM、无弃答框架、对象是时序规约非答案投影。**主动引用化威胁为纵深** |

**跨域旁系**（输入歧义 vs 输出欠约束，采样 vs 单次可判定查询）：AmbiQT (Bhaskar et al. "Benchmarking and Improving Text-to-SQL Generation under Ambiguity". **EMNLP 2023**)；AMBROSIA (Saparina, Lapata. arXiv:2406.19073, NeurIPS 2024 D&B——**venue 投稿前再核**)；AmbiSQL (arXiv:2508.15276; SIGMOD Companion)。

**命名权**："satisfiable but wrong" 经 4 轮精确检索未见先例，安全。近义未命名讨论：arXiv 2605.12421（Heuristic Trap，**预印本**）、arXiv 2606.16118（legal reasoning "scope laundering"，**预印本**）。

---

## 8. Introduction / Related Work 论证结构

### Introduction 骨架（6 步）
1. **现状**：LLM 形式化 + 求解器管线把 SAT 当接受依据（Logic-LM、SatLM、LINC、LLM+ASP…）。
2. **问题**：SAT 只证内部一致，不证忠实。遗漏/弱化线索 ⇒ 仍 SAT 但任务层面错。命名 SBW，引"点名但未解决"证据链（Logic-LM §4.4、SatLM App G、KR 2023 语义错误实例、LINC L1/L2）。
3. **现有应对不覆盖**：(a) 修复循环只由显式故障触发（语法/执行/UNSAT），UNSAT-core 机器是对偶侧；(b) 语义对齐要额外模型/文本比较/k 采样/金标，且启发式或半可判定（BEq+ 定量：确定性化后 recall 48.3%）；(c) 弃答信号谱系中确定性求解器象限几乎空缺——除 SatLM 的 ad-hoc AMBIG（正面引用+切割）。
4. **本文问题（窄而可判定）**：任务规范给出答案空间结构条件时，SAT 后一次增量 blocking-clause 查询即可判定结构性弃答，无金标、无额外模型、无采样。
5. **理论（前置）**：单侧保证——纯欠约束（未排除真实答案）⇒ 投影非唯一 ⇒ 必被捕获；unique-but-wrong 通过 ⇒ 信号是必要条件检查而非语义正确性证明；依赖可信结构先验、完整 V_A 投影、预算内判定（UNKNOWN≠通过）。
6. **贡献清单**：命名并量化 SBW；一等原语（一般 V_A、单查询、三值语义、成本分析）；单侧保证定理；ZebraLogic/AR-LSAT 上系统 risk-coverage 评测（对比置信度/self-consistency/SatLM-AMBIG）；探索性候选补全明确定界为非验证修复。

### Related Work 分节（按机制，6 小节）
- **2.1 Solver-augmented LLM reasoning**：SAT-as-acceptance 惯例；SatLM 详细切割放此。
- **2.2 Repair and diagnosis of formalizations**：显式故障触发普查；UNSAT-core 对偶；定位句（§2 末尾那句）。
- **2.3 Semantic alignment of NL and formal representations**：五机制资源/保证对比；互补性声明（unique-but-wrong 是其适用域）。
- **2.4 Selective prediction and abstention**：四级信号谱系；本文在第 4 级的位置与 SatLM/DTV/SSV 的区分。
- **2.5 Solver primitives and solution-space structure**：原语标准（McMillan/Eén–Sörensson/Gebser）、唯一性血统（Yato–Seta、谜题生成门控）、复杂度定位（V-V、Blass–Gurevich）、投影动机（Freuder 互换性）、vacuity 概念先祖。
- **2.6 Constraint acquisition and synthesis**：oracle 依赖对照；"same query, no oracle to consult" 对仗（Jha et al.、QuAcq）；两条旁路（CodeT 自造伪 oracle、TiCoder 人在环）与本文第三条路。

---

## 9. 风险点与待办清单

### 写作红线
1. 永远不把"答案投影唯一"写成"形式化语义正确/答案正确"——审稿人抓到一处即全文可信度崩塌。
2. LLM 候选约束补全只能写 exploratory completion，不得写 verified/causal repair 收益（CodeT 同源偏差是理由引文）。
3. 不声称"首次用多解信号弃答/首次求解器信号弃答"（SatLM 堵死）；不声称机制新（VCSearch 堵死）。

### 必须的实验/讨论补强
4. **AR-LSAT 多选设定下结构谓词的表述**：答案投影 vs 选项判定必须写清（SatLM 的 AR-LSAT 路径用逐选项蕴含检查——正好说明多选任务上"唯一性"需另行形式化，审稿人必问）。
5. **SatLM-AMBIG 基线**：复现其标量版检查作为对比臂。
6. **SSV 对比/讨论**：成本（每题多次 LLM 实例化调用 vs 一次 solver 查询）+ 正交性（可叠加）。
7. **投影消融**：全模型第二解 vs V_A 投影第二解（Freuder 互换性动机的实证）。
8. **UNKNOWN 率报告**：三值输出中 UNKNOWN 占比与预算敏感性（Yato–Seta NP-完全性说明必要）。
9. **谓词一般化讨论**：唯一性之外的结构谓词至少给一个（回应 "benchmark-specific" 质疑）。

### 引用待复核（投稿前）
10. SatLM Table 4/5 的 selective prediction 覆盖数据集（是否含 LSAT 子集）——下载原文确认页码与表号。
11. AR-LSAT 引用版本：arXiv 2021 vs "Analytical Reasoning of Text" Findings-NAACL 2022（两代理返回的 venue 记载有出入：Findings of NAACL 2022，需查 ACL Anthology 确定最终著录）。
12. AMBROSIA 正式 venue（NeurIPS 2024 D&B 待核）。
13. FormalRx "Accepted at ICML 2026" 以最终出版为准。
14. LOGIC-LM++ 是 workshop（NLRSE），著录时标明。
15. SatLM 的 NeurIPS DOI 两代理返回不一致（10.52202/075280-1974 vs proceedings hash 8e9c7d4a）——以 proceedings.neurips.cc 页面为准。

### 预期审稿质疑速查（附其弹药）
- "SatLM already does this" → 逐字引用 + 三点切割（信号地位/理论/评测）。
- "唯一性双查在 VCSearch 逐字出现" → 承认同源，用途+单次调用+selective 框架切割。
- "SSV 已在 AR-LSAT 上 100% precision@coverage" → 成本+正交性。
- "answer-set counting 已有" (AAAI 2026) → 修复信号 ≠ 弃答门。
- "唯一性是基准构造性质，方法 benchmark-specific" → 谓词一般化 + 适用条件明说。
- "这就是 vacuity checking 移植" → 主动引用承认承继，写明差异（答案投影可判定谓词、selective 语义、单侧保证）。
- "text-to-SQL 歧义检测已有" → 输入歧义 vs 输出欠约束、采样 vs 单次可判定查询。
