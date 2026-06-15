# V9 Agent 架构导航

**版本:** V9.2 | **最后更新:** 2026-06-15

## 30 秒定位

| 你想找... | 在这里 |
|----------|--------|
| 内核决策逻辑 | [`mpc_kernel/kernel.py`](../mpc_kernel/kernel.py) `kernel_step()` |
| 16 维状态向量定义 | [`protocol/v9_types.py`](../protocol/v9_types.py) `StateVector` |
| 8 门路由控制器 | [`mpc_kernel/route_controller.py`](../mpc_kernel/route_controller.py) `route_controller()` |
| ODE 信任积分器 | [`mpc_kernel/ode_integrator.py`](../mpc_kernel/ode_integrator.py) `integrate_state()` |
| Harness 主循环 | [`harness/harness.py`](../harness/harness.py) `Harness.step()` |
| LLM 总线桥接器 | [`harness/llm_bridge.py`](../harness/llm_bridge.py) `LLMBridge` |
| 工具总线桥接器 | [`harness/tool_bridge.py`](../harness/tool_bridge.py) `ToolBridge` |
| Track C 管道 | [`harness/track_c.py`](../harness/track_c.py) `RealTrackC` |
| 插件注册表 | [`harness/plugin_registry.py`](../harness/plugin_registry.py) `PluginRegistry` |
| CLI 入口 | [`v9_cli.py`](../v9_cli.py) |

## 五层架构

```
Layer 5: UI ── CLI / VSCode / Web (任意载体)
    │ user_text
    ▼
Layer 4: Observer ── 语义翻译 (自然语言 → ObservationResult)
    │ obs ── [observer/observer.py]
    ▼
Layer 3: Harness ── 总线矩阵 + 编排层
    │                 [harness/harness.py]
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐
    │  │ LLM Bus  │ │ Tool Bus │ │Event Bus │ │Telemetry Bus│
    │  │ (AHB级)  │ │ (APB级)  │ │ (NVIC级) │ │(CoreSight)  │
    │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘
    │  KernelInput                          ControlFrame
    ▼
Layer 2: MPC Kernel ── 纯函数决策 (零自然语言)
    │  [mpc_kernel/kernel.py] kernel_step() — 8 步:
    │    0.NaN入口 → 1.ODE积分 → 2.交互基 → 3.Lipschitz
    │    → 4.Streak+Pre-exit → 5.8门路由 → 6.连续量
    │    → 7.仲裁器 → 8.NaN出口
    │  ControlFrame (next_action + data_policy + trace)
    ▼
Layer 1: Execution ── LLM Synthesis / Tool Execution / Track C
```

## 四条总线

| 总线 | 对标硬件 | 方向 | 职责 | 文件 |
|------|---------|------|------|------|
| **LLM Bus** | AHB (高速总线) | 双向 | LLM 调用：地址解码 + 协议翻译 + MAC 重试 | `harness/llm_bridge.py` |
| **Tool Bus** | APB (外设总线) | 双向 | 工具调用：Semaphore(5) 限流 + 超时 + 事件转发 | `harness/tool_bridge.py` |
| **Event Bus** | NVIC (中断控制器) | 外设→内核 | 中断脉冲：优先级仲裁 + Lamport 时钟 + 合并去重 | `harness/event_bridge.py` |
| **Telemetry Bus** | CoreSight (调试跟踪) | 单向出 | (s,a,r) 三元组 → JSONL 异步写入 | `harness/telemetry_bus.py` |

## 插件协议 (V9.2)

```
harness/
  plugin_protocol.py   — PROTOCOL_VERSION + 6 Slot Protocols
  plugin_registry.py   — PluginRegistry + HarnessToolRegistry (桥接 COMPONENT_REGISTRY)
  plugin_discovery.py  — manifest.json 驱动 + LazyPluginLoader
  plugin_validator.py  — validate_slot() 挂载时校验
  plugins/
    manifest.json       — 显式插件清单
    prompts/            — PromptSlot 实现
    events/             — EventTypeSlot 实现
    observers/          — ObserverSlot 实现
    tracks/             — TrackSlot 实现
```

六个 Slot 类型: `tool`, `prompt`, `track`, `observer`, `event`, `policy`

## 内核铁律

| # | 铁律 | 含义 |
|---|------|------|
| 1 | 纯函数边界律 | `kernel_step()` 零副作用 |
| 2 | 连续控制律 | verbosity/tone/θ 连续推导，禁用查表 |
| 3 | 零自然语言律 | 内核输入输出绝对无自然语言 |
| 4 | 形式化可重放律 | 相同输入 → 相同输出 (DecisionTrace) |
| 5 | 零动态分配律 | tuple 替代 list，MappingProxyType 替代 dict |
| 6 | 梯度有界律 | ‖Δs‖ ≤ 0.30 (Lipschitz) |
| 7 | 信息损失可审计律 | 降维压缩规则显式声明 |

## 目录约定

```
godot-qwen-agent/
  mpc_kernel/          # V9 内核（纯函数）
  harness/             # V9 编排层 + 四条总线 + 插件协议
  observer/            # V9 观察器
  protocol/            # V9 冻结 ABI 类型
  core/                # 旧合约层（桥接依赖 — 逐步迁移）
  components/          # 工具实现（桥接依赖）
  engines/             # 引擎实现（桥接依赖）
  LLM/                 # LLM 客户端（桥接依赖）
  tests/               # 测试
  _legacy/             # V8 旧代码隔离区
  .ai_reasoning/       # 推理链 + 计划归档
  docs/                # 架构文档
```

## 关键不变量

- 注册表启动后冻结 (`freeze()` before first `step()`)
- 内核不感知插件协议
- 总线状态保全：管道中断时 checkpoints 不丢弃
- 事件合并：drain() 按 `(type, tool_name)` 分组
- 所有公共类型 `@dataclass(frozen=True)` + `MappingProxyType`
