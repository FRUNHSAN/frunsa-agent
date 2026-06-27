# 00 — 项目演化档案：从 RAG Bot 到 MPC 决策微内核

**定位**：工程考古报告。不解释"这是什么"，只证明"怎么走到今天的"。

> 本文档回答面试官/导师不开口的第一个问题：**"这东西是你自己做的吗？"**  
> 本文件有 100 个原始文件（58 条推理链 + 15 个计划 + 7 个归档 + 4 个充分性报告 + index.yaml 及 YAML schemas 等），每个都记录了 alternatives 对比

---

## 一、演化全景

```
2026-05-24 ──────────────────────────────── 2026-06-15
        约 3 周，4 次架构跃迁，100 个原始决策文件

  契约地基              数学转向              物理化               微内核隔离
  (05-24~25)           (05-28~06-05)        (06-07~11)           (06-14~15)
  ┌──────────┐        ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │Phase 01-18│   →    │Phase 19-25   │ →   │V5 V6 V7 V8   │ →   │V9.0 V9.2b    │
  │三平台架构  │        │管道组合+肌肉层│     │Wasserstein   │     │V9.2c         │
  │198 tests  │        │PLAN2-7 归档  │     │双传感器+DAG  │     │MPC 微内核    │
  └──────────┘        └──────────────┘     └──────────────┘     └──────────────┘
```

---

## 二、四大演化阶段

### 阶段一：契约地基（05-24 ~ 05-25）

**这次跃迁回答的问题**："一个 AI Agent 系统，如果安全不是事后补丁，骨架应该长什么样？"

```
Phase 01-07: 三平台架构
  ├── Phase 01: pipeline/contracts/adapters 三平台分离
  ├── Phase 02: 数据完整性（frozen dataclass + MappingProxyType）
  ├── Phase 03: 严格适配器模式（AdapterTypeError + Protocol）
  ├── Phase 04: 可观测性契约（TraceLog + DependencyHealth）
  ├── Phase 05: 外部 I/O（health_probe + async wrapper）
  ├── Phase 06: 管道引擎（PipelineStep Protocol + StepOutput）
  └── Phase 07: 组件注册表（COMPONENT_REGISTRY + freeze）

Phase 08-13: 观测闭环
  ├── 08-11: 追踪键体系（18 个 trace keys），SQLiteTraceSink
  ├── 12: 观测先行原则（不变式 #11）
  └── 13: Guardrail 扫描器（16 条 AST 规则，pre-commit hook）

Phase 14-18: 引擎层
  ├── 14-16: 三个引擎 Stub（Planning / Orchestration / Critic）
  ├── 17: LLM 生产引擎接入
  └── 18: Factory DI 装配契约 + Sufficiency Report v4
```

**关键决策**：
 
- **pipeline/contracts/adapters 三平台分离**（phase_01_three_platform）—— 管道层永不 import 领域类型，契约层永不 import 编排类型。这条边界到今天 V9 依然铁打不动。
- **观测先行**（phase_12_observability_closed_loop）—— 每加一个能力层，先被观测层覆盖。不是"写完代码再加 trace"——trace 比代码先设计。

**交付**：198 测试，3 引擎，18 trace keys，16 条 AST 规则。

> 参见：[CLAUDE.md](../CLAUDE.md) 不变式 #1-#16，[.ai_reasoning/chains/phase_01 ~ phase_18](..//.ai_reasoning/chains/)

---

### 阶段二：数学转向（05-28 ~ 06-05）

**这次跃迁回答的问题**："关键词驱动的'自适应'是伪自适应——真正的自适应应该长什么样？"

```
Phase 19: 管道组合语法层
  ├── SourceRouter（源码路由）+ PipelineComposer（管道编排）
  └── USB 模型：COMPONENT_REGISTRY 统一发现（不变式 #17-#20）

Phase 22-25: 肌肉层
  ├── Tool 合约（ToolResult 携带 contract_violation — 不变式 #31）
  ├── KernelService Protocol（应用层只依赖接口 — 不变式 #32）
  ├── HITL：HumanTicket（阻塞）+ RenegotiationProposal（非阻塞 — 不变式 #35）
  └── 自修复闭环（ContractAware* 包装器 — 不变式 #33）

PLAN1-7 归档
  └── 7 个旧 PLAN（PLAN1-7）被 V5 一举归档。
      原因：它们依赖关键词/规则/阈值表驱动决策——V5 用数学信号流替换了全部。
```

