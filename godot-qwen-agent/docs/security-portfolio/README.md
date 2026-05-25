# Frunsa-Agent: 安全感知的 AI Agent 基础设施

> 一个面向 AI Agent 的三层可验证安全机制实现，同时也是多引擎 LLM Agent 架构的实验平台。

**核心命题**: AI Agent 的安全属性可以被工程化地定义、检测和追溯——而非依赖运行时约定或事后审计。

---

## 项目概述

Frunsa-Agent 是一个三层平台架构的 AI Agent 系统（Protocol → Adapter → Pipeline），集成了 Planning、Orchestration、Critic 三类 LLM 引擎。项目的核心贡献不是功能丰富度，而是**将安全作为架构一等公民**的三层可验证机制：

| 层级 | 机制 | 阶段 | 技术实现 |
|------|------|------|---------|
| **编译时** | AST 合规扫描 (Guardrails) | 开发/CI 阶段 | 16 条 AST 规则自动检测架构违规，pre-commit hook 强制执行 |
| **运行时** | 安全隔离 (Safety Isolation) | 引擎运行阶段 | try/except → error terminal（不 crash）；ResourceContainer 凭证隔离；引擎目录互不 import |
| **事后** | Trace 溯源 (Auditability) | 事后审计阶段 | SQLiteTraceSink 单文件数据库；每次 LLM 调用完整记录输入/输出/令牌/延迟 |

这三层不是事后添加的"安全特性"，而是从 Phase 1 写入架构宪法（`PLAN.md` 六引擎层性质）的核心设计约束。

---

## 架构概览

```
                    ┌──────────────────────────────────┐
                    │         Engine Layer              │
                    │  Planning │ Orchestration │ Critic │
                    │  (stub + LLM) × 3 = 6 engines    │
                    ├──────────────────────────────────┤
                    │       Adapter Layer               │
                    │  GenerationAdapter (LLM calls)    │
                    │  DependencyCallTrace (per-call)   │
                    │  ResourceContainer (credentials)  │
                    ├──────────────────────────────────┤
                    │      Pipeline Layer               │
                    │  StreamingTraceRecord             │
                    │  SQLiteTraceSink (audit log)      │
                    │  Guardrails (AST enforcement)     │
                    └──────────────────────────────────┘
```

### 三条可更新性设计原则

系统在 18 个 Phase 的迭代中沉淀出三条面向长期演进的工程原则：

| 原则 | 说明 | 反例 |
|------|------|------|
| **Factory 装配契约** | 引擎通过可注入工厂函数获取依赖，切换实现 = 一行 lambda | `StubOrchestrationEngine()` 硬编码在 planning stub 中（Phase 18 修复） |
| **Contract Locking** | Protocol 签名 + Trace Key 集合 = 合约面，Guardrail 在 AST 级强制执行 | 新增 ad-hoc trace key 绕过 Sufficiency Report 流程 |
| **metadata 扩展槽** | 所有 Context 携带 `metadata: Mapping[str, Any]`，不参与强类型约束，不触发 guardrail | 引擎开发者因缺调试通道而向核心接口添加临时字段 |

---

## 安全机制详解

### 1. 编译时: Guardrail 架构合规扫描

系统包含 16 条 AST 级别的架构规则，在每次 commit 前自动执行。规则涵盖：

