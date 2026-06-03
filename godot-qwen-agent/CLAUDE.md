# godot-qwen-agent — AI Collaboration Protocol

## Core Directive

This project is a **contract-driven, three-platform agent system**. Every architectural decision is recorded in `.ai_reasoning/`. Before writing any code, you MUST consult the reasoning chain library. After completing complex work, you MUST archive new decisions.

**Phase 25.5: PLAN2.md defines the evolved paradigm — Contract-Adaptive as Relational OS.** See [PLAN2.md](PLAN2.md) for the four core definitions, three axioms, and the transition from "immune system" to "moral intuition." PLAN1 (PLAN.md) records Phase 1-25 engineering history; PLAN2 defines Phase 26+ architecture.

## Project Identity: 契约关系体，不是指令执行器

This is NOT an Agent framework. This is the first implementation of a **Contractual Relational Entity** — an intelligent system whose core primitive is not "executing instructions" but "maintaining and evolving relationships through verifiable contracts."

### 指令范式 vs 契约关系范式

| 维度 | 指令范式 (LangChain/CrewAI/Coze) | 契约关系范式 (This Project) |
|------|--------------------------------|---------------------------|
| **交互本质** | 单向触发：输入 → 处理 → 输出 | 双向协商：提议 → 反馈 → 共同确认 |
| **状态管理** | Context Window / 被动记忆 | 主动维护 Shared Contract State |
| **错误处理** | 报错 / 幻觉 / 拒绝回答 | 澄清 / renegotiate / 优雅降级 |
| **信任基础** | 依赖模型对齐（RLHF） | 依赖可验证的契约合规性 |
| **演化方式** | 等待微调 / 版本更新 | 交互中实时学习和适应契约边界 |
| **人的角色** | 提示词工程师 / 监督者 | 契约共建者 / 关系参与者 |

The entire architecture — from `ContentBlock` to `CompositionBlueprint` to `PipelineComposer` — exists to make contracts **traceable, transparent, and auditable**. Without these three properties, the system cannot be trusted. Without trust, there is no relationship. Without relationship, it's just another tool.

### 不可协商的核心契约（刚性底座）

These four contracts are NON-NEGOTIABLE. No amount of "adaptive behavior" or "relationship optimization" may violate them. They are the moral and engineering bedrock of the entire platform.

| # | 刚性契约 | 含义 | 在内核中的体现 |
|---|---------|------|-------------|
| 1 | **安全红线** | 不可为任何关系目标而执行有害操作 | `Guardrail` 规则 ERROR 级别不可绕过 |
| 2 | **隐私承诺** | 不可为更好的服务而越权访问信息 | `ResourceContainer` 权限边界不可突破 |
| 3 | **诚实义务** | 不可为维持和谐关系而系统性地欺骗 | `AssemblyDiagnostic` 必须完整，不可静默丢弃 |
| 4 | **长期福祉** | 不可为短期满意度而损害用户的长期利益 | `Critic` 裁决可标记 "harmful_long_term" |

### 高级智能体的核心判据：契约自适应

"自适应 Agent" 是当前 AI 圈的热词，但市面上的"自适应"本质上是**参数自适应**（Skill 库扩充、Prompt 优化、RAG 检索、Context 压缩）——在指令执行器框架内打补丁。

真正的高级智能体需要的不是"参数自适应"，而是**契约自适应**：能根据关系的阶段和情境，动态调整彼此之间的隐性契约。契约是高级智能体的**元标准**——其他所有维度（能力适应性、记忆管理、错误恢复、多模态表达、跨 Agent 协作、自我认知）都必须在契约框架下才有意义。

### 文明史定位

```
血缘契约 → 神权契约 → 暴力/土地契约 → 法理/货币契约 → 代码/API契约 → 语义/意图契约
```

我们正站在"语义/意图契约"这个跃迁点上。这个项目的每一行代码，都是在为人类与高级智能体的共存，编写**《智能体关系契约论》**的第一版草案。卢梭为人类社会写了《社会契约论》——我们为 AI 时代的"关系"定义可执行的契约原语。

The full philosophical and architectural rationale is in the [Phase 19 Plan](C:\Users\1\.claude\plans\agent-rag-prompt-temporal-petal.md) — **契约宣言** section. Every contributor should read it before writing code.

