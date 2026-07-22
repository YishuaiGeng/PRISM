# PRISM · Methodology 完整全文（中文学术版）

---

## 3 方法论

### 3.1 问题定义与符号体系

**约束满足问题（CSP）。** 本文所研究的约束满足问题形式化定义为三元组 $\mathcal{P} = (\mathbf{X}, \mathbf{D}, \mathbf{C})$，其中 $\mathbf{X} = \{x_1, x_2, \ldots, x_n\}$ 为变量集合，$\mathbf{D} = \{D_1, D_2, \ldots, D_n\}$ 为对应的有限值域集合（$x_i \in D_i$），$\mathbf{C} = \{c_1, c_2, \ldots, c_m\}$ 为约束集合，每条约束 $c_j$ 指定其关联变量子集上的允许赋值组合。一个**解**（solution）是满足所有约束的完全赋值 $\theta: \mathbf{X} \to \bigcup_i D_i$，使得 $\theta(x_i) \in D_i$ 且 $\forall c_j \in \mathbf{C}: c_j(\theta)$ 成立。本文以逻辑网格谜题（Logic Grid Puzzle / Zebra Puzzle）作为 CSP 的具体实例，其中变量对应实体-属性对，约束以自然语言形式给出，包括直接赋值、相邻位置、相对位置、互斥等类型。

**求解轨迹（Solving Trajectory）。** 对于谜题实例 $\mathcal{P}$，一条求解轨迹定义为推理状态的时序序列：

$$\mathcal{T} = \langle (S_0, a_1, S_1),\ (S_1, a_2, S_2),\ \ldots,\ (S_{T-1}, a_T, S_T) \rangle$$

其中 $S_t = (C_t, \delta_t)$ 为第 $t$ 步的**求解器状态**，$C_t \subseteq \mathbf{C}$ 为当前已形式化的约束集合，$\delta_t: \mathbf{X} \to 2^{\bigcup D_i}$ 为各变量的当前域赋值；$a_t$ 为第 $t$ 步的**推理动作**，即 LLM 生成的推断（一条自然语言陈述及其对应的 Z3 形式化断言）。若 $S_T$ 满足所有约束（Z3 返回 SAT 且赋值与 ground truth 一致），则称 $\mathcal{T}$ 为**成功轨迹**；否则为失败轨迹。每条推理动作 $a_t$ 均携带 Z3 验证标签（SAT / UNSAT / ERROR）和域变化记录 $\Delta_t = \{x : |\delta_t(x)| < |\delta_{t-1}(x)|\}$。

**求解范式（Solving Paradigm）。** 本文提出如下结构化定义：一个**求解范式** $P$ 是五元组

$$P = (\mathcal{Q},\ \mathcal{O},\ \phi_{\text{pre}},\ \phi_{\text{post}},\ \mathcal{S})$$

其中：$\mathcal{Q}$ 为**触发条件**，指定激活该范式所需的约束类型集合及求解器状态特征；$\mathcal{O}$ 为**推断操作**，以参数化模板形式给出应执行的推断（如 $\texttt{pos}(\{X\}) = \{k\} + \{d\}$）；$\phi_{\text{pre}}$ 为 Z3 形式化的**前条件断言**，描述应用范式前当前约束集应满足的性质；$\phi_{\text{post}}$ 为 Z3 形式化的**后条件断言**，描述应用范式后应新增的约束；$\mathcal{S}$ 为**适用范围**标签，记录该范式经验证有效的谜题类型和规模。与现有智能体记忆工作不同，范式中的 $\phi_{\text{pre}}$ 和 $\phi_{\text{post}}$ 具有形式语义，可被 Z3 机械化验证，这是 PRISM 与所有先前方法的根本区别。

**关键符号汇总。** 表 1 列出了本文使用的核心符号。

| 符号 | 含义 |
|------|------|
| $\mathcal{P}$ | CSP 问题实例 |
| $\mathcal{T}_i$ | 谜题 $i$ 的求解轨迹 |
| $S_t = (C_t, \delta_t)$ | 第 $t$ 步求解器状态 |
| $a_t$ | 第 $t$ 步推理动作 |
| $U_t$ | 第 $t$ 步的 UNSAT core（最小不满足约束子集）|
| $P$ | 求解范式（五元组） |
| $\mathcal{L}$ | 范式库 |
| $\mathcal{M}$ | 修复轨迹记忆 |
| $R_t$ | 第 $t$ 次修复记录 |
| $\sigma(S_t)$ | 当前状态的约束类型签名 |
| $\tau_s, \tau_e, \tau_p$ | 范式验证三项阈值 |
| $\tau_{\text{stag}}, \tau_{\text{loop}}$ | 停滞与循环检测阈值 |

---

### 3.2 PRISM 框架概述

PRISM 采用**离线-在线两阶段架构**，将"经验积累"与"任务推理"解耦（图 2）。

