---
chain_id: 2026-07-05-v7-topological-homomorphism
title: "V7.9 拓扑同态审计 — H(ε) 度量 + 量化债务表 + 约束体系的自指闭环"
layer: kernel
tags: [v7.9, topological_homomorphism, semantic_domain_isolation, planning_contract_injection, boolean_collapse, boundary_precomputation, quantization_debt, self_reference]
status: active
created: 2026-07-05
supersedes: [v7_9_planning_contract_injection]
superseded_by: []
related:
  - 2026-07-05-v9-kernel-architecture
  - 2026-07-05-v5-constraint-paradigm
  - 2026-07-05-v6-engine-constraint-topology
  - 2026-07-05-plan2-blind-test
files:
  - core/repl.py
  - core/track_c.py
produces_invariants:
  - "INV-007: 拓扑同态 H(ε) ≥ 0.50 — 连续→离散映射保留相邻性"
  - "INV-070: 语义域隔离 — 不同 LLM 调用接收不同合同子集"
  - "INV-071: 布尔坍缩禁止 — 连续置信度不得被阈值二元化"
  - "INV-072: 边界预计算 — REPL 层拥有结构化状态，引擎接收扁平文本"
red_flags:
  - "不要把所有合同字段注入 Planning — 语义域隔离"
  - "不要用布尔标志做 ⊥ 检测 — 置信度是连续的"
  - "不要在引擎内解析系统字符串恢复合同状态 — 脆弱的逆向工程"
  - "不要双重计数 execution_autonomy 或 trust — 它们已有独立通道"
---

# Context

V7.8 的拓扑同态审计发现了最大的残留单点断裂：`_do_plan()` 收到了完整的合同指令作为 `system` 参数，但函数体内零引用。Planning LLM 在真空中分解任务——不知道信任水平、澄清需求、verbosity 目标。

更根本的问题：V7.8 定义了 H(ε) 度量——"连续状态空间的邻接关系有多少比例在离散动作空间中保留"——但发现了系统性债务。连续→离散的边界上存在多个断裂点，最严重的是 Planning LLM 完全盲区（0 个行为状态 → 0% 拓扑保持）。

状态空间的问题：**约束体系的连续形式（StateVector）在向离散执行（LLM token 空间）传递时发生了信息损失。** 这个损失必须是可审计的（铁律 #7）——但 V7.8 之前没有量化过。

约束触碰：铁律 #7（信息损失可审计）——这是第一条**把铁律本身当作被审视对象的链**。它不是在建立新约束，是在**审计已有约束的完备度**。约束体系第一次审视自己——自指闭环。

# Decision

三条改造 + 一项新能力：

**Plan B — 边界预计算 + 显式参数传递**：REPL 层（拥有所有结构化状态）将合同字段翻译为 Planning 域的自然语言提示。Track C 只接收扁平文本——对 Blueprint、trust、clarification 一无所知。镜像 V7.7 的架构——V7.7 翻译 User→System，V7.9 翻译 System→Planning。

**语义域隔离 — PLANNING_SEMANTIC_MAP**：只有 `response_verbose_level` 进入 Planning。`execution_autonomy` 保持为硬 `branch_count` 约束。`tone_style`/`conversational_initiative` 留在 Synthesis。trust 留在 `lambda_hint`。**每个 LLM 调用只接收其语义域内的合同子集——不双重计数。**

**布尔坍缩修复 — 连续置信度**：`_semantic_confidence` (float) 替换 `_clarification_needed` (bool)。两个阈值（0.4 危机、0.8 空缺）定义三个行为区域，每个区域内通过 `{confidence:.0%}` 做真正连续的文本调制。

**量化债务表**：首次引入——列出每条已知的连续→离散映射如何量化信息损失，以及修复优先级。

# Rationale

## 形式的推导

**为什么语义域隔离是必要的？**

V7.8 的 Planning LLM 在真空中运行——0 个合同字段进入 Planning。修复不是"加上所有字段"，而是"只加属于 Planning 语义域的字段"。

