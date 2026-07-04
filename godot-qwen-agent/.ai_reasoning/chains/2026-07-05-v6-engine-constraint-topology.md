---
chain_id: 2026-07-05-v6-engine-constraint-topology
title: "V6 引擎约束拓扑 — 梯度流在四引擎之间的路由与校准"
layer: harness
tags: [v6, engine_landing, constraint_topology, dag, wasserstein_calibration, bias_tensor, multiplicative_gating, hardtanh, kahn_algorithm, semaphore]
status: active
created: 2026-07-05
supersedes: [v6_engine_landing]
superseded_by: []
related:
  - 2026-07-05-v9-kernel-architecture
  - 2026-07-05-v5-constraint-paradigm
  - 2026-07-05-plan2-blind-test
  - 2026-07-05-v7-topological-homomorphism
files:
  - core/track_c.py
  - engines/orchestration/interface.py
  - engines/orchestration/llm.py
  - core/adapters/wasserstein_proxy.py
  - core/adapters/output_pipeline.py
produces_invariants:
  - "INV-060: 乘法门控 — 独立风险因子用 × 耦合，不用 +"
  - "INV-061: 控制信号 HardTanh — 不用 sigmoid（避免梯度饱和）"
  - "INV-062: LLM 声明事实不输出控制参数 — produces/needs 标签不是 parallel_depth"
  - "INV-063: 贝叶斯伪计数冷启动 — α=3 伪计数，零硬编码 if-round<N"
red_flags:
  - "不要让 LLM 直接输出控制参数 parallel_depth — 结构幻觉"
  - "不要用认知标量 f_fused 驱动拓扑决策 — 信号错配"
  - "不要用标量 relax_bias 同时驱动 Planning 和 Critic — 控制耦合"
  - "不要硬编码 if-round<N 解决冷启动 — 贝叶斯伪计数天然提供阻尼"
  - "不要在代码块内计句子数 — 代码行是结构不是语义"
---

# Context

V5 建立了四条控制面（Path 1/2/3 + 路由），但执行层（Planning/Orch/Critic）的参数仍由硬编码或单一标量驱动。V5.3 将 Path 2 升级为 drift⊕clarity 双传感器融合，但 Orch 的全并行 gather 和 Critic 的静态阈值仍未与 V5 控制面联锁。Path 1（meta_adapt）的状态完全不流入 Track C。

状态空间的问题：**约束在单个引擎内成立，但跨引擎传播时断裂。** Planning 的 explore_bias 和 Critic 的 compromise_bias 被压进同一个标量 relax_bias——"能力穷尽"和"意图矛盾"是正交维度，用一个标量驱动 = 控制耦合。Orch 的 parallel_depth 由 LLM 输出——LLM 不懂系统并发约束，产生结构幻觉。

约束触碰：铁律 #2（连续控制律）——跨引擎的控制量必须从 StateVector 连续推导，不能由 LLM 离散 token 决定。铁律 #6（梯度有界）——单一标量驱动多个执行器的结果是梯度信号错配。

V6 的唯一使命：**把 V5 的控制面蓝图物理化到引擎层。不是新大版本，是"最后一公里"。**

# Decision

三条改造同时落地：

**V6.1 — Orchestration DAG 拓扑相变**：废除 LLM 决定 parallel_depth。Planning LLM 输出 produces/needs 标签（事实提取），Orch 引擎在本地执行 Kahn 环检测 + BFS 层级分配 → parallel_depth → asyncio.Semaphore(parallel_depth)。LLM 是证人，不是法官。

**V6.2 — WassersteinProxy 混合校准**：双层协议——Tier 1 四象限静态 QA 锚点（永不改变，防基准污染），Tier 2 贝叶斯平滑 session_gain（α=3 伪计数，零硬编码冷启动阻尼）。gain ∈ [0.5, 2.0]，效果 ±0.05 永远从属于 f×g 乘法门控。

**V6.3 — Path 1 ↔ Track C 偏置张量裂变**：废除单一 relax_bias 标量。drift>0.5 → 意图矛盾 → explore_bias=0.20（Planning 广搜）；drift≤0.5 → 能力穷尽 → compromise_bias=0.05（Critic 降标准）。两个偏置各自驱动各自的执行器，零串扰。

