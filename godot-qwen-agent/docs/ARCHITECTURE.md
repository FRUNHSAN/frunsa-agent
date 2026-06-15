# V9 Agent 架构导航

**版本:** V9.2 | **最后更新:** 2026-06-15

## 30 秒定位

| 你想找... | 在这里 |
|----------|--------|
| 内核决策逻辑 | [`mpc_kernel/kernel.py`](../mpc_kernel/kernel.py) `kernel_step()` |
| 16 维状态向量定义 | [`protocol/v9_types.py`](../protocol/v9_types.py) `StateVector` |
| 8 门路由控制器 | [`mpc_kernel/route_controller.py`](../mpc_kernel/route_controller.py) `route_controller()` |
| ODE 信任积分器 | [`mpc_kernel/ode_integrator.py`](../mpc_kernel/ode_integrator.py) `integrate_state()` |
| Harness 主循环 | [`mainboard/orchestrate/harness.py`](../mainboard/orchestrate/harness.py) `Harness.step()` |
| CPU socket 适配器 | [`mainboard/cpu/adapter.py`](../mainboard/cpu/adapter.py) `adapter_step()` |
| LLM 总线桥接器 | [`mainboard/bus/llm.py`](../mainboard/bus/llm.py) `LLMBridge` |
| 工具总线桥接器 | [`mainboard/bus/tool.py`](../mainboard/bus/tool.py) `ToolBridge` |
| Track C 管道 | [`mainboard/track/track_c.py`](../mainboard/track/track_c.py) `RealTrackC` |
| 插件注册表 | [`mainboard/plugin/registry.py`](../mainboard/plugin/registry.py) `PluginRegistry` |
| 主板配置 | [`mainboard/config/`](../mainboard/config/) |
| CLI 入口 | [`v9_cli.py`](../v9_cli.py) |

## 五层架构

```
Layer 5: UI ── CLI / VSCode / Web (任意载体)
    │ user_text
    ▼
Layer 4: Observer ── 语义翻译 (自然语言 → ObservationResult)
    │ obs ── [observer/observer.py]
    ▼
Layer 3: Mainboard ── 主板 (总线矩阵 + 编排层 + 插件系统)
    │                 [mainboard/orchestrate/harness.py]
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
| **LLM Bus** | AHB (高速总线) | 双向 | LLM 调用：地址解码 + 协议翻译 + MAC 重试 | `mainboard/bus/llm.py` |
| **Tool Bus** | APB (外设总线) | 双向 | 工具调用：Semaphore(5) 限流 + 超时 + 事件转发 | `mainboard/bus/tool.py` |
| **Event Bus** | NVIC (中断控制器) | 外设→内核 | 中断脉冲：优先级仲裁 + Lamport 时钟 + 合并去重 | `mainboard/bus/event.py` |
| **Telemetry Bus** | CoreSight (调试跟踪) | 单向出 | (s,a,r) 三元组 → JSONL 异步写入 | `mainboard/bus/telemetry.py` |

## 插件协议 (V9.2) — 三层挂载点

```
Layer 2 (mpc_kernel):     slots/ — 策略插件
Layer 3 (mainboard):      slots/ — 工具 + 提示词 + Track + 事件
Layer 4 (observer):       slots/ — 观察器后端

统一规范:
  - 每层 slots/__init__.py — 空壳，禁止硬编码 import
  - 每层 slots/manifest.json — 插件清单（LazyPluginLoader 驱动）
  - mainboard/plugin_sdk/ — 共享 SDK (protocol/registry/discovery/validator)
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

## 目录约定 — 双平面架构

```
# ═══════════════════════════════════════════════
# 控制平面 (Control Plane) — 纯代码与协议
# ═══════════════════════════════════════════════
godot-qwen-agent/
  mpc_kernel/          # Layer 2: MPC 内核（纯函数决策）
    kernel.py / ode_integrator.py / route_controller.py / safety_arbiter.py
    slots/             # 🔴 L2 挂载点 — 策略插件

  mainboard/           # Layer 3: 主板 — 编排 + 总线 + 插件
    orchestrate/       #   编排器主循环
    cpu/               #   CPU socket (adapter_step)
    bus/               #   四条总线 (llm/tool/event/telemetry)
    track/             #   Track 管道
    plugin_sdk/        #   插件 SDK (Protocol + Registry + Discovery + Validator)
    slots/             #   🔴 L3 挂载点 — 工具/提示词/Track/事件
      tools/           #     ToolSlot 实例 (薄包装器 → 调用子系统)
    config/            #   主板级配置 (总线参数、LLM provider)

  observer/            # Layer 4: 语义观察器
    observer.py
    slots/             # 🔴 L4 挂载点 — 观察器后端

  rag/                 # 独立子系统: 检索增强生成引擎
    chunker.py         #   分块逻辑
    vector_store.py    #   向量库接口
    retriever.py       #   检索逻辑
    # 非插件 — 被 mainboard/slots/tools/knowledge_search.py 薄包装调用

  protocol/            # 跨层冻结 ABI (v9_types.py)

  core/                # 旧合约层（桥接依赖）
  components/          # 旧工具实现（桥接依赖）
  engines/             # 旧引擎（桥接依赖）
  LLM/                 # LLM 客户端（桥接依赖）

# ═══════════════════════════════════════════════
# 资产平面 (Asset Plane) — 数据与配置
# ═══════════════════════════════════════════════
  data/                # 纯数据 (大文件进 .gitignore)
    knowledge/         #   知识库原始文件 (wiki, docs)
    vector_db/         #   本地向量库持久化 (ChromaDB/FAISS)

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