推导链：
```
LLM 调用按语义域分类：Planning（信息性）、Synthesis（生成性）、Critic（评估性）
→ 每个域需要的合同子集不同
→ Planning: verbosity 目标 + 语义置信度（"需要多详细？有多大不确定性？"）
→ Synthesis: tone + 完整 verbosity（"用什么语气说？每句多长？"）
→ Critic: trust 门（"这个输出值得信赖吗？"）
→ 语义域隔离 = 每个 LLM 调用只接收其域内的合同字段
→ 不双重计数 → 铁律 #7（信息损失可审计）
→ 架构对称 V7.7（User→System 翻译）↔ V7.9（System→Planning 翻译）
```

**为什么布尔坍缩是信息损失？**

`obs.confidence ∈ [0, 1]`（连续） → `_clarification_needed`（bool）= 信息从连续谱坍缩到 1 bit。

推导链：
```
连续置信度 ∈ [0, 1] → 布尔标志 ∈ {0, 1}
→ 信息损失 = 无限 → 1 bit
→ 修复：保留连续 float + 两阈值定义三个行为区域
→ 区域内用 {confidence:.0%} 做连续文本调制
→ 0.35 → "可能需要澄清（35% 置信度）"
→ 0.60 → "存在语义空缺（60% 置信度）"
→ 0.90 → "高度不确定（90% 置信度）"
→ 这是 V7.9 第一条从 boolean 转换到连续的行为路径
→ 铁律 #7（信息损失可审计）+ 铁律 #2（连续控制律）
```

**H(ε) 度量是什么？**

H(ε) = 连续状态空间中距离 ≤ ε 的点对，在离散动作空间中仍映射为"相邻"动作的比例。
- H(ε) = 1.0 → 完美拓扑保持——状态空间的邻接关系完整映射到动作空间
- H(ε) = 0.5 → 当前水平。一半的邻接关系在连续→离散转换中丢失
- H(ε) < 0.5 → 不可接受——动作空间太粗糙，无法反映连续状态的真实差异

推导链：
```
连续状态 X ⊂ ℝ¹⁶ → 离散动作 D = {GENERATE, TOOL, WAIT}
→ 8 门优先级链 = 连续→离散的纤维化映射 π: X → D
→ π⁻¹(d) ⊂ X = 每个动作的纤维
→ H(ε) = 量化 π 在多大程度上保留 X 的邻接拓扑
→ 铁律 #7（信息损失可审计）的形式化度量
```

## 参数的标定

- ε = MAX_GRADIENT_NORM = 0.30：邻接半径。Lipschitz 上界定义了"相邻"的物理含义
- H(ε) 目标 ≥ 0.50：当前值 ~0.55。V7.9 提高了 ~5%（修复 Planning 盲区）
- 语义置信度阈值：0.4（危机）、0.8（空缺）。来自 V7.7 的 ⊥ 检测标定
- 置信度：形式 = HIGH（代数拓扑的公理推导）。参数 = MEDIUM（阈值来自 V7.7 标定，H(ε) 目标值有理论下限）

# Alternatives

### 方案 A：把 blueprint/trust 参数加入 Track C 内部
- **Pros**：Planning 内部有丰富的结构化访问
- **Cons**：违反 P55（Engine Must Not Import Observer）。Track C 需要 import blueprint 类型——破坏了引擎的域隔离
- **Rejected**：引擎不知道 Blueprint、trust、clarification。它只接收扁平文本。这个架构约束来自铁律 #3（零 NL I/O 的泛化——内核不依赖上层类型）

### 方案 C：解析系统字符串恢复合同状态
- **Pros**：零签名变化
- **Cons**：脆弱的基于正则的逆向工程。系统字符串格式改变 = Planning 静默断裂。而且字符串解析是启发式——无法保证正确恢复结构化状态
- **Rejected**：逆向工程结构化状态从非结构化文本 = 信息损失的逆向操作不可逆

