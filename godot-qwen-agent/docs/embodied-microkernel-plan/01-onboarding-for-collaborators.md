# 01 — 协作者上手指南：内核在哪、怎么读

**定位**：课题组新成员（做感知的、做控制的、做 RL 的）30 分钟上手指南。  
**目标**：读完这份文档后，你能找到你要的代码、知道怎么跑起来、知道从哪里开始改。

> 姐妹文档：[11-migration-guide.md](./11-migration-guide.md) — "内核怎么拆出来、怎么装到别处"

---

## 一、一句话讲清（30 秒）

这是一个**领域无关的 MPC 决策微内核**。它不关心驱动机器人还是对话 Agent——它只做一件事：

> **接收 16 维浮点状态向量 → 9 步纯函数决策链（Step 0-8）→ 输出安全动作帧**

内核代码只有 9 个文件，不含自然语言，不含业务逻辑。业务逻辑在你的 Observer 和 Actuator 里实现。

---

## 二、我运行在架构的哪一层

```
Layer 5: UI ── CLI / VSCode / Web（任意载体）
    │
Layer 4: Observer ── 语义翻译（你在这里实现传感器 → StateVector）
    │                        👆 做感知的
    ▼
Layer 3: Mainboard ── 主板（总线矩阵 + 编排）
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐
    │  │ LLM Bus  │ │ Tool Bus │ │Event Bus │ │Telemetry Bus│
    │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘
    │                        👆 做总线/通信的
    ▼
Layer 2: MPC Kernel ── 纯函数决策（你不改这层，只消费输出）
    │  kernel_step() 9步（Step 0-8）：NaN→ODE→交互基→Lipschitz→Streak+Gate→连续量→仲裁→NaN出口→组装
    │                        👆 做控制的 + 做 RL 的
    ▼
Layer 1: Execution ── LLM Synthesis / Tool Execution / Track C
```

**"你在这里"标注**：

| 你的方向 | 你应该读的层 | 关键文件 |
|---------|------------|---------|
| **做感知的**（视觉/语音/力觉 → 特征） | Layer 4 Observer | `observer/observer.py`, `mainboard/cpu/adapter.py` |
| **做控制的**（决策算法/路由/安全） | Layer 2 MPC Kernel | `mpc_kernel/kernel.py`, `route_controller.py`, `safety_arbiter.py` |
| **做 RL 的**（策略训练/数据采集） | Layer 2 策略槽位 + Telemetry Bus | `mpc_kernel/slots/policy_slots.py`, `mainboard/bus/telemetry.py` |
| **做总线/通信的**（ROS2/DDS/中间件） | Layer 3 Mainboard 总线 | `mainboard/bus/event.py`, `mainboard/bus/tool.py` |

> 参见：[08-architecture-diagram.md](./08-architecture-diagram.md) — 完整架构图 + 时序预算

---

## 三、按方向分文件导读

### 如果你做感知（视觉 / 语音 / 力觉融合）

**你的任务**：把多模态传感器数据翻译成 16 维 StateVector。

**必读文件**（3 个）：
1. `protocol/v9_types.py` — StateVector 的 16 个维度定义。  
   维度分三类：`INSTANT`（Observer 写入）、`ODE`（内核演化）、`DERIVED`（内核计算输出）。**Observer 只写 INSTANT 维度。**
2. `observer/observer.py` — Observer 的 Protocol。实现 `observe(raw_input) → ObservationResult`。
3. `mainboard/cpu/adapter.py` — CPU Adapter 如何把 ObservationResult 翻译成 `KernelInput`。

**阅读深度**：接口层 — 你只需要理解"把传感器特征塞进哪些 StateVector 维度"，不需要理解 ODE 积分器内部。

### 如果你做控制（路由 / 安全仲裁 / 决策算法）

**你的任务**：理解 9 步决策链（Step 0-8）的每一步在做什么，可能自定义门或仲裁规则。

**必读文件**（4 个）：
1. `mpc_kernel/kernel.py` — `kernel_step()` 的 9 步主循环（Step 0-8）。这是内核的入口函数。
2. `mpc_kernel/route_controller.py` — 8 门优先级路由（P0-P7）。每个门是一个 Schmitt 触发器。
3. `mpc_kernel/safety_arbiter.py` — 三层降级矩阵（Hoyer 稀疏度 + Lipschitz 约束）。
4. `mpc_kernel/ode_integrator.py` — ODE 连续状态演化（脉冲响应 + EMA 弛豫）。

**阅读深度**：物理意义层 — 你需要理解每个门在什么条件下触发，仲裁器在什么情况下降级。

> 参见：[03-math-whitepaper-bridge.md](./03-math-whitepaper-bridge.md) — 核心公式的面试速读版  
> 参见：[../docs/V5-V6-mathematical-backplane.md](../docs/V5-V6-mathematical-backplane.md) — 完整数学推导

### 如果你做 RL（策略训练 / 数据采集）

**你的任务**：把你的 RL 策略网络挂载到内核的 Policy Slots。

**必读文件**（3 个）：
1. `mpc_kernel/slots/policy_slots.py` — 三个 RL 标准 Protocol：
   - `BoundaryPolicy` → 对应 RL 的 π(a|s)（策略）
   - `CostPolicy` → 对应 RL 的 R(s,a)（奖励）
   - `ValuePolicy` → 对应 RL 的 V(s)（价值函数）
