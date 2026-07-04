---
chain_id: 2026-07-05-v9-kernel-architecture
title: "V9.0 MPC 内核架构 — 七条铁律的形式推导"
layer: kernel
tags: [v9.0, kernel, iron_laws, five_layer_architecture, four_buses, mpc_kernel, ode, route_controller, safety_arbiter, policy_slots, pure_function, topological_homomorphism]
status: active
created: 2026-07-05
supersedes: [v9_0_harness_architecture]
superseded_by: []
related:
  - 2026-07-05-v5-constraint-paradigm
  - 2026-07-05-v6-engine-constraint-topology
  - 2026-07-05-plan2-blind-test
  - 2026-07-05-v7-topological-homomorphism
files:
  - mpc_kernel/kernel.py
  - mpc_kernel/ode_integrator.py
  - mpc_kernel/route_controller.py
  - mpc_kernel/safety_arbiter.py
  - protocol/v9_types.py
produces_invariants:
  - "INV-001: 纯函数边界 — kernel_step() 零副作用"
  - "INV-002: 连续控制律 — 所有控制量从 StateVector 连续推导"
  - "INV-003: 零自然语言 I/O — 内核不包含 NL 字符串"
  - "INV-004: 形式化可重放 — ControlFrame 携带 DecisionTrace"
  - "INV-005: 零动态分配 — 内核内无 malloc/new/list.append"
  - "INV-006: 梯度有界 — ‖Δsv‖₂ ≤ MAX_GRADIENT_NORM (0.30)"
  - "INV-007: 信息损失可审计 — 拓扑同态 H(ε) ≥ 0.50"
red_flags:
  - "不要在 kernel_step() 中调用 LLM"
  - "不要新增 NextAction 枚举值 — 3 模态数学完备"
  - "不要在 Adapter 中持有对话历史 — Adapter 是纯翻译器"
  - "不要让 Bridge 做业务决策 — Bridges 执行，内核决策"
  - "不要在生产环境跳过 DecisionTrace — 铁律 #4"
---

# Context

V8.4 经历了 6 轮工具分发的迭代调试。根因不是代码质量——是**完全没有架构边界**。REPL（1700 行）、Track C、ToolEngine、LLM Planning 全部耦合在单个单体文件中。

用户意识到继续修补 V8.4 没有意义。系统需要根本性的架构分解——就像 Linux 把内核（调度/内存/VFS）和用户空间（bash/ssh/nginx）分开。

状态空间的问题：**V8.4 的所有控制逻辑都在 LLM 的 token 空间内——连续控制量（信任衰减速率、工具并发度、降级阈值）被离散的 prompt 指令替代。这是指令式工程在复杂系统中的必然失稳——控制器的带宽远低于被控对象的带宽。**

约束触碰：系统缺的不是更多规则，而是**定义状态空间形状的物理定律**。

# Decision

采用完整的五层架构 + MPC 内核隔离 + JSON 协议边界 + 四条独立总线。

内核（Layer 2）是**纯函数**——不调 LLM、不执行工具、无文件 I/O、无自然语言。输入 16 维 StateVector + 事件队列，输出 ControlFrame（NextAction + DataPolicy + DecisionTrace）。

Harness（Layer 3）是**总线矩阵**——路由内核决策到物理执行（LLM 调用、工具分发），不做决策。

协议冻结为 16 维 StateVector、3 个 NextAction、8 门（可插拔优先级链）、3 个策略槽位。

# Rationale

## 形式的推导

**五层架构**来自一个控制论必然性：连续控制和离散执行必须物理隔离。连续控制（ODE 积分、Lipschitz 裁剪、Schmitt 触发器）需要确定性、微秒级、无外部依赖。离散执行（LLM 调用、工具运行）是不可靠的、秒级的、依赖外部服务的。混在一起 = V8.4。

推导链：
```
连续/离散物理隔离 → 内核（连续）和 Harness（离散）分属不同层
→ 内核是纯函数的控制面 → 铁律 #1（纯函数边界）
→ Harness 是路由和适配层，不做决策 → 铁律 #3（零 NL I/O）
```

