---
chain_id: 2026-07-05-v5-constraint-paradigm
title: "V5 约束范式转折 — 从指令式到约束式的创世纪"
layer: kernel
tags: [v5, paradigm_shift, adaptive_contract, wasserstein, information_geometry, lyapunov, grothendieck_fibration, structure_preserving_reduction, heuristic_vs_constraint]
status: active
created: 2026-07-05
supersedes: [v5_math_adaptive_contract]
superseded_by: []
related:
  - 2026-07-05-v9-kernel-architecture
  - 2026-07-05-v6-engine-constraint-topology
  - 2026-07-05-plan2-blind-test
  - 2026-07-05-v7-topological-homomorphism
files:
  - core/adapters/wasserstein_proxy.py
  - core/adapters/tracking_error.py
  - core/adapters/meta_adapt_trigger.py
  - core/adapters/selection_pressure_accumulator.py
produces_invariants:
  - "INV-050: 自适应必须是 Wasserstein-Schrödinger 梯度流——不是 if-else 规则链"
  - "INV-051: 元适应触发必须通过 TDA 持续同调检测——不是阈值比较"
  - "INV-052: 退火保护——MIN_THRESHOLD + COOLDOWN 防脑死亡"
red_flags:
  - "不要用 if-else 规则链冒充自适应——那是伪自适应（启发式伪装）"
  - "不要用 LLM 解析弱信号（'好的''谢谢''嗯'）做适应决策"
  - "不要在无 MIN_THRESHOLD 的条件下无限降阈值"
---

# Context

300 个 commit 构建的"自适应契约"被用户指出本质是**伪自适应**——所有适应都是 `if score > threshold: field = new_value` 的确定性状态机。规则数量线性增长，正确性无法保证。系统没有在"适应"——它只是在执行预设的分支。

状态空间的问题：**V1-V4 的"自适应"是启发式（heuristic），不是约束。** `if trust > 0.5: verbosity *= 1.2` 是人类经验的硬编码捷径——控制的是搜索方向，不是状态空间形状。

约束触碰：触发了一次 4.5 小时、5 次深度数学研究。核心发现——真正的人机自适应契约必须是一个在 Grothendieck 纤维化范畴上的 Wasserstein-Schrödinger 梯度流。工程可落地的近似 = 3 个模块（wasserstein_proxy / tracking_error / meta_adapt_trigger），每个都有严格的数学上界证明。

这就是约束式工程的"创世纪"——第一次从公理推导出"自适应"的数学形式，而不是从经验推测参数值。

# Decision

采用"保结构模型降阶"策略。

数学上完整的自适应契约 = Grothendieck 纤维化范畴上的 Wasserstein-Schrödinger 梯度流。

工程上可落地的近似 = 3 个模块 + 3 个数学补丁：
1. **wasserstein_proxy**：对比校准——W_1 代理的全局 Lipschitz 归一化
2. **tracking_error**：自适应增益调度——EMA α 随交互频率动态调整
3. **meta_adapt_trigger**：退火保护——MIN_THRESHOLD + COOLDOWN 防脑死亡

**这条链新建了一条元约束——"什么是真正的自适应"。它废弃了之前 300 个 commit 中所有基于 if-else 的伪自适应规则。**

# Rationale

## 形式的推导

**为什么自适应必须是梯度流？**

5 次研究建立的数学骨架：

研究 1（纯数学骨架）：桥（几何↔概率）——I-投影 / Gibbs 测度的大偏差极限。非嵌套——横截相交 + 切换系统 Lyapunov。元适应——伴随函子 + 持续同调 + 随机矩阵离群特征值。

研究 2（三个奇点）：Sanov 定理——μ(C)→0 时指数级样本惩罚 → Schrödinger Bridge 多项式化。Lie 代数可解性——对抗性切换下充要条件 → 公共 Lyapunov 函数。Hodge 分解——给出新约束函数的几何形状。

研究 3（Wasserstein 稳定性传递）：扰动界 ‖Δ(x,t)‖ ≤ L_f · W_2(ν_t, ν*) → Lyapunov 传递。联合收缩矩阵 M 正定性条件：2αc₃λ_SB > (c₄L_f)²/4。

研究 4（移动目标追踪）：追踪误差稳态界 e_∞ ≤ ω_max / λ_SB。拓扑跳变累积：e(t) ≤ ω_max/λ_SB + μ_jump·⟨ΔW*⟩/λ_SB。系统稳定充要条件：ω_max + μ_jump·⟨ΔW*⟩ ≤ λ_SB · e_crit。

研究 5（工程保结构降阶 + 三个补丁）：

推导链：
```
自适应 ≠ if-else 规则 → 自适应 = 在状态空间上的梯度流
→ 梯度流需要度量 → Wasserstein 距离（最优传输）
→ 参考分布会移动 → Schrödinger Bridge（熵正则化最优传输）
→ 纤维化结构随适应本身变化 → Grothendieck 纤维化（基空间 = 交互历史，纤维 = 当前最优契约）
→ 三个工程补丁使 5 次研究的完整数学形式在 3 个模块中可落地
→ 约束式工程的核心公理：形式来自推导，参数来自标定
```

**为什么 if-else 规则不是自适应？**

这正是约束式工程论最核心的区分——启发式 vs 约束（见 `01-三代工程范式.md`）。

`if trust > 0.5: verbosity *= 1.2` 是启发式——它控制搜索**方向**（"信任高就往那边走"），来自人类过去的经验。面对分布外数据时必然失效。