**离线阶段**（一次性执行）以训练谜题集合为输入，依次执行：（1）收集 LLM+Z3 成功求解轨迹；（2）识别轨迹中的关键决策点（KDP）；（3）基于约束结构特征对 KDP 进行跨轨迹聚类；（4）LLM 对每个聚类执行范式抽象；（5）Z3 三重验证过滤低质量候选；（6）将通过验证的范式写入持久化范式库 $\mathcal{L}$。整个离线过程无需人工标注，由谜题生成器提供带 ground truth 的训练数据，Z3 充当唯一质量 oracle。

**在线阶段**（每道谜题执行）以新谜题的自然语言描述为输入，执行以下循环：（1）提取当前状态的约束类型特征；（2）从 $\mathcal{L}$ 中检索相关范式并执行一致性预检；（3）将通过预检的范式作为结构化提示注入 LLM；（4）LLM 生成推理步骤，Z3 实时验证；（5）若返回 UNSAT，进行原因归因并将修复记录写入修复轨迹记忆 $\mathcal{M}$；（6）$\mathcal{M}$ 执行停滞与循环检测，按需触发策略切换；（7）求解成功后，有效修复经验通过写回机制补充 $\mathcal{L}$。

下文依次详述各个组件。

---

### 3.3 离线阶段：求解范式提炼

#### 3.3.1 轨迹收集

给定训练谜题集合 $\{\mathcal{P}_1, \mathcal{P}_2, \ldots, \mathcal{P}_N\}$（由可控谜题生成器产出，涵盖 easy/medium/hard 三个难度级别），对每道谜题运行 LLM+Z3 求解系统 $r = 3$ 次，每次调用时采用 $\text{temperature} = 0.7$ 以引入推断路径多样性。仅保留最终 Z3 返回 SAT 且与 ground truth 匹配的成功轨迹。

每条轨迹的每步推理动作 $a_t$ 附加以下元信息：
- **Z3 验证标签**：$\texttt{outcome}_t \in \{\text{SAT}, \text{UNSAT}, \text{ERROR}\}$
- **域变化记录** $\Delta_t$：本步赋值后域大小缩减的变量集合
- **约束指纹**：当前活跃约束类型的哈希签名
- **步骤类型**（初始值）：由规则分类器初步估计，后续精化

对 N = 600 道训练谜题进行收集，每道 3 次，去重后约得 1500 条成功轨迹，构成范式提炼的原始数据池。

#### 3.3.2 关键决策点识别

**定义（关键决策点）。** 轨迹 $\mathcal{T}$ 中的步骤 $(S_{t-1}, a_t, S_t)$ 满足以下任一条件，则称其为**关键决策点**（Key Decision Point，KDP）：

- **条件 A（域显著收缩）**：$\exists x \in \Delta_t: |\delta_t(x)| \leq 1$，即存在某变量的值域在本步被唯一确定；
- **条件 B（非平凡步骤类型）**：步骤类型 $\tau_t \in \{\text{CHAIN\_PROPAGATION}, \text{CONTRADICTION\_ELIM}\}$，即涉及推导传播或矛盾消去的推断。

步骤类型 $\tau_t$ 由轻量规则分类器根据推理动作的自然语言文本判定：含"传播""因此位置""推出"等关键词时分类为 CHAIN\_PROPAGATION，含"矛盾""不可能""排除"等关键词时分类为 CONTRADICTION\_ELIM，其余默认为 DIRECT\_ASSIGNMENT。

对所有 1500 条训练轨迹提取 KDP，汇总得到约 6000 个关键决策点，构成聚类的输入数据。

#### 3.3.3 跨轨迹聚类与范式抽象

**特征表示。** 为实现跨轨迹的结构相似性度量，将每个 KDP 表示为固定维度的特征向量 $\mathbf{f}(\text{kdp})$：

$$\mathbf{f}(\text{kdp}) = \left[\underbrace{\mathbf{h}_{\text{ct}}}_{\text{约束类型直方图}},\ \underbrace{\mathbf{b}_{\text{dom}}}_{\text{域大小分布}},\ \underbrace{\mathbf{e}_{\tau}}_{\text{步骤类型独热}},\ \underbrace{n_{\text{var}},\ n_{\text{con}}}_{\text{谜题规模（归一化）}}\right]$$

其中约束类型直方图 $\mathbf{h}_{\text{ct}} \in \mathbb{R}^{|\mathcal{T}_c|}$ 统计当前求解器状态中各类型约束的归一化频次，$\mathcal{T}_c$ 为预定义的约束类型词汇表（含 direct\_position、adjacent\_left、adjacent\_right、exclusion、binding 等 10 种类型）；域大小分布 $\mathbf{b}_{\text{dom}} \in \mathbb{R}^4$ 为四分箱直方图（$|D|=1, 2, 3\text{-}5, \geq 6$）；$n_{\text{var}}, n_{\text{con}}$ 分别为变量数和约束数的最大归一化值。

**层次聚类。** 对所有 KDP 特征向量执行以距离阈值 $\theta$ 为截断的完全链接层次聚类（agglomerative clustering，complete linkage，余弦距离）：

$$\text{dist}(\mathbf{f}_i, \mathbf{f}_j) = 1 - \frac{\mathbf{f}_i \cdot \mathbf{f}_j}{\|\mathbf{f}_i\| \cdot \|\mathbf{f}_j\|}$$