**七条铁律**不是安全规则。不是编码规范。它们是**状态流形 X ⊂ ℝ¹⁶ 上的 Finsler 度量**——每一点 x ∈ X，允许的变化方向和速率是被约束的。

| # | 铁律 | 拓扑声明 | 公理来源 |
|---|------|---------|---------|
| 1 | 纯函数边界 | 状态空间是闭流形——边界条件完整 | 控制论：开环系统的自由度不可控 |
| 2 | 连续控制律 | 地形光滑——梯度处处定义 | ODE：1-exp(-dt/τ) 帧率无关形式 |
| 3 | 零自然语言 I/O | 语义噪声不进拓扑 | 量子退相干类比：LLM token 不确定性被隔离 |
| 4 | 形式化可重放 | 路径可验证——相同初始 → 相同终态 | 确定性系统的 Liouville 定理 |
| 5 | 零动态分配 | 运行时拓扑不变——编译时锁死 | 硬实时系统：WCET 可分析性 |
| 6 | Lipschitz 有界 | 地形无悬崖——最大坡度 ≤ 0.30 | 控制论：梯度爆炸 = 系统失稳 |
| 7 | 信息损失可审计 | 拓扑同态 H(ε) ≥ 0.50 | 代数拓扑：连续→离散映射保留相邻性 |

这和 AlphaFold 的能量函数 E(sequence, structure) 是同构的。AlphaFold 不画蛋白质的图纸——它定义能量景观，让分子自己找到最低能态。**铁律不规定 Agent 的行为——它们定义状态空间的能量景观，让行为从梯度流中涌现。**

**四条总线**来自 ARM SoC 的硬件类比：
- LLM Bus（AHB 级）：高速双向。Planning、Synthesis、Critic 共享 LLM Provider
- Tool Bus（APB 级）：外设级。文件工具、MCP 工具、注册表（HAL）查找
- Event Bus（NVIC 级）：中断控制器。Dirac δ 脉冲——TOOL_FAILURE、LLM_TIMEOUT、USER_ABORT
- Telemetry Bus（CoreSight 级）：调试追踪。(s,a,r) 三元组 → JSONL，RL 训练源

总线宪法：
1. 状态保全——管线中止打包已完成检查点
2. 中断边界——MAC 层重试留在内部，只有耗尽稳态故障进入 Event Bus
3. 按 (type, tool_name) 等价类合并
4. 硬保留槽位——4 个槽位保护 priority ≤ 1 的事件

## 参数的标定

- StateVector 维度 = 16：前 8 维独立（trust, e_t, context_depth, rhythm_ratio, cognitive_load, tool_success_rate, latency_ratio, safety_margin），后 8 维 DERIVED（代数组合）。维度数 = 铁律需要的最少独立控制量。
- MAX_GRADIENT_NORM = 0.30：来自 PLAN2 盲测，⚠ 单域标定（Agent 对话域）。游戏引擎域和具身智能域待验证。
- 8 门优先级顺序：P0（社交）> P1（信任危机）> P2（外部升级）> P3（外部放松）> P4（冷启动）> P5（错误上升）> P6（错误下降）> P7（方差危机）。顺序 = 安全关键度降序。
- τ_decay = 120s, τ_build = 600s：来自 V9.0 默认值，⚠ 未经经验标定。标定方法见 [A1] 系统辨识。

置信度：形式 = HIGH（从控制论公理推导）。参数 = LOW（单域默认值，待多域标定）。

# Alternatives

### 方案 A：继续修补 V8.4 单体
- **Pros**：改动最小，不碰已有测试
- **Cons**：V8.4 的 6 轮调试证明没有边界的前提下每次修复产生新的上游问题。继续修补 = 在沙滩上建楼
- **Rejected**：违反铁律 #1——控制和执行在同一层，无法独立验证

### 方案 B：微服务式 Agent 拆分（每个功能独立服务）
- **Pros**：独立部署，独立扩缩容
- **Cons**：Agent 的决策是全局的——信任、疲劳、上下文是一体的。微服务拆分引入网络延迟和分布式状态管理，与控制论原则冲突
- **Rejected**：连续控制需要原子状态——分布式状态引入的分区容错破坏了 ODE 的确定性