# Rationale

## 形式的推导

**为什么 LLM 不能输出控制参数？**

V6.1 的致命反例：三篇独立论文 → 应该并行，但 LLM 输出的 f_fused≈0（因为 LLM 不理解论文之间的独立性是图的拓扑结构而不是语义相似度）→ 标量映射判串行。

推导链：
```
LLM 擅长语义命名（produces: "paper_list"）→ LLM 不擅长数值索引（depends_on: [3]）
→ 标签匹配是确定性字符串相等 → 零概率误匹配空间
→ Kahn 环检测 + BFS 层级分配 → 图论必然：含环图无拓扑排序
→ 唯一安全 fallback = depth=1
→ 约束：LLM 声明事实（produces/needs），引擎执行控制（parallel_depth）
→ 铁律 #2（连续控制）→ 铁律 #6（梯度有界）
```

**为什么标量 relax_bias 是控制耦合？**

能力穷尽（低 drift）：目标清晰但做不到 → 不应搜索更多，应降标准。
意图矛盾（高 drift）：目标畸形 → 应搜索更多解读，不应降标准。

两个正交维度被压进一个标量 → 系统性信号错配。+0.15 同时推高 Planning（explore）和拉低 Critic（compromise）→ 控制耦合。

裂变后的形式：
```
偏置张量 B = [explore_bias, compromise_bias]
其中 explore_bias   = f(drift, meta_adapt.is_relaxed)  → 只驱动 Planning
     compromise_bias = g(drift, meta_adapt.is_relaxed)  → 只驱动 Critic
Minimax Fallback: drift=None → 1.0（零信息最大熵 = 假设混沌）
```

推导链：
```
控制耦合 → 两个正交维度被压进一个标量 → 无法独立调节
→ 裂变为张量 → 每个执行器持有独立充分统计量
→ 乘法门控 f×g → 独立风险因子用 × 耦合（不加——加法假设因子独立，实际非独立）
→ HardTanh 截断 → 不用 sigmoid（sigmoid 在饱和区梯度消失 = 系统对变化不敏感）
→ 铁律 #6（梯度有界）
```

**为什么贝叶斯伪计数替代硬编码 if-round<N？**

σ²_smoothed = (α·σ²_base + n·σ²_session)/(α + n) 自带渐近性质：
- n=1 → session 权重 25%，n→∞ → session 主导
- 不需要 `if round < 3: use_default()`

这是启发式（硬编码 if-round<N）到约束（贝叶斯渐近性质 = 数学必然）的典型转换。

推导链：
```
冷启动问题 → 需要阻尼 → 两种方案
→ 方案 A：if round < N → 启发式（"前 3 轮用默认值，因为经验说这样好"）
→ 方案 B：贝叶斯伪计数 → 约束（"随着数据增加，后验自然从先验过渡到似然——这是概率论的定理"）
→ 选 B → 形式来自推导（贝叶斯定理），不是来自试错
```

## 参数的标定

- 贝叶斯 α = 3（伪计数）：提供适度阻尼，n=1 时 session 权重 25%。理论最优值——α 太小阻尼不足，α 太大冷启动过慢。
- explore_bias 默认值 = 0.20：来自 V5 meta_adapt 的 drift 映射。⚠ 单域标定。
- compromise_bias 默认值 = 0.05：非对称——降标准应该比广搜更保守。来自 V5 盲测。
- gain ∈ [0.5, 2.0]：Wasserstein 校准的理论上界。超出此范围 = 校准基准已被污染。
- 置信度：形式 = HIGH（图论必然 + 贝叶斯定理）。参数 = MEDIUM（部分理论最优 + 部分经验标定）。

# Alternatives

### 方案 A：LLM 输出 parallel_depth（被 V6.1 致命反例废除）
- **Pros**：实现简单
- **Cons**：三篇独立论文 → f_fused≈0 → 标量映射判串行。LLM 结构性幻觉：越界索引、循环依赖、漏标依赖
- **Rejected**：LLM 是证人不是法官。事实提取（produces/needs）= LLM 的能力域。控制决策（parallel_depth）= 引擎的能力域