| Guardrail 名称 | 检测目标 | 安全意义 |
|---------------|---------|---------|
| `cross_platform` | cross-platform import 边界违反 | 防止架构腐化导致隔离失效 |
| `engine_interface_purity` | Protocol 签名被意外修改 | 合约变更必须在 Sufficiency Report 中记录 |
| `orchestration_trace_completeness` | 6 个 orchestration.* keys 在所有路径上存在 | 确保 Audit Log 完整性 |
| `critic_engine_contract` | 2 个 critic.* keys + agent.identity | 确保评估结果可追溯 |
| `planning_engine_contract` | 5 个 planning.* keys + agent.identity | 确保规划过程可审计 |
| `trace_key_registration` | 所有 trace key 在 Registry 中声明 | 防止未注册 key 污染日志 |
| `trace_key_serializability` | trace_context 值类型可 JSON 序列化 | 防止运行时序列化异常 |
| `frozen_dataclass` | 所有 dataclass 使用 frozen=True | 防止不可变数据被意外修改 |
| `stream_isolation` | internal stream 不泄露到 user-facing stream | 防止内部状态暴露 |
| `sink_schema_consistency` | Sink schema 与 trace key registry 一致 | 防止 schema drift |
| `chain_coverage` | 新 core module 必须有对应 reasoning chain | 确保架构决策有文档追溯 |
| `component_registry` | Component 注册完整性 | 防止未注册组件进入 pipeline |
| `component_trace_completeness` | Component trace key 完整性 | 组件可观测性保证 |
| `transport_adapter_boundary` | Transport 层 adapter 边界 | 防止跨层耦合 |
| `internal_stream_only` | Internal stream 隔离 | 流式数据边界保护 |
| (reserved) | — | — |

**新增一条 guardrail 的成本**: 在 `guardrails/rules/` 下编写一个 Python 文件，继承现有的 `_ast_utils.py` 工具函数，15-30 行代码即可完成 AST 模式匹配。

### 2. 运行时: 安全隔离与纵深防御

三个引擎类型（Planning / Orchestration / Critic）各有两个实现（Stub 确定性参考 + LLM 生产引擎），运行时隔离通过以下机制保证：

**故障隔离**:
- 所有引擎的 LLM 调用包裹在 `try/except` 中，解析失败 → `error terminal StreamItem` → **向上传播信息，不向外传播崩溃**
- LLM 输出强制 JSON 解析 + 类型校验 + 枚举校验（如 critic verdict 仅允许 `accept/rework/reject`），非预期输出被拒绝而非静默通过

**凭证隔离**:
- `ResourceContainer` 统一管理 LLM API Keys
- `GenerationAdapter` 封装凭证注入逻辑，引擎代码不接触原始 key

**架构隔离**:
- `core/pipeline/` MUST NOT import from `core/contracts/`
- `core/contracts/` MUST NOT import from `core/pipeline/`
- AST 规则 `cross_platform` 强制执行，禁止跨层 import

**输入/输出纵深防御**:
- **输入层**: 所有 LLM prompt template 要求结构化输出（`Respond with ONLY the JSON object, no other text`），限制自由文本响应面
- **输出层**: `_parse_critic_evaluation()` / `_parse_route_decision()` / `_parse_merge_decision()` 对 LLM 输出做类型校验和枚举校验
- **审核层**: Critic Engine 对 Planning Engine 输出做二次评估——如果 score 低于阈值或 verdict 为 reject，产生 error terminal

### 3. 事后: Trace 溯源与可审计性

每次 LLM 调用生成 `DependencyCallTrace`，每条 StreamItem 携带 `trace_context`（键值对字典），全部持久化到 `SQLiteTraceSink`（单文件数据库）。

**Trace Key 体系 (18 keys)**:
- `planning.*` (5 keys): 规划过程的每一步都有独立 trace
- `orchestration.*` (6 keys): 并行分发、分支选择、重试计数、资源池路由、合并排序、DAG 节点身份——全部可查询
- `critic.*` (2 keys): 质量评分 + 评估结论（accept/rework/reject）
- `retrieval.*` (2 keys): 检索块的 chunk_id 和延迟
- `agent.identity` (1 key): 每条记录标记产出引擎的身份（role/id/version/capabilities）
- `component.*` (2 keys): 组件平台通用 trace

**可审计性验证**: Sufficiency Report v4 证明了 18 个 keys 对 3 个 LLM 引擎 + 3 个 Stub 引擎完全充分——不需要新 key 就能覆盖所有引擎行为。

---

## 关键数字

