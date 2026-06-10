# PRISM 论文相关工作（正式中文学术版）

---

## 2 相关工作

### 2.1 神经符号推理与约束满足求解

将大语言模型（LLM）与外部形式化求解器相结合，构成了当前神经符号推理研究的主流范式。该领域的奠基性工作 **Logic-LM**（Pan et al., 2023）提出三阶段流水线框架：首先由 LLM 将自然语言前提翻译为符号化表示（Prolog/Z3/Pyke），随后由确定性符号求解器执行推理，最终由 LLM 对求解结果进行解释。Logic-LM 还引入了自修复模块，将求解器返回的报错信息直接反馈给 LLM 进行迭代修正，在 ProofWriter、FOLIO 及 AR-LSAT 等基准上实现了相对于标准提示和链式思维推理分别 39.2% 和 18.4% 的平均性能提升。**LINC**（Olausson et al., 2023）与 Logic-LM 同期独立提出，专注于将自然语言转化为一阶逻辑（FOL）并调用 Prover9 求解，深入分析了翻译质量作为整个流程性能瓶颈的关键地位，然而该工作未设计修复模块，翻译失败时直接降级为纯语言模型推理。**SAT-LM**（Ye et al., 2023）将问题形式化为 SAT 实例，并系统梳理了 LLM 在符号翻译过程中的三类典型错误：变量命名不一致、子句缺失和唯一性约束遗漏，但同样未涉及迭代修复机制。

在修复机制的精细化方面，**Logic-LM++**（Kirtania et al., 2024）引入了候选修复方案的两两比较机制（pairwise comparison），由 LLM 在多个修复方案中择优，相较于 Logic-LM 取得了进一步的性能改善。**VERUS-LM**（Callewaert et al., 2025）提出了结合 IDP-Z3 求解器的多范式框架，专注于自然语言形式化的可验证性问题。**Logic.py**（Kesseli et al., 2025）另辟蹊径，设计了专用于逻辑谜题求解的领域特定语言（DSL），通过引导 LLM 将谜题形式化为 DSL 表示再交由约束求解器执行，在 ZebraLogicBench 上相较于基线实现了 65% 的绝对提升，精度超过 90%。**VERGE**（2026）代表了该方向的最新进展，通过提取最小修正子集（Minimal Correction Subsets, MCS）来精确定位需要修改的声明集合，并结合语义路由机制（逻辑性声明交由 SMT 求解，常识性声明交由多模型集成判断），在 ZebraLogic 等基准上取得 18.7% 的显著提升。然而，VERGE 的研究场景为开放域事实声明，并非结构化约束满足问题，且其 MCS 机制不涉及跨题目的经验积累，亦不具备停滞检测能力。

在约束满足问题（CSP）基准测试与错误分析方面，**ZebraLogic**（Lin et al., ICML 2025）构建了目前最系统的逻辑网格谜题评测框架，涵盖从 2×4 到 6×6 规模的 1,000 道程序化生成谜题，并以 Z3 求解器的冲突数量（conflict count）作为谜题难度的客观量化指标。ZebraLogic 揭示了"复杂度诅咒"现象：随着谜题规模增大，当前最强模型（包括 o1、DeepSeek-R1）的精度均呈现急剧下降的趋势，且扩大推理计算量（如 Best-of-N 采样、自我验证提示等）的收益极为有限。**GridPuzzle**（Tyagi et al., 2024）对 LLM 在逻辑网格谜题上的失败模式进行了细粒度的人工标注与统计分析，认定"推理步骤错误"与"消去法使用失当"是最主要的两类失败来源——这两类问题恰好对应本文范式库中直接赋值范式（P1）和链式传播范式（P2）所针对的推理场景。

**与本文的区别。** 上述所有工作均将每道谜题/问题视为独立求解实例，求解过程中积累的经验在实例切换后全部清零。此外，修复信号普遍停留在求解器的原始报错层面，缺乏对 UNSAT 成因的精确诊断与类型化管理，也不具备检测和打破修复循环的机制。本文提出的 PRISM 通过构建跨题目的范式库与类型化修复轨迹记忆，同时解决了"经验不积累"和"修复停滞"两个根本性问题。

---

### 2.2 大语言模型的迭代自修复机制

