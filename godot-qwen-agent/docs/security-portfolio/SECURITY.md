# Security Design Document (安全设计文档)

> 版本: 1.0.0 | 最后更新: 2026-05-25 | 适用范围: Frunsa-Agent v0.18.x

本文档描述 Frunsa-Agent 的威胁模型、安全设计决策、纵深防御体系及已知局限性。它是安全能力专项文档的核心组成部分，用于证明"安全属性可以被工程化地定义、检测和追溯"这一核心主张。

---

## 威胁模型 (Threat Model)

### 系统边界与信任域

```
┌─────────────────────────────────────────────────────┐
│  不受信任域 (Untrusted Zone)                          │
│  ┌───────────────────────────────────────────────┐  │
│  │  LLM Provider (OpenAI / Claude / Qwen)         │  │
│  │  - 输入: Prompt (可能含恶意指令)                 │  │
│  │  - 输出: 非结构化文本 (可能含注入载荷)            │  │
│  │  - 信任度: ZERO TRUST                           │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                         │
              GenerationAdapter (边界)
                         │
┌─────────────────────────────────────────────────────┐
│  受控域 (Controlled Zone) — Agent Runtime             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Planning │  │   Orch   │  │  Critic  │          │
│  │  Engine  │  │  Engine  │  │  Engine  │          │
│  └──────────┘  └──────────┘  └──────────┘          │
│              Pipeline / Observability                │
│  ┌──────────────────────────────────────────────┐  │
│  │  SQLiteTraceSink (Audit Log)                  │  │
│  │  Guardrails (AST Enforcement)                 │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 威胁清单 (Threat Enumeration)

以下威胁按 STRIDE 模型分类：

| ID | 威胁 | 分类 | 严重度 | 缓解状态 |
|----|------|------|--------|---------|
| T-01 | LLM 输出包含恶意 JSON / Prompt Injection 载荷经由 trace_context 传播 | Tampering | High | Partially mitigated |
| T-02 | 恶意构造的 Prompt 导致 LLM 产生越权操作（如泄露其他用户的 trace 数据） | Information Disclosure | High | Partially mitigated |
| T-03 | 引擎内部异常未正确处理，导致 Agent 进程崩溃（DoS） | Denial of Service | Medium | Mitigated |
| T-04 | API Key 硬编码泄露到代码仓库 | Information Disclosure | Critical | Mitigated |
| T-05 | 非确定性 LLM 输出绕过类型校验（如 score 字段返回字符串而非数值） | Elevation of Privilege | Medium | Mitigated |
| T-06 | 跨引擎 trace context 污染（Orchestration 写入 critic.* key） | Tampering | Low | Mitigated |
| T-07 | Guardrails 规则被绕过（未检查新 engine 目录） | Tampering | Medium | Partially mitigated |
| T-08 | SQLite Sink 文件被未授权读取（trace 数据包含 LLM prompt/response） | Information Disclosure | Medium | Not mitigated |

---

## 安全设计决策 (Security Design Decisions)

### Decision 1: 结构化输出约束 + 类型校验 = 最小可行输出防御

**问题**: LLM 输出是非结构化文本，可能包含恶意内容或格式错误。

**决策**: 所有 LLM prompt template 要求结构化输出（JSON），parser 对输出做三级校验：
1. **语法校验**: `json.loads()` 解析，失败则 reject
2. **类型校验**: `isinstance(data["score"], (int, float))`，类型不匹配则 reject
3. **枚举校验**: `verdict in ("accept", "rework", "reject")`，未定义枚举值则 reject

**防御效果**:
- 防止非 JSON 输出进入下游
- 防止类型不一致导致的运行时错误
- 限制 verdict 的取值范围，防止注入自定义枚举值

**已知局限**: 不防御 GCG (Greedy Coordinate Gradient) 等针对 LLM 本身的对抗性攻击。结构化输出约束是输出防御层，不是模型鲁棒性方案。

### Decision 2: 引擎级 try/except → error terminal StreamItem（永不 Crash）

**问题**: LLM 调用可能因网络、API 限额、解析失败等原因抛出异常。传统做法是让异常向上冒泡，可能导致整个 pipeline 崩溃。

**决策**: 每个引擎的每次 LLM 调用都包裹在 `try/except` 中：
```python
try:
    result = await self._adapter.generate(prompt, [])
    eval_data = _parse_critic_evaluation(result.text)
except Exception as e:
    yield StreamItem(
        delta=f"Critic {step_name} evaluation failed: {e}",
        finish_reason="error",
        error=str(e),
        trace_context={
            "critic.score": 0.0,
            "critic.verdict": "reject",
            "agent.identity": identity_value,
        },
    )
