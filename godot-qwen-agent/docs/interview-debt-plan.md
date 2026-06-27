# 面试暴露的项目债务 — 综合整改 Plan

> **来源**：七轮深度技术面试 Q&A，从候选人自述中提取的技术债、架构缺口、前瞻风险和外部审查意见。
> **日期**：2026-06-27
> **原则**：每项标注严重度、当前实现状态、候选人是否已识别、修复方向（若有）、预估工作量。

---

## 一、总览

| 领域 | 🔴 高危 | 🟡 中危 | 🟢/🔵 低危/理论 | 合计 |
|---|---|---|---|---|
| A. 域迁移（语义→具身） | 4 | 3 | 1 | 8 |
| B. ODE 积分器 & 参数化 | 2 | 2 | 1 | 5 |
| C. 拓扑同态度量 & 连续→离散映射 | 1 | 4 | 2 | 7 |
| D. 契约安全 — 具身域物理表达 | 1 | 1 | 1 | 3 |
| E. RL 策略槽位 — 集成与安全 | 3 | 2 | 2 | 7 |
| F. 外部审查：缺失的对标与验证 | 0 | 4 | 0 | 4 |
| G. 自我批判：过度设计风险 | 0 | 1 | 2 | 3 |
| **合计** | **11** | **17** | **9** | **37** |

---

## 二、按领域逐项展开

---

### A. 域迁移 — 语义域 → 具身域（8 项）

面试暴露的最大单一风险面。"16 个 float 不关心来自对话文本还是激光雷达"在内核层为真，在全系统层需要域适配补完。

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| A1 | **具身域 Gate 元组空缺** — `EMBODIED_GATES` 不存在，`DEFAULT_GATES` 语义域设计（P0 社交信号优先）在物理域可能导致安全事故 | 🔴 | Policy Slot 接口已预留（`gates` 参数），`EMBODIED_GATES` 实现为零 | ✅ 完整识别 | 在 `mpc_kernel/slots/embodied_gates.py` 中实现物理紧急门 + 带安全前置条件的社交门 | 3-5d |
| A2 | **具身域 Policy Slot 整体空缺** — Observer 归一化策略、仲裁矩阵域加载、Gate 参数域迁移标定，三个 Policy Slot 层全空白 | 🔴 | 架构预留完备（`route_controller` 的 `gates` 参数、`PluginRegistry.discover("embodied")`），实现为零 | ✅ 完整识别 | 逐层实现：①Observer 归一化协议形式化 ②Gate 触发阈值域重标定 ③仲裁矩阵域加载 | 2-3w |
| A3 | **安全硬件栈未实现** — Layer 0 硬件互锁 / Layer 1 Reflex 控制器 / Shared memory 协议，全在设计层 | 🔴 | 仅在面试回答中描述了五层架构。无代码、无硬件选型、无原理图 | ✅ 识别并标出 | Phase 1: SIL 仿真（Gazebo/Isaac Sim）。Phase 2: Safety MCU（STM32G4）+ Teensy 4.0 原型 | 2-3m |
| A4 | **SIL 认证未启动** — ISO 13482 要求 Layer 0 达到 SIL 2+，当前无任何安全完整性认证计划 | 🔴 | 零 | ✅ 主动提及 | 需外部认证机构介入。前期：内部 gap analysis → SIL 等级判定 → 硬件选型约束 | 3-6m |
| A5 | **门链 `for...break` 线性单选** — 单帧只能输出一个动作，多危机叠加场景无法处理 | 🟡 | V9 架构限制。V10 路线图规划升级为门向量 + `arbitration_matrix` | ✅ 识别 | V10: `for...break` → `[g(...) for g in gates]` + `arbitration_matrix.resolve(triggered)` | 1-2w（V10） |
| A6 | **仲裁矩阵（arbitration_matrix）零实现** — "多门并发 → urgency_score → 域感知仲裁"机制不存在 | 🟡 | 方向已规划，代码零 | ✅ 识别 | 需改内核路由循环。语义域用"首个触发者胜出"，具身域用"最高 urgency 者胜出" | 1-2w（V10） |
| A7 | **控制频率双域差异未分析** — 语义域 0.1Hz（30s/round），具身域 200Hz（5ms/frame）。门仲裁逻辑在 200Hz 下同一危机连续触发 200 帧的行为未经分析 | 🟡 | 帧率无关 ODE 保证动力学不变，但门仲裁在该频率下的循环行为未评估 | ⚠️ 面试官指出 | 在仿真中以 200Hz 运行门链 10,000 帧，观察门触发模式是否有高频振荡 | 1d |
| A8 | **StateVector 维度命名偏语义域** — `rhythm_ratio`/`cognitive_load`/`context_depth` 命名暴露设计时的领域偏见 | 🟢 | 纯命名问题，不影响内核逻辑 | ✅ 识别 | 后续版本 review 命名，或至少加 docstring 注明具身域等价语义 | 0.5d |