迭代自修复（iterative self-refinement）是提升 LLM 输出质量的重要范式之一。**Self-Refine**（Madaan et al., 2023）率先提出通用框架：LLM 生成初始输出后，自行对输出进行批评（critique），根据批评结果修正（refine），循环迭代直至输出质量满足要求。在代码生成、数学推理、逻辑谜题等多类任务上，Self-Refine 相较于直接生成取得了 5% 至 40% 以上不等的性能提升。**Reflexion**（Shinn et al., 2023）将自修复思想引入强化学习视角，提出语言强化（verbal reinforcement）机制：智能体在每轮任务失败后生成自然语言形式的"语言反思"（verbal reflection），将反思内容写入情节记忆（episodic memory）供后续尝试参考，从而在 AlfWorld、HotpotQA 等任务上显著减少达成目标所需的尝试次数。

然而，多项研究表明 LLM 的自修复能力存在深层局限性。Huang et al.（2023）通过系统实验证明，在缺乏外部监督的情况下，LLM 无法可靠地自我纠正推理错误——所谓的"自我修正"往往只是改写了表述形式，而非真正修正了逻辑错误。在神经符号推理领域，这一局限尤为突出：Logic-LM 明确观察到修复迭代数轮后精度趋于平台（stagnation）的现象，修复行为趋于重复而实质进展停滞；在程序验证领域，循环不变量生成工作（2025）为避免无效迭代而设定了 N=5 的硬性迭代上限。VERGE（2026）将这一现象正式命名为"相关性悬崖"（correlation cliff），指出概率性自修复的收益随迭代轮数的增加而显著递减。上述发现共同揭示了一个核心问题：当修复信号本身不携带新信息时，迭代修复必然陷入停滞。

在引入结构化外部反馈方面，部分工作探索了如何将验证工具的精确信息转化为 LLM 可利用的修复指导。**基于实例化的形式化验证**（IJCAI 2025）提出逐条验证策略：对每条翻译后的约束生成正例（应满足）和反例（应不满足），借助求解器逐一校验语义正确性，首次实现了约束级别的语义验证。然而，该工作的正/反例生成本身依赖 LLM，引入了二次误差来源，且无法处理约束间的交互冲突问题。**代码修复**领域的相关研究（Tang et al., 2025; 2026）发现，给定相同的 token 预算，顺序修复与并行重采样之间存在探索-利用权衡，但无论哪种策略，在缺乏有针对性的类型化错误诊断时，修复成功率均迅速趋于饱和。

**与本文的区别。** 现有自修复工作的共同缺陷在于：修复反馈信号粒度粗糙（原始报错字符串或自然语言批评），无法提供形式化的错误定位；不同错误类型（语法错误、语义翻转、过度约束等）由统一模板处理，缺乏差异化的修复策略；且无跨题目学习机制，相同类型的错误在不同题目中重复出现时仍从零修复。本文的修复轨迹记忆系统基于 UNSAT core 提供精确的约束级错误定位，类型化记录每次修复的尝试与结果，并通过 Jaccard 相似度和余弦相似度实现停滞与循环的自动检测，从根本上突破了现有自修复机制的局限。

---

### 2.3 智能体记忆与经验蒸馏

为赋予 LLM 智能体跨任务积累和复用经验的能力，近年来涌现出一系列以"记忆增强"为核心的研究工作。**Reflexion**（Shinn et al., 2023）作为该方向的奠基性工作，引入语言强化学习框架，将任务失败后的自然语言反思作为情节记忆注入后续尝试，验证了文本形式的经验可以改善同一任务序列内的后续决策。然而，Reflexion 的记忆仅在单一任务序列内生效，不支持跨任务的经验迁移，且自然语言反思的质量完全依赖 LLM 的自我评估，缺乏外部验证机制。

**ExpeL**（Zhao et al., 2024）在跨任务经验积累方面取得重要进展：通过对比多组成功与失败轨迹对，借助 LLM 的总结与提炼能力，以 ADD、UPVOTE、DOWNVOTE、EDIT 四种操作动态维护一个 insight 列表，在 ALFWorld 等具身任务上展现出有效的跨任务迁移能力。然而，ExpeL 存在两个主要缺陷：一是随经验积累 insight 列表线性增长，所有 insight 无差别全量注入每次测试，导致严重的 context 污染和扩展性问题；二是 insight 为自由文本形式，没有任何形式验证机制，错误经验与正确经验在存储时完全无法区分（Experiential Reflective Learning, 2026）。**AutoGuide**（Fu et al., 2024）通过对比具有不同结果的轨迹对，在离线阶段生成上下文感知的行动准则（context-aware guidelines），在测试时进行情境识别与准则检索；然而其检索机制在每个智能体轮次均引入大量额外开销，且当当前状态无法匹配任何已存储情境时，系统无法提供任何指导。

