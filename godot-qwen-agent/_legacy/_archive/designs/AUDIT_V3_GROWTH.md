# V3 生长审计 — 缺失的能力与未来的契机

## 关键发现

| 类别 | 数量 | 影响 |
|------|------|------|
| 有实现未接入 | 7 个适配器 | MCP、ToolFormats、EmbodiedReflex…写了但没用 |
| 有 Protocol 无多实现 | 11 个 | ~500 行抽象税，YAGNI 风险 |
| 代码重复 | 1 对 | run_live.py ≈ core/repl.py，已分叉 |
| 未接入引擎 | 3 个 | Planning/Orchestration/Critic 引擎未接入主循环 |
| 缺失测试 | 4 类 | Repl 类、RAG 管道、LLM 降级、Composer |
| 不变量违规 | 1 条 | COMPONENT_REGISTRY.freeze() 从未调用 |
| 未归档功能 | 4 个 | X-Ray、/rag、/mood、会话日志 |

---

## 详细发现

### 1. 写了但没接入的（7 个适配器）

| 文件 | 功能 | 为什么没用 |
|------|------|-----------|
| `core/adapters/mcp_adapter.py` | MCP 工具发现+注册 | 没有 MCP 服务端可连 |
| `core/adapters/tool_formats.py` | Anthropic/OpenAI 工具格式 | ToolFormatRegistry 从未实例化 |
| `core/adapters/embodied_reflex.py` | 工具结果→自然语言 | 只在 demo 中被调用 |
| `core/adapters/renegotiation_watcher.py` | 违约重谈 | 只在 demo 中被调用 |
| `core/adapters/transports/grpc_transport.py` | gRPC 传输 | 抽象存根，未实现 |
| `core/adapters/transports/redis_streams_transport.py` | Redis 流 | 抽象存根，未实现 |
| `core/adapters/sqlite_profile.py` | WAL 模式画像 | 只被测试引用，主线用 JSON |

### 2. Protocol 抽象税（11 个，~500 行）

| Protocol | 实现数 | 建议 |
|----------|--------|------|
| `KernelService` | 0 | 删或留为远期蓝图 |
| `ContractGateway` | 0 | 删或让 ContractEngine 实现它 |
| `TransportBackend` | 0 (2 个抽象存根) | 删，gRPC/Redis 存根一并删 |
| `SemanticTrustDetector` | 1 | 保留——V3.1 会有第 2 个 |
| `PatternRepository` | 1 | 保留——V3.1 会有 Redis 版 |
| `ToolRegistry` | 1 | 保留——MCP 接入后会分叉 |
| `ToolFormatAdapter` | 2 但 0 调用 | 删或接入 ToolAdapter |
| `InteractionRepository` | 1 | 保留 |
| `EventSink` | 1 | 保留 |
| `StateAggregator` | 1 | 保留 |
| `SeedGenerator` | 1 | 保留 |
| `InertiaTracker` | 1 | 保留 |

### 3. 代码重复

`run_live.py` (429 行) 和 `core/repl.py` (429 行) 是近重复——`run_live.py` 有语义兜底逻辑，`repl.py` 有 X-Ray+`/rag`。已分叉。应合并，保留 `core/repl.py` 为唯一实现。

### 4. 四类缺失测试

- **Repl 类**：429 行，0 测试。主交互循环完全未经自动化验证
- **RAG 管道**：knowledge_search + guard_post_retrieval 无集成测试
- **LLM 降级路径**：双轨信任中的 Track B 无测试
- **Composer/PipelineAssembler**：语法引擎无专用单元测试

### 5. 不变量违规

`COMPONENT_REGISTRY.freeze()` 从未调用。应该在 `container.py` 构建完成后调用。

### 6. 未归档的功能

| 功能 | 文件 | 文档状态 |
|------|------|---------|
| X-Ray 仪表盘 | core/xray.py | 无 PLAN 文档 |
| /rag on\|off | core/repl.py:247-253 | 无用户文档 |
| /mood | core/repl.py:209 | 无用户文档 |
| 会话日志保存 | core/repl.py:422-428 | 无用户文档 |

### 7. 引擎层隔离

PlanningEngine、OrchestrationEngine、CriticEngine（共 15 个文件）架构完整、有 conformance 测试——但在 `core/repl.py` 中被完全绕过。主循环直接调用 `cloud_llm.generate()`，不经过任何引擎。

---

## 优先修复建议

| # | 动作 | 理由 |
|---|------|------|
| 1 | 删除 4 个死 Protocol（KernelService, ContractGateway, TransportBackend, ToolFormatAdapter） | 清掉 ~300 行永不用到的抽象 |
| 2 | 合并 run_live.py → core/repl.py | 消除代码重复 |
| 3 | `COMPONENT_REGISTRY.freeze()` in container.py | 修复不变量违规 |
| 4 | 给 Repl 类加 10 个基础单测 | 主循环零测试是最大风险 |
| 5 | 归档 X-Ray, /rag, /mood 到 README | 功能做了但用户不知道 |

---

## 远期中寻找的的契机

这些不是缺陷——是架构已经预留了接口但还没到用的时候：

| 组件 | 什么时候有用 |
|------|------------|
| MCP Adapter | 接入真实 MCP 服务端 |
| ToolFormats | 多 LLM 后端切换 |
| 三引擎 (Planning/Orch/Critic) | Agent 需要多步推理时 |
| EmbodiedReflex | 工具结果需要"人性化"时 |
| gRPC/Redis 传输 | 分布式部署时 |