丢弃成员数低于最小支持度 $m_{\min} = 5$ 的聚类，保留结构上充分相似且有足够轨迹支撑的候选聚类集合 $\{C_1, C_2, \ldots, C_K\}$。超参数 $\theta = 0.25$（默认值）在开发集上通过网格搜索确定，§5.4 分析了系统对该参数的敏感性。

**范式抽象。** 对每个聚类 $C_k$，从中均匀采样最多 10 个代表性 KDP，将其求解器状态、推理文本和域变化信息格式化后提交给 LLM，要求其抽象出一个可复用的范式：

> *给定以下来自成功轨迹的相似推理步骤……请提取一个通用求解范式，以 JSON 格式输出（trigger, operation\_nl, operation\_template, pre\_condition\_z3, post\_condition\_z3, scope）。*

LLM 输出的范式候选 $\hat{P}_k$ 进入下一阶段的形式化验证。由于范式抽象本身存在 LLM 引入的不确定性，每个聚类最多允许重试 2 次。

#### 3.3.4 范式的 Z3 三重验证

为保证写入范式库的每个范式具有形式化质量保证，对每个候选范式 $\hat{P}_k$ 执行以下三项独立验证，**任一不通过则拒绝写入**：

**（1）Soundness（正确性）验证。** 从谜题池中随机采样 50 个满足触发条件 $\mathcal{Q}$ 的求解器状态，对每个状态在当前约束集基础上叠加范式操作模板的实例化结果，检验 Z3 的可满足性：

$$\text{soundness}(\hat{P}_k) = \frac{1}{N_s} \sum_{i=1}^{N_s} \mathbf{1}\left[\text{Z3-SAT}\left(C_i \cup \{\text{op}(\hat{P}_k, \mathbf{b}_i)\}\right)\right] \geq \tau_s$$

其中 $\mathbf{b}_i$ 为第 $i$ 个测试状态的模板变量绑定，$\tau_s = 0.90$。

**（2）Effect（效果）验证。** 在 Soundness 通过的实例上，进一步检验应用范式后是否确实引发了域收缩：

$$\text{effect}(\hat{P}_k) = \frac{1}{N_e} \sum_{i=1}^{N_e} \mathbf{1}\left[|\delta_{\text{after}}| > |\delta_{\text{before}}|\right] \geq \tau_e$$

其中 $|\delta|$ 为已确定赋值（域大小为 1）的变量数，$\tau_e = 0.80$。此条件保证范式的应用具有实质性推理价值，而非仅在 Z3 层面可满足。

**（3）Trigger Precision（触发精度）验证。** 从谜题池中采样 20 个**不满足**触发条件的状态，验证范式操作在这些状态上应为 UNSAT（即范式不会错误触发）：

$$\text{precision}(\hat{P}_k) = \frac{1}{N_p} \sum_{i=1}^{N_p} \mathbf{1}\left[\text{Z3-UNSAT}\left(C_i \cup \{\text{op}(\hat{P}_k, \mathbf{b}_i)\}\right)\right] \geq \tau_p$$

其中 $\tau_p = 0.80$。

通过三重验证的范式更新其质量指标（$\text{soundness\_score}$、$\text{effect\_score}$），计算综合置信度 $\text{conf}(\hat{P}_k) = 0.5 \cdot \text{soundness} + 0.3 \cdot \text{effect} + 0.2 \cdot \text{hit\_rate}$（初始 hit\_rate = 0），并写入 SQLite 持久化范式库 $\mathcal{L}$。在 600 道训练谜题上，离线阶段共提炼约 35 个通过验证的范式，压缩比约为 40:1。

---

### 3.4 在线阶段：范式引导推理

#### 3.4.1 约束特征提取与两层范式检索

给定新谜题 $\mathcal{P}^*$，LLM 首先执行初始翻译，将自然语言约束集转化为 Z3 形式化表示并构建初始求解器状态 $S_0$。在每个推理步骤 $t$ 开始时，从当前状态 $S_t$ 提取**约束类型签名** $\sigma(S_t) = \text{sorted}(\{type(c) \mid c \in C_t\})$，作为范式检索的查询键。

范式检索采用**两层过滤**策略，兼顾效率与精度：

**第一层（类型集合匹配，硬过滤）：** 返回所有满足以下条件的范式：

$$\mathcal{L}_1(S_t) = \left\{P \in \mathcal{L} \mid \mathcal{Q}_P.\text{required\_types} \subseteq \sigma(S_t)\ \wedge\ \text{conf}(P) \geq \tau_{\min}\right\}$$

此层仅需集合包含性判断，时间复杂度 $O(|\mathcal{L}|)$，通常可将候选集从 $|\mathcal{L}| \approx 35$ 压缩至 5 以内。

**第二层（语义匹配，LLM 判断）：** 对 $\mathcal{L}_1$ 中的候选范式，构造提示描述当前求解器状态，询问 LLM 哪些范式的触发条件被真正满足。此层仅在候选数量 $\geq 2$ 时触发，每步最多引入 1 次额外 LLM 调用。返回最终候选集 $\mathcal{L}_2(S_t)$，按置信度降序取前 $k = 3$ 个。