2. `mainboard/bus/telemetry.py` — TelemetryBus 记录 (s,a,r) 三元组。这是你的训练数据来源。
3. `mpc_kernel/kernel.py` — 理解策略如何在 9 步决策链中被调用。

**阅读深度**：RL 物理意义层 — 你需要理解三个槽位的语义，以及 Telemetry 的数据格式。你不需要理解 Schmitt 触发器的内部实现。

> 参见：[../docs/RL技术路线与V9对照.md](../docs/RL技术路线与V9对照.md) — RL 面试速查

### 如果你做总线/通信（ROS2 / DDS / 中间件）

**你的任务**：把内核的总线接口映射到实际的通信协议（如 ROS2 topic）。

**必读文件**（4 个）：
1. `mainboard/bus/event.py` — Event Bus Protocol（中断脉冲 + Lamport 时钟）。
2. `mainboard/bus/llm.py` — LLM Bus（AHB 级高速总线）。
3. `mainboard/bus/tool.py` — Tool Bus（APB 级外设总线，Semaphore(5) 限流）。
4. `mainboard/bus/telemetry.py` — Telemetry Bus（CoreSight 级调试总线）。

**阅读深度**：接口层 — 你只需要理解每条总线的 Protocol 语义，然后在你的实现里映射到具体协议。

---

## 四、怎么跑起来（5 个命令）

```bash
# 1. 进入主项目
cd godot-qwen-agent

# 2. 安装依赖（纯 Python 标准库 + numpy，无 PyTorch/ROS）
pip install -r requirements.txt

# 3. 运行内核自检
python -c "from mpc_kernel.kernel import kernel_step; print('✅ Kernel loaded')"

# 4. 运行全部测试
pytest tests/ -q

# 5. 运行架构合规检查
python -m guardrails check --all
```

---

## 五、怎么接入：你的模块通过什么接口和内核对话

```
你的传感器 → Observer.observe(raw) → ObservationResult
    → CPUAdapter → KernelInput(StateVector)
    → kernel_step(KernelInput) → ControlFrame
    → 你的 Actuator 把 ControlFrame 翻译成电机指令/ROS2 消息
```

**关键接口**：

| 接口 | 类型 | 你实现什么 |
|------|------|-----------|
| `Observer.observe()` | 输入 | 传感器 → StateVector 的 INSTANT 维度 |
| `kernel_step()` | 纯函数 | **不需要改** — 传入 KernelInput，接收 ControlFrame |
| `ControlFrame` | 输出 | 把 action + params 翻译成你的执行指令 |

---

## 六、贡献规则：铁律通俗版

### 你不能改的（改了会让内核的数学契约断裂）

| # | 铁律 | 通俗解释 |
|---|------|---------|
| 1 | 纯函数边界 | `kernel_step()` 不能有副作用——不能写文件、不能发网络请求、不能改全局变量 |
| 2 | 连续控制律 | 所有控制参数（verbosity/tone/θ）从 float 推导，不能写 `if trust > 0.5: mode = "friendly"` |
| 3 | 零自然语言 I/O | 内核输入输出是 float 和 enum——没有 prompt，没有 token |
| 6 | Lipschitz ≤ 0.30 | 两次相邻调用之间 ‖Δs‖ 不能超过 0.30——防止过度反应 |

### 你欢迎改的（不改内核内部，通过接口扩展）

| 扩展方式 | 你需要写的 | 不需要改的 |
|---------|-----------|-----------|
| 新 RL 策略 | 实现 `BoundaryPolicy` Protocol → 挂载到 slot | `kernel.py` 不变 |
| 新门（P8, P9） | 实现 `Gate` Protocol → 注册到 RouteController | 现有 P0-P7 不变 |
| 新 ODE 维度 | 在 `protocol/v9_types.py` 末尾追加 → Observer 提供值 | `ode_integrator.py` 自动适配 |
| 新总线实现 | 实现总线 Protocol → 替换默认实现 | 内核不感知 |

---

## 七、FAQ

**Q1: 内核为什么是纯函数？**  
纯函数确保相同输入 → 相同输出。这意味着决策可复现、可审计、可测试——不需要 mock 任何外部状态。

**Q2: 我训练了一个 RL 策略，怎么装进去？**  
实现 `BoundaryPolicy` 的 `evaluate(state) → float`，然后替换 `kernel_step` 调用时的策略参数。不需要改 `kernel.py`。

**Q3: StateVector 的 16 维分别是什么？**  
见 `protocol/v9_types.py` 的字段定义。关键区分：带 `ode_` 前缀的维度由 ODE 积分器演化（Observer 不写）；`instant_` 前缀的由 Observer 写入。

**Q4: 内核跑一次多久？**  
纯 Python ~1.7ms。目标（含 Observer 感知推理）< 5ms。见 [08-architecture-diagram.md](./08-architecture-diagram.md) 的时序预算表。

**Q5: 我能用 C++/Rust 重写内核吗？**  
可以——而且这正是 V10 路线图的一部分。内核的 Protocol 定义（`protocol/`）是跨语言 ABI。Rust 重写只需要实现相同的 Protocol，不改任何上层代码。

> 参见：[00-project-evolution.md](./00-project-evolution.md) — V10 RL 基础设施与 Rust 重写路线

---

> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。