**关键决策**：
 
- **变异-选择-保留达尔文三元组**（BRAINSTORM_TRUE_ADAPTIVE.md）—— LLM 幻觉 = 变异（探索新行为空间），用户行为 = 选择压力（环境反馈），契约 = 保留（固化有利变异）。这是整个项目的哲学脊椎。
- **路由是控制问题，不是分类问题**（V5 Brainstorm）—— 把"选哪个 chunker"从分类器重构为控制器。这条决策直接通向 V9 的 8 门优先级路由。

**交付**：7 个 PLAN 归档，V4.2 完整 10 阶段旅程，契约生命周期状态机。

> 参见：[BRAINSTORM_TRUE_ADAPTIVE.md](../.ai_reasoning/BRAINSTORM_TRUE_ADAPTIVE.md)，[PLAN2.md](../PLAN2.md)

---

### 阶段三：物理化（06-07 ~ 06-11）

**这次跃迁回答的问题**："如果系统状态是连续的，但输出动作是离散的，中间怎么映射？"

```
V5: 二元路由 + 观察者降级
  ├── Bang-Bang 控制（Pontryagin 最大值原理）
  ├── 双传感器融合（drift ⊕ clarity → 三引擎正交信号）
  └── 观察者 = X-Ray（不注入控制回路 — 不变式 #51）

V6: 引擎落地
  ├── Wasserstein-Schrödinger 梯度流
  ├── Critic 乘法门控（drift × e(t) — 不变式 #46）
  ├── HardTanh 激活（替代 Sigmoid — 不变式 #47）
  └── LLM 是证人不是法官（不变式 #62）

V7: 物理批评 + 恒等流形 + 熵监控
  ├── V7.1-V7.2: 物理沙盒循环
  ├── V7.4: 12 维恒等流形 M_id ⊂ ℝ¹²（OU 过程 + Betti 检测）
  ├── V7.5: 熵监控（信息论 + 自然变换）
  └── V7.9: 拓扑同态审计 — 不变式 #63（量化债务表诞生）

V8: 信任衰减 + 循环范畴论 + 跨子系统耦合
  ├── V8.0: 信任衰减模型（非对称 EMA：负信号 α=0.30，正信号 α=0.08）
  └── V8.3: 跨子系统耦合分析
```

**关键决策**：

- **乘法门控替代加法耦合**（V6）—— 两个独立风险源的惩罚必须相乘。任一因子为 0 → 整个惩罚为 0。加法耦合导致单因子泄漏（高 σ² 独自降低 Critic 标准）。

- **HardTanh 替代 Sigmoid**（V6）—— Sigmoid 的渐近残差（~0.01）泄漏噪声进入控制回路，导致极限环振荡和积分器饱和。
- **LLM 是证人不是法官**（不变式 #62）—— LLM 可声明拓扑事实（depends_on / produces / needs），但不得输出控制参数（parallel_depth / semaphore_count）。控制参数由确定性图算法推导。

**交付**：63 条架构不变式，7 条内核铁律，量化债务表（trust=6 states, e(t)=4, clarity=5, drift=4），PLAN2 盲测校准（真人被试确认系统"听得进去"）。

> 参见：[docs/V5-V6-mathematical-backplane.md](../docs/V5-V6-mathematical-backplane.md)（1791 行完整推导），[CLAUDE.md](../CLAUDE.md) 不变式 #38-#63

---

### 阶段四：微内核隔离（06-14 ~ 06-15）

**这次跃迁回答的问题**："如果把所有'业务逻辑'剥离，只留最纯粹的决策骨架——剩什么？"