#### 3.4.2 一致性预检与提示注入

**一致性预检。** 在将范式注入提示之前，对每个候选范式 $P \in \mathcal{L}_2$ 执行实时 Z3 一致性检验：

$$\text{check\_consistent}(P, S_t) = \text{Z3-SAT}\left(C_t \cup \{\text{op}(P, \cdot)\}\right)$$

若范式操作模板在当前约束集下为 UNSAT，则将该范式从候选集中移除，不注入提示。此机制构成范式引导的**第二道防线**，保证注入给 LLM 的任何范式建议在当前求解器状态下逻辑可行，不会误导 LLM 生成矛盾的推断。经预检通过的范式构成最终注入集 $\mathcal{L}_{\text{inject}}(S_t)$。

**结构化提示注入。** 通过如下格式将范式作为结构化提示注入 LLM 上下文：

> *当前约束结构中以下已验证求解策略可能适用：*
> *[P1] 直接赋值传播：当约束"实体 X 具有属性 V"成立时，令 $\texttt{domain}(X) \leftarrow \{V\}$，并对同属性类所有其他实体执行 $\texttt{domain}(Y) \leftarrow \texttt{domain}(Y) \setminus \{V\}$。*
> *[P2] 链式位置传播：若 $\texttt{pos}(A) = k$ 已知且存在约束 $\texttt{pos}(B) = \texttt{pos}(A) + d$，则推导 $\texttt{pos}(B) = k + d$。*

采用**建议式（soft injection）**而非**强制式（hard injection）**格式：提示 LLM 将范式作为参考策略，而非硬性规定必须执行的推断步骤。此设计的理由在于，强制式注入在范式不完全适用时可能导致 LLM 机械地套用错误操作，消融实验（§5.4）验证了软注入在准确率和范式遵从率方面均优于强制式注入。

#### 3.4.3 逐步 Z3 验证与 UNSAT 归因

LLM 生成推理动作 $a_{t+1}$（含自然语言推理和 Z3 形式化断言）后，通过约束注册表（Constraint Registry）以 `assert_and_track` 方式添加至求解器，保证每条约束具有可追踪的唯一标识符。随后调用 Z3 进行验证：

**SAT 分支：** 更新域赋值 $\delta_{t+1}$，记录当前状态为检查点（用于后续可能的策略切换回退）。若模型赋值覆盖所有目标变量（完全解），则终止推理循环。

**UNSAT 分支：** 提取 UNSAT core $U_{t+1} \subseteq C_t \cup \{a_{t+1}\}$，执行**原因归因**：

$$\text{attr}(a_{t+1}, U_{t+1}) = \begin{cases} \text{NEW\_ASSERTION} & \text{if } a_{t+1} \in U_{t+1} \\ \text{LEGACY\_ERROR} & \text{if } a_{t+1} \notin U_{t+1} \end{cases}$$

若归因为 **LEGACY\_ERROR**，说明矛盾在添加新推断前已潜伏于先前翻译的约束中，此时撤销 $a_{t+1}$，将 $U_{t+1}$ 中的先前约束标记为待修复目标，进入修复流程。若归因为 **NEW\_ASSERTION**，说明当前推断本身引入了矛盾，以 $U_{t+1}$ 为诊断信息直接进入修复流程。

UNSAT core 通过约束注册表映射回对应的自然语言约束文本，构成传递给 LLM 的语义诊断信号，使修复提示具有精确的约束级别定位（与 Logic-LM 系列仅提供原始报错字符串形成对比）。

---

### 3.5 修复轨迹记忆

#### 3.5.1 记忆数据结构

修复轨迹记忆 $\mathcal{M}$ 维护一个有序的修复记录列表 $\{R_1, R_2, \ldots, R_L\}$，每条记录为六元组：