```

**防御效果**:
- 异常被转换为带 `error` 字段的合法 StreamItem，而非进程级崩溃
- 失败时 trace_context 仍然完整写入 Sink，保留归因信息
- 错误信息包含在 delta 中，不丢失诊断数据

**安全含义**: 这是故障安全 (Fail-Safe) 的最小实现——系统崩溃时，最后的状态已被记录。

### Decision 3: ResourceContainer 凭证隔离

**问题**: API Key 如果在引擎代码中直接引用，会扩散访问权限，增加泄露面。

**决策**: `ResourceContainer` 统一管理所有外部凭证。`GenerationAdapter` 封装凭证注入逻辑。引擎代码仅调用 `adapter.generate(prompt, [])` 而不接触 key。

**代码路径**: `LLM/openai.py` → `api_key = os.getenv("OPENAI_API_KEY")` → `GenerationAdapter` → Engine

**防御效果**:
- 引擎代码零凭证依赖
- 切换凭证只需修改环境变量
- 测试环境自动使用 MockBackend（无需真实 key）

### Decision 4: 不可变数据模型 (frozen dataclass + MappingProxyType)

**问题**: Python 的可变默认参数和运行时可修改属性可能导致数据被意外篡改，在安全审计路径上引入不确定性。

**决策**: 所有数据模型使用 `@dataclass(frozen=True)` + `MappingProxyType`。`MockBackend` 的 `_call_count` 突变通过 `object.__setattr__()` 显式标记为有意的内部操作。

**Guardrail 强制**: `frozen_dataclass` 规则扫描所有 dataclass 定义，标记 `frozen=False` 的情况。

### Decision 5: 跨引擎 Key 命名空间隔离

**问题**: 多个引擎写入同一个 trace_context 时可能发生 key 碰撞，导致审计数据被覆盖或混淆。

**决策**: 每个引擎使用独立的 key 前缀（`planning.*` / `orchestration.*` / `critic.*`）。`agent.identity` 是唯一的跨引擎 key，通过多引擎注册模型管理。

**E2E 测试验证**: `test_no_key_collision_critic_orch` / `test_engine_partitioning_isolation` — 验证 critic.* 不出现在 orchestration rows，反之亦然。

---

## 纵深防御体系 (Defense-in-Depth)

| 层级 | 机制 | 时机 | 防御目标 |
|------|------|------|---------|
| L1: 开发时 | `.gitignore` + `os.getenv()` 模式 | 编码阶段 | T-04: API Key 泄露 |
| L2: 提交前 | 16 条 AST Guardrails (pre-commit hook) | git commit | T-07: 架构合规破坏 |
| L3: CI/CD | `pytest tests/ -q` (673 tests) | Push/PR | T-05: 类型校验绕过 |
| L4: 引擎边界 | `try/except` → error terminal | Runtime | T-03: DoS via crash |
| L5: LLM 边界 | Structured output + Parser 三级校验 | LLM call | T-01/T-02: Prompt Injection |
| L6: 输出审核 | Critic Engine 二次评估 | Post-generation | T-01: 恶意输出传播 |
| L7: 审计 | SQLiteTraceSink 全量持久化 | Post-execution | T-08: 事后归因需求 |

---

## 已知局限性 (Known Limitations)

以下局限已被识别和记录，按严重度排序：

| ID | 局限 | 影响 | 缓解计划 |
|----|------|------|---------|
| L-01 | **未防御 GCG / AutoDAN 等对抗性 Prompt Injection** | LLM 可能在遭受对抗性攻击时产生非预期输出 | 短期无法缓解（需模型级防御），可在 Critic Engine 中增加异常输出检测规则 |
| L-02 | **Guardrails 仅做静态 AST 扫描** | 无法检测运行时行为异常（如动态 import、反射调用） | 可以接受（CI 阶段静态检查已覆盖主要风险），后续可引入 runtime assertion |
| L-03 | **Trace 系统未做性能压测** | 高频 LLM 调用下 SQLite 可能成为瓶颈 | 当前引擎吞吐量未达到 SQLite 瓶颈，后续可迁移到 WAL 模式或切换到嵌入式 DuckDB |
| L-04 | **未实现 trace 数据加密** | SQLite .db 文件若被未授权访问，所有 prompt/response 明文可读 | 后续可增加 SQLCipher 或文件系统级加密 |
| L-05 | **仅单级 DAG 并行** | 不支持多级嵌套并行，无法测试更复杂的隔离场景 | 后续 Phase 可扩展 DAG depth > 1 |
| L-06 | **MockBackend 确定性掩盖了真实 LLM 的非确定性风险** | CI 测试通过不代表生产环境安全 | 需要独立的生产环境验证流程（Phase 19+） |
| L-07 | **未实现鉴权/访问控制** | 任何能访问 Agent 进程的调用方均可触发引擎执行 | 当前为单用户实验平台，暂不需要 |

---

## 安全开发生命周期 (SDL)

本项目遵循的 SDL 实践：

1. **威胁建模**: 本文档的威胁清单在 Phase 7（LLM 风险预分析）首次建立，Phase 18 更新
2. **安全设计评审**: 每次架构决策记录在 `.ai_reasoning/chains/` 中，包含 alternatives 和 anti-patterns
3. **自动化安全测试**: 16 条 AST Guardrails 在 CI 中自动执行
4. **合约完整性验证**: Sufficiency Report 流程确保 trace key 充分性不被破坏
5. **依赖管理**: `LLM/` 目录下的客户端均为可选依赖导入（`try/except ImportError`）