**ReasoningBank**（Ouyang et al., 2025）在经验蒸馏的结构化程度上进一步提升：不再存储原始轨迹，而是将成功与失败经验共同蒸馏为结构化知识单元（包含标题、描述和可复用内容）；并提出记忆感知的测试阶段扩展策略（MaTTS），证明经验积累与推理时间计算量存在协同增益关系，在网页导航和软件工程任务上实现了最高 20% 的相对提升。然而，ReasoningBank 的知识单元仍为自然语言散文，以 LLM-as-a-Judge 作为质量评估手段，不具备形式化验证机制；应用于 CSP 推理时，一条错误的自然语言策略与正确策略在存储格式上无法区分，质量评估不可靠。**图记忆框架**（2025, ICLR 2026 投稿）将历史决策路径编码为可微分图结构作为规划先验，**MACLA**（2025）以 15:1 的压缩比将 ALFWorld 轨迹压缩为可执行程序级记忆，**ProcMEM** 则通过非参数 PPO 门控对技能质量进行动态过滤；上述工作均在具身或 GUI 操控类任务上展开，以 LLM 自评作为唯一质量保证手段，不具备外部形式化验证能力。**ERL**（Experiential Reflective Learning, 2026）对成功与失败经验的相对价值进行了定量分析，发现在搜索类任务中失败经验提炼的启发式规则相较于成功经验具有更高的正向贡献（+14.3%），原因在于其提供了显式的"负约束"（"不要走此路径"）——这一发现为本文的修复轨迹记忆设计提供了重要的理论支撑。

**与本文的区别。** 本文所处领域——神经符号 CSP 推理中的经验积累——在现有所有智能体记忆工作中属于完全空白的交叉地带。与上述工作的本质区别体现在三个维度：第一，**记忆单元的形式语义**：本文提出的求解范式具有结构化的触发条件、推断操作和 Z3 可验证的前/后条件，而现有工作的记忆单元均为无法形式化验证的自由文本；第二，**质量保证机制**：范式在写入库之前必须通过 Z3 机械验证（soundness ≥ 90%），而非依赖 LLM 自评；第三，**记忆粒度**：本文的记忆运作于推理操作级别（约束传播步骤），而非任务执行级别，粒度与 CSP 求解的实际工作单元相匹配。此外，本文提出的**修复轨迹记忆**是首个将形式化修复过程本身建模为可学习的结构化轨迹的工作，每条修复记录携带错误类型、UNSAT core 和结果标注，支持停滞与循环的程序化检测，这在现有任何记忆增强框架中均未有先例。

---

## 参考文献（按小节整理）

### §2.1 引用的工作

| 缩写 | 全称 | 发表 | 核心贡献 |
|------|------|------|---------|
| Logic-LM | Logic-LM: Empowering LLMs with Symbolic Solvers for Faithful Logical Reasoning | EMNLP 2023 Findings | 三阶段神经符号框架 + 自修复模块 |
| LINC | LINC: A Neurosymbolic Approach for Logical Reasoning by Combining LMs with FOL Provers | EMNLP 2023 | LLM→FOL + Prover9/Z3，翻译质量分析 |
| SAT-LM | SATLM: Satisfiability-Aided Language Models Using Declarative Prompting | NeurIPS 2023 | NL→SAT，系统性翻译错误分类 |
| Logic-LM++ | LOGIC-LM++: Multi-Step Refinement for Symbolic Formulations | ACL 2024 Workshop | Pairwise 比较机制选择最优修复 |
| VERUS-LM | VERUS-LM: ... | arXiv 2025 | 多范式 IDP-Z3 形式化框架 |
| Logic.py | Logic.py: Bridging the Gap between LLMs and Constraint Solvers | arXiv Feb 2025 | DSL 领域特定语言 + 约束求解，ZebraLogicBench SOTA |
| VERGE | VERGE: ... | 2026 | MCS 定位冲突声明，语义路由，+18.7% |
| ZebraLogic | ZebraLogic: On the Scaling Limits of LLMs for Logical Reasoning | ICML 2025 | 1000道CSP谜题基准，"复杂度诅咒" |
| GridPuzzle | GridPuzzle (Tyagi et al.) | 2024 | 逻辑网格谜题细粒度错误标注分析 |
| Inst-Formal | Instantiation-based Formalization | IJCAI 2025 | 逐条约束正/负例实例化验证 |