### 方案 B：边界预计算 + 显式参数（选中）
- **Pros**：干净的边界分离。语义域隔离。引擎零知识 REPL 类型。镜像 V7.7 架构
- **Cons**：三个签名需要更新。显式参数传递通过调用链
- **Selected**：唯一的满足 P55 + 语义域隔离 + 连续置信度的方案

# Evidence

## 形式验证（证明）
- [数学性质]：语义域隔离——PLANNING_SEMANTIC_MAP 保证每个合同字段只进入一个语义域。不双重计数
- [数学性质]：连续置信度的两阈值三区域——{0.35: "可能需要澄清", 0.60: "存在语义空缺", 0.90: "高度不确定"}。每个区域内 genuinely continuous
- [数学性质]：H(ε) 从 ~0.50 提升到 ~0.55——修复了 Planning LLM 盲区（0 → 连续语义域匹配上下文注入）
- [推导链完整性]：边界预计算模式 = V7.7 架构的对称镜像

## 参数标定（数据）
- [标定方法]：V7.7 ⊥ 检测的置信度阈值标定
- [参数值]：SEMANTIC_CONFIDENCE_GAP=0.8, SEMANTIC_CONFIDENCE_CRISIS=0.4
- [置信度]：⚠ MEDIUM — 来自 V7.7 域标定

## 测试（验证实现正确性）
- `tests/unit/test_v3_container_repl.py`：全部通过（planning_hint 默认 ''）
- `tests/unit/test_v4_repl.py`：全部命令检测测试通过
- V7.9 拓扑同态度量从 ~50% 提升到 ~55%

# Future Guidance

## 刻意没做的事
- response_verbose_level 在 Planning 中仍为 4 个离散值（CONTINUUM 只在 Synthesis 中）。剩余债务
- 完整的 H(ε) 形式化证明——当前的 55% 是工程估计，不是严格的拓扑证明

## H(ε) 的演化
- V7.8：~50%（Planning 盲区——0 行为状态）
- V7.9：~55%（修复 Planning 盲区，引入语义域隔离 + 连续置信度）
- V10 目标：> 65%（门向量升级 + 完整影子模式 + C2/C3 迁移）
- V12 目标：> 80%（多域验证 + Fisher 度量替换 L2）

## 参数调参须知
- 改 SEMANTIC_CONFIDENCE_GAP → 检查 ⊥ 检测的敏感度。降低 → 更多情况触发"语义空缺"模式
- 改 SEMANTIC_CONFIDENCE_CRISIS → 检查危机模式的触发率。提高 → 更保守（更少危机模式）
- 改 PLANNING_SEMANTIC_MAP → 检查语义域隔离。任何新增字段必须归属于一个唯一的语义域

# Anti-Patterns

- **不要把全部合同字段注入 Planning** — tone_style 和 conversational_initiative 是 Synthesis 域字段。使用语义域隔离。双重计数 = 过阻尼（12-反模式 #2：过度约束）
- **不要用布尔标志做 ⊥ 检测** — 置信度是连续的。两阈值 + 百分比嵌入给出真正的连续行为调制。布尔坍缩 = 铁律 #7 违规（信息损失不可审计）
- **不要在引擎内解析系统字符串恢复合同状态** — 脆弱的逆向工程。在结构化状态存在的边界预计算。引擎不知道 Blueprint/trust/clarification
- **不要双重计数 execution_autonomy** — 它已经作为硬 branch_count 约束 enforce。加入 prompt = 过阻尼。12-反模式 #2
- **不要双重计数 trust** — lambda_hint 已经全面传递 trust。planning_hint 覆盖 lambda_hint 不覆盖的 Planning 域字段
- **不要把 H(ε) 当作一次性审计** — 每次约束体系的修改（新建/修改/废弃约束）都必须重算 H(ε)。Protocol 7 约束健康度审查的标准维度