| 指标 | 数值 |
|------|------|
| 测试用例 | 673（conformance + integration + e2e） |
| 测试通过率 | 100%（0 failures） |
| Guardrail 规则 | 16 条（AST 级架构强制） |
| 引擎实现 | 6 个（Planning × 2 + Orchestration × 2 + Critic × 2） |
| Trace Keys | 18 个（覆盖三层引擎全链路） |
| 推理链文档 | 21 条（`.ai_reasoning/chains/`，每条记录决策/alternatives/anti-patterns） |
| Sufficiency Reports | 4 份（v1 → v4，形式化 trace key 语义充分性） |

---

## 项目结构

```
frunsa-agent/
├── core/                    # 核心基础设施
│   ├── adapters/            #   Adapter 层（GenerationAdapter + DependencyCallTrace）
│   ├── contracts/           #   Protocol 定义 + 数据模型（frozen dataclass）
│   ├── observability/       #   Trace 系统（SQLiteTraceSink + TraceRegistry）
│   └── pipeline/            #   Pipeline Runner + 资源管理
├── engines/                 # 引擎层
│   ├── planning/            #   Planning Engine（stub + LLM 双实现）
│   ├── orchestration/       #   Orchestration Engine（stub + LLM 双实现）
│   └── critic/              #   Critic Engine（stub + LLM 双实现）
├── guardrails/              # 架构合规扫描器
│   └── rules/               #   16 条 AST 规则
├── tests/                   # 测试
│   ├── conformance/         #   协议符合性测试
│   ├── integration/         #   集成测试
│   └── e2e/                 #   端到端测试
├── docs/security-portfolio/ #   安全能力专项文档（你在这里）
├── .ai_reasoning/           # 架构推理链库
│   ├── chains/              #   21 条推理链（决策/替代方案/反模式）
│   └── sufficiency/         #   4 份 Sufficiency Reports
├── PLAN.md                  # 完整架构规划（18 Phase 演进史）
└── CLAUDE.md                # AI 协作协议 + 架构不变式
```

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行全部测试
pytest tests/ -q
# 673 passed, 0 failed

# 3. 运行架构合规检查
python -m guardrails check --all
# Guardrails: PASSED (36 files, 16 rules)

# 4. 查看 Trace 日志（运行任一测试后）
python -c "
from core.observability.sqlite_sink import SQLiteTraceSink
import tempfile, os
# 测试会在临时目录生成 .db 文件，query_by_engine('critic') 查看评判引擎记录
"
```

---

## 技术栈

- **语言**: Python 3.12+
- **异步**: asyncio（单事件循环，无 `asyncio.run()` 污染）
- **数据模型**: `@dataclass(frozen=True)` + `MappingProxyType`（不可变防御）
- **LLM 集成**: GenerationAdapter 统一接口（OpenAI / Claude / Qwen / Ollama）
- **CI 确定性**: MockBackend frozen dataclass + round-robin（每条引擎独立定义）
- **测试框架**: pytest 9.x

---

## 定位与局限

**这个项目的定位**是 AI Agent 安全机制的"最小可行验证"——它展示了安全属性可以被结构化地设计、实现和测试，而不是声称覆盖了所有攻击面。

已知局限（详见 [SECURITY.md](./SECURITY.md)）:
- Prompt Injection 防御仅实现了结构化输出约束，未覆盖 GCG 等对抗性攻击
- AST Guardrails 仅检查静态模式，不检测运行时行为
- Trace 系统未做性能压测，大数据量下的查询优化是后续工作
- 未实现多级 DAG 并行（仅单级 fan-out）

**诚实胜过完美。** 安全工程的核心素养不是"我防住了所有攻击"，而是"我清楚自己防了什么、没防什么、以及为什么"。

---

## 相关文档

- [SECURITY.md](./SECURITY.md) — 威胁模型、安全设计决策、已知局限
- [PLAN.md](../../PLAN.md) — 18 Phase 完整架构演进史
- [CLAUDE.md](../../CLAUDE.md) — 架构不变式参考
- [.ai_reasoning/](../../.ai_reasoning/) — 21 条架构推理链

---

## 作者

FRUNHSAN — 该项目为个人独立开发的 AI Agent 架构实验平台，同时作为 AI 安全工程能力的展示作品。

投递岗位: 华为 网络安全与隐私保护工程师（AI for Security / AI 安全方向）