### 方案 C：纯 LLM 路由（LangGraph/CrewAI 模式）
- **Pros**：开发速度快，不需要数学建模
- **Cons**：LLM 做控制决策 = 结构幻觉。LLM 不懂系统并发约束、Lipschitz 条件、帧率无关性
- **Rejected**：违反铁律 #2（连续控制）——LLM 输出的控制量是离散 token，不是连续推导

# Evidence

## 形式验证（证明）
- [数学性质]：1-exp(-dt/τ) 在任何 dt > 0 下不超调。帧率无关性从指数衰减的解析形式证明
- [数学性质]：Lipschitz ‖Δsv‖₂ ≤ 0.30 在 ODE 积分 + 事件脉冲后，经 rescale 保持
- [数学性质]：Schmitt 触发器 2 升/3 降非对称——Galois 连接，消除 1 帧抖动
- [不变量保持]：铁律 #1-#7 全部在 kernel_step() 的 8 步流水线中 enforce
- [推导链完整性]：每条铁律追溯到控制论/代数拓扑/硬实时系统的公理

## 参数标定（数据）
- [标定方法]：PLAN2 盲测 (n=1) — Agent 对话域
- [参数值]：MAX_GRADIENT_NORM=0.30, τ_decay=120s, τ_build=600s, gate thresholds
- [置信度]：⚠ LOW — 单用户、单域。需多域验证
- [待标定]：所有参数在游戏引擎域和具身智能域的取值。标定方法见前沿注入 [A1]/[B3]

## 测试（验证实现正确性）
- 13 个冻结源文件（~3000 行），通过红队对抗审查
- 30 个 V9 内核测试全部通过
- 完整 DecisionTrace 审计链：gate_id + operands + shield_flags
- Hoyer 稀疏度鉴别器：8 独立维上的故障 vs 变化检测
- Schmitt 触发器 Galois 连接：2-up/3-down + EPS=1e-4 防浮点抖动

# Future Guidance

## 刻意没做的事
- V9.0 协议已冻结。StateVector 维度 (16)、NextAction 枚举 (3)、门优先级顺序在 V9.x 生命周期内不可变
- 新维度 → 元数据压缩规则（铁律 #7）
- 新门 → 插入 DEFAULT_GATES 元组——不需要改内核
- 新 RL 策略 → 实现 BoundaryPolicy/CostPolicy/ValuePolicy Protocol 并通过 slot_registry 挂载——不需要改内核
- 新总线 → 注册到 Harness，URI 命名空间——不需要改内核

## 版本路线
- V10：RL 训练管线填充策略槽位
- V11：多 Agent 会话管理器（内核"MMU"）
- V12：具身智能——状态向量扩展 + 物理安全门
- V13：体液池模型——内部血管总线 + 间质池 + 淋巴池

## 参数调参须知
- 改 MAX_GRADIENT_NORM → 重跑拓扑同态 H(ε) 审计。ε 值域特化见 [B3]
- 改 gate 阈值 → 检查 Schmitt 触发器非对称性和迟滞带
- 改 τ_decay/τ_build → 检查 τ_eff < 10× τ_recovery 守卫不变式（见 2026-07-05-v9-kernel-architecture）

# Anti-Patterns

- **不要在 kernel_step() 中调用 LLM** — 铁律 #3。内核不知道文本。任何 LLM 调用属于 Harness 层
- **不要新增 NextAction 枚举值** — 3 模态是数学完备的。新行为 = EXECUTE_TOOL 下的新 Track 管线
- **不要让 Bridge 做业务决策** — Bridges 执行。内核决策。LLM Bridge 的 degraded output 是故障降级，不是决策
- **不要在 Adapter 中持有对话历史** — Adapter 是纯翻译器。对话历史 = Harness 插件
- **不要跳过 DecisionTrace** — 铁律 #4。每个决策必须可重放。任何绕过 DecisionTrace 的 = L3 违规
- **不要用 LLM 输出控制参数** — LLM 声明事实（produces/needs 标签），不输出 parallel_depth、threshold 等控制量。控制量从 StateVector 连续推导