---

### B. ODE 积分器 & 参数化（5 项）

候选人展现出对该模块的深度分析能力，暴露了参数耦合和文档化不足。

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| B1 | **恢复区 τ 参数耦合（静默炸弹）** — Lerp baseline 线性化使 `τ_eff = τ_decay/(1−a)`。若有人把 `crisis_baseline` 从 0.30 调到 0.20，`a` → 6/7 ≈ 0.857，`τ_eff` 暴涨到 ~840s | 🔴 | 代码无保护。调参者不会预期此连锁反应 | ✅ 完整分析 | ①立即加 `tau_recovery` 独立字段 ②在调参文档中记录 `τ_eff` 公式 ③加 assertion：`crisis_baseline < recovery_baseline * 0.85` | 1d |
| B2 | **`TrustDynamics` 缺 `tau_recovery` 字段** — 只有 `tau_decay`(120s) 和 `tau_build`(600s)，恢复区速度与危机区绑死 | 🔴 | [v9_types.py:262-265] 可验证 | ✅ 识别并指出是"意外后果" | 在 `TrustDynamics` 中新增 `tau_recovery: float = 200.0`，在 `ode_integrator.py` 恢复区分支中引用 | 0.5d |
| B3 | **Event 脉冲 × Lerp baseline 双重惩罚** — 事件脉冲同时拉低 trust 和 baseline，在事件密集场景下产生 path-dependent slowdown | 🟡 | 代码逻辑可推导，无测试覆盖，无文档 | ✅ 完整分析 | 编写回归测试：模拟"连续 3 次 TOOL_FAILURE + trust 在恢复区"场景，记录恢复时间并文档化预期行为 | 1d |
| B4 | **参数耦合关系未形式化文档化** — `τ_eff = τ/(1−a)` 的推导、`crisis_baseline` 调参影响分析，全未写入任何设计文档 | 🟡 | 仅存在于候选人头脑中 | ✅ 识别 | 在 `ode_integrator.py` 模块级 docstring 中写入"参数调优须知"一节，含 `τ_eff` 公式和参数联动表 | 0.5d |
| B5 | **安全裕度 `safety_margin[7]` 未激活** — `sm = 1.0` 是占位符（[ode_integrator.py:130]），ODE 维度标注 RESERVED，动力学未设计 | 🟢→🔴 | 需要基于真实机器人数据的物理仿真标定 | ✅ 识别 | Phase 1: 在仿真中标定。Phase 2: 在真实机器人上验证 | 1-2w |

---

### C. 拓扑同态度量 & 连续→离散映射（7 项）

