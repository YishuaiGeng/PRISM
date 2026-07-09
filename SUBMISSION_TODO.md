# PRISM 投稿路线图（AAAI-27）

> 目标：AAAI-27（预计摘要截止 ~7 月底，全文 ~8 月初，参照 AAAI-26 惯例）
> 创建：2026-07-08 ｜ 距截稿约 3–4 周
> 结论基线：创新性骨架够 AAAI（求解器作为经验准入门控 + 错误范式发现 + 停滞检测/策略切换）；
> 风险在实验数据（大量占位）与基准组合（合成谜题为主、需 AR-LSAT 对标锚点）。

---

## 📌 当前状态快照（2026-07-08）

- ✅ AR-LSAT 已重新下载：`data/hf/ar-lsat/`（train 1,630 / dev 231 / test 230），
  下载逻辑已固化到 `scripts/download_datasets.py --datasets arlsat`
- ⚠️ **论文草稿把 dev(231) 误当 test**：Logic-LM/Logic-LM++ 的 43.0%/46.3% 是在 **test 230 题**上报告的，
  实验和正文统一改用 test 230；dev 231 用于调超参
- ✅ ZebraLogic 官方测试集已下载（1,000 题 = 25 规模 × 40；见下方"规模口径"决策项）
- ✅ K&K 已扩容：test 100/规模（共 700）+ train 6,200（people2 为 200，其余 1,000/规模）
- ⚠️ Logical Deduction（BBH）接近饱和 + 结构上是 ZebraLogic 子集，只能当辅助迁移基准
- ⚠️ 论文主草稿（`docs/paper_draft/templates/paper_draft_template_zh.tex`）中
  AR-LSAT 表、多规模修复表、错误分布、HR 基线、多模型表、敏感性表均为【待补实验】占位数据

---

## P0 — 不完成就无法投稿（第 1–2 周，7/8–7/21）

### 数据准备（先行，1–2 天内完成）

- [x] **下载官方 ZebraLogic 测试集**（2026-07-08 完成）：`data/hf/zebralogic/grid_mode_test.jsonl`，
      1,000 题 = 25 种规模（2×2–6×6）× 40 题。自生成数据只用于离线范式提炼
- [ ] **ZebraLogic 正式测试集定义（建议方案，2026-07-08）**——
      官方集为 25 规模 × 40 题；线索类型固定，无需全量跑所有系统。建议：
      (a) **正式测试集 = 3–6 房 × 3–6 属性共 16 种规模、640 题**，
      剔除 2×N / N×2 平凡规模（所有系统接近天花板，无区分度）；
      (b) 主表按难度桶分组报告（对齐 ZebraLogic 官方 Easy/Hard 划分，
      按搜索空间 (houses!)^attributes 计算，阈值需对照原论文核对），
      避免 25 列的表；
      (c) 仅 PRISM 完整版 + LLM+Z3 基线各跑一次**全量 1,000 题单种子**，
      作为与官方 leaderboard 可比的 headline 行；
      多系统 × 3 种子的完整矩阵只在 640 题子集上跑。
      论文正文"900 道/六种规模"的描述随之改写
- [x] **K&K 扩容**（进行中，后台下载 test 100/规模 + train 分割）
- [x] **AR-LSAT 口径修正**（2026-07-08 完成）：tex 5 处 + 2 个 md 已统一 test=230、dev=231

### 实验类（按风险从高到低）