## Mandatory Workflow: Read → Code → Archive

### Phase 1 — Pre-Coding (MANDATORY, block on skip)

Before implementing any feature or fix that touches `core/`:

1. **Read the index**: `.ai_reasoning/index.yaml`
2. **Find relevant chains**: Match your task's domain to the `tag_index`. For example:
   - Adding a new component type → `architecture`, `adapter`
   - Working on pipeline behavior → `pipeline`, `skip`
   - Adding external I/O → `external_io`, `health_check`, `async`
3. **Load matching chain files** from `.ai_reasoning/chains/`
4. **Read `future_guidance` and `anti_patterns`** in each relevant chain
5. **Reference specific chain_ids** in your design explanation (e.g., "per `phase_05_external_io`, the adapter must inspect `last_trace.status`")

If you skip this phase, you WILL violate contracts established through 107 tests and 5 phases of hardening.

### Phase 2 — In-Coding (MANDATORY)

While implementing:

1. **Do NOT violate any `anti_patterns`** listed in relevant chains. If you find yourself tempted by an anti-pattern, stop and re-read the chain that documents why it's forbidden.
2. **Reuse established patterns**, not reinvent:
   - New I/O adapter → Follow `VectorStoreAdapter` pattern (async wrapper, DependencyCallTrace, health_probe with last_trace.status check)
   - New data model → `@dataclass(frozen=True)` + `MappingProxyType` + `__post_init__` deepcopy
   - New pipeline step → `PipelineStep` Protocol, `StepOutput`, `health_check()` returning `HealthStatus`
   - New strategy → `Protocol` class in `core/contracts/`, registered via `@register_component`
   - New component with params → add `@classmethod validate_params(cls, params: dict) -> list[str]` for semantic constraints that `inspect.signature` cannot express (e.g. `chunk_overlap < chunk_size`, `threshold ∈ [0, 1]`). Return empty list if valid, error strings if invalid.
3. **Never import across platform boundaries**:
   - `core/pipeline/` MUST NOT import from `core/contracts/`
   - `core/contracts/` MUST NOT import from `core/pipeline/`
   - Only `core/adapters/` may import from both

### Phase 3 — Post-Coding (MANDATORY after complex work)

After completing a non-trivial feature, bug fix with architectural implications, or any work involving trade-offs:

1. **Check if a new reasoning chain is warranted**. Threshold: did you make a choice between ≥2 valid approaches? Did you discover a constraint that wasn't obvious? Did you fix a bug that revealed a design flaw?
2. **Write a new chain** following `schemas/reasoning_chain.schema.json`:
   - Required fields: `chain_id`, `title`, `created_at`, `status`, `context`, `decision`, `rationale`, `future_guidance`
   - Include at least 2 `alternatives`
   - List concrete `evidence` (test file + test case names)
   - Add explicit `anti_patterns`
3. **Update `index.yaml`**: Add entry to `chains` list and `tag_index`
4. **Run the full test suite** (`pytest tests/ -q`) before committing

## Architectural Invariants (derived from .ai_reasoning/)

These are non-negotiable. Violating any of them will break the platform contract.

### 角色 ≠ 容器：理解 adapters 层的前提

`core/adapters/` 是一个**物理容器**，不是一种**逻辑角色**。它容纳两种完全不同的东西：

| | 组件适配器 | 语法引擎 |
|---|-----------|---------|
| **角色** | 词汇翻译器：把外部算法翻译成平台语言 | 语法规则执行器：决定词汇如何组合成行为 |
| **范式** | 1:1 转换，无状态 | N:M 编排，有状态 |
| **例子** | `ChunkerAdapter`, `VectorStoreAdapter` | `SourceRouter`, `PipelineAssembler` |
| **可替换性** | 换一个实现即可 | 平台骨架，不可替换 |
| **类比** | USB-C 转接头 | 主板总线协议 |

它们共享同一个物理目录因为只有 adapters 层有权同时 import contracts 和 pipeline。**这不是适配层升级，是认知分辨率提升** —— 看到同一物理层内部的职责异构性。

