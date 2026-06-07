# V5 模块生存资格审查 — 2026-06-07

**背景：** 17/47 个适配器模块零测试覆盖。在补测试之前，先按 V5 范式（变异-选择-保留、追踪误差、行为驱动的选择压力）对每个模块做兼容性分类。

**V5 范式检查标准：**
- ✅ 对齐：追踪真实行为差距，不猜测用户内部状态
- ❌ 不对齐："用 LLM/嵌入/关键词猜用户意图"（疲劳/沮丧/情绪维度那一套）
- 🔵 中性：纯基础设施，与范式无关

---

## 分类结果

### ⚠️ 需重构（4 个模块）
角色有价值，但实现用的是旧的"猜意图"范式。

| 模块 | 角色 | V5 差距 | 使用位置 |
|------|------|---------|----------|
| **contract_auditor** | System 2 契约合规审计 | 用 LLM 从对话历史"提取隐式信号"——这是在猜意图，不是在量行为差距 | `repl.py:902-903`（生产环境） |
| **agent_router** | 契约感知的后端选择（本地/云端） | HIGH_COMPLEXITY_MARKERS = 用关键词列表猜复杂度的旧范式 | `repl.py:12`（生产环境，每轮都调） |
| **embodied_reflex** | 工具结果 → 自然语言直觉 | PLAN2 遗留概念（"翻译膜"）。做呈现层有价值，但只被 demo 使用 | 仅 `demo/*.py` |
| **hitl_gateway** | 人机协同网关（修复预算耗尽时介入） | 概念上 V5 对齐（人作为最终选择者），基于协议，设计扎实，但仅被 demo 使用 | 仅 `demo/*.py` |

**动作：** 列入 Phase 2 backlog。重构完成前不补测试。

---

### 🟡 混合态（1 个模块）
生产在用但范式老旧。

| 模块 | 角色 | V5 差距 | 使用位置 |
|------|------|---------|----------|
| **relational_inertia** | 关系状态 EMA 平滑（信任、能量、疲劳） | 信任 EMA 仍有价值。但疲劳/能量维度已被 tracking_error.py 的自适应增益调度 EMA 替代 | `prompt_generator.py`、`relational_state_aggregator.py`、`config/relational_params.py`（生产环境） |

**动作：** Phase 2 提取信任 EMA（V5 兼容），废弃疲劳/能量平滑（已被 tracking_error.py 取代）。

---

### ❌ 应废弃/归档（2 个模块）
"读心术"范式，已被 V5 取代，仅 demo 使用。

| 模块 | 废弃理由 | 使用位置 |
|------|---------|----------|
| **renegotiation_watcher** | 统计 INTENTIONAL_VIOLATION 事件来提议契约重协商。PLAN2 概念："Agent 故意违反契约来展示自主性"。V5 拒绝了这一假设：Agent 不主动协商，它是**被环境选择的** | 仅 `demo/demo_plan2_closed_loop.py` |
| **interaction_telemetry** | JSONL 黑匣子记录器。纯观测，无行为影响。可重用于 V5 遥测，但目前记录的是旧信号维度（疲劳、能量、方差） | 仅 `demo/demo_data_generator.py`、`demo/demo_stress_test.py` |

**动作：** 加 `[DEPRECATED_BY_V5]` 标记，移入 `.ai_reasoning/archive/`。不补测试。

---

### 🔵 基础设施（10 个模块）
范式中立工具，无 V5 兼容问题。

| 模块 | 角色 | 优先级 |
|------|------|--------|
| **cloudllm_backend** | DeepSeekClient → GenerationBackend 适配器 | 低 |
| **keyword_chunker** | 基于段落的分块（COMPONENT_REGISTRY 注册） | 低 |
| **semantic_chunker** | 基于嵌入的句边界检测 | 低 |
| **semantic_retriever** | 基于嵌入的块检索 | 低 |
| **mcp_adapter** | MCP 服务器/工具注册 | 中 |
| **mock_mcp_tools** | Mock MCP 工具（demo/测试用） | 低 |
| **output_grammar** | 从契约字段生成 GBNF 语法规则 | **高** |
| **reranker_adapter** | 打分/重排序后端的异步封装 | 低 |
| **tool_format_defaults** | AnthropicToolFormat + OpenAIToolFormat 适配器 | 低 |
| **tool_format_registry** | LLM 提供商工具格式的 USB 注册表 | 中 |

**动作：** 按优先级补测试。高优先级：`output_grammar`（repl + local_llm 每轮都在用）。中优先级：`mcp_adapter`、`tool_format_registry`。低优先级：其余。

---

## 总结

| 分类 | 数量 | 命运 |
|------|------|------|
| ⚠️ 需重构 | 4 | Phase 2 backlog |
| 🟡 混合态 | 1 | 提取信任 EMA，废弃其余 |
| ❌ 应废弃 | 2 | 加 DEPRECATED_BY_V5，移入 archive |
| 🔵 基础设施 | 10 | 按优先级补测试 |

**零个模块被分类为 ✅ V5-原生。** 这恰好印证了本次审计的价值：V5 的范式转换是真刀真枪的——"猜意图"是旧范式的核心，而 V5 的核心是"追踪误差"。连架构支撑模块都需要重构才能对齐。

---

## 当前已执行动作

contract_auditor 已补 15 个 V5 合规测试（`tests/unit/test_v5_contract_auditor.py`），验证了：
1. 审计员不直接修改 Blueprint 字段（只检测 + 报告）
2. 熔断器防止级联 LLM 故障
3. Schema 注入约束审计员输出
4. 格式错误的 LLM 响应优雅降级