### 方案 B：Mahalanobis + Ledoit-Wolf 距离
- **Pros**：统计优雅
- **Cons**：384 维 × 5-10 样本 → 矩阵病态 → 距离震荡。过度工程
- **Rejected**：理论优雅不敌数据稀疏。384 维的协方差矩阵需要 n ≫ 384 样本才可逆——当前 n=5-10

### 方案 C：单一 relax_bias 标量（被废除）
- **Pros**：实现最简单
- **Cons**：控制耦合——能力穷尽和意图矛盾被同一种偏置处理。信号错配在 V5 盲测中被证实
- **Rejected**：两个正交维度压进一个标量 = 系统性信号丢失。铁律 #7（信息损失可审计）要求显式声明维度压缩

# Evidence

## 形式验证（证明）
- [数学性质]：Kahn 环检测 + BFS 层级分配 → 图论必然。含环图无拓扑排序的唯一安全 fallback = depth=1
- [数学性质]：贝叶斯伪计数的渐近性质——n→∞ 时 session 权重 → 1，n=0 时 → 0。不需要硬编码轮次
- [数学性质]：乘法门控的独立性保持——f×g 的偏导数 ∂/∂f = g, ∂/∂g = f。加法 f+g 的偏导数 ∂/∂f = 1——f 的变化对输出的影响不依赖 g

## 参数标定（数据）
- [标定方法]：Wasserstein 双层校准——Tier 1 四象限 QA 锚点 + Tier 2 贝叶斯平滑
- [参数值]：见各模块默认值
- [置信度]：⚠ MEDIUM

## 测试（验证实现正确性）
- `tests/unit/test_v6_1_dag_topology.py`：19 测试全绿
- `tests/unit/test_v6_2_wasserstein_gain.py`：16 测试全绿
- `tests/unit/test_v6_3_bias_tensor.py`：13 测试全绿
- Session 77：代码块感知截断生效，输出完整

# Future Guidance

## 刻意没做的事
- 流式输出（降低感知延迟）→ V7+
- 跨会话模式发现（行为模式固化到用户画像）→ V7+
- TDA 集成（持续同调检测需要新维度的信号）→ V8+
- Schrödinger Bridge 离散近似（Sinkhorn 算法 token 空间熵正则化）→ V8+

## 扩展约束
任何新增信号源或执行器必须遵守：
- 每个引擎持有独立的充分统计量（不共享 σ²）
- 控制信号用 HardTanh（不用 sigmoid）
- 乘法门控（不加法耦合独立风险因子）
- 自标定（不硬编码阈值）
- LLM 只声明事实，不输出控制参数

## 参数调参须知
- 改 explore_bias → 不同时改 compromise_bias（已裂变，无耦合）
- 改 Wasserstein baseline → 先跑四象限 QA 锚点验证（防基准污染）
- 改贝叶斯 α → 检查冷启动行为（n=1 时 session 权重是否合理）

# Anti-Patterns

- **不要让 LLM 直接输出控制参数** — parallel_depth、threshold、budget 等控制量从 StateVector 连续推导。LLM 声明事实（produces/needs），引擎执行控制。12-反模式 #1（启发式伪装）
- **不要用认知标量驱动拓扑决策** — f_fused ≠ 任务并行度。语义相似度是连续值，并行度是离散拓扑属性——信号错配
- **不要让标量 relax_bias 同时驱动 Planning 和 Critic** — 控制耦合。能力穷尽和意图矛盾是正交维度。裂变为偏置张量
- **不要硬编码 if-round<N 解决冷启动** — 贝叶斯伪计数的渐近性质天然提供阻尼。硬编码轮次 = 12-反模式 #1（启发式伪装）
- **不要在代码块内计句子数** — 代码注释、docstring、方法链的换行符不是语义句子边界。代码块感知截断是结构修复，不是参数调优
- **不要用 sigmoid 做控制信号激活** — sigmoid 在饱和区梯度消失 = 系统对变化不敏感。HardTanh 保持统一的梯度强度