候选人在 V7.9 完成了第一阶段的修复（50%→55%），剩余 gap 已识别但未完成。

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| C1 | **同态度量缺少 sensitivity analysis** — 50% 对采样分辨率敏感：N=20→~60%, N=1000→~48%，度量本身的鲁棒性未检验 | 🟡 | 度量算法已完整，边界条件未测绘 | ✅ 坦诚指出 | 测绘 N∈[5, 2000] 的度量稳定性曲线，确定稳定区间。编写度量稳定性报告 | 2d |
| C2 | **`response_verbose_level` 仍为离散枚举** — 4 个离散值（terse/normal/verbose/detailed）阻止了 clarity 的全连续路径 | 🟡 | V7.9 后剩余工程 | ✅ 识别并给出连续化方案 | 改为连续 `verbosity_budget ∈ [0,1]`，注入 prompt 时使用 `{verbosity:.0%}` 替代枚举标签 | 2d |
| C3 | **trust → lambda_hint 仍有 5 个 if/elif bin** — 框架文本包装在分支里，未实现纯连续模板 | 🟡 | V7.9 后剩余工程 | ✅ 识别 | 消除所有 `if trust < X` 分支，改为纯连续模板 `"信任水平: {trust:.3f}"` | 2d |
| C4 | **drift 未透传到 Planning 语义域** — drift 只影响 Critic θ 和 branch_count，不进入 `planning_hint`，影响 DIRECT vs FULL_DAG 判断质量 | 🟡 | 信号路径断裂 | ✅ 识别 | 将 drift 值纳入 `planning_hint` 生成逻辑 | 1d |
| C5 | **clarity → Planning 曾存在"断路"（已修复）** — V7.9 前 `_do_plan()` 函数体零引用 Blueprint 信息 | ✅ 已修复 | V7.9 已修复（`_semantic_confidence` + `planning_hint` 注入 goal 字符串） | ✅ 识别并已修复 | 作为架构教训条目记录在 docs/ 中，防止类似断路在后续开发中重现 | — |
| C6 | **同态度量各路径增益"统计独立"假设未验证** — trust 连续化 + clarity 连续化的线性叠加（+3-4% + 3-4% + 2-3%）未验证交互效应 | 🟢 | 假设 | ✅ 识别 | 在真实 LLM 上做 factorial 实验（2×2×2），测量各路径的交互效应系数 | 3d |
| C7 | **LLM tokenization 离散性为拓扑同度理论上限** — `trust=0.4237` vs `0.4238` 产生不同字符串，但 LLM 有效数值分辨率未知 | 🔵 | 理论 Open Question #3 | ✅ 识别 | 设计实验：nudge trust 以 δ=0.0001 步长递增，测量 LLM 输出的实际行为变化阈值 | 1w（研究级） |

---

### D. 契约安全 — 具身域物理表达（3 项）

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| D1 | **安全红线具身域物理表达未实现** — 4 个刚性契约（安全红线/隐私/诚实/长期福祉）在语义域有代码实现，具身域物理等价物全空缺 | 🔴 | 五层安全栈设计已完成，Layer 0-4 实现为零 | ✅ 完整识别并给出五层架构 | Phase 1: Layer 0-1 SIL 仿真原型。Phase 2: 物理硬件验证 | 3-6m |
| D2 | **Shared memory 无锁环形缓冲区协议未设计** — 当前 ControlFrame 通过 Python 对象传递（μs 级），具身域内核↔Reflex 控制器是跨芯片通信，延迟预算从 ms→μs | 🟡 | 候选人类比 Tool Bus APB 设计，但协议未设计 | ✅ 识别 | 设计双缓冲 + 序列号校验的无锁协议。参考 seL4/L4 microkernel IPC ring buffer | 1w |
| D3 | **累积损伤监测逻辑零实现** — Critic 的 `harmful_long_term` 标记在具身域应对应"重复次 maximal 力矩 → 关节退化监测" | 🟢 | 设计思路已描述 | ✅ 识别 | 在 Gazebo 中模拟重复载荷，设计 `harmful_long_term` 触发的力矩-循环数曲线 | 1w |

---

### E. RL 策略槽位 — 集成与安全（7 项）