```
V9.0: MPC 内核框架
  ├── 5 层架构：Observer → Mainboard → MPC Kernel → Execution
  ├── 4 条硬件总线：LLM Bus (AHB级) / Tool Bus (APB级) / Event Bus (NVIC级) / Telemetry Bus (CoreSight级)
  ├── 7 条铁律（纯函数边界、零自然语言、Lipschitz ≤ 0.30…）
  └── 9 步纯函数决策链（Step 0-8）：Step0.NaN入口 → Step1.ODE积分 → Step2.交互基 → Step3.Lipschitz → Step4.Streak+Gate → Step5.连续量 → Step6.仲裁 → Step7.NaN出口 → Step8.组装输出

V9.1: RealTrackC
  └── Track C 管道 — 真实 LLM 调用 + 编排 + 评估

V9.2b: 硬编码消除
  └── 六处硬编码全部消除，Lipschitz 基线修正

V9.2c: 当前
  ├── 规则引擎测试覆盖
  └── 沙盒防御验证
```

**关键决策**：
 
- **纯函数边界**（铁律 #1）—— `kernel_step()` 零副作用。相同输入 → 相同输出。内核是纯数学函数，外部世界通过总线观察它。
- **零自然语言 I/O**（铁律 #3）—— 内核输入输出绝对无自然语言。StateVector 是 16 个 float，ControlFrame 是枚举 + float。没有 prompt，没有 token。
- **连续控制律**（铁律 #2）—— 所有控制量（verbosity/tone/critic θ）从 StateVector 连续浮点值导出，禁用 `if trust > 0.5` 式离散查表。
- **帧率无关 ODE**（设计性质，非铁律）—— `1-exp(-dt/τ)` 驱动的 EMA 积分器。对话 Agent（秒级）和机器人控制（毫秒级）共享同一动力学。


**交付**：16 维状态向量，8 门优先级路由（P0-P7），3 个 RL 策略槽位（Boundary/Cost/Value），内核层 9 文件 ~2500 行纯 Python。

> 参见：[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)（5 层 + 4 总线 + 7 铁律），[mpc_kernel/kernel.py](../mpc_kernel/kernel.py)（9 步决策链入口）

---

## 三、关键数字（每阶段的证据密度）

| 阶段 | 测试 | 引擎 | 不变式 | 推理链 | 新增类型 |
|------|------|------|--------|--------|---------|
| 契约地基 | 198 | 3 | 16 | 18 | Trace Keys ×18 |
| 数学转向 | +362 | +0 | +21 | +12 | ContractLifecycle, HumanTicket, RenegotiationProposal |
| 物理化 | +113 | +0 | +26 | +20 | 双传感器融合, Wasserstein, 量化债务表 |
| 微内核隔离 | 673 | 6 | 63 | 58 | StateVector(16), RouteGate(8), PolicySlot(3) |

> 引擎数从 3 跃至 6：新增 Tool Engine + RealTrackC Pipeline，原有 Planning / Orchestration / Critic ×2（Stub + LLM 双实现）共 6 个引擎实例。
> 测试数从 198 → 673 不是"重写测试"——每一个测试都是前一个阶段的回归保障。198 个旧测试在 4 次跃迁中全部保留并持续通过。

---

## 四、Commit 范围（按日期分组，可 git log 验证）

| 日期 | 内容 | 关键链 |
|------|------|--------|
| 05-24..25 | Phase 01-18：核心架构 + 引擎 | `phase_01_three_platform` ~ `phase_18_orch_critic` |
| 05-28 | Phase 19：管道组合语法层 | `phase_19_composition` |
| 06-03 | Phase 22-25：肌肉层 + HITL | `phase_22a_tool_contract` ~ `phase_25_anti_corruption` |
| 06-04 | plan2~7：V5 前框架 | `plan2` ~ `plan7` |
| 06-07 | V4.x 清理 + V5 头脑风暴 → 7个旧PLAN归档 | `BRAINSTORM_TRUE_ADAPTIVE` |
| 06-08 | V5：二元路由 + Path 3 反射 + 观察者降级 | `v5_binary_routing` |
| 06-09 | V5.3：双传感器融合 + V6：引擎落地 | `v5_3_dual_sensor`, `v6_engine_landing` |
| 06-10 | V7：物理批评/流/层论/身份/熵 | `v7_physics_critic` ~ `v7_5_entropy` |
| 06-11 | V7.9：规划契约注入 + V8.0~8.3：信任/范畴/耦合 | `v7_9_planning_contract`, `v8_0_trust` ~ `v8_3_coupling` |
| 06-14 | V9.0：MPC 内核框架 | `v9_0_mpc_kernel` |
| 06-15 | V9.1 RealTrackC + V9.2b 硬编码消除 + V9.2c 当前 | `v9_1_real_track_c`, `v9_2b_hardcoded`, `v9_2c_finalize` |