- [ ] **1. AR-LSAT 全量流水线跑通**（最大不确定项）
      — train 1,630 构建独立范式库；test 230 上跑 LLM+Z3 基线、PRISM 完整、
      两个消融变体（无修复记忆 / 无范式库）× 3 种子。
      决定"跨任务泛化"主线是否成立
      - [x] 评测代码已实现（2026-07-08）：`prism/evaluation/benchmarks/arlsat.py`
            （loader + 题型分类器 + SatLM 式逐选项 SAT/UNSAT 判定）+
            `scripts/run_arlsat.py` + `tests/test_arlsat.py`（29 个测试全过，
            离线含真实数据 smoke）。协议：GuidedSolver 形式化 passage →
            LLM 单独翻译五个选项 → could/must/cannot/except 四类判定
      - [x] 带 API 的 smoke 完成（2026-07-08，4 轮迭代，GPT-4o-mini × 10 题）。
            **机制验证通过**：翻译→背景约束→选项公式→逐选项 SAT/UNSAT→选letter
            全链路工作，修复回路可触发。期间修掉 3 个 bug：
            ① 翻译器 schema 过滤器误杀 AR-LSAT 约束（加 `schema_filter` opt-out）；
            ② `final_constraints` 取到修复失败的 UNSAT 状态（改为优先最后 SAT 状态）；
            ③ 选项翻译 null 率过高（prompt 改 best-effort + max tokens 2048，
            null 率 9/50 → 6/50）
      - [x] **AR-LSAT 专用翻译 prompt**（2026-07-08）：`LLMClient.translate/retranslate`
            按 `domain="arlsat"` 分发到 LSAT 专用 prompt（排序/分组/选择三类游戏
            编码规则 + Sum(If) 基数模式 + 防错指引）；L4 重翻译同步；430 测试全过
      - [x] **GPT-4o 定标通过**（2026-07-08，test 前 40 题，LLM+Z3 纯基线）：
            **Acc 42.5%**（Logic-LM GPT-4 为 43.0%，量级吻合，流水线放行）；
            extracted 67.5%，ambiguous 32.5%，平均 3.0 次调用/题。
            分题型：cannot 50%、could 42.9%、must 41.7%、unknown 33.3%
      - [ ] **遗留（实验阶段处理）**：
            (a) 未提取率 32.5%（选项全无候选时输出 None 计错）——考虑加
            Logic-LM 式随机回退协议（期望 +6pp 左右），实验前定协议并全表统一；
            (b) unknown 题型约 24/230（计数/完整列表类）当前回退 could_be_true；
            (c) 4o-mini 上新 prompt 使翻译错误显性化为 UNSAT（修复轮数 0→3），
            修复回路和错误范式在 AR-LSAT 上有了发挥空间，可作机制分析点；
            (d) API 通道：只用 mmm（用户要求，yunwu 已从 model_configs 全局移除）；
            mmm 单模型后端偶发 503，重试即可
      - [x] **离线提炼 100 题试跑**（2026-07-08，GPT-4o，train 前 100 题 × 1 轮）：
            端到端走通；94/109 轨迹 SAT；126 KDP → 4 聚类 → 4 候选 → 1 条过筛
            （`paradigm_store/arlsat_trial.db`）。诊断：域缩减跟踪在 AR-LSAT 失效
            （zebra n_houses 解析不适用）→ KDP 产量 1.26/轨迹（zebra ~4.2）、
            条件 A/C 死亡 → 聚类特征弱 → LLM 抽象出过宽 trigger（9–10 种约束
            类型），被 τ_p 正确拒掉 3 条。通过的 1 条（exclusion_contradiction_repair,
            support=30, precision=0.4）trigger 仅 2 类型，质量正常
      - [x] **放全量前的修复**（2026-07-08，三项，438+ 测试全过）：
            ① TrajectoryCollector 加 `_infer_value_range`（从约束字面量推值域，
            复活 KDP 条件 A/C；zebra 走原路径不受影响）；
            ② ParadigmAbstractor trigger 改为主导类型选择（多数阈值 0.5 +
            top-4 截断）——此前用聚类并集导致 AR-LSAT trigger 爆到 12 类、
            全被 τ_p 拒掉；③ 精度池增加 implication/cardinality 两类 kind
            和 AR-LSAT 条目
      - [x] **二次试跑验证**（同 100 题轨迹 `--resume` 零成本重跑下游）：
            过筛 0/7 → **3/7**（precision 0.24/0.50/0.24），入库含
            `implies_inclusion`（Implies+Or 条件包含，zebra 语料不存在的
            AR-LSAT 原生结构——跨域挖掘 claim 的直接证据）。
            关键观察：66% 轨迹零修复步（一次翻译即 SAT），正向范式基底
            天然薄，与论文"AR-LSAT 错误范式贡献更大"的预判一致
      - [x] **错误范式提取验证**：`extract_error_paradigms.py` 开箱即用，
            100 轨迹 → 94 条（UNSAT 签名去重，最高 support=11）；
            全量跑时建议 `--min-support 2` 压噪声
      - [x] **全量离线提炼完成**（2026-07-08，train 1,630 × n_runs=1，GPT-4o，
            约 3 小时）：1,630 轨迹（88% SAT，406 条含修复步）→ 1,421 KDP →
            17 聚类 → **正向库 8 条**（precision 0.24–0.50，平均 support 107，
            top 两条 adjacent 类 support 395/382，覆盖
            exclusion/ordering/implication；`paradigm_store/arlsat_full.db`）
            + **错误库 131 条**（min-support 2，top support 14；
            `paradigm_store/arlsat_error_full.db`）。
            质检注意：`sum_non_negative`（Sum≥0）疑似平凡范式，主表实验前
            人工复核一遍 8 条正向范式，可疑的手动禁用
      - [x] **半量主表 v1/v2 + 方法学审查**（2026-07-08）：
            seed 42 × 230 题：基线 47.0%、仅修复记忆 **50.0%**（+3.0pp,
            p=0.070）、仅范式库 45.2%→47.0%（curated 后归零）、完整
            47.8%→48.7%。诊断出带毒库（SAT 优化伪范式）并触发方法学审查
            （`docs/method_review_20260708.md`，6 项缺口，2 项硬伤）
      - [x] **轨迹答案验证（方案 B）**（2026-07-08）：
            `verify_arlsat_trajectories.py` 三值判定 1,630 条轨迹——
            correct 122 / incorrect 418 / indeterminate 900 / skipped 190，
            **可判定 SAT 轨迹中 77% 答案错误**（"SAT≠正确"量化证据，进论文）。
            重挖 verified 库：3 条（`paradigm_store/arlsat_verified.db`）
      - [x] **v3/v4 收官（2026-07-08）——AR-LSAT 机制归因完成**：
            verified 库更差（full 44.3%、nomem 46.1%）；
            v4 决定性单元格（修复记忆+错误库，无正向库）= 47.8%，
            比仅修复记忆（50.0%）低 2.2pp（p=0.855）。
            **稳健结论**：AR-LSAT 上唯一有增益的机制是题内修复记忆
            （+3.0pp, p=0.070 单种子）；正向库三种配置、错误库均
            中性偏负。77% 错误 SAT 是根因解释。
            叙事定稿：失败侧题内机制可跨结构迁移；范式库价值待
            ZebraLogic 主场检验
      - [x] **test 230 × 3 种子锁表完成（2026-07-08/09）——最终零结果**：
            baseline 47.5±0.5 / 仅修复记忆 47.8±2.4 / 完整 47.8±0.9；
            pooled 配对 bootstrap（n=690）全部 +0.3pp 以内、p≈0.44–0.52。
            seed 42 的 +3.0pp 被证实为种子噪声（nopar 单系统 std 2.4）。
            **AR-LSAT 定稿口径**：PRISM 各组件均无显著增益（也无显著伤害，
            但完整版调用成本 ~2×）；基线 47.5% 本身已超 Logic-LM++ 46.3%。
            章节转型为边界分析：77% 错误 SAT + 伪范式案例 + 修复步稀疏
            解释为何记忆机制不迁移。**论文正面证据全部押注 ZebraLogic 主场**
      - [ ] 方法学审查清单落地：题内/跨题术语分家（写作）、错误范式表示
            决策（类型化签名 vs 降格口径）、范式覆盖率回验、检索 P/R 评测