面试第六轮暴露的深层架构债务。候选人发现 `slot_registry` 被传遍整个调用链但从未被任何门函数读取——这是 V7.9 Planning 真空在同层级的复现。

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| E1 | **RL 策略槽位是旁观者，不参与决策** — `slot_registry` 传入整个调用链（kernel→route_controller→eval_state），8 个门函数零个调用 `slot_registry.get("boundary").evaluate()`。`safety_arbiter` 的 `SLOT_RL_ACTIVE` 只打标记不读取返回值 | 🔴 | 钩子就位，线路未接 | ✅ 通过代码审计发现 | ①先在 1 个门函数（建议 P5 error_streak）中接入 RL 推荐作为影子仲裁输入 ②验证 e2e 数据流 | 3-5d |
| E2 | **安全仲裁器对 Sim2Real 静默失效三重盲区** — (a) Lipschitz 只看 `‖ΔStateVector‖`，FORWARD 动作状态变化小不触发；(b) Hoyer 区分传感器故障不看决策错误；(c) 根本性缺失：无"该状态下 FORWARD 是否合理"的判断器 | 🔴 | 架构假设"危险来自状态跳变"在具身域不成立 | ✅ 精确诊断 | 新增行动语义验证器（Action Semantic Validator）：给定 (state, action, context) 三元组，返回合理性评分 | 2-3w（研究级） |
| E3 | **RL 策略缺少不确定性量化（UQ）输出** — `BoundaryPolicy.evaluate()` 只返回 `float ∈ [0,1]`，不返回 epistemic uncertainty 或 KL divergence | 🔴 | Protocol 定义最小化，需扩展 | ✅ 识别 | 扩展 `PolicyOutput` 协议为 `(action_prob, epistemic_unc, kl_from_training)`。ensemble 3 个不同 seed 的模型即可起步 | 3-5d |
| E4 | **缺少 OOD 检测门** — 门链之前无 RL 分布外检测器，RL 即使 KL 散度极大也会输出动作且不被拦截 | 🟡 | 设计思路已给出（`gate_p0_ood_guard`），零实现 | ✅ 识别 | 在门链最前端插入 OOD 门：`epistemic_unc > 0.70 → 禁用 RL slot，fallback 到确定性门` | 2d |
| E5 | **缺少影子模式** — RL 策略无"只记录不控制"的渐进上线路径，无法在真实场景中积累可靠性数据 | 🟡 | 候选人在面试中临时设计了影子模式方案 | ✅ 识别 | 实现 Telemetry Bus 记录 `(state, rl_action, gate_action, agreement)` 四元组。设 `agreement_rate > 95% × 10k 帧` 为实控切换阈值 | 3-5d |
| E6 | **缺少行动语义验证器** — 安全仲裁器监控状态导数和传感器模式，不监控"动作与上下文语义一致性"。这是 Sim2Real 安全的理论缺口 | 🔵 | 候选人识别为方向③论文第三维度（当前只有 Lipschitz + Hoyer） | ✅ 识别 | 设计并实现 ActionSemanticValidator。初步方案：用 World Model 前向预测动作后果 → 评估安全性 | 2-3w（研究级） |
| E7 | **Safe RL 文献对比缺失** — RL 策略槽的安全集成有成熟工作（Fisac et al. Safety-constrained RL, Achiam et al. CPO, Berkenkamp et al. SafeOpt），当前设计独立但未做文献对比 | 🟡 | 文献调研空白 | ⚠️ 面试官指出 | 完成 Safe RL 文献调研并撰写对比分析，明确现有工作的定位和差异点 | 1w |

---

### F. 外部审查：缺失的对标与验证（4 项）