---

## 五、演化规律

从 4 次跃迁中可以读出一条清晰的设计哲学：

1. **每次跃迁都是"发现伪自适应 → 替换为数学框架"**  
   关键词列表 → 贝叶斯 EMA → Wasserstein 梯度流 → MPC 铁律

2. **每次归档不是因为失败，是因为找到了更简洁的数学基底**  
   PLAN1-7 不是"做错了"——它们在当时是正确的。V5 用一个达尔文三元组覆盖了 7 个 PLAN 想做的事。归档 = 数学进步的痕迹。

3. **复杂度不增加，迁移到数学层**  
   V9 的内核只有 9 个文件——但每个文件背后是一个被充分辩论过的数学选择（见 CLAUDE.md 63 条不变式）。简洁不是偷懒，是消化了复杂度的结果。

---

## 六、诚实性声明

- **所有日期和链 ID 可验证**：`index.yaml`（69 条注册链）+ `git log`（每个 commit 对应链 ID 的时间戳）
- **归档的 7 个 PLAN 保留了原始措辞**，未事后修改。它们读起来"像 V5 前的思维"——因为确实是。
- **缺口坦诚列出**：
  - V4.2 phase 5-10 状态为"待审批"而非"已完成"
  - 拓扑同态 50% 是当前基线，目标 ≥65%（V8.0 路线图）
  - 连续→离散路径中只有 2 条是真正连续的（e(t)→critic θ, drift→critic θ），其余仍是阶梯函数
  - 量化债务表记录了 4 个已知债务（trust gap 0.25 span, e(t) trivial signals invisible to routing, clarity normal range no prompt effect, blueprint enums no continuous interpolation）
- **这个项目不是"做完了"——是每个方向都值得一篇论文，一个人的精力只能选其一。**

---

## 七、结语：7 个可独立成文的研究方向

这个项目不是因为"做完了"而停止的。以下是 7 个可从现有代码和数学推导中直接展开的论文方向，每个都有代码、有测试、有已知缺陷：

| # | 方向 | 类型 | 目标会议 | 已有支撑 |
|---|------|------|---------|---------|
| ① | MPC 微内核架构 | 系统 | ICRA/RSS/EMNLP | `mpc_kernel/` + 673 tests |
| ② | 拓扑同态映射 | 理论 | CDC/NeurIPS | 量化债务表 + V7.9 审计 |
| ③ | Hoyer+Lipschitz 安全仲裁 | 安全AI | CoRL/SafeRL | `safety_arbiter.py` |
| ④ | 契约驱动降级与自修复 | HRI | HRI/AAMAS | HITL + 自修复闭环 |
| ⑤ | 帧率无关 ODE 控制 | 控制 | CDC/ACC | `ode_integrator.py` |
| ⑥ | RL 策略槽位作为通用接口 | RL工程 | RLC/ICRA | `policy_slots.py` + Telemetry |
| ⑦ | 达尔文式契约演化 | AGI | ALIFE/GECCO | V5 数学框架 + PLAN2 盲测 |

**"我不是带着一个结束的项目来镀金——我是带着一个有 7 个论文分支的活系统来求合作。"**

---

> **原始素材**：`.ai_reasoning/` 100 个文件（58 条推理链 + 15 个计划 + 7 个归档 + 4 个充分性报告 + `index.yaml` 66 条索引 + schemas + 顶级文档）
>
> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。