- [ ] **2. 手工规则 HR 基线**（ZebraLogic 5×5 + AR-LSAT）
      — 决定正向范式叙事：若 PRISM（无修复记忆）打不过 HR，
      按论文 6.5 节预案把主贡献重心移到修复记忆（影响摘要/引言写法，必须第一周出结果）
- [ ] **3. 多基础模型实验** — o1-mini 优先（防"推理模型已解决此问题"质疑的关键证据），
      其次 Llama-3-70B，各跑 5×5 主表（基线 vs PRISM 完整）
- [ ] **4. 消融表补真** — "移除错误范式" / "移除正向范式"两行真实数值
      （"错误范式是并列核心机制"claim 的唯一支撑）
- [ ] **5. 占位数据全量替换** — 多规模修复效率表、错误类型分布、迁移表中所有斜体数字
- [ ] **6. VERGE 处理方案定稿**（二选一，不能留空）
      - 方案 A：同基础模型复现 VERGE 的 MCS 定位模块作对照
      - 方案 B：正文把比较锚定在"同模型、同修复预算"受控设置，
        VERGE 原文 91.7%（GPT-OSS-120B）放脚注并说明模型差距

### 文献 / 严谨性（零散时间完成）

- [x] **7. 修复引用错配**（2026-07-08 完成）：`olausson2023` 已改为真正的 LINC
      （Olausson et al., EMNLP 2023, 5153–5176）；正文三处 `\cite{olausson2023}` 均指 LINC，语义正确
- [x] **8. ReasoningBank arXiv 号**（2026-07-08 完成）：arXiv:2509.25140，作者列表已更正
- [ ] **9. 显著性检验落实**：所有对比表 3 种子 + 配对 bootstrap 实际执行并标注，
      不能只在实现细节里声明

### 🔴 最终判决（2026-07-09）：zebra 主表 seed-42 — 机制反向

- 官方测试集 16 规模 640 题 × GPT-4o-mini：baseline **50.8%**、
  仅库 49.5%（−1.2, ns）、完整 42.3%（**−8.4, p=1.000**）、
  仅修复记忆 41.7%（**−9.1, p=1.000**）