面试官在综合评价中指出的外部视角缺口。这些不是候选人主动暴露的——是"站在外人角度看项目"时缺失的东西。

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| F1 | **Benchmark 对比缺失** — 673 个确定性测试验证内部一致性，但没有与其他决策架构（Behavior Trees、HTN、SMACH、纯 RL）在标准任务上的对比 | 🟡 | 零外部对标 | ⚠️ 面试官指出 | 选 1 个标准任务（建议 Social Navigation），实现 BT/HTN/纯RL/MPC 四种方案的对比，产出 benchmark 报告 | 2-3w |
| F2 | **MPC-RL 融合范式文献定位缺失** — "影子模式渐进接管"与现有 MPC-RL 融合范式（RL-MPC residual policy, MPC as policy prior, MBRL）的关系未厘清 | 🟡 | 文献调研空白 | ⚠️ 面试官指出 | 在相关工作中加入与 RA-L/IJRR 中 MPC-RL 融合范式的系统对比 | 1w |
| F3 | **ROS2 生态术语映射缺失** — "Event Bus → ROS2 topic"有方向性的提法，但没有具体的 QoS/profile 映射（RELIABLE vs BEST_EFFORT, TRANSIENT_LOCAL, KEEP_LAST 等） | 🟡 | 连接层设计留空 | ⚠️ 面试官指出 | 编写 `bus/ros2_bus.py` QoS 映射表：Telemetry→BEST_EFFORT, Shield→RELIABLE+TRANSIENT_LOCAL, KernelEvent→RELIABLE | 1d |
| F4 | **Observer 归一化协议缺少分布漂移适应** — 候选人承认"还没做但知道怎么做"，但分布漂移（Observer 输出分布随时间变化）时 ODE 积分器的适应机制未考虑 | 🟡 | Fréchet 距离/MMD 概念未引入 | ⚠️ 面试官指出 | 在 Observer 协议中增加分布漂移检测：滑动窗口 MMD(current, baseline) > threshold → 触发归一化参数重标定 | 3d |

---

### G. 自我批判：过度设计风险（3 项）

候选人第七轮自我批判中主动暴露的问题。面试官认可这种坦诚。

| ID | 债务项 | 严重度 | 当前状态 | 候选人是否识别 | 修复方向 | 预估工作量 |
|---|---|---|---|---|---|---|
| G1 | **文档/代码比过高** — 63 条不变式、1791 行数学推导、17 个 Markdown 文件 vs ~2500 行代码。部分不变式"理论上正确但从未在测试中被违反过" | 🟡 | 候选人自我批判 | ✅ 主动提出 | 将不变式从 63 压缩到 ~35 条——保留所有被测试覆盖或被具体失败触发的，归档"理论上正确但未被违反过"的 | 2d |
| G2 | **哲学基座和代码之间的距离** — CLAUDE.md 有卢梭《社会契约论》引用，00-project-evolution 有"文明史定位"叙述。对外部评审委员可能被视为过度包装 | 🟢 | 候选人自我批判但选择保留 | ✅ 主动识别 | 保留但分区：在 CLAUDE.md 中明确标注"设计哲学"和"工程技术"的边界，让读者可以跳过前者直接进入代码 | 0.5d |
| G3 | **拓扑同态度量"学术界尚无同类度量"的声称未验证** — 诚实（确实没找到）但不证明正确。未完成的度量被包装为差异化卖点 | 🟢 | 候选人自我批判 | ✅ 主动识别 | 完成系统性的文献检索（Google Scholar + Semantic Scholar），确认或修正"尚无同类度量"的声称 | 1d |

---

## 三、优先级排序（建议实施顺序）

### Phase 0 — 入组首周：静默炸弹拆除 + 展示基建

| 优先级 | 债务 ID | 事项 | 预估 |
|---|---|---|---|
| **P0** | B1, B2 | 加 `tau_recovery` 字段，解耦恢复区速度。加 `crisis_baseline < recovery_baseline * 0.85` 断言 | 1.5d |
| **P0** | E1 | 在 1 个门函数（建议 P5）中接入 RL 推荐——打通 e2e 数据流，证明 RL 槽位不是空壳 | 2d |
| **P0** | C2, C3 | verbosity 连续化 + lambda_hint 去 bin——V7.9 后自然延续，每个 2d，合计 4d | 4d |

**Phase 0 合计：~7.5 工作日**

### Phase 1 — 首月：域迁移最小闭环 + 安全底座