### §2.2 引用的工作

| 缩写 | 全称 | 发表 | 核心贡献 |
|------|------|------|---------|
| Self-Refine | Self-Refine: Iterative Refinement with Self-Feedback | NeurIPS 2023 | 通用 LLM 自修复框架：生成-批评-修正循环 |
| Reflexion | Reflexion: Language Agents with Verbal Reinforcement Learning | NeurIPS 2023 | 语言强化，情节记忆，任务序列内改进 |
| Huang et al. | Large Language Models Cannot Self-Correct Reasoning Yet | ICLR 2024 | 证明 LLM 在无外部监督时无法可靠自我纠正 |
| RefineBench | RefineBench (2025) | arXiv 2025 | 结构化外部反馈 = 近完美自修复 |
| Iterative Repair | How Many Tries Does It Take? Iterative Self-Repair in LLM Code Generation | arXiv 2026 | 修复与重采样的 token 预算权衡分析 |

### §2.3 引用的工作

| 缩写 | 全称 | 发表 | 核心贡献 |
|------|------|------|---------|
| Reflexion | Reflexion: Language Agents with Verbal Reinforcement Learning | NeurIPS 2023 | 情节记忆，语言强化学习 |
| ExpeL | ExpeL: LLM Agents Are Experiential Learners | AAAI 2024 | 跨任务 insight 提取，成功/失败轨迹对比 |
| AutoGuide | AutoGuide: Automated Generation and Selection of State-Aware Guidelines | 2024 | 对比型指南生成，上下文感知检索 |
| ReasoningBank | ReasoningBank: Scaling Agent Self-Evolving with Reasoning Memory | arXiv Sep 2025 | 结构化知识单元蒸馏，MaTTS |
| Graph Memory | From Experience to Strategy: Empowering LLM Agents with Trainable Graph Memory | arXiv Nov 2025 | 可微分图结构决策记忆 |
| MACLA | MACLA: ... | 2025 | 15:1 压缩比，程序级可复用记忆 |
| ERL | Experiential Reflective Learning for Self-Improving LLM Agents | arXiv Mar 2026 | 失败经验价值分析，负约束启发式 |

---

## 写作说明

**三个小节的叙事逻辑：**

```
§2.1（神经符号方法）
    建立基础：翻译-执行-修复的方法论脉络
    揭示问题：修复停滞 + 经验不积累
         ↓
§2.2（自修复机制）
    深入分析：自修复的内在局限性
    关键发现：无形式化信号时停滞不可避免
         ↓
§2.3（智能体记忆）
    提供对比：记忆方法的进展与局限
    指出空白：CSP域 + 形式验证 = 空白交叉点
         ↓
本文 PRISM：填补交叉空白
```

**每小节末尾的"与本文的区别"段落是审稿人最关注的内容**，建议保留并在正式投稿中进一步精炼。

**引用数量控制建议：**
- §2.1：9-11 篇（主要神经符号工作 + CSP 基准）
- §2.2：5-7 篇（自修复核心工作 + 局限性分析）
- §2.3：7-9 篇（记忆工作谱系）
- 总计：约 22-27 篇，符合 ACL/EMNLP 长文的引用密度标准

**中英文术语对照表（供翻译参考）：**

| 中文术语 | 英文术语 |
|---------|---------|
| 约束满足问题 | Constraint Satisfaction Problem (CSP) |
| 不可满足核心 | UNSAT core |
| 最小修正子集 | Minimal Correction Subsets (MCS) |
| 修复停滞 | repair stagnation |
| 情节记忆 | episodic memory |
| 形式可验证范式 | solver-verified paradigm |
| 类型化修复轨迹记忆 | typed repair trajectory memory |
| 停滞检测 | stagnation detection |
| 循环检测 | loop detection |
| 策略切换 | strategy switching |
| 经验蒸馏 | experience distillation |
| 链式传播范式 | chain propagation paradigm |
| 关键决策点 | key decision point (KDP) |
| 语言强化学习 | verbal reinforcement learning |