- **机制解剖（wrong-SAT 计数）**：baseline 与仅库的"SAT 但答错"= **0**；
  带修复记忆的系统 = **54–60 题**——精确等于其准确率亏损。
  修复记忆的策略升级阶梯（L1→L4）把"诚实的失败"转换成"自信的错误"：
  在唯一解谜题上，忠实形式化的 SAT 必然正确，而记忆引导的降级修复
  （放松/删除约束直到 SAT）产出错误赋值
- **三基准×两模型全景**：AR-LSAT×4o 全零；zebra×4o 前提消失（98% 一次解）；
  zebra×mini 记忆显著为害、库中性。核心论文主张（两机制提升准确率）
  被实证反转。统一根因：**SAT 是 LLM 修复回路的错位奖励信号**
- 待用户战略决策：修方法（correctness-aware repair）/ 转负结果论文 / 混合

### ⚠️ 结构性发现三（2026-07-09）：挖掘前提在强模型上不成立

- ZebraLogic 618 条 GPT-4o 训练轨迹：**98% 首翻即 SAT、零修复步**，
  仅提出 34 KDP（论文口径 ~4.2/轨迹，实际 0.055）——范式挖掘基底消失。
  部分原因：新翻译 prompt 内置 zebra 关系模板与防错指引（prompt 工程
  替代了范式库的功能）
- GPT-4o-mini 探针（20 题）：**首翻 SAT 仅 2/20，18/20 需要 1–5 轮修复**
  ——PRISM 假设的失败模式在弱模型上大量存在
- **待决策**：主实验基模型（A=4o-mini + 多模型缩放行；B=更难谜题保 4o；
  C=重构为边界研究）。影响所有主表

## P1 — 显著提升创新性论证（第 2–3 周，与写作并行）

- [ ] **10. 错误类型分布对比直方图**（ZebraLogic vs AR-LSAT）
      — "LLM 翻译失败模式跨任务普遍存在"这一发现性 claim 的直接证据，性价比最高的一张图
- [ ] **11. 超参敏感性真实曲线** — 把 τ_p（0.20 偏宽松，审稿人可能追问）加进扫描范围
- [ ] **12. ExpeL-CSP 适配细节 + prompt 放附录** — 防"刻意做弱基线"质疑
- [ ] **13. Logical Deduction 定位** — 只用 seven_objects 作低成本迁移健全性检查，
      正文一段话带过；three/five objects 不进主表（饱和、随机基线高、污染风险）

## P2 — 写作与格式（第 3 周起，7/22–8 月初）

- [ ] **14. 英文化 + AAAI 双栏模板迁移**，正文压到 7 页：
      主表、修复效率表、消融表进正文；多规模修复、敏感性、成本分析、案例时序进附录
- [ ] **15. Claim 口径收窄**：标题与贡献从 "CSP" 收窄为"自然语言约束推理任务"
      （不在本周期补调度/图着色）
- [ ] **16. 图表升级**：架构图正式化、错误分布转直方图、
      修复时序转 tikz 图（建议换 AR-LSAT 案例，更能体现非网格泛化）
- [ ] **17. 摘要/引言按 HR 基线结果定稿**（依赖 P0-2 的结论，出结果后 48 小时内定叙事）

---

## 🚦 决策点

| 时间 | 条件 | 动作 |
|------|------|------|
| 7/20 | AR-LSAT 流水线仍未跑通 | 转投 IJCAI-27（约 1 月截稿），用多出时间补齐 P1/P2 |
| HR 基线出结果后 48h | PRISM（无修复记忆）≥ HR？ | 是 → 维持"范式发现 + 修复记忆"双主线；否 → 主贡献重心移到修复记忆，重写摘要/引言 |
| o1-mini 结果出来后 | PRISM 增益 ≥ +10pp？ | 是 → 正文主打"与基础模型能力正交"；否 → 讨论节坦承增益随模型能力收窄 |

## 💰 成本提醒

- 单次 ZebraLogic 全量（900 题）约 $900（GPT-4o，按论文附录估算）；
  3 种子 × 多系统组合需提前排预算和并发跑批
- AR-LSAT 230 题 × 3 种子 × 4 系统规模较小，但范式库构建（train 1,630 × r 次轨迹收集）是大头

## 📎 相关文件

- 论文主草稿：`docs/paper_draft/templates/paper_draft_template_zh.tex`（文末含原始待补实验清单）
- 代码实现验证：`IMPLEMENTATION_CHECKLIST.md`（2026-05，模块级验证，与本清单互补）
- 数据下载：`scripts/download_datasets.py`（支持 zebralogic / knights_knaves / logical_deduction / arlsat）