| 优先级 | 债务 ID | 事项 | 预估 |
|---|---|---|---|
| **P1** | A1 | 实现 `EMBODIED_GATES` 最小可行版——物理紧急门 + 带安全前置的社交门 | 5d |
| **P1** | D1.B5 | 激活 `safety_margin[7]` ODE 维度——在仿真环境中标定动力学 | 1-2w |
| **P1** | C4 | drift → planning_hint 透传 | 1d |
| **P1** | A7 | 200Hz 门仲裁行为分析——在仿真中运行 10,000 帧，观察门触发模式 | 1d |
| **P1** | E3 | RL 策略 UQ 协议扩展——`PolicyOutput` 替代裸 float，ensemble 3 个 seed | 5d |
| **P1** | E4 | OOD 检测门——在门链最前端插入，epistemic_unc > 0.70 → 禁用 RL | 2d |

**Phase 1 合计：~4-5 周**

### Phase 2 — 第 2-3 月：域迁移全闭环 + Benchmark

| 优先级 | 债务 ID | 事项 | 预估 |
|---|---|---|---|
| **P2** | A2 | 具身域 Policy Slot 整体补完——Observer 归一化协议形式化 + Gate 参数域迁移标定 | 2-3w |
| **P2** | A3 | 五层安全栈 Layer 0-1 原型——Safety MCU 选型 + Gazebo/Isaac Sim SIL 仿真 | 2-3w |
| **P2** | D2 | Shared memory 无锁环形缓冲区协议设计 | 1w |
| **P2** | E5 | 影子模式 + Telemetry 闭环 | 5d |
| **P2** | F1 | 第一个 Benchmark 对比：MPC vs BT vs 纯 RL — 在社交导航标准任务上 | 2-3w |
| **P2** | C1 | 同态度量 sensitivity analysis——测绘 N∈[5,2000] 稳定性曲线 | 2d |

**Phase 2 合计：~8-10 周**

### Phase 3 — 第 3-6 月：安全认证 + 文献补齐

| 优先级 | 债务 ID | 事项 | 预估 |
|---|---|---|---|
| **P3** | A4 | SIL 2 认证启动——ISO 13482 gap analysis | 3-6m（与认证机构并行） |
| **P3** | A5, A6 | V10 门向量升级——从 `for...break` 到 `arbitration_matrix` | 2w |
| **P3** | E2, E6 | 行动语义验证器——安全仲裁器的第三维度（Lipschitz + Hoyer + ActionSemantic） | 2-3w |
| **P3** | E7, F2 | Safe RL + MPC-RL 融合文献调研与对比分析 | 2w |
| **P3** | C6, C7 | 拓扑同度交互效应实验 + LLM 数值敏感性实验 | 1-2w |
| **P3** | F3, F4 | ROS2 QoS 映射 + Observer 分布漂移适应 | 4d |

**Phase 3 合计：~12-16 周（含外部认证机构时间）**

### Phase 4 — 持续：文档化 + 缩减 + 测试

| 优先级 | 债务 ID | 事项 | 预估 |
|---|---|---|---|
| **P4** | G1 | 不变式压缩：63 → ~35 条 | 2d |
| **P4** | B3, B4 | Event × Lerp double penalty 回归测试 + `τ_eff` 公式写入 ODE 模块文档 | 1.5d |
| **P4** | G2 | CLAUDE.md 哲学/工程边界标注 | 0.5d |
| **P4** | G3 | 文献检索确认"尚无同类度量"声称 | 1d |
| **P4** | A8 | StateVector 维度命名 review——加具身域等价语义 docstring | 0.5d |
| **P4** | D3 | 累积损伤监测实验设计 | 1w |

---

## 四、面试综合评价侧面

### 强项（来自面试官的结论）