$$R_t = (\underbrace{e_t}_{\text{错误类型}},\ \underbrace{U_t}_{\text{UNSAT core}},\ \underbrace{\hat{U}_t}_{\text{core 指纹}},\ \underbrace{\alpha_t}_{\text{修复动作}},\ \underbrace{o_t}_{\text{修复结果}},\ \underbrace{U'_t}_{\text{修复后 core}})$$

其中：
- $e_t \in \{\text{SYNTAX, OVER\_CONSTRAINT, UNDER\_CONSTRAINT, SEMANTIC\_FLIP, SCOPE\_ERROR, LEGACY}\}$ 为错误类型标签；
- $U_t$ 为当前 UNSAT core 中的约束 ID 列表；
- $\hat{U}_t = \text{MD5}(\text{sorted}(U_t))$ 为 core 的哈希指纹，用于快速比较；
- $\alpha_t = (\text{type}, \text{target}, \text{summary}, \mathbf{e}_t)$ 为修复动作，其中 $\mathbf{e}_t$ 为 summary 的语义嵌入向量；
- $o_t \in \{\text{SAT, UNSAT}\}$ 为修复后的 Z3 验证结果；
- $U'_t$ 为修复后的新 UNSAT core（若 $o_t = \text{UNSAT}$）。

**嵌入计算。** 修复动作的语义嵌入 $\mathbf{e}_t$ 由轻量预训练句向量模型（all-MiniLM-L6-v2）对 summary 字段计算得到，用于循环检测中的相似度度量。若计算资源受限，可用基于哈希的确定性向量替代，作为实现降级方案。

#### 3.5.2 停滞检测

**定义（修复停滞）。** 当连续 $k$ 条修复记录的 UNSAT core 集合两两之间均具有高度重叠，说明修复努力未能改变矛盾的本质来源，系统处于**停滞**状态。形式化定义为：

$$\text{stagnate}(\mathcal{M}, k) = \mathbf{1}\left[\min_{i \neq j \in \{L-k+1,\ldots,L\}} J(U_i, U_j) \geq \tau_{\text{stag}}\right]$$

其中 Jaccard 相似度定义为

$$J(U_i, U_j) = \frac{|U_i \cap U_j|}{|U_i \cup U_j|}$$

$\tau_{\text{stag}} = 0.75$，$k = 3$（默认值）。取**最小值**而非平均值保证了检测的保守性：只有当所有相邻记录对的 core 重叠均超过阈值时，才确认停滞，从而避免误报。

#### 3.5.3 循环检测

**定义（修复循环）。** 当系统即将执行的修复动作 $\alpha_{\text{new}}$ 与历史中某条修复动作在语义上高度相似时，判定系统陷入**修复循环**，定义为：

$$\text{loop}(\mathcal{M}, \alpha_{\text{new}}) = \mathbf{1}\left[\max_{t \in \{1,\ldots,L\}} \cos(\mathbf{e}_{\text{new}}, \mathbf{e}_t) \geq \tau_{\text{loop}}\right]$$

其中 $\cos(\cdot,\cdot)$ 为余弦相似度，$\tau_{\text{loop}} = 0.90$。循环检测在修复动作实际执行**前**触发，若检测为正，则阻断该动作的执行，防止无效重复。

停滞检测关注 UNSAT core 的演化（结构层面），循环检测关注修复动作的重复（行为层面），两者互补，覆盖不同模式的修复失效场景。

#### 3.5.4 四级策略切换协议

当停滞或循环检测触发时，系统依次评估并执行以下四级策略切换，按优先级升序排列：

**L1 — 切换修复目标约束。** 触发条件：停滞检测首次触发。响应：保持修复类型不变，从当前 UNSAT core 中选择**尚未被修改过**的约束作为新修复目标。向 LLM 注入提示：

> *"已尝试修改约束 $\{c_j\}$，结果仍为 UNSAT，请改为修改 UNSAT core 中的其他约束 $\{c_k\}$。"*

**L2 — 切换修复类型。** 触发条件：L1 执行后连续 2 次仍停滞。响应：切换修复策略类型（如从"放松约束"改为"重新翻译约束"），向 LLM 注入新策略描述。

**L3 — 回退至最近 SAT 检查点。** 触发条件：循环检测触发，或 L2 执行后仍停滞。响应：将求解器状态回退至最近一次 Z3 返回 SAT 时保存的检查点状态 $S_{\tau^*}$，从该状态出发以**不同的推理路径**重新开始（通过 prompt 中列出已失败路径来引导 LLM 探索替代方向）。若检查点列表为空（从未出现 SAT 中间状态），则自动升级至 L4。

**L4 — 全量重新翻译（last resort）。** 触发条件：L3 失败或无可用检查点。响应：丢弃当前全部形式化结果，提示 LLM 从原始自然语言约束重新翻译完整的约束集，并提供历史失败经验摘要（"以下翻译方案均已失败，请注意方向性约束和作用域约束的表述"）作为防错指导。

策略切换的执行历史通过 level\_attempts 计数器记录（如 $k_{L1} = 2$ 表示 L1 已触发 2 次），确保升级决策的确定性与可追溯性。

#### 3.5.5 经验写回机制

当在线阶段成功求解一道谜题后，系统对修复记忆 $\mathcal{M}$ 执行**回溯分析**：识别所有导致最终 SAT 的修复记录（即 $o_t = \text{SAT}$ 的记录），提取其错误类型、UNSAT core 模式与修复动作类型，构成**修复范式候选**三元组 $(e_t, \hat{U}_t, \alpha_t.\text{type})$。

候选三元组提交至离线阶段的 Z3 验证流程（soundness 检验），通过者以较低初始置信度写入范式库（$\text{conf}_{\text{init}} = \max(0, \text{soundness} - 0.1)$），作为在线提炼的修复范式。此机制使范式库在系统运行过程中持续扩充，体现了"解题越多、范式越丰富"的正反馈特性。

综合以上各组件，PRISM 形成了一个在 **CSP 求解能力**（范式库引导推理）与**失败恢复能力**（修复记忆防止停滞）两个维度上均持续增长的智能体系统，填补了现有神经符号推理工作（无经验积累）与智能体记忆工作（无形式验证）之间的研究空白。

---

### 3.6 三类核心范式的形式化实例

为使范式概念具体可理解，本节以 Zebra 谜题为场景，给出三类核心范式（P1、P2、P3）的完整形式化定义与应用示例。三类范式对应 §3.3.2 中识别的三种步骤类型，覆盖 CSP 求解中最主要的三类非平凡推断场景。

**范式 P1：直接赋值传播（Direct Assignment Propagation）**

$$P_1 = \left(\mathcal{Q}_1,\ \mathcal{O}_1,\ \phi^1_{\text{pre}},\ \phi^1_{\text{post}},\ \mathcal{S}_1\right)$$

- $\mathcal{Q}_1$：当前约束集中存在直接赋值类型约束（$\texttt{direct\_binding}$ 或 $\texttt{direct\_position}$），且目标变量 $X$ 的当前值域 $|\delta(X)| \geq 2$；
- $\mathcal{O}_1$：令 $\delta(X) \leftarrow \{V\}$，并对属性类 $\text{attr}(X)$ 下所有其他变量 $Y \neq X$ 执行 $\delta(Y) \leftarrow \delta(Y) \setminus \{V\}$；
- $\phi^1_{\text{pre}}$：$\exists c \in C_t: c \equiv (X = V)$，即当前存在确定性绑定约束；
- $\phi^1_{\text{post}}$：$\texttt{Z3: And}(X == V,\ \texttt{ForAll}(Y,\ \texttt{Implies}(Y \neq X,\ Y \neq V)))$；
- $\mathcal{S}_1$：所有规模的逻辑网格谜题，触发频率最高（覆盖约 60% 的 KDP）。

> **应用示例**：自然语言约束"挪威人住在第 1 号房子"直接触发 P1。应用后：$\delta(\texttt{house}[\text{Norwegian}]) \leftarrow \{1\}$，同时对其他国籍 $Y \in \{\text{German, English, Swedish, Danish}\}$ 有 $1 \notin \delta(\texttt{house}[Y])$。Z3 验证该推断与当前约束集 SAT。

**范式 P2：链式位置传播（Chain Position Propagation）**

$$P_2 = \left(\mathcal{Q}_2,\ \mathcal{O}_2,\ \phi^2_{\text{pre}},\ \phi^2_{\text{post}},\ \mathcal{S}_2\right)$$

- $\mathcal{Q}_2$：当前约束集中同时存在（i）已确定赋值 $\texttt{pos}(A) = k$，以及（ii）相对位置约束 $\texttt{pos}(B) = \texttt{pos}(A) + d$（$d \in \mathbb{Z}$），且 $|\delta(\texttt{pos}(B))| \geq 2$；
- $\mathcal{O}_2$：将 $\texttt{pos}(A) = k$ 代入相对位置约束，推导 $\texttt{pos}(B) = k + d$，令 $\delta(\texttt{pos}(B)) \leftarrow \{k+d\}$；
- $\phi^2_{\text{pre}}$：$\texttt{Z3: And}(\texttt{pos}(A) == k,\ \texttt{pos}(B) == \texttt{pos}(A) + d)$；
- $\phi^2_{\text{post}}$：$\texttt{Z3: pos}(B) == k + d$，且需满足边界约束 $1 \leq k+d \leq n_{\text{houses}}$；
- $\mathcal{S}_2$：含相对位置约束的逻辑网格谜题，边界溢出时（$k+d \notin [1, n]$）触发 P3 而非 P2。

> **应用示例**：已知 $\texttt{pos}(\text{Norwegian}) = 1$，约束"蓝色房子紧挨挪威人右侧"即 $\texttt{pos}(\text{Blue}) = \texttt{pos}(\text{Norwegian}) + 1$，触发 P2。推导 $\texttt{pos}(\text{Blue}) = 2$，Z3 验证 SAT。若翻译错误将方向写反（$\texttt{pos}(\text{Blue}) = \texttt{pos}(\text{Norwegian}) - 1 = 0$），则 Z3 因边界越界返回 UNSAT，自动触发 UNSAT 归因流程，将该约束标记为翻译错误候选。

**范式 P3：矛盾消去（Contradiction-Based Elimination）**

$$P_3 = \left(\mathcal{Q}_3,\ \mathcal{O}_3,\ \phi^3_{\text{pre}},\ \phi^3_{\text{post}},\ \mathcal{S}_3\right)$$

- $\mathcal{Q}_3$：P1 和 P2 均无法进一步缩减当前变量域（域大小 $\geq 2$ 的变量仍存在），需通过试探性赋值排除候选值；
- $\mathcal{O}_3$：对域大小为 2 的变量 $X$，选取候选值 $v \in \delta(X)$，令 $\delta^{\text{test}}(X) \leftarrow \{v\}$，将其与 $C_t$ 传递给 Z3；若 Z3 返回 UNSAT 且 UNSAT core 包含试探约束（即矛盾由 $X=v$ 引发），则令 $\delta(X) \leftarrow \delta(X) \setminus \{v\}$，若 $|\delta(X)| = 1$ 则触发 P1；
- $\phi^3_{\text{pre}}$：$|\delta(X)| = 2$，且 $X = v$ 被试探时 $\texttt{Z3-UNSAT}(C_t \cup \{X=v\})$；
- $\phi^3_{\text{post}}$：$\delta(X) \leftarrow \delta(X) \setminus \{v\}$，追加约束 $X \neq v$；
- $\mathcal{S}_3$：P1/P2 穷尽后激活，复杂谜题（$4\times5$ 及以上）中使用频率较高。

> **关键区分**：P3 的 UNSAT core 中必须包含试探约束 $X = v$，以区分"试探导致矛盾"（正常 P3 消去）与"先验约束翻译错误导致矛盾"（LEGACY\_ERROR，应触发修复而非消去）。此区分由 §3.4.3 的 UNSAT 归因机制负责。

---

### 3.7 算法伪代码

本节以算法伪代码形式完整描述 PRISM 的离线与在线两个阶段，作为 §3.3–§3.5 的形式化汇总。

**算法 1：PRISM 离线范式提炼**

```
算法 1：PRISM-Offline(Puzzles, LLM, Z3, θ, m_min, τ_s, τ_e, τ_p)
输入：训练谜题集合 Puzzles，LLM，Z3 求解器，
      聚类阈值 θ，最小支持度 m_min，
      三项验证阈值 τ_s, τ_e, τ_p
输出：范式库 L

1.  T_all ← ∅                           // 初始化轨迹池
2.  for each P in Puzzles do
3.      for r = 1, 2, 3 do              // 每题收集 3 条轨迹
4.          T ← LLM_Solve(P, temperature=0.7, Z3)
5.          if T.outcome == SAT then
6.              T_all ← T_all ∪ {T}
7.  
8.  KDP_all ← ∅                         // 关键决策点提取
9.  for each T in T_all do
10.     for each step (S_{t-1}, a_t, S_t) in T do
11.         if IsKDP(S_{t-1}, a_t, S_t) then   // 条件 A 或条件 B
12.             KDP_all ← KDP_all ∪ {(T.id, t, Featurize(step, T))}
13. 
14. Clusters ← AgglomerativeCluster(KDP_all, metric=cosine, θ=θ)
15. Clusters ← {C ∈ Clusters : |C| ≥ m_min}   // 过滤小聚类
16. 
17. L ← ∅                               // 初始化范式库
18. for each C_k in Clusters do
19.     Reps ← SampleRepresentatives(C_k, n=10)
20.     P̂_k ← LLM_Abstract(Reps, T_all)  // LLM 范式抽象（最多重试 2 次）
21.     if P̂_k == NULL then continue
22.     
23.     Match ← SampleMatchingStates(P̂_k.Q, PuzzlePool, n=50)
24.     NonMatch ← SampleNonMatchingStates(P̂_k.Q, PuzzlePool, n=20)
25.     
26.     soundness ← CheckSoundness(P̂_k, Match, Z3)       // 验证阶段 1
27.     if soundness < τ_s then continue
28.     
29.     effect ← CheckEffect(P̂_k, Match, Z3)              // 验证阶段 2
30.     if effect < τ_e then continue
31.     
32.     precision ← CheckPrecision(P̂_k, NonMatch, Z3)    // 验证阶段 3
33.     if precision < τ_p then continue
34.     
35.     P̂_k.soundness_score ← soundness
36.     P̂_k.effect_score ← effect
37.     P̂_k.confidence ← 0.5·soundness + 0.3·effect
38.     L ← L ∪ {P̂_k}
39. 
40. return L
```

**算法 2：PRISM 在线范式引导推理**

```
算法 2：PRISM-Online(P*, L, LLM, Z3, τ_stag, τ_loop, K)
输入：测试谜题 P*，范式库 L，LLM，Z3 求解器，
      停滞阈值 τ_stag，循环阈值 τ_loop，最大修复轮数 K
输出：求解结果（解赋值或失败）

1.  M ← ∅                               // 初始化修复记忆
2.  S_0 ← (∅, D_initial)                // 初始求解器状态
3.  Switcher.init(M)
4.  repair_count ← 0
5.  
6.  for t = 1, 2, ..., MAX_STEPS do
7.      // ── 范式检索 ──
8.      σ ← ExtractTypeSignature(S_{t-1})
9.      L_1 ← {P ∈ L : P.Q.required_types ⊆ σ ∧ conf(P) ≥ τ_min}
10.     L_2 ← LLM_SemanticFilter(L_1, S_{t-1})     // 仅当 |L_1| ≥ 2
11.     L_inj ← Z3_ConsistencyFilter(L_2, S_{t-1}) // 一致性预检
12.     
13.     // ── 范式引导推断 ──
14.     hints ← FormatParadigmHints(L_inj)
15.     history ← M.GetHistorySummary()
16.     a_t ← LLM_Infer(P*.nl, S_{t-1}, hints, history)
17.     
18.     // ── Z3 验证 ──
19.     S_t ← Z3_AddAndCheck(S_{t-1}, a_t)
20.     
21.     if S_t.outcome == SAT then
22.         for P in L_inj do
23.             L.RecordUsage(P.id, was_hit=True)
24.         M.SaveCheckpoint(S_t)
25.         if IsSolved(S_t, P*) then
26.             WriteBack(M, L, Z3)               // 经验写回
27.             return S_t.assignment
28.     
29.     else if S_t.outcome == UNSAT then
30.         U_t ← Z3_GetUNSATCore(S_t)
31.         attr ← Attribute(a_t, U_t)           // UNSAT 归因
32.         if attr == LEGACY_ERROR then
33.             S_t ← Revert(S_t, a_t)           // 撤销新推断
34.         e_t ← ClassifyError(U_t, attr)
35.         
36.         if repair_count ≥ K then break
37.         repair_count ← repair_count + 1
38.         
39.         // ── 停滞与循环检测 ──
40.         α_proposed ← ProposedRepairAction(U_t, M)
41.         level ← Switcher.Diagnose(M, α_proposed, τ_stag, τ_loop)
42.         switch_prompt ← Switcher.GetPrompt(level, U_t, M)
43.         Switcher.Record(level)
44.         
45.         // ── 修复步骤 ──
46.         α_t ← LLM_Repair(P*.nl, U_t, M, switch_prompt, Z3)
47.         S_t ← Z3_ApplyRepair(S_t, α_t, Z3)
48.         o_t ← Z3_Check(S_t)
49.         
50.         R_t ← MakeRecord(t, e_t, U_t, α_t, o_t)
51.         M.Append(R_t)
52. 
53. return FAILED
```

---

### 3.8 实现细节

**大语言模型。** 主实验中 LLM backbone 统一使用 GPT-4o（版本 gpt-4o-2024-08-06）。评估阶段所有推断调用采用 $\text{temperature} = 0.0$（确定性输出），并设置 $\texttt{seed} = 42$ 以保证跨 run 可复现；离线轨迹收集阶段采用 $\text{temperature} = 0.7$ 以引入推断路径多样性。全部 LLM 调用均以 JSON 格式要求输出，并对格式解析失败设置最多 3 次自动重试。

**Z3 求解器。** 采用 Z3 Python API（z3-solver $\geq$ 4.12.0）。所有约束以 `assert_and_track` 方式添加，保证 `unsat_core()` 接口的可用性。单次 Z3 调用超时设置为 5 秒，超时判定为 TIMEOUT 并不计入求解精度统计。约束注册表（Constraint Registry）维护从约束 ID 到自然语言文本及 Z3 表达式对象的双向映射，是 UNSAT core 回译机制的基础设施，在 NL→Z3 翻译阶段与约束添加同步建立。

**范式检索嵌入。** 修复记忆的循环检测模块使用 `all-MiniLM-L6-v2` 模型计算修复动作的语义嵌入（384维），通过 sentence-transformers 库懒加载以避免冷启动开销。范式的第一层检索（约束类型集合匹配）为纯集合操作，无需嵌入计算。

**范式库持久化。** 范式库通过 SQLite 数据库持久化存储，同时提供 JSON 格式导出以支持人工检查和跨实验共享。在线阶段每次范式命中或未命中均更新对应范式的 `usage_count` 和 `hit_count` 计数器，用于动态计算置信度 $\text{conf}(P)$。

**超参数设置。** 表 2 汇总了 PRISM 的所有超参数，其默认值均在 ZebraLogic 开发集（100 道）上通过单变量网格搜索确定；§5.4 报告了系统对关键超参数的敏感性分析结果。

| 超参数 | 默认值 | 搜索范围 | 含义 |
|--------|--------|---------|------|
| $\theta$ | 0.25 | [0.15, 0.35] | 聚类余弦距离阈值 |
| $m_{\min}$ | 5 | [3, 10] | 范式最小轨迹支持数 |
| $\tau_s$ | 0.90 | [0.85, 0.95] | Soundness 验证阈值 |
| $\tau_e$ | 0.80 | [0.75, 0.90] | Effect 验证阈值 |
| $\tau_p$ | 0.80 | [0.75, 0.90] | Trigger precision 阈值 |
| $\tau_{\text{stag}}$ | 0.75 | [0.60, 0.85] | 停滞检测 Jaccard 阈值 |
| $k$ | 3 | [2, 5] | 停滞检测窗口大小 |
| $\tau_{\text{loop}}$ | 0.90 | [0.85, 0.95] | 循环检测余弦相似度阈值 |
| $\tau_{\min}$ | 0.50 | [0.40, 0.65] | 范式检索最低置信度 |
| $K_{\text{top}}$ | 3 | [1, 5] | 每步注入范式数量上限 |
| $K_{\text{repair}}$ | 8 | [5, 12] | 最大修复轮数 |

**计算开销。** PRISM 的在线推理阶段不涉及任何模型参数更新，全部计算分布在 LLM API 调用（主要开销）和本地 Z3 调用（单次 Zebra 6×6 谜题 $<$ 0.5 秒，可忽略不计）之间。相较于不使用范式和记忆的基线（Paper-1），每道谜题在成功情形下的额外 LLM 调用约为 1–2 次（范式检索第二层语义判断），在触发修复情形下的额外调用视停滞检测结果而定，平均额外增加不超过 1.5 次调用（见 §5.2 效率分析）。