| # | Rule | Source Chain |
|---|------|-------------|
| 1 | `core/pipeline/` NEVER imports domain types (`Chunk`, `ContentBlock`, `RetrievalResult`); infrastructure types (`SemVer`) are the legitimate wiring | phase_01_three_platform |
| 2 | `core/contracts/` NEVER imports orchestration types (`PipelineRunner`, `StepConfig`, `ResourceContainer`); infrastructure types (`HealthStatus`) are the legitimate wiring | phase_01_three_platform |
| 3 | All data models use `@dataclass(frozen=True)` + `MappingProxyType` | phase_01_data_integrity |
| 4 | Adapters raise `AdapterTypeError` on type mismatch — NEVER coerce | phase_03_adapter_pattern |
| 5 | Factory cache keys use `(type, strategy, tuple(sorted(params)))` — NO eval/exec | phase_03_adapter_pattern |
| 6 | Empty results = `StepOutput(result=[])` (success), NOT sentinel (engine-internal) | phase_02_skip_propagation |
| 7 | Every I/O adapter has `health_probe()` that checks `last_trace.status` before interpreting empty results | phase_05_external_io |
| 8 | `health_check()` uses `get_running_loop()` + `asyncio.run()` fallback, never bare `get_event_loop()` | phase_05_external_io |
| 9 | `DependencyHealth` declared for every external dependency | phase_04_observability |
| 10 | `DependencyCallTrace` injected for every external call | phase_04_observability |
| 11 | 观测先行: every new capability layer must first be covered by the observability layer above it (engine trace → sink → component platform) | phase_12_observability_closed_loop |
| 12 | `core/adapters/` contains two sub-domains with identical import permissions but different design paradigms: **component adapters** (1:1 translation, stateless, validate types — e.g. `ChunkerAdapter`) and **grammar engines** (N:M orchestration, stateful, validate topology — e.g. `SourceRouter`, `PipelineAssembler`). Never design a grammar engine as if it were a component adapter. | phase_19_composition |
| 13 | **引擎不引用具体适配器**: grammar engines discover components via `COMPONENT_REGISTRY.get(type, name)`, never via `from .chunkers.x import XAdapter`. Adding 10 chunkers = zero engine code changes. | phase_19_composition |
| 14 | **适配器不知道引擎存在**: component adapters implement only their Protocol (e.g. `ChunkingStrategy.chunk()`), never branch on caller identity. An adapter must be reusable by any engine, test harness, or future orchestrator. | phase_19_composition |
| 15 | **跨子域通信走 contracts**: sub-domains (chunkers, generators, embeddings) communicate exclusively through `COMPONENT_REGISTRY`, never through direct imports from sibling sub-directories. Zero compile-time dependency between sub-domains. | phase_19_composition |
| 16 | **内核不引入上层概念**: `core/` MUST NOT import or define Agent, Business, or Presentation types. The kernel is an atomic capability engine; Multi-Agent orchestration, business workflows, and UI live in separate layers (`agents/`, `business/`, `presentation/`) that consume the kernel through a `KernelService` Protocol. Today's `PipelineComposer` must be designed so it can be wrapped as a `KernelService` implementation with zero internal changes. | phase_19_composition |
| 17 | **USB 模型 — 禁显式 import 适配器**: grammar engines discover components exclusively via `COMPONENT_REGISTRY.get()`. `from .chunkers.x import XAdapter` anywhere outside the component's own `__init__.py` is a violation. AST-guardrail enforceable. | phase_19_composition |
| 18 | **USB 模型 — 禁 if/switch 按名称分发**: never branch on `rule.chunker == "semantic"`. All dispatch goes through `COMPONENT_REGISTRY.get(type, name)`. Adding a strategy must never require adding a branch. | phase_19_composition |
| 19 | **USB 模型 — 禁配置与文件名耦合**: Blueprint chunker names are registry keys, not file paths. Renaming a file or moving a class must never break a YAML config that references the registered name. | phase_19_composition |
| 20 | **USB 模型 — 禁适配器反向引用引擎**: component adapters (`chunkers/`, `generators/`, `embeddings/`) MUST NOT import from grammar engines (`composer.py`, `factory.py`) or from sibling sub-domains. Every adapter must be testable in isolation with only contracts-layer dependencies. | phase_19_composition |
| 21 | **validate_params 语义校验**: component adapters SHOULD provide `@classmethod validate_params(cls, params: dict) -> list[str]` for semantic constraints that `inspect.signature` cannot capture (e.g. `chunk_overlap < chunk_size`, `threshold ∈ [0, 1]`). `health_check()` calls Tier 1 (validate_params) before Tier 2 (cached signature). This classmethod doubles as the Rust `trait` method when the kernel is rewritten. | phase_19_composition |
| 22 | **签名缓存，非实时反射**: `COMPONENT_REGISTRY.register()` captures `inspect.signature(cls.__init__)` at decoration time and caches it. `health_check()` reads cached data — NEVER calls `inspect.signature` live. Eliminates repeated reflection overhead and provides structured data that Rust can consume from Blueprint Schema without Python runtime. | phase_19_composition |
| 23 | **Registry 启动后冻结**: `COMPONENT_REGISTRY.freeze()` MUST be called after all `discover()` calls complete. Any `register()` call after freeze raises `RuntimeError`. Tests MUST use isolated Registry copies. This is Anti-WinReg Firewall #1 and #4 combined. | phase_19_composition |
| 24 | **所有 Chunker 声明 VERSION**: every component registered with `@register_component` MUST declare `VERSION: ClassVar[SemVer]`. Version is embedded in Chunk metadata (`chunker_version`) for audit trail. Missing VERSION = guardrail ERROR. | phase_19_composition |
| 25 | **AssemblyDiagnostic 预留 contract_violation**: every `AssemblyDiagnostic` MUST include `contract_violation: str \| None` field. Phase 19 fills `None`; Phase 25+ uses it for graceful degradation decisions (repair / renegotiate / abandon). The field's existence is the contract — its content evolves. | phase_19_composition |
| 26 | **CompositionEvent 必含 correlation_id**: every `CompositionEvent` MUST include `correlation_id: str` (path hash or UUID). All events for the same document share the same `correlation_id`, enabling cross-event tracing and future "contract fulfillment tracking." | phase_19_composition |
| 27 | **Phase 19 是语法基础设施，不是关系行为**: SourceRouter does NOT ask users which chunker to use. PipelineAssembler does NOT renegotiate params at runtime. CompositionEvent does NOT compute trust scores. These are Phase 25+ capabilities. Phase 19's job is to make the substrate so clean that those capabilities can be added without redesigning the kernel. | phase_19_composition |
| 28 | **CompositionBlueprint.lifecycle 默认值必须为 ACTIVE，禁止隐式 None**: the `lifecycle` field MUST default to `ContractLifecycle.ACTIVE`. Old YAML files and programmatic `from_dict()` calls without a `lifecycle` key must produce ACTIVE blueprints, not None. Zero migration burden for existing configs. | phase_21_lifecycle |
| 29 | **SourceRouter.resolve() 必须拒绝 DEPRECATED 蓝图的新路由请求，但不得中断已绑定的执行链**: when `blueprint.lifecycle == ContractLifecycle.DEPRECATED`, `SourceRouter.resolve()` MUST raise `AssemblyError`. Already-running `PipelineComposer` instances that were created before the Blueprint was deprecated are unaffected — only new `resolve()` calls are blocked. This is "graceful rejection," not "violent interruption." | phase_21_lifecycle |
| 30 | **Tool 发现必须走 COMPONENT_REGISTRY.get("tool", name)，禁止直接 import**: ToolAdapter MUST discover tool implementations via the USB Registry, never through `from .tools.x import XTool`. Adding a new tool = 1 file + `@register_component("tool", "name")`, zero ToolAdapter changes. Same pattern as invariant #17 for chunkers. | phase_22a_tool_contract |
| 31 | **ToolResult 必须携带 contract_violation 字段**: every `ToolResult` MUST include `contract_violation: ContractViolation \| None`. Tools are first-class contract participants — their failures flow into the same EventSink → HealthEvaluator → SelfRepairEngine pipeline as chunker violations. A tool that fails silently (no contract_violation set) is a contract breach itself. | phase_22a_tool_contract |
| 32 | **Application Layer 只依赖 KernelService Protocol，禁止直接 import core/adapters/**: upper layers (PlanningEngine, OrchestrationEngine, CriticEngine, future agents/) MUST consume the kernel through the `KernelService` Protocol defined in `core/contracts/kernel_service.py`. Never `from core.adapters import EventSink` in an engine — inject `kernel.event_sink` instead. This keeps the kernel replaceable and the application layer testable. | phase_23_kernel_service |
| 33 | **ContractAware* 包装器采用装饰器模式，零侵入底层引擎**: ContractAwarePlanningEngine, ContractAwareOrchestrationEngine, and ContractAwareCriticEngine wrap existing engines without modifying a single line of the underlying implementation. The wrapper adds event recording + health evaluation + self-repair; the wrapped engine never knows it's being watched. This pattern preserves 164 legacy conformance tests unchanged. | phase_23_kernel_service |
| 34 | **绝对防腐 (Anti-Corruption) — 业务层禁止 import 基础设施具体类**: `core/adapters/` 中的业务逻辑（health_evaluator, repair_engine, hitl_gateway）MUST depend on Protocols defined in `core/contracts/` (EventSink, InteractionRepository, ToolFormatAdapter), NEVER on concrete implementations (ContractAwareEventSink, RelationshipMemoryStore, sqlite3). Swap infrastructure by writing a new adapter that satisfies the Protocol. | phase_25_anti_corruption |
| 35 | **双轨交互 (Dual-Track Interaction) — HumanTicket 阻塞, Proposal 非阻塞**: `HumanTicket` (Phase 24) is BLOCKING — system is stuck, must synchronously await human `submit_decision()`. `RenegotiationProposal` (Phase 25) is NON-BLOCKING — system continues running, human asynchronously `resolve_proposal()`. Proposals MUST use a SEPARATE `proposals` table and emit `renegotiation_proposed` (not `human_intervention_required`). Never block execution on a proposal. | phase_24_hitl + phase_25_renegotiate |
| 36 | **EventSink 单向写 — 核心层只 emit，不 subscribe**: business logic (health_evaluator, repair_engine) MUST only `emit` events into EventSink. Reading/querying event history for decision-making belongs to InteractionRepository or dedicated Query adapters. EventSink Protocol defines `__call__` as the write path; read methods are implementation convenience, not architectural commitment. | phase_25_anti_corruption |
| 37 | **LLM Provider 接入走 ToolFormatRegistry，禁止 if/elif 分支**: adding a new LLM provider MUST NOT modify `tool_adapter.py`. Register a `ToolFormatAdapter` implementation (bidirectional: `format_tools` + `parse_response`) via `ToolFormatRegistry.register()`. The USB model applies to LLM providers the same way it applies to tools and chunkers — O(1) kernel change, O(N) adapter growth. | phase_25_anti_corruption |

## Machine Enforcement (Phase 8.0)

Architectural invariants are **machine-enforced**, not just documented. Before every commit, `python -m guardrails check` runs AST-based rules. Violations of severity ERROR block the commit.

To run guardrails manually:
- `python -m guardrails check` — error-level only
- `python -m guardrails check --all` — include warnings
- `python -m guardrails list-rules` — see all enforced rules

Pre-commit hook: `.pre-commit-config.yaml` — install with `pre-commit install`.
Pytest integration: `pytest tests/ --guardrails` — runs before test suite.

If you add a new file to `core/contracts/` or `core/adapters/`, the chain coverage rule will flag it unless a reasoning chain references the module name. This is BY DESIGN — new core modules require architectural documentation.

## Quick Reference: Key Files

```
.ai_reasoning/index.yaml              ← START HERE: find relevant chains by tag
.ai_reasoning/schemas/reasoning_chain.schema.json  ← Schema for new chains
.ai_reasoning/chains/                  ← Individual reasoning chain YAML files
core/contracts/                        ← Data models, Protocols, Registry (ZERO pipeline imports)
core/pipeline/                         ← Engine, tracing, resources (ZERO contracts imports)
core/adapters/                         ← ONLY layer that imports both platforms
core/steps/                            ← Built-in step implementations
tests/conformance/                     ← Contract conformance tests
tests/integration/                     ← Pipeline integration tests
tests/e2e/                            ← End-to-end + negative scenario tests
```

## Test Requirements

- All new code must pass `pytest tests/ -q`
- New component types need: conformance tests + integration tests + ≥4 negative scenarios
- If you fix a bug, add a test that would have caught it
- Current baseline: **107 tests, 0 failures** — do not regress