1. **数学可解释性到工程确定性的双向翻译能力**——能从 ODE 结构消去隐式耦合、从 if/elif 分支配对反推拓扑同态百分比、从代码路径审计发现 `slot_registry` 从未被门函数读取
2. **诚实标注边界的能力**——七轮面试中主动标注了 15+ 项"未完成/未验证/不在控制范围"
3. **架构一致性**——从 V5 达尔文三元组到 V9 MPC 微内核，经历真实架构演进（PLAN1-7 全废），63 条不变式来自具体失败的证据链可信
4. **差异性定位清晰**——不在 VLA/感知/RL 训练等拥挤赛道上竞争，选择"大模型与硬件之间的中间层"这个被低估的空间

### 入组后前 3 个月最关键的三件事

1. **在 Gazebo/Isaac Sim 中用内核驱动一个机器人完成一次社交导航。** 零论文、零 benchmark、只是跑通。证明"域无关"不是空话。
2. **激活 `safety_margin[7]` 并完成 ODE 动力学标定。** 这是当前 16 维中最弱的一环——RESERVED 标签不能永远是盾牌。
3. **完成第一个 benchmark 对比。** 你的内核 vs Behavior Tree vs 纯 RL——在社交导航标准任务上。不需要赢，但需要有数字。没有对比就没有坐标系。

---

## 五、给候选人的备忘

以下 6 项是面试官在"查漏补缺清单"中指出的、候选人未主动暴露的短板。建议入组前自行补课：

1. **Safe RL 文献**：Fisac et al. (Safety-constrained RL), Achiam et al. (CPO), Berkenkamp et al. (SafeOpt)。你当前的设计是独立的，但面学术界面试官时会暴露文献空白。
2. **MPC-RL 融合范式**：RL-MPC residual policy, MPC as policy prior, MBRL with safety filters。你的"影子模式渐进接管"需要在这些范式中找到自己的坐标。
3. **控制频率的双域差异**：语义域 0.1Hz vs 具身域 200Hz——门仲裁逻辑在 200Hz 下的行为（同一危机连续触发 200 帧）未经分析。
4. **ROS2 生态术语映射**：QoS/profile 的具体映射（RELIABLE vs BEST_EFFORT, TRANSIENT_LOCAL）需要具体化。
5. **Benchmark 对比**：Behavior Trees, HTN, SMACH, 纯 RL——需要标准任务上的数值对比。
6. **Observer 归一化分布漂移**：当 Observer 输出分布随时间变化时，ODE 积分器的适应机制需要 Fréchet 距离或 MMD 的概念。

---

## 六、债务统计图

```
严重度分布：

🔴 高危 (11):
  A1 A2 A3 A4          ← 具身域迁移 4 项
  B1 B2                ← ODE 参数耦合 2 项
  D1                   ← 契约安全物理表达 1 项
  E1 E2 E3             ← RL 槽位旁观 + 三重盲区 + UQ 缺失 3 项
  [C5 已修复]          ← 1 项已关闭

🟡 中危 (17):
  A5 A6 A7             ← 门链架构 + 控制频率 3 项
  B3 B4                ← 参数文档化 2 项
  C1 C2 C3 C4          ← 拓扑同态剩余工程 4 项
  D2                   ← Shared memory 协议 1 项
  E4 E5 E7             ← OOD 门 + 影子模式 + Safe RL 文献 3 项
  F1 F2 F3 F4          ← Benchmark + 文献 + ROS2 + Observer 漂移 4 项

🟢/🔵 低危/理论 (9):
  A8                   ← 命名 1 项
  B5                   ← safety_margin 1 项 → Phase 1 升级为 🔴
  C6 C7                ← 统计独立 + LLM 离散性 2 项
  D3                   ← 累积损伤 1 项
  E6                   ← 行动语义验证器 1 项 → Phase 3
  G1 G2 G3             ← 自我批判 3 项

已修复 ✅ (1): C5
```

---

> **文档版本**: v1.0
> **产生方式**: 从七轮深度技术面试 Q&A 逐轮提取 → 去重 → 分类 → 优先级排序
> **下次 review**: Phase 1 结束后（预计入组后 4 周）