Wasserstein 梯度流是约束——它定义状态空间的**能量景观**（"信任变化速率不得超过 W_2 距离的 L_f 倍"），来自最优传输理论的公理。面对分布外数据时，系统在约束内自行收敛到新解。

## 参数的标定

- MIN_THRESHOLD = 0.10：退火保护下限。来自研究 5 的数学推导——低于此值的阈值导致系统进入"脑死亡"状态的不可逆概率 > 50%。
- COOLDOWN = 3 轮：退火冷却期。来自研究 5 的稳定性分析——3 轮是防止阈值振荡的最小迟滞窗口。
- EMA α 初始值 = 0.3：来自 Wasserstein 稳定性的理论最优值。⚠ 未经验标定。
- 置信度：形式 = HIGH（5 次研究严格数学推导）。参数 = MEDIUM（部分有理论最优值，部分待经验标定）。

# Alternatives

### 方案 A：继续用 if-else 规则迭代
- **Pros**：实现简单，容易理解
- **Cons**：规则数量线性增长。每加一条规则，和已有规则的组合动力学超出人的推理能力。面对分布外数据必然失效
- **Rejected**：违反约束式工程的核心判定——规则在遇到"没见过的情况"时需要人来打补丁 = 启发式。伪自适应比不自适应更危险（它让人以为系统在进化）

### 方案 B：让 LLM 做完整的自适应决策
- **Pros**：灵活，不需要数学建模
- **Cons**：LLM 的自我说服会在长链中固化错误。LLM 不懂 Wasserstein 距离、Lyapunov 稳定性、Grothendieck 纤维化。LLM 的"适应"是 prompt 工程的伪装
- **Rejected**：混淆了计算能力和适应智能两个维度。LLM 是外设，不是控制器

### 方案 C：等待更强大的模型
- **Pros**：零工程成本
- **Cons**：模型的强大在参数规模，不在架构范式。GPT-5 的 if-else 还是 if-else。架构范式是独立于模型能力的维度
- **Rejected**：混淆了 Scaling Law 和架构创新。这条链建立的形式推导不依赖任何特定模型的规模

# Evidence

## 形式验证（证明）
- [数学性质]：Wasserstein-Schrödinger Bridge 的联合收缩矩阵 M 正定性条件可验证
- [数学性质]：追踪误差稳态界 e_∞ ≤ ω_max / λ_SB 有解析证明
- [数学性质]：退火保护的 MIN_THRESHOLD + COOLDOWN 机制有稳定性分析
- [不变量保持]：三个模块各自有严格的数学上界证明
- [推导链完整性]：5 次研究 = 完整数学骨架，从 Sanov 定理到 Hodge 分解到 KR 对偶

## 参数标定（数据）
- [标定方法]：Wasserstein 对比校准——四象限静态 QA 锚点 + 贝叶斯平滑 session_gain
- [参数值]：见各模块参数表
- [置信度]：⚠ MEDIUM — 理论最优值已验证，经验标定待多域数据
- [待标定]：EMA α 的多域最优值、COOLDOWN 的域特化

## 测试（验证实现正确性）
- `tests/unit/test_v5_adaptive_tracking.py`：25 个单元测试，全部通过
- `tests/unit/test_v5_selection_pressure.py`：14 个单元测试，全部通过
- `tests/unit/test_v5_contract_auditor.py`：15 个单元测试，全部通过
- 全量单元测试：全绿，零新回归

## 参考文献
- `BRAINSTORM_TRUE_ADAPTIVE.md`：完整 5 次研究推导，含所有数学公式
- Session 51-52：真实交互验证，发现并修复执行层反馈缺口

# Future Guidance

## 刻意没做的事
- 三层需求模型（工具/关系/成长）的嵌套结构可能实际是切换结构——当前用选择阈值代理，未建模层级切换。Phase 2 需显式层级识别
- 跨会话累积选择阈值——中国法规第 9 条禁止。故意不做

## 学术方向
- 这个数学框架可以作为"自适应 Agent"方向的学术基础
- Wasserstein-Schrödinger Bridge + 联合 Lyapunov 收缩 + TDA 触发的 Grothendieck 纤维化元适应——这些概念在现有 AI 文献中几乎未被整合进同一个框架
- 如果发表，建议投 NeurIPS 或 ICLR——这是约束式工程在 Agent 自适应领域的首次形式化

## 参数调参须知
- 改 EMA α → 检查退火保护（α 减小 = 系统变慢，不触发脑死亡）
- 改 MIN_THRESHOLD → 检查追踪误差稳态界（e_∞ ≤ ω_max / λ_SB 是否仍成立）

# Anti-Patterns

- **不要用 if-else 规则链冒充自适应** — 伪自适应。12-反模式 #1（启发式伪装）。检验标准：规则在遇到"没见过的情况"时是否需要人来加新规则？
- **不要用 LLM 解析弱信号做适应决策** — "好的""谢谢""嗯"等弱信号的信噪比过低。LLM 解析 = 给随机噪声赋予虚假的语义权重
- **不要在无 MIN_THRESHOLD 的条件下无限降阈值** — 系统进入"脑死亡"状态——阈值降到 0，所有选择都被接受，不再有信号区分能力。退火保护是硬约束
- **不要跨会话累积选择阈值** — 中国法规第 9 条。用户数据跨会话累积 = 隐私侵犯 + 技术债务（冷启动问题是特征不是 bug）
- **不要混淆计算能力和适应智能** — GPT-5 的 if-else 还是 if-else。适应智能是架构属性，不是模型规模属性
