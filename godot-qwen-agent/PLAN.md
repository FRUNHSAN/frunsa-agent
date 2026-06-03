# Plan: 组件平台 + 引擎平台 — 高度分化，转译层连通

---

## Global Guiding Principles — 架构宪法 (长期维护准则)

为防止系统在长期演进中出现**跨层职责代偿**与**边界模糊**，本项目确立以下核心准则作为所有后续迭代的最高约束。

### 一、引擎层优化指标 (Six Properties)

引擎层（Agent Runtime / Protocol Infrastructure）是所有上层业务的基石。任何针对引擎层的重构、优化或新功能引入，**必须且只能**服务于以下六大核心性质：

| # | 性质 | 定义 | 强制机制 |
|---|------|------|----------|
| **1** | **高效 (Efficiency)** | 极致的并发调度与资源利用率，杜绝不必要的阻塞与冗余计算 | GenerationAdapter 复用、deadline 强制、asyncio.gather 并行、token budget 封顶 |
| **2** | **全透明 (Full Transparency)** | 执行链路必须是白盒，状态流转、上下文截断及异常根因需完全可观测 | DependencyCallTrace 注入（每次 adapter 调用）、trace_context 在每个 StreamItem、SQLiteTraceSink 全链持久化 |
| **3** | **安全隔离 (Security & Isolation)** | 严格的凭证隔离、权限边界与沙箱机制，防止单点故障或恶意注入引发系统级雪崩 | try/except → error terminal StreamItem（不 crash）、ResourceContainer 凭证隔离、引擎目录互不 import |
| **4** | **冗余性 (Redundancy / Resilience)** | 具备优雅降级、超时熔断与多模型 Fallback 能力，确保非确定性环境下的生存底线 | Protocol 抽象 — stub 和 LLM 引擎共存、Factory 装配契约（DI）、组件注册表 |
| **5** | **可审计 (Auditability)** | 所有决策链路与 Guardrail 触发必须留存不可篡改的完整证据链，支持事后溯源 | SQLiteTraceSink 单文件数据库、guardrail 强制 key 完整性、Sufficiency Report 形式化语义充分性 |
| **6** | **可更新 (Updatability / Evolvability)** | 保持底层协议的极度稳定与接口的向后兼容，支持底层算法或模型的无缝热插拔与平滑升级 | 三条设计原则：Factory 装配契约 / Guardrail 合约锁定 / metadata 观测扩展槽 |

#### 可更新性 — 三条设计子原则

**可更新性**是六性质中最不显眼但最承重的一项。它回答"Phase 25 时系统是否仍然健康"。

| 原则 | 说明 | 反例 |
|------|------|------|
| **Factory 装配契约** | 引擎通过可注入工厂函数获取依赖，而非硬编码实例化。切换实现 → 改一行 lambda | `StubOrchestrationEngine()` 硬编码在 planning stub 中（Phase 18 修复） |
| **Contract Locking** | Protocol 签名 + Trace Key 集合 = 合约面。Guardrail 在 AST 级强制执行。内部实现自由重写 | 新增 ad-hoc trace key 绕过 Sufficiency Report 流程 |
| **metadata 扩展槽** | `metadata: Mapping[str, Any]` 字段在所有 Context 中。不参与强类型约束，不触发 guardrail，不透传 caller | 引擎开发者因缺调试通道而向核心接口添加临时字段 |

#### 六性质合规矩阵（按 Phase 追踪）

| Phase | 高效 | 全透明 | 安全隔离 | 冗余性 | 可审计 | 可更新 |
|-------|------|--------|---------|--------|--------|--------|
| Phase 14 (Stub 编排) | — | 6 orchestration keys | stub try/except | Stub 单一实现 | SQLiteTraceSink | — |
| Phase 15 (Stub 规划) | — | 5 planning keys + agent.identity | — | Stub 单一实现 | Sufficiency Report v1 | — |
| Phase 16 (混沌注入) | FailureInjectionConfig 确定性 | retry_count/resource_pool_key 真实语义 | 混沌隔离在 stub 内部 | 3 引擎共存 | Sufficiency Report v2 (6/6) | — |
| Phase 17 (真实规划) | GenerationAdapter 复用 | cumulative_tokens 追踪 | MockLLMBackend 确定性 CI | Stub + LLM 双实现 | Sufficiency Report v3 (trace 等价) | @property engine 零 breakage API 演进 |
| Phase 18 (真实编排+评判) | LLM routing 替代硬编码、deadline | DependencyCallTrace 每次调用 | try/except → error terminal | Factory DI、stub+LLM 共存 | Sufficiency Report v4 | Factory 装配契约、Contract Locking、metadata 扩展槽 |
| Phase 19 (Pipeline Composition) | lazy resolve, 零反射 health_check | CompositionEvent + event_sink + correlation_id | Router 纯函数 + Assembler 异常隔离 | Registry 发现, USB 热插拔 | blueprint_fingerprint + audit_manifest + rule_id 血缘 | validate_params trait 预留, Python→Rust 映射表 |
| Phase 19.5 (Contract-Aware Events) | — | ContractAwareEventSink 结构化存储 + 查询 | 死锁/truthiness trap 修复 | 违约分类, sink 可查询 | violation_count, violations_by_type, summary | _classify_violation 四种契约违约类别 |
| Phase 20 (Contract Health) | — | ContractHealthReport 结构化自省 | 违约严重度可配置映射 | SeverityMapping 注入, 纯函数评估器 | compliance_rate, trend, dominant_violation | ContractViolation StrEnum, 严重度梯度 |
| Phase 20+ (未来) | — | — | — | — | — | 三项原则持续承载 |

### 二、四轴演化方向 (Four Axes)

系统的功能扩展必须严格遵循分层架构，**禁止跨层实现**。未来的技术债偿还与新特性开发，围绕以下四个正交的轴进行：

```
        引擎轴 (Engine Axis)
        ───────────────────
        Planning ──→ Orchestration ──→ Critic ──→ Memory ──→ (未来: Learner, Executor, ...)
        │             │                  │
        │ Protocol 复用性 — 添加第 N+1 个引擎只需 identity + stub/llm + guardrail
        │
        │   编排轴 (Orchestration Axis)
        │   ──────────────────────────
        │   Agent 协作协议 ──→ DAG 路由 ──→ 并行合并 ──→ 重试/退避 ──→ 多池路由
        │   │
        │   │  观测轴 (Observability Axis)
        │   │  ───────────────────────────
        │   │  Trace Keys (18) ──→ SQLiteSink ──→ Guardrails (16) ──→ Sufficiency Reports ──→ 监控看板
        │   │  │
        │   │  │  组件轴 (Component Axis)
        │   │  │  ──────────────────────────
        │   │  │  Tools/Skills ──→ API 接入 ──→ 数据源连接器 ──→ 标准化封装
        │   │  │  │
        ▼   ▼  ▼  ▼
```

| 轴线 | 定义 | 深化方式 | 当前状态 |
|------|------|----------|---------|
| **引擎轴 (Engines Axis)** | Planning、Critic、Memory 等具体 AI 大脑的实现、Prompt 工程与模型适配 | 新增引擎类型，验证 Protocol 不退化 | 3 引擎（Planning, Orchestration, Critic），3 套 Protocol |
| **编排轴 (Orchestration Axis)** | Agent 间协作协议、DAG 路由、重试策略与合并逻辑（**当前核心战场**） | 增大并行度、引入更多 merge strategy、真实 LLM 故障替换混沌注入 | 2 分支 WAIT_ALL 合并、指数退避重试、cpu/gpu 双池 |
| **观测轴 (Observability Axis)** | Trace Key 定义、Sink 存储、Guardrails 拦截规则与监控看板 | 不增 key 数量，深化现有 key 的语义价值。每个 Phase 产出 Sufficiency Report | 18 keys、SQLite Sink、16 guardrails、3 份 Sufficiency Reports |
| **组件轴 (Components Axis)** | 外部工具链（Tools/Skills）、API 接入、数据源连接器的标准化封装 | 新增组件类型，遵循 frozen dataclass + Protocol 约定 | 4 组件类型、3 component_candidate keys |

### 三、轴线隔离原则与架构红线

**四轴隔离：**

- **引擎轴深化不能修改组件轴的数据模型** — 引擎只认 Protocol，不认 Chunk/ContentBlock
- **编排轴深化不能新增 Trace Key（观测轴）** — 现有 18 keys 语义必须充分；不充分 → Sufficiency Report 标记 → 下一 Phase 修复
- **观测轴深化不能触碰引擎内部实现** — guardrail 只校验合约面（Protocol 签名 + Key 集合），不检查内部逻辑
- **组件轴深化不能依赖引擎轴** — 组件契约是纯数据，可以被任何引擎消费

**架构红线 (Architecture Red Lines)：**

> **严禁使用低层级能力去弥补高层级的缺陷。**
>
> - 不准用引擎层的死循环重试来掩盖组件层的接口不稳定
> - 不准用中间服务层（如 Memory）的缓存来补偿引擎层的性能缺陷
> - 不准将应用层业务逻辑下沉到引擎层硬编码
>
> **各层必须恪守边界，独立演进。** 如果某次变更同时触碰 ≥2 条轴线 → 架构退化信号 → 退回重新设计。

---

## 架构决策

组件平台和引擎平台各自独立演进，互不依赖。两者之间通过一个**薄转译层**连通。三种契约的分工：

| 契约类型 | 归属 | 职责 |
|----------|------|------|
| 组件内部契约 | 组件平台 (`core/contracts/`) | 领域数据模型、Strategy Protocol、命名空间注册表、域内校验 |
| 引擎内部契约 | 引擎平台 (`core/pipeline/`) | Step/Pipeline 配置、统一步骤接口、ResourceContainer、TraceLog、调度/熔断/超时 |
| 跨平台转译契约 | 转译层 (`core/adapters/`) | 把任意组件包装成引擎认识的统一接口。严格、机械、无业务逻辑 |

**核心约束：**
- 引擎完全不知道 chunker/retriever/tool 的区别，只认 `run(inputs, resources) -> StepOutput`
- 适配器不做隐式类型转换——输入不合法就报错，不猜测意图
- 转译层发现自己在写判断/补全逻辑 → 说明某一侧平台契约没定好 → 退回修平台

---

## 构建顺序

```
Phase 1: core/contracts/     ← 先建（纯数据，最安全）
Phase 2: core/pipeline/      ← 再建（通用引擎，不感知组件）
Phase 3: core/adapters/      ← 最后（薄胶水，连接两者）
Phase 4: 端到端验证 + 负面用例
```

---

## Phase 1: 组件平台 (`core/contracts/`)

### 文件结构

```
core/contracts/
  __init__.py              # 导出 + 自注册 IdentityChunker
  chunking.py              # ContentBlock, Chunk, ChunkingStrategy (Protocol)
  validation.py            # ValidationError, ContractValidationResult, validate_chunk_output
  registry.py              # ComponentRegistry, COMPONENT_REGISTRY, register_component, validate_pipeline_steps
  identity_chunker.py      # IdentityChunker
```

### 1a. `chunking.py` — 数据模型 + 策略协议

```python
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, ClassVar, Dict, List, Optional, Protocol, Set, Tuple
from copy import deepcopy

@dataclass(frozen=True)
class ContentBlock:
    text: str
    source: str
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    @classmethod
    def from_dict(cls, text: str, source: str, metadata: Dict[str, Any] | None = None):
        # 深拷贝防御：外部后续修改原始 dict 不影响 ContentBlock
        return cls(text=text, source=source,
                   metadata=MappingProxyType(deepcopy(metadata or {})))

@dataclass(frozen=True)
class Chunk:
    text: str
    metadata: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    source_strategy: str = ""
    span: Tuple[int, int] = field(default_factory=lambda: (0, 0))

    def __post_init__(self):
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, 'metadata',
                              MappingProxyType(deepcopy(dict(self.metadata))))

    def with_metadata(self, **kwargs) -> "Chunk":
        new_meta = dict(self.metadata)
        new_meta.update(kwargs)
        return Chunk(text=self.text, metadata=MappingProxyType(new_meta),
                     source_strategy=self.source_strategy, span=self.span)


@dataclass(frozen=True)
class SemVer:
    """
    语义化版本对象，严格三段式（X.Y.Z），支持 pre-release 和 build metadata。
    拒绝宽松解析：'1' 或 '1.0' 直接抛 ValueError，无隐式转换。
    """
    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    _PATTERN: ClassVar[re.Pattern] = re.compile(
        r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
        r"(?:-(?P<prerelease>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?"
        r"(?:\+(?P<build>[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*))?$"
    )

    @classmethod
    def parse(cls, version_str: str) -> "SemVer":
        m = cls._PATTERN.match(version_str.strip())
        if not m:
            raise ValueError(
                f"Invalid SemVer: '{version_str}'. "
                f"Must be 'X.Y.Z' (e.g., '1.0.0'), "
                f"optionally with pre-release (-alpha.1) or build (+20240101)."
            )
        return cls(
            major=int(m.group("major")),
            minor=int(m.group("minor")),
            patch=int(m.group("patch")),
            prerelease=m.group("prerelease"),
            build=m.group("build"),
        )

    def __str__(self) -> str:
        s = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            s += f"-{self.prerelease}"
        if self.build:
            s += f"+{self.build}"
        return s

    def __ge__(self, other: "SemVer") -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease or "") >= \
               (other.major, other.minor, other.patch, other.prerelease or "")

    def __lt__(self, other: "SemVer") -> bool:
        if not isinstance(other, SemVer):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease or "") < \
               (other.major, other.minor, other.patch, other.prerelease or "")


class ChunkingStrategy(Protocol):
    VERSION: ClassVar[SemVer]

    def chunk(self, content: ContentBlock) -> List["Chunk"]: ...

    def validate_config(self, config: dict) -> None: ...

    requires_metadata: ClassVar[Set[str]]
    provides_metadata: ClassVar[Set[str]]
```

关键点：
- `ContentBlock.from_dict()` 使用 `deepcopy` 防御外部 dict 修改
- `Chunk.__post_init__` 同样使用 `deepcopy`
- `VERSION` 为严格三段式 `SemVer`，`parse("1")` 抛 ValueError
- Strategy 仍是 Protocol，不强制继承
- **外部依赖通过 `__init__` 注入工厂函数**（如 `tokenizer_factory: Callable[[], Tokenizer]`），Strategy 内部惰性初始化。`chunk(content)` 签名不变，策略不持有资源只持有"创建资源的函数"

### 1b. `validation.py` — 结构化校验

```python
from dataclasses import dataclass, field
from typing import List

@dataclass(frozen=True)
class ValidationError:
    """结构化校验错误，支持三级严重度。"""
    field: str
    code: str
    message: str
    level: Literal["error", "warning", "info"] = "error"  # error=阻断, warning=记录但继续, info=仅审计

@dataclass
class ContractValidationResult:
    passed: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)
    chunk_count: int = 0
    total_chars: int = 0


def validate_chunk_output(chunks: List["Chunk"]) -> ContractValidationResult:
    """
    运行时校验 chunking 输出。
    检查：类型正确、无空文本、span 合法性、无反向 span、策略一致性、重叠告警。
    返回结构化结果，供引擎 TraceLog 记录。
    """
    errors: List[ValidationError] = []
    warnings: List[ValidationError] = []

    if not isinstance(chunks, list):
        return ContractValidationResult(
            passed=False,
            errors=[ValidationError(field="output", code="NOT_A_LIST",
                     message=f"Expected list, got {type(chunks).__name__}")],
        )

    strategies_seen: set = set()
    spans: List[Tuple[int, int]] = []

    for i, item in enumerate(chunks):
        if not isinstance(item, Chunk):
            errors.append(ValidationError(
                field=f"chunks[{i}]", code="TYPE_MISMATCH",
                message=f"Expected Chunk, got {type(item).__name__}",
            ))
            continue

        if not item.text or not item.text.strip():
            errors.append(ValidationError(
                field=f"chunks[{i}].text", code="EMPTY_TEXT",
                message="Chunk text is empty or whitespace-only",
            ))

        start, end = item.span
        if start < 0:
            errors.append(ValidationError(
                field=f"chunks[{i}].span.start", code="NEGATIVE_SPAN",
                message=f"Span start is negative: {start}",
            ))
        if end < start:
            errors.append(ValidationError(
                field=f"chunks[{i}].span", code="INVERTED_SPAN",
                message=f"Span inverted: ({start}, {end})",
            ))
        if start == end and len(item.text) > 0:
            errors.append(ValidationError(
                field=f"chunks[{i}].span", code="ZERO_SPAN_WITH_TEXT",
                message=f"Zero-length span but text is non-empty",
            ))

        spans.append((start, end))
        strategies_seen.add(item.source_strategy)

    if len(strategies_seen) > 1:
        warnings.append(ValidationError(
            field="chunks[*].source_strategy", code="MULTIPLE_STRATEGIES",
            message=f"Chunks from multiple strategies: {strategies_seen}",
        ))

    sorted_spans = sorted(spans, key=lambda s: s[0])
    for j in range(len(sorted_spans) - 1):
        if sorted_spans[j][1] > sorted_spans[j + 1][0]:
            warnings.append(ValidationError(
                field=f"chunks[{j}].span", code="OVERLAPPING_SPANS",
                message=f"Overlap: {sorted_spans[j]} and {sorted_spans[j+1]}",
            ))
            break

    return ContractValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        chunk_count=len(chunks),
        total_chars=sum(len(c.text) for c in chunks if isinstance(c, Chunk)),
    )
```

### 1c. `registry.py` — 统一组件注册表

```python
from typing import Dict, Type, Generic, TypeVar, List, Tuple, Set
from .chunking import SemVer

T = TypeVar("T")

class ComponentRegistry(Generic[T]):
    """
    统一组件注册表：{component_type: {strategy_name: cls}}。
    Chunker、Retriever、Scorer、Tool 等所有组件类型共用同一套注册/查找/校验机制。
    分化的是领域契约（各自 Protocol），统一的是发现机制。
    """

    def __init__(self):
        self._registry: Dict[str, Dict[str, Type[T]]] = {}

    def register(self, component_type: str, name: str, cls: Type[T]) -> None:
        if not hasattr(cls, "VERSION") or not isinstance(cls.VERSION, SemVer):
            raise ValueError(
                f"{cls.__name__}: VERSION must be a SemVer instance"
            )
        if component_type not in self._registry:
            self._registry[component_type] = {}
        self._registry[component_type][name] = cls

    def get(self, component_type: str, name: str) -> Type[T]:
        if component_type not in self._registry:
            raise KeyError(f"Unknown component_type: {component_type}")
        if name not in self._registry[component_type]:
            raise KeyError(
                f"Unknown strategy '{name}' for '{component_type}'. "
                f"Available: {list(self._registry[component_type].keys())}"
            )
        return self._registry[component_type][name]

    def list_types(self) -> List[str]:
        return list(self._registry.keys())

    def list_strategies(self, component_type: str) -> List[str]:
        return list(self._registry.get(component_type, {}).keys())


# 全局单例
COMPONENT_REGISTRY: ComponentRegistry = ComponentRegistry()


def register_component(component_type: str, name: str):
    """通用注册装饰器：@register_component("chunker", "identity")"""
    def decorator(cls: Type) -> Type:
        cls._is_registered_component = True
        COMPONENT_REGISTRY.register(component_type, name, cls)
        return cls
    return decorator


def auto_discover(module_path: str, *, strict: bool = False) -> List[Type]:
    """
    自动扫描目录，加载所有 @register_component 装饰的类。
    非严格模式下扫描失败静默跳过（符合空结果优雅降级原则）。
    """
    import importlib.util
    from pathlib import Path
    components = []
    path = Path(module_path)
    if not path.exists():
        if strict:
            raise FileNotFoundError(f"Component path not found: {module_path}")
        return components
    for file in path.rglob("*.py"):
        spec = importlib.util.spec_from_file_location(file.stem, file)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if getattr(attr, "_is_registered_component", False):
                    components.append(attr)
    return components


def validate_pipeline_steps(steps: List[dict]) -> Tuple[List[str], List[str]]:
    """
    组件平台的静态兼容性校验（纯函数）。

    输入：chunking 步骤配置列表 [{"name":..., "strategy":...}, ...]
    返回：(errors, warnings) — errors 为空则硬约束通过，warnings 为软提示。
    """
    errors: List[str] = []
    warnings: List[str] = []
    last_provides: Set[str] | None = None
    last_version: SemVer | None = None
    last_name: str | None = None

    for step in steps:
        name = step.get("name", "?")
        strategy_name = step.get("strategy", "")

        try:
            cls = COMPONENT_REGISTRY.get("chunker", strategy_name)
        except KeyError:
            errors.append(
                f"Step '{name}': unknown chunking strategy '{strategy_name}'"
            )
            continue

        requires: set = getattr(cls, "requires_metadata", set())
        provides: set = getattr(cls, "provides_metadata", set())
        version: SemVer = cls.VERSION

        if last_provides is not None:
            missing = requires - last_provides
            if missing:
                errors.append(
                    f"Static compatibility error: Step '{name}' ({strategy_name}) "
                    f"requires metadata {missing}, but previous step '{last_name}' "
                    f"only provides {last_provides}."
                )

        if last_version is not None and version.major != last_version.major:
            warnings.append(
                f"Version note: Step '{name}' ({strategy_name}) is v{version}, "
                f"previous step '{last_name}' is v{last_version}. "
                f"Metadata compatibility is the binding constraint; this is advisory only."
            )

        last_provides = provides
        last_version = version
        last_name = name

    return errors, warnings
```

**新增策略 = 一个文件 + 一行 `@register_component("chunker", "fixed")`**

### 1d. `identity_chunker.py`

```python
from typing import ClassVar, List, Set
from .chunking import Chunk, ContentBlock, SemVer

@register_component("chunker", "identity")
class IdentityChunker:
    VERSION: ClassVar[SemVer] = SemVer(1, 0, 0)
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = set()

    def chunk(self, content: ContentBlock) -> List[Chunk]:
        return [Chunk(text=content.text, metadata=content.metadata,
                      source_strategy="chunking.identity", span=(0, len(content.text)))]

    def validate_config(self, config: dict) -> None:
        if config:
            raise ValueError(f"IdentityChunker takes no config, got: {list(config.keys())}")
```

### Phase 1 验收

- [ ] `ContentBlock.from_dict("hi", "s", {"k":"v"})` → 修改原始 dict → ContentBlock.metadata 不受影响
- [ ] `Chunk(text="x", source_strategy="test", span=(0,1))` → 属性赋值 → FrozenInstanceError
- [ ] `chunk.metadata["k"] = "v"` → TypeError
- [ ] `IdentityChunker().chunk(ContentBlock("hi", "test"))` → 1 个 Chunk, source_strategy="chunking.identity"
- [ ] `register_component("chunker", "bad")(object())` → ValueError（缺少 VERSION/SemVer）
- [ ] `validate_pipeline_steps([...])` → (errors, warnings) tuple；metadata 不匹配 → errors 非空；major version 差异 → warnings 非空
- [ ] `ContractValidationResult.errors[0]` 是 `ValidationError` 实例，含 field/code/message

---

## Phase 2: 引擎平台 (`core/pipeline/`)

引擎平台**不 import core.contracts**。

### 文件结构

```
core/pipeline/
  __init__.py              # 导出
  engine.py                # PipelineRunner, StepConfig, PipelineConfig, PipelineStep, StepOutput
  resources.py             # ResourceContainer
  tracing.py               # StepTrace, TraceLog, SnapshotPolicy, TraceWriter, LocalJSONWriter, serialize_tracelog
  config_loader.py         # load_pipeline_config, dump_pipeline_config (YAML ↔ StepConfig)
```

### 2a. `resources.py` — 资源容器（替代裸 dict）

```python
from contextlib import contextmanager
from threading import Lock
from typing import Any, Dict, Optional

class ResourceContainer:
    """
    引擎统一管理的资源容器，替代裸 Dict[str, Any]。

    生命周期语义（明确分离，避免双重释放）：
      - scoped(): 纯 with 块语义，退出时立即释放。不注册到全局生命周期。
      - 跨步骤存活的资源：通过 set_config()/set_state() 显式注册，
        由引擎在 pipeline 结束后统一 close()。
      - scoped() 和 close() 管理的资源永不重叠——每个资源只有一条释放路径。
    """

    def __init__(self):
        self._config: Dict[str, Any] = {}      # 配置型：初始化后不可变
        self._state: Dict[str, Any] = {}        # 状态型：需锁保护
        self._lock = Lock()
        self._managed: Dict[str, Any] = {}       # 由 close() 统一清理的长期资源
        self._closed = False

    def set_config(self, key: str, value: Any) -> None:
        if self._closed:
            raise RuntimeError("ResourceContainer is closed")
        self._config[key] = value

    def set_state(self, key: str, value: Any) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("ResourceContainer is closed")
            self._state[key] = value

    def get(self, key: str) -> Any:
        """只读访问（config 优先于 state）。"""
        if key in self._config:
            return self._config[key]
        return self._state.get(key)

    def register_managed(self, key: str, resource: Any) -> None:
        """注册需要跨步骤存活的资源，由 close() 统一释放。"""
        self._managed[key] = resource

    @contextmanager
    def scoped(self, factory: callable, **kwargs):
        """
        纯 with 块语义：退出时立即释放，不注册到容器全局生命周期。
        用法：with resources.scoped(create_llm_client, model="qwen") as client: ...
        资源清理路径唯一——只在 finally 块中执行，close() 不会再次触碰。
        """
        resource = factory(**kwargs)
        try:
            yield resource
        finally:
            _safe_close(resource)

    def close(self):
        """释放所有 register_managed 注册的长期资源。不触及 scoped 资源。"""
        self._closed = True
        for resource in self._managed.values():
            _safe_close(resource)
        self._managed.clear()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _safe_close(resource: Any) -> None:
    """安全关闭资源。优先 close()，其次 __exit__()。只调用一个，不双重释放。"""
    closer = getattr(resource, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass
        return

    exiter = getattr(resource, "__exit__", None)
    if callable(exiter):
        try:
            exiter(None, None, None)
        except Exception:
            pass
```

### 2b. `engine.py` — 编排引擎

```python
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol, Tuple

from .resources import ResourceContainer
from .tracing import StepTrace, TraceLog, SnapshotPolicy


class PipelineStep(Protocol):
    """引擎对一切组件的统一步骤接口。"""

    def run(self, inputs: Dict[str, Any], resources: ResourceContainer) -> "StepOutput":
        """同步执行。v1 所有组件均实现此方法。"""
        ...

    async def async_run(self, inputs: Dict[str, Any], resources: ResourceContainer) -> "StepOutput":
        """异步执行（可选）。引擎优先使用此方法，不存在时回退 run()。"""
        ...

    def health_check(self) -> "HealthStatus":
        """健康检查（可选）。引擎在 init 时批量调用，汇总全局健康视图。"""
        ...


@dataclass
class HealthStatus:
    status: Literal["healthy", "degraded", "unavailable"]
    message: str = ""
    details: Optional[Dict[str, Any]] = None


@dataclass
class StepOutput:
    """组件 run() 的标准返回值。"""
    result: Any                             # v1 主输出（非流式）
    stream: Optional[Iterator[Any]] = None   # v2 预留：流式输出，v1 忽略
    trace_log: Dict[str, Any] = field(default_factory=dict)
    contract_validation: Any = None          # 引擎不解析，透传到 TraceLog


@dataclass
class RetryPolicy:
    """步骤重试策略。max_retries=0 表示不重试（默认）。"""
    max_retries: int = 0
    backoff: Literal["none", "exponential"] = "exponential"
    retry_on: List[str] = field(default_factory=lambda: ["TimeoutError", "ConnectionError"])


@dataclass
class StepConfig:
    name: str
    component_type: str
    strategy: str
    version: Optional[SemVer] = None         # 组件的 SemVer 版本约束
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    provides: str = ""
    on_failure: Literal["abort", "skip", "default"] = "abort"
    default_value: Any = None
    timeout_seconds: Optional[float] = None
    output_type: Optional[str] = None
    retry_policy: Optional[RetryPolicy] = None  # None = 不重试
    sub_pipeline: Optional[str] = None           # 嵌套子 Pipeline 名称
    input_mapping: Optional[Dict[str, str]] = None  # {from: "upstream_key", to: "param_name"} 引擎层路由


@dataclass
class PipelineConfig:
    steps: List[StepConfig]
    pipeline_version: int = 1
    default_timeout_seconds: float = 300.0  # 步骤未指定超时时的默认值


class PipelineRunner:
    """
    业务无关的通用编排引擎。
    不认识 chunker/retriever/tool，只认 PipelineStep 协议。
    """

    def __init__(
        self,
        config: PipelineConfig,
        step_factories: Dict[str, Callable[[StepConfig], PipelineStep]],
        snapshot_policy: SnapshotPolicy = SnapshotPolicy.SUMMARY,
        type_compatibility_checker: Optional[Callable[[StepConfig, StepConfig], List[str]]] = None,
        initial_keys: Optional[Set[str]] = None,
        trace_writer: Optional[TraceWriter] = None,
    ):
        self.config = config
        self._factories = step_factories
        self._snapshot_policy = snapshot_policy
        self._type_checker = type_compatibility_checker
        self._trace_writer = trace_writer
        self._initial_keys: Set[str] = set(initial_keys or []) | {"original_query"}
        self._validate_structure()

    def _validate_structure(self) -> None:
        """
        静态校验 Pipeline 结构：
          1. 无循环依赖（depends_on 只引用已声明的 provides 或 initial_keys）
          2. 每个 depends_on key 要么被前面的步骤 provide，要么在 initial_keys 中
          3. 可选：调用 type_compatibility_checker 验证跨步骤类型兼容
        错误时抛出 PipelineStartupError。
        """
        errors: List[str] = []
        provided_keys: Dict[str, int] = {}  # key -> step_index that provides it

        for i, step in enumerate(self.config.steps):
            if not step.provides:
                continue
            if step.provides in provided_keys:
                errors.append(
                    f"Step '{step.name}' provides key '{step.provides}' "
                    f"already provided by step {provided_keys[step.provides]}"
                )
            provided_keys[step.provides] = i

        for i, step in enumerate(self.config.steps):
            for dep in step.depends_on:
                if dep in self._initial_keys:
                    continue
                if dep not in provided_keys:
                    errors.append(
                        f"Step '{step.name}' depends on '{dep}', "
                        f"but no previous step provides it and it is not "
                        f"in initial_keys ({list(self._initial_keys)})."
                    )
                    continue
                provider_idx = provided_keys[dep]
                if provider_idx >= i:
                    errors.append(
                        f"Step '{step.name}' depends on '{dep}' from "
                        f"step {provider_idx}, but it runs at index {i} (must be earlier)."
                    )
                    continue

        if errors:
            raise PipelineStartupError(
                f"Pipeline structure validation failed:\n" +
                "\n".join(f"  - {e}" for e in errors)
            )

    def _propagate_skip(
        self,
        failed_step: StepConfig,
        failed_idx: int,
        traces: List[StepTrace],
    ) -> None:
        """
        级联跳过：当前步骤 on_failure="skip" 时，遍历后续所有步骤，
        将 depends_on 包含 failed_step.provides 的步骤标记为 skipped。
        如果被跳过的步骤又提供了其他 key，递归传播。
        """
        skipped_key = failed_step.provides
        for future_step in self.config.steps[failed_idx + 1:]:
            if skipped_key in future_step.depends_on:
                # 这个步骤依赖了已跳过步骤的输出 → 标记跳过
                pass  # 在 run() 循环中通过检查 state 中的 None 来实现
        # 注意：实际标记在 run() 主循环中完成。
        # 此方法的核心是将 failed_step.provides 对应的 state 值设为
        # 一个特殊哨兵 _SKIP_SENTINEL，后续步骤在构建 input_dict 时
        # 检测到哨兵则自动 skip。

    def run(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
        on_step: Optional[Callable[[StepTrace], None]] = None,
    ) -> Tuple[Dict[str, Any], TraceLog]:
        """同步入口：内部用 asyncio.run() 封装异步引擎，对调用方透明。"""
        import asyncio
        return asyncio.run(self.arun(initial_state, resources, on_step))

    async def arun(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
        on_step: Optional[Callable[[StepTrace], None]] = None,
    ) -> Tuple[Dict[str, Any], TraceLog]:
        """
        异步入口：引擎核心。检测 step 是否有 async_run 方法，
        有则 await，无则同步调用 run()。未来服务化（FastAPI/gRPC）直接使用此方法。
        """
        pipeline_run_id = str(uuid.uuid4())
        # ... 异步执行循环（见下方详细逻辑）
```

**arun() 核心循环逻辑（async，支持重试 + step 自适应 dispatch）：**

```python
_SKIP_SENTINEL = object()

pipeline_run_id = uuid4()
state = dict(initial_state or {})
resources = resources or ResourceContainer()
traces = []

async with resources:
    for idx, step in enumerate(config.steps):
        step_trace = StepTrace(
            step_index=idx, step_name=step.name,
            pipeline_run_id=pipeline_run_id,
            snapshot_policy=self._snapshot_policy,
            ...
        )

        if any(state.get(dep) is _SKIP_SENTINEL for dep in step.depends_on):
            step_trace.status = "skipped"
            if step.provides:
                state[step.provides] = _SKIP_SENTINEL
            step_trace.finished_at = time.perf_counter()
            step_trace.duration_seconds = 0.0
            traces.append(step_trace)
            continue

        input_dict = {key: state.get(key) for key in step.depends_on}
        timeout = step.timeout_seconds or config.default_timeout_seconds
        retry = step.retry_policy

        try:
            component = self._factories[step.name](step)
            output = await _execute_with_retry(component, input_dict, resources, timeout, retry)
            state[step.provides] = output.result
            step_trace.status = "success"
            step_trace.output_snapshot = snapshot(output.result, self._snapshot_policy)

        except TimeoutError:
            step_trace.status = "failed"
            step_trace.error_type = "TimeoutError"
            step_trace.error_message = f"Step exceeded {timeout}s"
            self._apply_failure(step, state, step_trace)

        except Exception as exc:
            step_trace.status = "failed"
            step_trace.error_type = type(exc).__name__
            step_trace.error_message = str(exc)
            step_trace.error_traceback = traceback.format_exc()
            self._apply_failure(step, state, step_trace)

        step_trace.finished_at = time.perf_counter()
        step_trace.duration_seconds = step_trace.finished_at - step_trace.started_at
        traces.append(step_trace)

    if self._trace_writer:
        self._trace_writer.write(traces)

return state, TraceLog(pipeline_run_id=pipeline_run_id, steps=traces, ...)


async def _execute_with_retry(component, inputs, resources, timeout, retry):
    """引擎内部：带重试的步骤执行，含超时控制。"""
    max_retries = retry.max_retries if retry else 0
    for attempt in range(max_retries + 1):
        try:
            return await _dispatch(component, inputs, resources, timeout)
        except Exception as e:
            if attempt == max_retries:
                raise
            retry_on = retry.retry_on if retry else []
            if not any(e.__class__.__name__ == name for name in retry_on):
                raise
            if retry and retry.backoff == "exponential":
                await asyncio.sleep(0.5 * (2 ** attempt))
    raise RuntimeError("Unreachable")


async def _dispatch(component, inputs, resources, timeout):
    """
    自适应 dispatch：优先 async_run，回退到 run()。
    超时控制用 asyncio.wait_for 包裹。
    """
    if hasattr(component, "async_run") and callable(component.async_run):
        coro = component.async_run(inputs, resources)
    else:
        coro = asyncio.to_thread(component.run, inputs, resources)
    return await asyncio.wait_for(coro, timeout=timeout)
```

关键机制：
- **双模式执行**：`run()` 同步入口内部用 `asyncio.run()` 封装；`arun()` 异步入口供未来服务化使用。核心引擎只有一套异步逻辑
- **自适应 dispatch**：引擎检测 `async_run` 存在则 await，否则用 `asyncio.to_thread` 包裹 `run()`。同步组件和异步组件可在同一 pipeline 中混合使用
- **内置重试**：`RetryPolicy` 控制 max_retries + exponential backoff + retry_on 异常类型过滤。默认不重试（max_retries=0）
- **循环依赖检测**：DAG 校验已覆盖（depends_on 引用的 key 必须在之前步骤 provides，线性执行无环可能）
- **超时控制**：`asyncio.wait_for` 包裹步骤执行，超时触发 TimeoutError
- **on_failure** 三种策略：abort / skip（_SKIP_SENTINEL 传播）/ default
- **finished_at 必记录**：即使步骤失败，保证 TraceLog 完整性
- **错误聚合**：静态校验全量收集所有错误后一次性报告，用户一次修复所有问题
- **Pipeline 嵌套**：`StepConfig.sub_pipeline` 字段支持将一个 Pipeline 作为另一个的步骤。子 pipeline 自动继承所有引擎能力（重试/超时/错误收集），输出封装为 StepOutput
- **Step 健康检查**：`health_check() -> HealthStatus` 可选方法，引擎 init 时批量调用并汇总全局健康视图。未实现时默认 healthy。支撑 K8s readiness probe 和 CI/CD 部署门禁
- **优雅取消**：`on_step` 回调可返回 `True` 请求取消。引擎在当前步骤完成后停止后续，剩余步骤标记为 `cancelled`。不在步骤中途强杀，保证执行原子性
- **环境变量解析**：`StepConfig.params` 中的字符串值支持 `${ENV_VAR}` 和 `${ENV_VAR:-default}` 语法。引擎加载时自动解析，未找到且无 fallback 时抛 ConfigurationError。非 params 字段（name/strategy 等）不参与插值。自动脱敏日志中的敏感值
- **input_mapping 路由**：引擎在调用 step 前自动将上游输出按 `{from: "upstream_key", to: "param_name"}` 重映射。适配器只接收自己声明的参数名，完全不知晓数据来源
- **空结果自动 skip**：chunker 返回 `[]` 时引擎自动标记为 skipped 并传播，下游依赖步骤自动跳过。空列表是合法业务信号，不是错误

### 2c. `tracing.py` — Trace/Snapshot

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
import hashlib


class SnapshotPolicy(Enum):
    FULL = "full"        # 完整序列化（调试模式）
    SUMMARY = "summary"  # 仅长度 + hash + 前 N 字符
    NONE = "none"        # 不记录


def snapshot(value: Any, policy: SnapshotPolicy) -> Any:
    """根据策略生成值的快照。"""
    if policy == SnapshotPolicy.NONE:
        return None
    if policy == SnapshotPolicy.FULL:
        return _deep_serializable(value)
    if policy == SnapshotPolicy.SUMMARY:
        return _summarize(value)
    return None


def _summarize(value: Any, preview_chars: int = 200) -> dict:
    """生成摘要：类型、长度、hash、预览。

    Hash 仅用于变更检测，不保证密码学安全性或跨版本稳定性。
    使用 blake2b（比 sha256 快 3-5 倍，且默认 64 字节摘要足够防碰撞）。
    """
    if value is None:
        return {"type": "NoneType", "count": 0}
    if isinstance(value, list):
        # 不序列化列表内容——元素可能是大对象，str() 代价高且输出不稳定
        # 仅基于结构特征做轻量 fingerprint
        if len(value) == 0:
            fp = b"empty_list"
        else:
            first_type = type(value[0]).__name__.encode()
            last_type = type(value[-1]).__name__.encode()
            fp = f"{len(value)}:{first_type}:{last_type}".encode()
        return {
            "type": "list",
            "count": len(value),
            "hash": hashlib.blake2b(fp, digest_size=8).hexdigest(),
            "preview": repr(value[:3])[:preview_chars],
        }
    if isinstance(value, str):
        # 限制输入长度避免对大文本做完整 hash
        limited = value[:10000].encode()
        return {
            "type": "str",
            "length": len(value),
            "hash": hashlib.blake2b(limited, digest_size=8).hexdigest(),
            "preview": value[:preview_chars],
        }
    if isinstance(value, dict):
        return {"type": "dict", "keys": list(value.keys())[:20], "count": len(value)}
    return {"type": type(value).__name__, "repr": repr(value)[:preview_chars]}


@dataclass
class StepTrace:
    step_index: int
    step_name: str
    pipeline_run_id: str
    parent_run_id: Optional[str] = None          # 嵌套 pipeline 追踪
    snapshot_policy: SnapshotPolicy = SnapshotPolicy.SUMMARY
    component_type: str = ""
    strategy: str = ""
    status: Literal["pending", "running", "success", "failed", "skipped"] = "pending"
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_seconds: float = 0.0
    input_keys: List[str] = field(default_factory=list)
    input_snapshot: Optional[Dict[str, Any]] = None
    output_key: str = ""
    output_snapshot: Optional[Any] = None
    params: Dict[str, Any] = field(default_factory=dict)
    contract_validation: Optional[Any] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None


@dataclass
class TraceLog:
    pipeline_run_id: str
    parent_run_id: Optional[str] = None
    pipeline_version: int = 1
    started_at_iso: str = ""
    finished_at_iso: str = ""
    total_duration_seconds: float = 0.0
    snapshot_policy: SnapshotPolicy = SnapshotPolicy.SUMMARY
    steps: List[StepTrace] = field(default_factory=list)
    total_steps: int = 0
    success_count: int = 0
    failure_count: int = 0
    skipped_count: int = 0

    def to_dict(self) -> dict:
        ...  # 递归转换 MappingProxyType → dict, Chunk → dict 等


class TraceWriter(Protocol):
    """可插拔 TraceLog 写入器。默认本地 JSON，可扩展 Kafka/S3/DB 等。"""
    def write(self, traces: List[TraceLog]) -> None: ...


class LocalJSONWriter:
    """默认实现：追加写到本地 JSON 文件。"""
    def __init__(self, path: str):
        from pathlib import Path
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, traces: List[TraceLog]) -> None:
        import json
        data = [t.to_dict() for t in traces]
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, separators=(",", ":")) + "\n")


def serialize_tracelog(trace_log: TraceLog, format: str = "json") -> str | bytes:
    """
    序列化 TraceLog。默认 JSON（人类可读），支持 msgpack（生产高性能）。
    to_dict() 是核心抽象，序列化格式是其下游编码策略，完全解耦。
    """
    data = trace_log.to_dict()

    if format == "json":
        import json
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    if format == "msgpack":
        import msgpack
        from datetime import datetime
        from uuid import UUID

        def _default(obj):
            if isinstance(obj, (datetime, UUID)):
                return str(obj)
            raise TypeError(f"Unsupported type: {type(obj)}")

        return msgpack.dumps(data, default=_default, use_bin_type=True)

    raise ValueError(f"Unknown format: {format}. Use 'json' or 'msgpack'.")
```

### 2d. `config_loader.py` — YAML ↔ StepConfig 双向转换

```python
import yaml
from dataclasses import asdict
from typing import List, Union
from pathlib import Path

def load_pipeline_config(source: Union[str, Path, dict]) -> List[StepConfig]:
    """
    从 YAML 文件或 dict 加载 pipeline 配置，返回 StepConfig 列表。
    内部用 StepConfig(**raw) 做运行时校验——错误在加载时暴露。
    """
    if isinstance(source, dict):
        raw = source
    else:
        with open(source, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

    steps = []
    for step_data in raw.get("steps", raw if isinstance(raw, list) else []):
        version_str = step_data.pop("version", "1.0.0")
        step_data["version"] = SemVer.parse(version_str)
        steps.append(StepConfig(**step_data))
    return steps


def dump_pipeline_config(steps: List[StepConfig], path: Union[str, Path] | None = None) -> str:
    """将 StepConfig 列表导出为 YAML 字符串，可选写入文件。"""
    raw = [asdict(step) for step in steps]
    for item, step in zip(raw, steps):
        item["version"] = str(step.version)
    output = yaml.dump(raw, sort_keys=False, indent=2, allow_unicode=True)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(output)
    return output
```

**使用示例：**
```yaml
# pipeline.yaml
steps:
  - name: chunk_docs
    component_type: chunker
    strategy: identity
    version: "1.0.0"
    params: {}
    depends_on: ["document"]
    provides: "chunks"
```

```python
steps = load_pipeline_config("pipeline.yaml")
runner = PipelineRunner(PipelineConfig(steps=steps), ...)
```

### Phase 2 验收

- [ ] 空 pipeline（`steps=[]`）正常返回 initial_state + 空 TraceLog
- [ ] DAG 依赖缺失时 `__init__` 抛出 PipelineStartupError
- [ ] A→B→A 循环结构被检测到（depends_on 引用当前步骤自己的 provides）
- [ ] 某步骤超时 → TimeoutError → on_failure="abort" → 后续收到 None
- [ ] on_failure="skip" → 依赖此 key 的步骤自动 skip
- [ ] on_failure="default" → 填充 default_value
- [ ] 步骤失败后 `finished_at` 仍正确记录
- [ ] `SnapshotPolicy.SUMMARY` 不输出完整 Chunk 列表，只输出 count/hash/preview
- [ ] `resources.scoped("test", lambda **kw: SomeResource(), ...)` 自动 close
- [ ] `ResourceContainer` 作为 context manager 正常释放

---

## Phase 3: 转译层 (`core/adapters/`)

### 文件结构

```
core/adapters/
  __init__.py              # re-export
  chunker_adapter.py       # ChunkerAdapter: ChunkingStrategy → PipelineStep
  factory.py               # create_step_factory: 唯一的路由入口
```

### 3a. `chunker_adapter.py` — 严格转译

```python
from core.contracts import ChunkingStrategy, ContentBlock, validate_chunk_output
from core.pipeline.engine import PipelineStep, StepOutput, ResourceContainer
from typing import Any, Dict


class AdapterTypeError(Exception):
    """转译层类型不匹配错误。严格模式：输入不合法就报错，不做猜测。"""
    pass


class ChunkerAdapter:
    """
    把 ChunkingStrategy 包装成 PipelineStep。
    严格转译：ContentBlock 类型不匹配 → AdapterTypeError。
    超时由引擎 StepConfig.timeout_seconds + _run_with_timeout 控制，适配器不关心。
    """

    def __init__(self, strategy: ChunkingStrategy, content_key: str | None = None):
        self._strategy = strategy
        self._content_key = content_key  # None = 取 inputs 第一个值

    def run(self, inputs: Dict[str, Any], resources: ResourceContainer) -> StepOutput:
        # 提取 ContentBlock
        if self._content_key:
            if self._content_key not in inputs:
                raise AdapterTypeError(
                    f"Expected key '{self._content_key}' in inputs, "
                    f"but only have {list(inputs.keys())}"
                )
            content = inputs[self._content_key]
        else:
            content = next(iter(inputs.values()))

        if not isinstance(content, ContentBlock):
            raise AdapterTypeError(
                f"Expected ContentBlock, got {type(content).__name__}. "
                f"Value: {repr(content)[:200]}"
            )

        # 调用策略
        chunks = self._strategy.chunk(content)
        validation = validate_chunk_output(chunks)

        return StepOutput(
            result=chunks,
            trace_log={
                "chunker": self._strategy.__class__.__name__,
                "version": str(self._strategy.VERSION),
            },
            contract_validation=validation,
        )
```

关键：**没有隐式类型转换**。不是 ContentBlock → 直接 AdapterTypeError。这是转译层"严格"原则的核心。

### 3b. `factory.py` — 路由工厂（安全参数传递，无 eval）

```python
from functools import lru_cache
from core.contracts import COMPONENT_REGISTRY
from core.pipeline.engine import PipelineStep, StepConfig
from .chunker_adapter import ChunkerAdapter


def _make_cache_key(component_type: str, strategy_name: str, params: Dict[str, Any]) -> tuple:
    """
    生成安全的缓存键。params 转为 tuple(sorted(items())) 保证可哈希。
    绝不使用 eval()/exec() 或任何形式的代码执行。
    """
    return (component_type, strategy_name, tuple(sorted(params.items())))


@lru_cache(maxsize=128)
def _cached_create(cache_key: tuple) -> PipelineStep:
    """
    缓存无状态策略实例。
    cache_key = (component_type, strategy_name, (("key1", val1), ("key2", val2), ...))
    从 cache_key 安全还原参数——只做 dict 构造，不做任何 code execution。

    有状态策略可通过在类上设置 cacheable = False 声明，绕过缓存。
    """
    component_type, strategy_name, params_tuple = cache_key
    params = dict(params_tuple)

    cls = COMPONENT_REGISTRY.get(component_type, strategy_name)
    if not getattr(cls, "cacheable", True):
        raise _UncacheableError(component_type, strategy_name)
    instance = cls(**params)
    return ChunkerAdapter(instance)


class _UncacheableError(Exception):
    """内部信号：该策略不可缓存，请调用方直接创建。"""
    def __init__(self, component_type, strategy_name):
        self.component_type = component_type
        self.strategy_name = strategy_name
        super().__init__(f"Strategy '{strategy_name}' ({component_type}) is not cacheable")


def create_step_factory(step: StepConfig) -> PipelineStep:
    """
    连接两个平台的唯一切入点。路由逻辑仅限于 switch。
    不做业务判断、不做数据补全。
    """
    cache_key = _make_cache_key(step.component_type, step.strategy, step.params)
    try:
        return _cached_create(cache_key)
    except _UncacheableError as e:
        cls = COMPONENT_REGISTRY.get(e.component_type, e.strategy_name)
        instance = cls(**step.params)
        return ChunkerAdapter(instance)
```

转译层代码行数目标：< 100 行（不含注释和空行）。

### Phase 3 验收

- [ ] 向 ChunkerAdapter 传入非 ContentBlock 对象 → AdapterTypeError（非静默转换）
- [ ] 向 ChunkerAdapter 传入 ContentBlock → 正确的 StepOutput + contract_validation
- [ ] `_cached_create` 对相同参数返回同一个实例
- [ ] 转译层不 import 任何与业务策略相关的模块

---

## 端到端验证（所有场景）

| # | 场景 | 验证点 |
|---|------|--------|
| 1 | IdentityChunker 独立执行 | 1 个 Chunk，source_strategy="chunking.identity"，span 正确 |
| 2 | PipelineRunner + IdentityChunker | 引擎发现并执行，state["chunks"] 正确，TraceLog 完整 |
| 3 | 静态兼容性：metadata 不匹配 | validate_pipeline_steps() 返回 errors 非空；版本差异仅 warnings |
| 4 | Chunk 不可变 | FrozenInstanceError + TypeError |
| 5 | ContentBlock 深拷贝防御 | 修改原始 dict → ContentBlock.metadata 不受影响 |
| 6 | validate_chunk_output 捕获违规 | 空文本、反向 span、类型不匹配 → ValidationError 列表 |
| 7 | Circuit breaker 隔离故障 | 失败步骤不更新 state，pipeline 不崩溃 |
| 8 | 空 pipeline | steps=[] → 正常返回 initial_state + 空 TraceLog |
| 9 | 循环依赖检测 | 检测到并报 PipelineStartupError |
| 10 | on_failure="skip" | 级联标记后续步骤为 skipped |
| 11 | on_failure="default" | 填充 default_value |
| 12 | 步骤超时 | TimeoutError，finished_at 仍记录 |
| 13 | 适配器类型不匹配 | 非 ContentBlock → AdapterTypeError |
| 14 | TraceLog 完整性 | 失败步骤含完整 error_traceback + finished_at |
| 15 | SnapshotPolicy.SUMMARY | 不输出完整数据，只输出 count/hash/preview（hash 用 blake2b） |
| 16 | ResourceContainer 生命周期 | scoped 资源在 with 块退出时释放；managed 资源由 close() 统一清理；两者永不重叠 |
| 17 | on_failure="skip" + 多依赖 | 步骤 C depends_on=["a","b"]，A skip 但 B success → C 应 skip（任一依赖缺失即 skip） |
| 18 | ResourceContainer.get() 优先级 | 同 key 同时存在于 config 和 state → 返回 config 值（config 优先） |

---

## 依赖关系（严格遵守）

```
contracts/  ← 不依赖任何内部包
pipeline/   ← 不依赖 contracts/（也不依赖 adapters/）
adapters/   ← 依赖 contracts/ + pipeline/（唯一知道两边存在的包）
```

**决策原则：**
- adapters/ 出现判断/补全/转换以外的逻辑 → 退回 contracts/ 或 pipeline/
- pipeline/ 出现具体类型 import → 退回 adapters/
- contracts/ 依赖 pipeline/ 的任何类型 → 违反独立性，立即停止

---

## 工程规范

- **包管理**：`pyproject.toml` 主配置（构建/工具链） + `requirements.txt` 由 `pip-compile` 自动生成锁定版本。开发改 `.in` 文件，CI 用 `.txt` 部署
- **代码质量**：ruff（lint + format）+ mypy（strict 模式）+ pre-commit hook。pre-commit 阶段阻断类型违规，CI 重复验证
- **组件发现**：显式 `register_component()` 为默认方式 + `auto_discover("core/steps/")` 扫描目录自动加载。开发期用自动发现，生产/测试用显式注册精确控制

---

## 测试策略

采用**集中分层 + fixtures**：

```
tests/
  conformance/              # 契约一致性测试（核心协议验证）
    test_pipeline_step_contract.py
    test_strategy_contract.py
  unit/                     # 单元测试（聚焦边界行为）
  integration/              # 集成测试（v1 重点：pipeline 端到端）
  fixtures/                 # 统一 fixture 库
    models.py               # ContentBlock, Chunk, PipelineConfig 预构建实例
    mocks.py                # HTTP, LLM 模拟工具
    contexts.py             # StepContext, ExecutionContext fixtures
```

**策略：** v1 以集成测试为主（覆盖 pipeline 执行完整路径），契约测试覆盖核心 Protocol（所有 PipelineStep 实现必须通过 `health_check` / `run` 签名校验），单元测试聚焦边界条件（空列表、超时、无效 SemVer）。

**关键契约测试：**
```python
# tests/conformance/test_pipeline_step_contract.py
@pytest.mark.contract
def test_step_health_check_returns_valid_status(step_impl: PipelineStep):
    status = step_impl.health_check()
    assert status.status in ("healthy", "degraded", "unavailable")

@pytest.mark.contract
def test_step_run_returns_step_output(step_impl, sample_content_block):
    output = step_impl.run(inputs={"content": sample_content_block}, resources=ResourceContainer())
    assert isinstance(output, StepOutput)
```

---

## 旧代码迁移策略

采用**渐进迁移**：在 `core/legacy/` 中建适配子包，把旧 `components/` + `prompt/` 组件封装成新协议。

```
core/legacy/
  __init__.py
  adapter.py       # LegacyStepAdapter: 旧组件 → PipelineStep
```

**LegacyStepAdapter** 实现所有 PipelineStep 方法（`run`/`async_run`/`health_check`），内部委托给旧组件。旧代码零修改，通过适配器接入新引擎。引擎无感知——统一调用 `step.run()`。

迁移节奏：
- Phase 1：所有新功能用 `core/steps/` 实现，旧功能走 `legacy/`
- Phase 2：逐步将高频旧模块重写为新 Step，legacy 作 fallback
- Phase 3：移除所有 legacy 依赖，清理包

---

## Phase 4: 可观测性 (`core/pipeline/tracing.py`, `engine.py`)

**完成状态**: ✅ 已完成 (Phase 4)

### 关键交付
- `StepTrace` / `TraceLog` — 步骤级追踪，含 pipeline_run_id、duration、snapshot
- `DependencyCallTrace` / `SpanType` — 外部依赖调用追踪（LLM API、向量数据库）
- `HealthStatus` / `DependencyHealth` — 分级健康检查（healthy/degraded/unavailable）
- `SnapshotPolicy` — 三级快照策略（NONE/SUMMARY/FULL）
- `TraceWriter` — 可插拔的追踪输出接口

### 架构决策
- 引擎层所有类型（StepTrace、TraceLog）不导入 contracts/ 领域类型
- DependencyHealth 作为基础设施类型，连接引擎和适配器层
- 每个外部依赖必须声明 DependencyHealth（链 phase_04_observability）

---

## Phase 5: 外部 I/O 模式 (`core/steps/retriever.py`, `core/adapters/vector_store.py`)

**完成状态**: ✅ 已完成 (Phase 5)

### 关键交付
- `RetrieverStep` — 第一个外部 I/O 组件（向量检索）
- `VectorStoreAdapter` — async wrapper + health_probe + DependencyCallTrace
- `InMemoryVectorBackend` — 余弦相似度内存后端（零外部依赖）
- `RetrievalResult` frozen dataclass（score、rank、chunk）

### 架构决策
- Adapter level 统一封装外部调用：run_in_executor + timeout + trace 注入
- health_check 执行语义探测（search sentinel vector），不依赖虚假返回值
- 空结果 = `StepOutput(result=[])`，不是 sentinel（链 phase_05_external_io）

---

## Phase 7: LLM / Reranker (`core/steps/generator.py`, `core/steps/reranker.py`)

**完成状态**: ✅ 已完成 (Phase 7)

### 关键交付
- `GeneratorStep` + `GenerationAdapter` — LLM 生成，token budget 强制
- `RerankerStep` + `ScoringAdapter` — chunk 重排序，合约强制（输出 ≤ 输入）
- `MockGenerationBackend` / `MockScoringBackend` — 零 API key 测试后端
- `validate_generation_output()` / `validate_reranker_output()` — 运行时合约校验
- 7 个预定义 anti-patterns 全部规避（链 phase_07_llm_risks）

### 架构决策
- Budget enforcement 两层分拆：adapter 追踪累计 token，step 强制执行上限
- 每种组件类型有独立的"安全空值"：Generator → GenerationResult(finish_reason="error")，Reranker → []
- frozen dataclass 不可变：重排序时创建新实例，不原地修改 rank（链 phase_07_implementation_reality）

### 测试覆盖
- E2E 管道测试（chunker → generator）、健康检查、后端故障、预算超限
- 49 个测试，覆盖正常 + 负面 + 合约场景

---

## Phase 8.0: 机器强制护栏 (`guardrails/`)

**完成状态**: ✅ 已完成 (Phase 8.0)

### 关键交付
- `guardrails/checker.py` — AST-based 架构规则引擎
- 4 条规则：cross_platform、frozen_dataclass、component_registry、chain_coverage
- `guardrails/cli.py` — `python -m guardrails check [--all] [--rule X] [--json]`
- `.pre-commit-config.yaml` — git commit 前自动运行
- `tests/conftest.py` — pytest `--guardrails` 集成

### 架构决策
- Severity 分级：ERROR（阻止提交）、WARNING（CI 告警）、INFO
- frozen_dataclass 规则排除 `__post_init__` 中的 `object.__setattr__`（合法模式）
- "在加速前，先焊死护栏" — Phase 8.0 在 engine 重构之前完成（用户战略指令）

---

## Phase 8.1: Async-Native 引擎重构 (`core/pipeline/engine.py`)

**完成状态**: ✅ 已完成 (Phase 8.1)

### 关键交付
- DAG-based 并发执行 — 独立分支通过 `asyncio.gather()` 并行
- 所有 step `run()` 改为 `async def`，引擎 `_dispatch()` 用 `iscoroutine()` 检测
- 单事件循环 — `asyncio.run()` 仅 1 处（`PipelineRunner.run()`）
- `resources.close()` 在 `try/finally` 中，保证异常安全
- 独立 `ThreadPoolExecutor`（默认 4 workers）替代 `asyncio.to_thread()`
- Sync health_check — 直接调用 backend 同步方法，0 个 `asyncio.run()` 在 steps 中

### Bug 修复
- DAG 依赖解析：`depends_on` 引用 provided keys（如 "chunks"），不是 step names。修复前所有步骤错误地并行执行导致 retriever 拿空数据（链 phase_08_async_native_evolution）

### 架构决策
- `PipelineRunner` 支持 context manager（`__enter__`/`__exit__`）
- Sync 步骤通过 `loop.run_in_executor(executor, ...)` 走独立线程池，不抢占 adapter I/O 线程
- 209 测试，0 失败，guardrails 通过

---

## Phase 8.2a: Single-Link Streaming (Generator→User)

### Context

Phase 8.1 完成了 async-native 引擎：单事件循环、DAG 并发、独立线程池、try/finally 资源释放。Streaming 是第一个"原生 async 消费者"。

8.2a 范围限定为**单链路**（Generator→User），不涉及多节点 DAG 流式传播（那是 8.2b）。目标：用户能通过 `runner.run_streaming()` 逐 token 拿到生成结果。

### Key Decisions

1. **新增 `run_streaming()` 方法，不重载 `run()`** — Python 不能同时 return 和 yield。PipelineStep 上加可选的 `run_streaming() -> AsyncIterator`
2. **8.2a 流式路径绕过 DAG 调度器** — 单链路场景：先跑 generator 之前的步骤（批次 DAG），再对 generator 调 `run_streaming()` 逐 token yield
3. **双入口** — `run_streaming() -> Iterator[Any]`（同步，内部 `asyncio.run()`）+ `arun_streaming() -> AsyncIterator[Any]`（异步，给 FastAPI 直接用 `async for`）。`core/` 中 `asyncio.run()` 从 1 变 2
4. **Sync Backend → AsyncIterator 桥接** — Producer-Consumer + Sentinel 模式：`asyncio.run_coroutine_threadsafe(queue.put(item), loop)` 替代 `put_nowait`，backpressure 自然传导

### Implementation Steps (10 steps)

| # | 文件 | 改动 | 
|---|------|------|
| 1 | `core/contracts/generation.py` | 新增 `StreamItem` frozen dataclass |
| 2 | `core/contracts/validation.py` | 新增 `validate_stream_output()` |
| 3 | `core/contracts/__init__.py` | 导出新类型 |
| 4 | `core/adapters/generator_adapter.py` | `StreamingBackend` Protocol |
| 5 | `core/adapters/generator_adapter.py` | `GenerationAdapter.generate_stream()` + 桥接逻辑 |
| 6 | `core/steps/generator.py` | `MockStreamingBackend` |
| 7 | `core/steps/generator.py` | `GeneratorStep.run_streaming()` |
| 8 | `core/pipeline/engine.py` | `run_streaming()` + `arun_streaming()` + `_arun_streaming_impl()` |
| 9 | `core/pipeline/engine.py` | `_dispatch()` async generator 防护 |
| 10 | `core/pipeline/engine.py` | `StepOutput.stream` 类型修正 `Iterator`→`AsyncIterator` |

### Bridge Pattern (Step 5)

```python
queue: asyncio.Queue = asyncio.Queue(maxsize=32)  # backpressure 窗口
sentinel = object()

def _producer():
    try:
        for item in backend.generate_stream(prompt, ctx, **params):
            asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)
    except Exception:
        asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)

task = loop.run_in_executor(executor, _producer)
while True:
    item = await queue.get()
    if item is sentinel:
        break
    yield item
await task
```

### Test Plan — `tests/e2e/test_streaming_e2e.py`

| 测试类 | 用例 |
|--------|------|
| `TestStreamItemContract` | frozen 不可变、MappingProxyType 防护 |
| `TestMockStreamingBackend` | 逐词 yield、空 prompt、序号连续、finish_reason |
| `TestGenerationAdapterStreaming` | stream backend / 非 stream fallback / 累计 token |
| `TestGeneratorStepStreaming` | `run_streaming()` yield、预算超限 error item |
| `TestPipelineRunnerStreaming` | 完整管道、自动检测 generator、无 generator 抛异常 |
| `TestValidateStreamOutput` | 合法流、空流报错、多项 finish_reason、序号不连续 |

### Files Modified

| 文件 | 行数 |
|------|------|
| `core/contracts/generation.py` | ~25 |
| `core/contracts/validation.py` | ~55 |
| `core/contracts/__init__.py` | ~3 |
| `core/adapters/generator_adapter.py` | ~70 |
| `core/steps/generator.py` | ~55 |
| `core/pipeline/engine.py` | ~80 |
| `tests/e2e/test_streaming_e2e.py` | ~250 (新文件) |

### Verification

1. `pytest tests/e2e/test_streaming_e2e.py -v` — 流式测试全通过
2. `pytest tests/ -q` — 全量不回归（209 → 234+）
3. `python -m guardrails check --all` — 通过
4. `grep -rn "asyncio.run(" core/` — 恰好 2 处
5. 同步：`for item in runner.run_streaming(...):` 逐 token 输出
6. 异步：`async for item in runner.arun_streaming(...):` 逐 token 输出

---

## Phase 8.2b: DAG 流式汇聚 (多节点流式传播)

**完成状态**: ✅ 已完成

### 关键交付
- `merge_streams()` in `core/pipeline/streaming.py` — WAIT_ALL 合并，N-Sentinel 收敛 (108 行)
- `StepOutput.internal_stream` — InternalStream (DAG 内部) vs `.stream` (UserFacing, 仅 generator)
- `StreamItem.is_terminal` + `StreamItem.error` — 错误承载的终端标记（替代裸 sentinel）
- 引擎自动合并 — `stream_state` dict 追踪 internal_stream，多上游自动调 `merge_streams()`
- `guardrails/rules/stream_isolation.py` — AST 级强制：仅 generator 步骤可设置 `StepOutput.stream`
- `.ai_reasoning/chains/phase_08_dag_streaming_semantics.yaml` — 推理链

### 架构决策

1. **WAIT_ALL 仅此一种 (FIRST_N 推迟到 8.2c)**：所有 N 个上游生产者必须完成后，下游才收到合并终端信号。N 个 sentinel 被计数；第 N 个哨兵到达后才产出。最安全、最简单正确。

2. **N-Sentinel 收敛模型**：每个上游生产者发送数据 StreamItem 后跟恰好一个终端 StreamItem (`is_terminal=True`)。共享 `asyncio.Queue` 累积所有生产者的 item。合并消费者计数终端，count == N 时产出单个合并终端。

3. **错误承载的 StreamItem 替代裸 Sentinel**：错误通过 `StreamItem(delta="", finish_reason="error", is_terminal=True, error="...")` 发送。保持协议统一——一切皆为 StreamItem。收到错误终端时：
   - a) 立即产出错误终端
   - b) 通过 `asyncio.Task.cancel()` 取消所有剩余生产者任务
   - c) 退出合并循环

4. **UserFacingStream vs InternalStream 隔离**：`StepOutput.internal_stream: Optional[AsyncIterator]` 新增（8.2a 已将 `.stream` 改为 AsyncIterator 用于 UserFacing）。仅 `component_type="generator"` 暴露 UserFacingStream；所有其他步骤走 `internal_stream`。引擎保证 internal_stream 数据绝不触碰 SSE/UserFacing 序列化。

### 反模式

- "使用裸 sentinel 对象替代 `StreamItem(is_terminal=True)`。这迫使 `isinstance()` 检查，破坏协议统一性。"
- "在步骤的 `run()` 方法内合并流。合并逻辑属于引擎或专用 merge helper——步骤消费单个合并流，不是 N 个原始流。"
- "错误时忘记取消剩余生产者任务。这会泄漏协程并导致 'Task was destroyed but it is pending' 警告。"
- "硬编码生产者数量 N。merge 函数必须从步骤的 `depends_on` 列表中推导 N。"
- "internal_stream 数据跨越进入 UserFacing 序列化。Guardrails 必须静态验证此边界。"

### 测试覆盖
- `tests/e2e/test_dag_stream_merge.py` — 17 个测试 (N-Sentinel 收敛 / 错误传播与取消 / InternalStream 隔离 / 背压 / 契约 / 引擎集成)
- 265 测试，0 失败，1 skip

---

## Phase 9: 云原生适配层

### 背景

Phase 8 确立了 async-native DAG 流式 (WAIT_ALL 合并、N-Sentinel 收敛、InternalStream 与 UserFacing 隔离)。RAG 引擎在单进程内是正确的。Phase 9 回答：当这个引擎在云原生环境中与未来的引擎类型 (Planning、Reflection、Multi-Agent) 一起运行时，会发生什么？

**战略约束：**
- RAG 引擎是"领域特定运行时"——不得吸收 Agent 概念（对话历史、用户身份、Agent 状态）
- DeepSeek-TUI → JSON-RPC 作为云原生内部总线（但 JSON-RPC 是选项之一，不硬编码）
- Pi → Pace Shaping 作为传输层 QoS（参数化为 `item_throughput`，非 `token_rate`）
- 去 RAG 特化：全局使用基于行为的命名
- 传输适配器仅在 `core/adapters/` ——引擎核心保持纯净

### 1. 契约层: `core/contracts/streaming_protocol.py`

两个可插拔 Protocol + 一个配置 dataclass。无中间 `DataStreamMessage`——`StreamItem` 既是内存模型也是网络模型。`SerializationFormat` 直接将 StreamItem ↔ bytes 转换。

```python
# SerializationFormat — 可插拔序列化格式
class SerializationFormat(Protocol):
    def serialize(self, item: StreamItem) -> bytes: ...
    def deserialize(self, data: bytes) -> StreamItem: ...

# TransportBackend — 可插拔网络传输
class TransportBackend(Protocol):
    async def connect(self) -> None: ...
    async def send(self, data: bytes) -> None: ...
    async def receive(self) -> AsyncIterator[bytes]: ...
    async def close(self) -> None: ...
    def health_check(self) -> bool: ...

# PaceConfig — QoS 参数 (item_throughput 非 token_rate)
@dataclass(frozen=True)
class PaceConfig:
    """流式服务质量参数。

    adaptive=True 时，backpressure_signal 返回值语义：
      0.0 = 下游完全空闲，可全速发送
      1.0 = 下游完全饱和，应暂停发送
      中间值 = 线性插值缩放 item_throughput

    信号采样频率由 PaceShapingWrapper 内部控制（建议每 burst_size
    个 item 采样一次），避免高频 await 成为性能瓶颈。
    """
    item_throughput: Optional[float] = None  # items/sec, None = 不限速
    burst_size: int = 0
    adaptive: bool = False
```

### 2. 适配器层: `core/adapters/stream_adapter.py`

**`JsonRpc20Serializer`** — 实现 `SerializationFormat`。必须覆盖完整 4 种 StreamItem 状态：

| StreamItem 状态 | JSON-RPC method | params 附加字段 | 备注 |
|---|---|---|---|
| `is_terminal=False, error=None` | `stream.item` | `data: ...` | 常规数据 |
| `is_terminal=True, error=None` | `stream.finish` | `{}` | 正常结束 |
| `is_terminal=True, error="..."` | `stream.error` | `error: {...}` | 错误终端 |
| `is_terminal=False, error="..."` | N/A | N/A | 非法状态 → `serialize()` 中 `raise ValueError` |

TDD 锚点测试必须在实现前写出——确保 `serialize()` 把状态机校验放在第一行：

```python
def test_serialize_invalid_state_raises(self):
    """非法状态 (is_terminal=False, error!=None) 必须在序列化层被拦截"""
    serializer = JsonRpc20Serializer()
    invalid_item = StreamItem(
        delta="some chunk", index=0,
        is_terminal=False, error="unexpected error"
    )
    with pytest.raises(ValueError, match="Non-terminal item cannot carry error"):
        serializer.serialize(invalid_item)
```

**`PaceShapingWrapper`** — 用吞吐量控制包装 `AsyncIterator[StreamItem]`：
- 不修改 StreamItem 数据——仅改变 yield 之间的时序
- `item_throughput` (items/sec) + `burst_size` + `adaptive` 模式
- Adaptive 模式：接受可选的 `backpressure_signal: Callable[[], Awaitable[float]]` 返回 0.0-1.0
- 使用 `asyncio.sleep()`——非阻塞
- 采样策略：每 `burst_size` 个 item 采样一次 backpressure_signal
- burst_size > 0 时批量 sleep：累积 burst_size 个 item 后一次性 sleep，减少延迟抖动
- Docstring 必须标注 "InternalStream only"

虚拟时钟 fixture 消除物理延迟：
```python
@pytest.fixture
def mock_sleep(monkeypatch):
    sleep_calls = []
    async def fake_sleep(duration):
        sleep_calls.append(duration)
    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return sleep_calls
```

**`AsyncDataStreamAdapter`** — 桥接引擎 ↔ 云传输：
- 构造函数: `(serializer, transport, dependency_name, default_timeout, pace_config)`
- `send_stream(stream)`: 序列化 + 通过传输发送
- `receive_stream()`: 从传输接收 + 反序列化
- 遵循 VectorStoreAdapter 模式：auto-tracing, `health_probe()`, `last_trace`

### 3. 传输占位: `core/adapters/transports/`

使用 ABC + abstractmethod (非裸 `NotImplementedError`)，让占位符成为 IDE 可感知的接口文档：

```python
# core/adapters/transports/grpc_transport.py
from abc import ABC, abstractmethod
from core.contracts.streaming_protocol import TransportBackend

class GrpcBidiTransport(TransportBackend, ABC):
    """gRPC Bidirectional Streaming transport.

    生产实现需要:
    - protobuf schema 定义在 protos/stream.proto
    - grpc.aio.insecure_channel / secure_channel 配置
    - Metadata-based dependency_name 路由
    """
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def send(self, data: bytes) -> None: ...
    @abstractmethod
    async def receive(self) -> AsyncIterator[bytes]: ...
    @abstractmethod
    async def close(self) -> None: ...
    @abstractmethod
    def health_check(self) -> bool: ...
```

### 4. 管道便利函数: `core/pipeline/streaming.py`

在 `merge_streams()` 旁边添加 `pace_stream()`——对 `PaceShapingWrapper` 的薄委托：

```python
async def pace_stream(
    stream: AsyncIterator[StreamItem],
    item_throughput: Optional[float] = None,
    burst_size: int = 0,
    adaptive: bool = False,
) -> AsyncIterator[StreamItem]:
```

**引擎核心 (engine.py) 零变更。** Pace shaping 由包装流的适配器应用，非引擎。

### 5. Guardrails: 2 条新规则

**共用基础设施**：与 `cross-platform-imports.py` 复用 AST 解析，提取 `_get_import_nodes(tree)` 工具函数。

**`internal_stream_only.py`** — 规则 ID `internal-stream-001` (ERROR)：

| 检测模式 | 易误报场景 | 排除策略 |
|---|---|---|
| `StepOutput(stream=...)` 中 stream 参数非 None | 测试文件中 Mock StepOutput | 排除路径含 `test` 的文件 |
| | `stream=None` 显式传参 | AST 检查 `Constant(value=None)` |

**`transport_adapter_boundary.py`** — 规则 ID `transport-boundary-001` (ERROR)：

| 检测模式 | 易误报场景 | 排除策略 |
|---|---|---|
| `import grpc` / `from redis` / `import nats` 等 | `core/adapters/transports/` 内允许 | 检查文件路径是否在 `core/adapters/` 下 |
| | 注释/docstring 中的提及 | 仅检查 AST `Import`/`ImportFrom` 节点 |

总计: 7 条 guardrails 规则。

### 6. 推理链: `.ai_reasoning/chains/phase_09_multi_engine_architecture_vision.yaml`

记录：
- RAG 引擎是众多引擎类型之一（非 THE engine）
- 传输无关架构（AsyncDataStreamAdapter 模式）
- Pace shaping 作为通用 QoS（item_throughput，非 token_rate）
- 什么属于 RAG 引擎 vs. 未来 Agent 引擎 vs. 云原生层
- 反模式：硬编码 token_rate、将传输放入 pipeline/、Agent 状态放入 RAG 引擎

### 7. 导出: `core/adapters/__init__.py`

将全部适配器加入导出（当前仅导出 ChunkerAdapter）。按类别分组，遵循 `contracts/__init__.py` 模式。

### 8. 测试: `tests/e2e/` (~35 新测试)

| 文件 | 类 | 用例 |
|------|-----|------|
| `test_stream_serialization.py` | `TestJsonRpcSerializer`, `TestPaceConfig` | 往返 (data/error/terminal)、frozen 完整性、协议一致性、非法状态断言 |
| `test_pace_shaping.py` | `TestPaceShaping`, `TestAdaptivePace` | 固定速率、burst、不限速=直通、StreamItem 完整性、自适应缩放 |
| `test_transport_backpressure.py` | `TestTransportBackpressure`, `TestTransportWithMerge` | 慢消费者节流、队列容量、共享背压、merge+transport 集成 |

### 实施顺序

| # | 步骤 | 关键文件 |
|---|------|---------|
| 1 | `streaming_protocol.py` | `core/contracts/streaming_protocol.py`, 更新 `__init__.py` |
| 2 | `stream_adapter.py` | `core/adapters/stream_adapter.py` (3 个类) |
| 3 | 传输占位 | `core/adapters/transports/` (3 个文件) |
| 4 | `pace_stream()` | `core/pipeline/streaming.py` (追加) |
| 5 | Guardrails (2 新规则) | `guardrails/rules/` + `checker.py` |
| 6 | 推理链 | `.ai_reasoning/chains/phase_09_multi_engine_architecture_vision.yaml` |
| 7 | 导出 | `core/adapters/__init__.py` |
| 8 | 测试 (~35) | `tests/e2e/` 3 个新文件 |

### 架构不变量检查清单

| # | 不变量 | 验证 |
|---|--------|------|
| 1 | `asyncio.run()` count = 2 | `grep -rn "asyncio.run(" core/` → 仅 engine.py |
| 2 | 新适配器无同步阻塞 | `stream_adapter.py` 只用 `await`/`async for`/`asyncio.sleep()` |
| 3 | StreamItem frozen dataclass 不变 | `git diff core/contracts/generation.py` 为空 |
| 4 | 传输适配器仅在 `adapters/` | guardrails 规则 `transport-adapter-boundary` 通过 |
| 5 | `item_throughput` 非 `token_rate` | `grep -rn "token_rate" core/` 为空 |
| 6 | 无 Agent 概念进入 RAG 引擎 | `grep -rn "agent_state" core/` 为空 |
| 7 | 基于行为的 guardrails 命名 | `internal_stream_only`, `transport_adapter_boundary` |
| 8 | 265 + ~35 = 300+ 测试全部绿色 | `pytest tests/ -q` |

### 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|---|---|---|---|
| PaceShapingWrapper 在 adaptive 模式下引入额外延迟抖动 | 中 | 体验退化 | 测试中加入 `time.monotonic()` 方差断言；`burst_size > 0` 时批量 sleep |
| JsonRpcSerializer 与现有 StreamItem frozen 约束冲突 | 低 | 序列化失败 | StreamItem 不变；序列化器只做读取，反序列化时用 `StreamItem(...)` 构造 |
| 35 个新测试使总测试时间超过阈值 | 低 | CI 变慢 | pace_shaping 测试用虚拟时钟 (`monkeypatch asyncio.sleep`)；transport 测试用内存 Fake |
| `pace_stream()` 被误用于 UserFacing 流 | 中 | 违反隔离契约 | `internal-stream-001` 规则已覆盖；Docstring 标注 "InternalStream only" |

### 验证

1. `python -m guardrails check` — 7 条规则，全部 PASSED
2. `pytest tests/e2e/test_stream_serialization.py tests/e2e/test_pace_shaping.py tests/e2e/test_transport_backpressure.py -v` — ~35 新测试通过
3. `pytest tests/ -q` — 300+ 测试，无回归
4. `python -c "from core.adapters import AsyncDataStreamAdapter, JsonRpc20Serializer, PaceShapingWrapper"` — 全部可导入
5. `python -c "from core.contracts import SerializationFormat, TransportBackend, PaceConfig"` — 契约面整洁

---

## Phase 9.1: 运维契约加固 — 为第二引擎验证打开扩展点

**完成状态**: ✅ 已完成 (Phase 9.1)

### 背景

Phase 9 构建了云原生适配层（AsyncDataStreamAdapter、PaceShapingWrapper、TransportBackend），但所有抽象仅对 RAG 一种引擎类型进行了验证。N=1 的抽象是猜测，N=2 的抽象才是契约。Phase 9.1 在"不对适配器填充实现"的前提下打开三个扩展点，作为 Phase 10 第二引擎（Planning）的探针。

### 三个扩展点

| 扩展点 | 位置 | 语义 | 当前状态 |
|--------|------|------|----------|
| `StreamItem.trace_context: Optional[Dict[str, Any]]` | `core/contracts/generation.py` | 引擎专属追踪数据的不透明容器，适配器盲传 | 字段已添加，deepcopy 防御已就位 |
| `PaceConfig.adaptive_strategy: Optional[str]` | `core/contracts/streaming_protocol.py` | 引擎声明其调速需求（如 `"jitter"`），适配器路由到对应策略分支 | 字段已添加，PaceShapingWrapper 含 jitter 路由（抛 NotImplementedError 证明路由可达） |
| `TransportBackend.send_with_deadline(data, deadline)` | `core/contracts/streaming_protocol.py` | 操作级超时，区别于传输级超时 | Protocol 方法已声明，两个 transport 占位已添加 abstractmethod |

### Bug 修复（Phase 9 测试中暴露）

| 问题 | 根因 | 修复 |
|------|------|------|
| `SpanType.EXTERNAL_CALL` 不存在 | stream_adapter.py 从未对真实测试运行 | → `SpanType.DEPENDENCY_CALL` |
| `dependency=` 无效字段 | DependencyCallTrace 字段名是 `dependency_name` | → 4 处替换 |
| `span=` 无效字段 | DependencyCallTrace 字段名是 `span_type` | → 4 处替换 |
| `error_message=` 无效字段 | DependencyCallTrace 使用 `metadata={"error": str(exc)}` | → 4 处替换 |
| `pace_stream()` 无法传递 backpressure_signal | 函数签名缺少参数 | → 添加 `backpressure_signal` 参数 |
| `timeout` 参数被静默忽略 | send_stream/receive_stream 未使用 | → `asyncio.wait_for` 包裹 send；`asyncio.timeout_at` 包裹 receive |
| merge 测试 hang | merge_streams 要求每个生产者以 terminal item 结束 | → 测试生成器末尾添加 terminal items |

### 架构不变量

- StreamItem frozen dataclass 不变（仅新增 Optional 字段）
- PaceConfig adaptive/adaptive_strategy 均 Optional，向后兼容
- 所有三个扩展点均"打开但未填充"——Planning 的真实需求将定义其最终形态

---

## Phase 10: 多引擎编排原型 — Planning 引擎集成验证

**完成状态**: ✅ 已完成 (Phase 10)

### 背景

Phase 9/9.1 的适配器契约仅对一种引擎类型（RAG）进行了验证。在软件工程中，N=1 的抽象是猜测，N=2 的抽象才是契约。Phase 10 的目标**不是**构建可用的 Planning 引擎，而是利用 Planning 的正交行为（突发的 CPU 密集型推理 vs. 均匀的 I/O 密集型检索）作为对 Phase 9 适配器契约的最强对抗性测试。

**战略约束**：零改动 RAG 引擎。适配器改动 ≤5 行。所有 Planning 专属行为驻留在 `engines/planning/`。

### 引擎选择：为什么是 Planning？

| 候选引擎 | 压力维度 | 结论 |
|----------|----------|------|
| **Planning** | 突发时序、多步超时、层级化 trace_context | **选中**：与 RAG 正交性最大 |
| Tool Use | 请求-响应，无流式 | 拒绝：无法验证 pace_stream() 或 backpressure |
| Reflection | 消费者，非生产者 | 拒绝：产出不足以对适配器施压 |
| Code Generation | 均匀文本流 ≈ 同构于 RAG | 拒绝：N=1.1，不是 N=2 |

### 架构：engines/ 作为顶级消费者包

```
engines/                              ← 新建顶级包
  __init__.py                         ← "每个引擎是核心平台的消费者"
  planning/
    __init__.py                       ← 导出 PlanningEngine、PlanningStep
    interface.py                      ← PlanningStep + PlanningEngine Protocol（零实现）
    stub.py                           ← 最小 3 步硬编码桩
```

`engines/` 与 `core/` 平行，不在其内部。引擎通过核心平台的公开 API（AsyncDataStreamAdapter、StreamItem、PaceConfig）**消费**平台，不扩展或修改 core 内部。

### Step 1: Planning 引擎接口（零实现）

**`engines/planning/interface.py`**：

```python
@dataclass(frozen=True)
class PlanningStep:
    step_index: int
    reasoning_depth: int
    parent_step_id: Optional[str]
    content: str
    is_terminal: bool = False

class PlanningEngine(Protocol):
    async def plan(
        self, goal: str, deadline: float, pace_config: PaceConfig
    ) -> AsyncIterator[StreamItem]: ...
```

关键设计决策：
- `PlanningStep` 是引擎内部数据模型——**不是** StreamItem。桩负责 PlanningStep → StreamItem 转换
- trace_context 键命名空间：`planning.step_index`、`planning.reasoning_depth`、`planning.parent_step_id`、`planning.cumulative_tokens`。所有键使用 `planning.` 前缀加点分隔符
- `deadline` 参数在通过适配器时映射到 `send_with_deadline`
- `pace_config` 携带 `adaptive_strategy="jitter"`——引擎声明其调速需求

### Step 2: TDD 测试（实现前先写 10 个失败测试）

**`tests/e2e/test_planning_adapter_integration.py`** — 3 个测试类：

**TestTraceContextNamespaceIsolation**（5 个测试）：
- `test_planning_keys_survive_round_trip`：携带 `planning.step_index`、`planning.reasoning_depth` 的 StreamItem 经序列化往返后键完整保留
- `test_parent_step_id_round_trip`：`planning.parent_step_id` 经往返后保留
- `test_planning_keys_dont_conflict_with_rag_keys`：混合 trace_context（planning.* + rag.*）共存无覆盖
- `test_no_cross_engine_key_leakage`：两个引擎的键命名空间保持隔离
- `test_bare_key_awareness_meta`：确认无前缀键可被检测到（为 WARNING 级 guardrail 提供依据）

**TestAdaptiveStrategyJitterRouting**（3 个测试）：
- `test_jitter_strategy_recognized`：`PaceConfig(adaptive=True, adaptive_strategy="jitter")` 路由到 jitter 分支（捕获 NotImplementedError 作为路由证明）
- `test_jitter_strategy_error_context`：错误消息具有 grep 可搜索性
- `test_null_strategy_uses_default`：无策略时使用默认调速行为

**TestDeadlineTimeout**（2 个测试）：
- `test_planning_deadline_triggers_timeout`：deadline=0.0 立即触发 asyncio.TimeoutError，adapter.last_trace.status == "timeout"
- `test_planning_with_sufficient_deadline_completes`：充足 deadline 下所有 3 步完成

### Step 3: 最小 Planning 桩

**`engines/planning/stub.py`** — 实现 PlanningEngine Protocol：

- 3 步硬编码序列，无 LLM：
  - Step 0："Analyzing goal: {goal}"（深度 0，根节点）
  - Step 1："Decomposing into sub-tasks..."（深度 1）
  - Step 2："Final conclusion..."（深度 2，is_terminal=True）
- 使用 `time.perf_counter()` 进行 μs 级 deadline 检查（**非** monotonic）
- Deadline 语义：持续时间（`perf_counter() - start > deadline`），**非**绝对时间戳
- 每个 step 产生携带 `planning.*` trace_context 键的 StreamItem

### Step 4: PaceShapingWrapper — jitter 策略路由（~3 行）

在 `PaceShapingWrapper._throttled_iter()` 中，adaptive 检查之后、backpressure_signal 检查之前：

```python
if self._config.adaptive_strategy == "jitter":
    raise NotImplementedError(
        f"adaptive_strategy='jitter' recognized but not implemented; "
        f"pace_config={self._config}"
    )
```

这是**唯一的适配器改动**。它证明了策略路由机制有效，且未过早实现 jitter 语义。Jitter 检查位于 backpressure_signal 检查**之前**——因为 jitter 关注的是时序方差，与队列深度无关。

### Step 5: Guardrails — 2 条新规则（总计 9 条）

**`engine_interface_purity`**（ERROR）：
- 目标：`engines/*/interface.py`
- 检测：AST 扫描 Protocol 类中函数体非 `...`（Ellipsis）或纯 docstring 的方法
- 排除：测试文件、不在 engines/ 中的文件
- 规则 ID：`engine-interface-001`

**`trace_context_namespace`**（WARNING）：
- 目标：所有 `core/` 和 `engines/` Python 文件
- 检测：AST 扫描 `trace_context={...}` 赋值中的字典键——所有字符串键必须包含 `.`（点分隔符）
- 理由：防止 `"step"` 等裸键在引擎间冲突
- 排除：测试文件、`None` 赋值、`**` 解包
- 规则 ID：`trace-context-001`

### 实际集成发现

1. **trace_context 不透明 Dict = 正确设计**：适配器序列化/反序列化 trace_context 时不检查键。JsonRpc20Serializer 原封不动地往返所有键命名空间。Planning.* 和 rag.* 键共存于单个 StreamItem 中无冲突。`Dict[str, Any]` 优于结构化字段——任何结构化 schema 都会将 RAG 或 Planning 的假设泄露到契约中。

2. **adaptive_strategy 路由机制有效**：PaceConfig.adaptive_strategy 被 PaceShapingWrapper 读取并路由到正确的策略分支。jitter 分支抛出 NotImplementedError——证明了路由可达且未过早实现。检查位于 backpressure_signal 检查之前——jitter 策略不需要 backpressure 信号（jitter 关注的是时序方差，而非队列深度）。

3. **操作级 deadline 语义已验证**：Planning 桩在每次 step yield 前检查已用时间（perf_counter，非 monotonic）。deadline=0.0 时，第一次迭代即捕获并抛出 asyncio.TimeoutError。适配器的 send_stream 在其 asyncio.TimeoutError 处理器中捕获并在 last_trace 中记录 status="timeout"。分层超时契约（传输级 vs. 操作级）得到证明。

4. **时钟分辨率对亚毫秒级 deadline 至关重要**：`time.monotonic()` 在 Windows 上分辨率约 15ms——不足以在快速桩中执行 deadline。`time.perf_counter()` 提供微秒级分辨率，是操作级 deadline 的正确时钟。真实的 LLM 调用的 Planning 引擎（每步 >100ms）不会触发此问题，但桩暴露了它——这正是 Phase 10 设计的 N=2 边界条件发现。

5. **两项 guardrails 强制执行多引擎卫生**：
   - `engine_interface_purity`：AST 强制 engines/*/interface.py 中零实现（仅 Ellipsis 体）
   - `trace_context_namespace`：WARNING 级强制执行 trace_context 键中的点分隔引擎前缀

### 反模式

- "在 PaceShapingWrapper 中硬编码 engine_type 分支。策略路由使用 PaceConfig.adaptive_strategy——引擎声明其需求，适配器提供机制。无 `if engine_type == 'planning'` 检查。"
- "对操作级 deadline 使用 time.monotonic()。使用 time.perf_counter() 以获得亚毫秒级分辨率。monotonic() 在 Windows 上粒度约 15ms。"
- "向 StreamItem 添加引擎专属字段。使用不透明的 trace_context Dict——每个引擎拥有自己的键命名空间。"
- "仅凭 Planning 桩数据实现 jitter 策略。等待真实的 Planning 工作负载画像后再选择调速算法参数。"
- "创建无 '.' 分隔符的 trace_context 键。始终使用引擎前缀：'planning.*'、'rag.*'。Guardrail trace-context-001 强制执行此规则。"

### 交付物

| 文件 | 说明 |
|------|------|
| `engines/__init__.py` | 引擎注册包 |
| `engines/planning/__init__.py` | 导出 PlanningEngine、PlanningStep |
| `engines/planning/interface.py` | PlanningStep frozen dataclass + PlanningEngine Protocol（零实现） |
| `engines/planning/stub.py` | 3 步硬编码 Planner，含 deadline 支持 + trace_context |
| `core/adapters/stream_adapter.py` | +3 行（jitter 策略路由） |
| `tests/e2e/test_planning_adapter_integration.py` | 10 个 E2E 测试 |
| `guardrails/rules/engine_interface_purity.py` | 新规则（ERROR） |
| `guardrails/rules/trace_context_namespace.py` | 新规则（WARNING） |
| `.ai_reasoning/chains/phase_10_planning_engine_selection.yaml` | 引擎选择推理链 |
| `.ai_reasoning/chains/phase_10_planning_engine_integration.yaml` | 集成发现推理链 |

### 架构不变量检查

| # | 不变量 | 结果 |
|---|--------|------|
| 1 | RAG 引擎零改动 | `git diff core/pipeline/engine.py` 为空 ✅ |
| 2 | 适配器改动 ≤5 行 | `git diff core/adapters/stream_adapter.py` = 3 行 ✅ |
| 3 | 适配器中无 `if engine_type ==` 分支 | `grep -rn "engine_type" core/adapters/` 为空 ✅ |
| 4 | Planning 代码仅在 engines/ 中 | 所有新代码在 core/ 外 ✅ |
| 5 | StreamItem frozen dataclass 不变 | `git diff core/contracts/generation.py` 为空 ✅ |
| 6 | 331 个已有测试仍通过 | `pytest tests/ -q` 无回归 ✅ |
| 7 | 9 条 guardrails 通过 | `python -m guardrails check --all` PASSED ✅ |
| 8 | 2 条新推理链 | index.yaml 含 phase_10_planning_engine_selection + phase_10_planning_engine_integration ✅ |

### 对未来 Phase 的指导

1. **Phase 11（可观测性）**：trace_context 现已被证明可通过适配器携带引擎专属追踪数据。可观测性层应按引擎前缀读取 trace_context 键以构建每引擎追踪视图，且不解析引擎专属语义。last_trace 已记录 timeout/error/success 状态——应添加 trace_context 传播到 DependencyCallTrace 以使跨引擎调用链可追踪。

2. **未来引擎集成（Phase 11+）**：遵循 Planning 模式——定义 interface.py（Protocol + 数据模型），针对适配器契约编写 TDD 测试，实现最小桩。每个新引擎应使用**唯一**的 trace_context 键前缀。下一种引擎类型应与 RAG（I/O 密集型）**和** Planning（CPU 密集型突发）都不同——考虑 Event-driven 或 streaming-ingest 引擎以最大化契约覆盖。

3. **Jitter 策略实现**：推迟到 Phase 11+。需要真实的 Planning 引擎延迟数据。策略应控制项间时序方差（连续 yield 之间的最大抖动毫秒数），而非吞吐量。实现属于 PaceShapingWrapper._throttled_iter()，将当前的 NotImplementedError 替换为实际的调速逻辑。

4. **trace_context_namespace 升级**：当前为 WARNING。在现有裸键迁移后（目标：Phase 11），升级为 ERROR 以阻止新裸键进入代码库。

### 验证

1. `pytest tests/e2e/test_planning_adapter_integration.py -v` — 10 个测试全部通过
2. `pytest tests/ -q` — 331 个测试，0 个失败
3. `python -m guardrails check` — 9 条规则 PASSED
4. `python -c "from engines.planning import PlanningEngine, PlanningStep; from engines.planning.stub import StubPlanningEngine"` — 全部可导入
5. `grep -rn "engine_type" core/adapters/` — 空（无硬编码引擎分支）

---

## Phase 11: Trace 契约验证 — 文件导出器 + 声明式键注册表

**完成状态**: ✅ 已完成 (Phase 11)

### 背景

Phase 10 证明了 `trace_context` 能无损通过适配器管道——Planning 的 `planning.*` 键和 RAG 的 `rag.*` 键共存于单个 StreamItem 中，经过 JSON-RPC 往返后不冲突。但这是"飞行中"验证：没有任何下游消费者读取这些 trace 数据。

**缺口**：`AsyncDataStreamAdapter` 为每次 send/receive 操作构造 `DependencyCallTrace`，但 `DependencyCallTrace` 没有 `trace_context` 字段。每个 StreamItem 内部的 trace_context 经过序列化、线上传输、反序列化——然后被丢弃。

Phase 11 构建第一个"静态"消费者：一个文件导出器，将 trace_context 以结构化 JSON Lines 格式写入文件，可直接用 `cat | jq` 验证。这在实际选用任何可观测性后端之前，证明了契约的运行时可见性。

**战略约束**：零外部依赖。纯标准库。文件导出器实现已有的 `TraceWriter` 协议——不新增抽象层。

**核心约束（用户提出）**：组件平台尚未搭建（Phase 13+），因此 Trace Key Registry **不是**跨引擎语义标准——它是 N=2 引擎桩实际产出的私有语义快照。其价值在于：
1. 防止引擎私有语义在组件平台搭建前就固化
2. 标记 `component_candidate=True` 的键，保留被组件平台接管的空间
3. 为组件平台接口设计积累实证数据（哪些 trace 是"引擎的"vs"组件的"）

### 架构

```
core/observability/                    ← 新建包
  __init__.py                          ← 导出 FileTraceExporter, TraceKeyDef, TRACE_KEY_REGISTRY
  file_exporter.py                     ← ~65 LOC, 纯 stdlib (json, pathlib, random)
  trace_registry.py                    ← ~40 LOC, 声明式 key→semantics 映射
```

### 数据流

```
StreamItem.trace_context
  → AsyncDataStreamAdapter 捕获最终项的 ctx
    → DependencyCallTrace.trace_context (新字段)
      → StepTrace.dependency_calls
        → TraceLog.steps
          → FileTraceExporter.write() → JSON Lines 文件
```

### 关键设计决策

**a) Last-item 语义**：`DependencyCallTrace.trace_context` 捕获本次依赖调用中**最后一个** StreamItem 的上下文。对于 RAG（所有项上下文一致），每项携带相同上下文。对于 Planning（逐步上下文），仅保留终止步骤的上下文。逐项流式 trace 推迟到 Phase 12+。

此决策在三个位置显式记录：
1. `DependencyCallTrace.trace_context` 字段 docstring
2. `file_exporter.py` 模块级 docstring
3. Phase 11 推理链 "Known Limitations" 部分

**b) Sample rate**：`FileTraceExporter.__init__(path, sample_rate=1.0)`。参数从第一天就存在——声明导出器不是无限带宽管道。所有 Phase 11 测试使用 `sample_rate=1.0`（无采样，验证期间无数据丢失）。

**c) O(1) 引擎前缀推断**：`_infer_engine()` 使用 `@lru_cache(maxsize=1)` + 注册表派生前缀映射。不硬编码引擎名称——映射完全从 TRACE_KEY_REGISTRY 派生。

**d) 写原子性**：`write()` 将批次的所有记录拼接为单个字符串，在单次 `f.write()` 中写入。防止多个写入器共享同一文件路径时的行交错。

**e) JSON Lines 格式**：每行一个自包含的 JSON 对象，代表一条 `DependencyCallTrace` 记录。字段包含 `run_id`、`step_name`、`dependency`、`status`、`duration_ms`、`engine`、`trace_context`（原始 dict）、`_registered_keys`、`_unregistered_keys`。

**f) 语义冲突防护（用户提出）**：键命名空间隔离（Phase 10 `trace-context-001`）和值类型安全（Phase 11 `trace-key-serializability-001`）防止**语法**冲突。但两者都防不住**语义**冲突：

| 场景 | Key 1 | Key 2 | 冲突？ |
|------|-------|-------|--------|
| 相同后缀，不同引擎 | `planning.cumulative_tokens` | `rag.cumulative_tokens` | 无语义键冲突，但**语义重叠**：RAG tokens = 检索上下文 tokens，Planning tokens = 推理 LLM tokens。Phase 12 汇聚器若按 `cumulative_tokens` 聚合将静默合并不相关指标 |
| 相同后缀，不同延迟类型 | `planning.latency_ms` | `rag.latency_ms` | RAG = I/O 延迟（网络受限），Planning = CPU 延迟（计算受限）。键结构完全相同，含义截然不同 |

解决方案：**Trace Key Registry** —— 声明式、只读元数据表，记录系统中每个 trace 键的语义。配合 WARNING 级 guardrail（标记未注册键）。

这**不是**运行时强制执行机制。它是编译时文档契约——"如果你新增 trace_context 键，你必须声明其含义。"

### Step 1: DependencyCallTrace + trace_context 字段

**文件**: `core/pipeline/tracing.py` (+4 行)

```python
trace_context: Optional[Dict[str, Any]] = None
# Captures trace_context from the LAST StreamItem in this dependency call.
# For engines emitting per-step context (e.g., Planning), only the terminal
# step's context is retained here. Per-item streaming trace → Phase 12+.
```

`_deep_serializable()` 已递归处理 `dict` 值——`to_dict()` 无需改动即可工作。

### Step 2: AsyncDataStreamAdapter 捕获 trace_context

**文件**: `core/adapters/stream_adapter.py` (~15 行变更)

`send_stream()` 中：
```python
last_ctx = None
async for item in stream:
    last_ctx = item.trace_context  # 在序列化+发送之前捕获
    data = self._serializer.serialize(item)
    await self._transport.send(data)
return last_ctx
```

`DependencyCallTrace` 构造的三个分支中：
- success: `trace_context=last_ctx`
- timeout: `trace_context=None`
- error: `trace_context=None`

`receive_stream()` 同理：`last_ctx = item.trace_context`（在反序列化之后，yield 之前）。

### Step 3: Trace Key Registry

**文件**: `core/observability/trace_registry.py` (新建, ~60 行)

```python
@dataclass(frozen=True)
class TraceKeyDef:
    """单个 trace_context 键的声明式元数据。"""
    type: type
    semantics: str
    engine: str
    unit: str = ""
    component_candidate: bool = False
    # True = 此键的语义属于组件能力（retrieval, generation, scoring），
    # 不属于引擎本身。当组件平台搭建时，这些键应迁移到组件级 trace 契约。

TRACE_KEY_REGISTRY: Dict[str, TraceKeyDef] = {
    # ── Planning 引擎键（引擎内部） ──
    "planning.step_index": TraceKeyDef(type=int, semantics="...", engine="planning"),
    "planning.reasoning_depth": TraceKeyDef(type=int, semantics="...", engine="planning"),
    "planning.parent_step_id": TraceKeyDef(type=str, semantics="...", engine="planning"),

    # ── Planning 引擎键（component-candidate: LLM generation） ──
    "planning.cumulative_tokens": TraceKeyDef(
        type=int, semantics="...", engine="planning", unit="tokens",
        component_candidate=True,
    ),

    # ── RAG 引擎键（component-candidate: retrieval） ──
    "rag.chunk_id": TraceKeyDef(
        type=str, semantics="...", engine="rag",
        component_candidate=True,
    ),
    "rag.retrieval_latency_ms": TraceKeyDef(
        type=float, semantics="...", engine="rag", unit="ms",
        component_candidate=True,
    ),
}
```

**6 个键总计**：3 个引擎内部键 (planning.step_index/reasoning_depth/parent_step_id) + 3 个 component_candidate (planning.cumulative_tokens, rag.chunk_id, rag.retrieval_latency_ms)。

3 个引擎内部键将永久保留在引擎级注册表中。3 个 component_candidate 键标记为待迁移至 `core/contracts/trace_keys.py`（当组件平台搭建时，Phase 13+）。

### Step 4: FileTraceExporter

**文件**: `core/observability/file_exporter.py` (新建, ~85 行)

实现 `TraceWriter` 协议。关键特征：

- **JSON Lines 格式**：每行一个 JSON 对象，代表一条 DependencyCallTrace 记录
- **自包含行**：每行包括 `run_id`、`step_name`、`dependency`、`status`、`duration_ms`、`engine`（通过注册表从 trace_context 键前缀派生）、`trace_context`（原始 dict）、`_registered_keys`、`_unregistered_keys`
- **仅追加**：以 `"a"` 模式打开文件，立即写入并刷新——长时间运行的进程安全
- **sample_rate**：`random.random() > sample_rate` → 跳过。确定性：在测试中设置 `random.seed()` 可得到可复现的采样
- **引擎前缀推断**：使用 `TRACE_KEY_REGISTRY` 从键前缀推断引擎类型（非硬编码）。对未注册键回退到前缀分割
- **Schema anchoring**：输出中 `_registered_keys` 和 `_unregistered_keys` 分类，使 Phase 12 消费者能区分"已知语义"和"未注册"

```python
def write(self, traces: List[TraceLog]) -> None:
    lines: List[str] = []
    for trace_log in traces:
        for step in trace_log.steps:
            for dep_call in step.dependency_calls:
                if dep_call.trace_context is None:
                    continue
                if self._sample_rate < 1.0 and random.random() > self._sample_rate:
                    continue
                ctx = dep_call.trace_context
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "run_id": trace_log.pipeline_run_id,
                    "step": step.step_name,
                    "dependency": dep_call.dependency_name,
                    "status": dep_call.status,
                    "duration_ms": dep_call.duration_ms,
                    "engine": self._infer_engine(ctx),
                    "trace_context": ctx,
                    "_registered_keys": [k for k in ctx if k in registry_keys],
                    "_unregistered_keys": [k for k in ctx if k not in registry_keys],
                }
                lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    if lines:
        with open(self._path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
```

### Step 5: Guardrail — trace_key_serializability

**文件**: `guardrails/rules/trace_key_serializability.py` (新建, ~60 行)

规则 ID: `trace-key-serializability-001`

**分级严重度**：基于 AST 节点类型两级违规：

| 节点类型 | 严重度 | 理由 |
|----------|--------|------|
| `ast.Call` | ERROR | 函数调用 (datetime.now(), uuid4()) 产生非 JSON 类型 |
| `ast.Attribute` | ERROR | 属性访问可能解析为非可序列化对象 |
| `ast.Tuple` | ERROR | 非有效 JSON 类型 |
| `ast.Set` | ERROR | 非有效 JSON 类型 |
| `ast.BinOp` | ERROR | 表达式结果类型未知 |
| `ast.UnaryOp` | ERROR | 表达式结果类型未知 |
| `ast.Name` | WARNING (REVIEW_REQUIRED) | 变量引用——AST 无法追踪运行时类型。保守策略：标记人工审查而非阻止提交 |

**设计理由**：AST 级类型推断有根本性的局限。对 JSON 可序列化类型的变量引用（`step_idx: int`、`chunk_name: str`）是常见且有效的模式。用 ERROR 阻止会迫使所有 trace_context 值都是内联字面量，损害代码可读性。WARNING 在保持可见性的同时不干扰合法使用。

**允许的值类型**（白名单，静默通过）：
- `ast.Constant`: str, int, float, bool, None
- `ast.List`: 若所有元素为允许类型
- `ast.Dict`: 若所有值为允许类型

**排除**：测试文件（路径含 "test"）、None 值（合法）、`**` 解包（无法静态分析）、stub.py 文件（桩产生 trace_context 自然产物）。

### Step 6: Guardrail — trace_key_registration

**文件**: `guardrails/rules/trace_key_registration.py` (新建, ~35 行)

规则 ID: `trace-key-registration-001`, Severity: WARNING

AST 扫描 `trace_context=` dict 字面量。对每个**键**（字符串常量），检查是否存在于 `TRACE_KEY_REGISTRY`。未注册键触发 WARNING——它们序列化正常，但缺乏文档化语义。

```
trace_context key 'planning.estimated_complexity' is not registered in TRACE_KEY_REGISTRY.
Add a TraceKeyDef(type=..., semantics="...", engine="planning") entry to
core/observability/trace_registry.py to document its meaning.
```

**WARNING（非 ERROR）的设计理由**：
- 未注册键不会破坏序列化或命名空间隔离
- Phase 11 是在记录当前已知键，而非定义"所有可能的"键
- Phase 12+ 的新引擎自然会新增键——WARNING 提醒而不阻塞
- 注册表覆盖度达到成熟后（Phase 13+）可升级为 ERROR

**排除**：测试文件、stub.py 文件、None 键、`**` 解包、变量名键（无法静态验证）。

### Step 7: Guardrail 注册

**文件**: `guardrails/rules/__init__.py` + `guardrails/checker.py` (+8 行)

两条新规则注册到 checker 的 `_rules` dict 中，导入并加入 `__all__`。总计 11 条 guardrails 规则。

### 反模式

1. **在组件平台存在前设计组件级 trace 契约**。当前注册表捕获 N=2 引擎桩的实际产出。`component_candidate=True` 标记的是假设，尚未验证（需要组件平台来验证）。

2. **预集成 OTel/Jaeger 之后再理解自己的 trace 数据**。文件导出器是路径 C（零依赖验证）→ B（自定义轻量汇聚器）。OTel 在路径 A 上——可能永远不会到达。

3. **向注册表添加推测性 trace 键（tool.\*、memory.\*、skill.\*）**。Phase 11 之后唯一允许的注册表键是引擎桩实际产生的键或 guardrail 检测到的未注册键。

4. **将 trace_key_registration 设为 ERROR 而非 WARNING**。在注册表覆盖度成熟前，ERROR 会扼杀引擎演进。新引擎在 Phase 12+ 自然会新增键。

5. **将引擎级键视为永久键，而它们属于组件**。`planning.cumulative_tokens`、`rag.chunk_id`、`rag.retrieval_latency_ms` 被标记为 `component_candidate=True`——当组件平台搭建时它们应迁移到组件级契约。

6. **在 `_infer_engine()` 中硬编码引擎名称**。引擎前缀映射完全从 TRACE_KEY_REGISTRY 派生。新引擎注册后自动获得正确的引擎推断，无需改动 file_exporter。

7. **在 AST guardrail 中对 `ast.Name` 使用 ERROR**。这会阻止常见的有效模式如 `trace_context={key: local_var}`。WARNING 保留可见性而不阻断合法代码。

### 对未来 Phase 的指导

1. **Phase 12（自定义汇聚器/可视化）**：文件导出器生产 JSON Lines——任何消费者都能用 `json.loads()` 独立解析。`_registered_keys` / `_unregistered_keys` 分类使下游汇聚器能区分"已知语义"和"未注册"。优先构建汇聚器（聚合 + 查询），而非实时可视化。

2. **Phase 13+（组件平台）**：3 个 `component_candidate=True` 键应迁移到组件级 trace 契约。文件导出器的 JSON Lines 样本为组件平台接口设计提供实证基础——哪些键在不同引擎间结构相同、语义却不同，哪些模式反复出现。

3. **Guardrail 升级路径**：`trace_key_registration` 当前为 WARNING。注册表覆盖度达到 >95% 且稳定后，升级为 ERROR。`trace_context_namespace`（Phase 10）同样目标在裸键迁移后升级为 ERROR。

4. **Last-item → per-item**：当前 DependencyCallTrace.trace_context 捕获最后一个 StreamItem 的上下文。逐项流式 trace（每个 StreamItem 一条 trace 记录）推迟到 Phase 12+。需要评估每项 trace 的存储成本 vs. 调试价值。

5. **Sample rate 调优**：`sample_rate=1.0` 对验证友好，对生产不实际。Phase 12 应添加 sample_rate 配置（按引擎、按环境），在生产负载下进行基准测试后确定合理默认值。

### 交付物

| 文件 | 说明 |
|------|------|
| `core/pipeline/tracing.py` | DependencyCallTrace 新增 trace_context 字段 (+4 行) |
| `core/adapters/stream_adapter.py` | send/receive_stream 捕获 trace_context (~15 行) |
| `core/observability/__init__.py` | 导出 FileTraceExporter, TraceKeyDef, TRACE_KEY_REGISTRY |
| `core/observability/trace_registry.py` | 6 键声明式注册表 (3 engine-internal + 3 component_candidate) |
| `core/observability/file_exporter.py` | JSON Lines 导出器，O(1) 引擎推断，写原子性 |
| `guardrails/rules/trace_key_serializability.py` | 新规则 (ERROR for Call/Attribute/Set/Tuple/BinOp/UnaryOp, WARNING for Name) |
| `guardrails/rules/trace_key_registration.py` | 新规则 (WARNING for unregistered keys) |
| `guardrails/rules/__init__.py` | 导入并导出两条新规则 |
| `guardrails/checker.py` | 注册两条新规则 (总计 11 条) |
| `tests/e2e/test_trace_serialization.py` | 19 个测试，5 个测试类 |
| `.ai_reasoning/chains/phase_11_trace_contract_verification.yaml` | 推理链 |
| `.ai_reasoning/index.yaml` | 新增 chain entry + 6 个 tags |

### 架构不变量检查

| # | 不变量 | 结果 |
|---|--------|------|
| 1 | 零外部依赖 | `grep -rn "import openai\|import opentelemetry" core/observability/` 为空 ✅ |
| 2 | TraceWriter 协议不变 | `git diff core/pipeline/tracing.py` — 仅 DependencyCallTrace 新增字段 ✅ |
| 3 | 已有 TraceWriter 实现不受影响 | LocalJSONWriter 仍正常工作（新字段通过 to_dict() 自动包含） ✅ |
| 4 | 适配器变更 ≤15 行 | `git diff core/adapters/stream_adapter.py` ~15 行 ✅ |
| 5 | RAG 引擎零变更 | `git diff core/pipeline/engine.py` 为空 ✅ |
| 6 | StreamItem frozen dataclass 不变 | `git diff core/contracts/generation.py` 为空 ✅ |
| 7 | 350 个已有测试仍通过 | `pytest tests/ -q` 无回归 ✅ |
| 8 | Guardrails: 11 条规则 PASSED | `python -m guardrails check --all` PASSED (0 errors, 0 warnings) ✅ |
| 9 | 1 条新推理链 | index.yaml 含 phase_11_trace_contract_verification ✅ |
| 10 | Trace Key Registry 只读 | `grep "TRACE_KEY_REGISTRY\[" core/observability/` — 仅定义，无修改 ✅ |
| 11 | 所有 Planning/RAG trace 键已注册 | Planning stub (4 keys) + RAG (2 keys) 均在 TRACE_KEY_REGISTRY 中 ✅ |
| 12 | 6 个注册表键，3 个 component_candidate | `len(TRACE_KEY_REGISTRY)` = 6, `sum(1 for v in TRACE_KEY_REGISTRY.values() if v.component_candidate)` = 3 ✅ |

### 验证

1. `pytest tests/e2e/test_trace_serialization.py -v` — 19 个新测试全部通过
2. `pytest tests/ -q` — 350 个测试, 0 个失败
3. `python -m guardrails check --all` — 11 条规则 PASSED
4. `python -c "from core.observability import FileTraceExporter, TraceKeyDef, TRACE_KEY_REGISTRY; print(len(TRACE_KEY_REGISTRY))"` — 6 个注册表条目
5. `python -c "from core.observability.file_exporter import FileTraceExporter; m=FileTraceExporter._get_engine_prefix_map(); print(m)"` — O(1) 前缀映射 `{'planning': 'planning', 'rag': 'rag'}`
6. `python -c "from core.pipeline.tracing import DependencyCallTrace; dt=DependencyCallTrace(dependency_name='x', trace_context={'planning.step_index':0}); print(dt.to_dict()['trace_context'])"` — trace_context 在 to_dict() 中存活

---

## Phase 12: 观测闭环 — 逐项 trace + SQLite 落盘 + 组件候选实证分析

**完成状态**: ✅ 已完成 (Phase 12)

### 背景

Phase 11 证明了 `trace_context` 能无损通过适配器管道，并构建了第一个"静态"消费者（FileTraceExporter 写入 JSON Lines + 声明式 TRACE_KEY_REGISTRY）。350 个测试，0 个失败，11 条 guardrails。

**关键缺口**：`DependencyCallTrace.trace_context` 仅捕获**最后一个** StreamItem 的上下文——非逐项。一个 50 chunk 的 RAG 调用和一个 3 步的 Planning 调用各产生恰好 1 条 trace 记录。这无法支撑逐项延迟分析、流完整性验证和组件级 trace key 实证分析。

Phase 12 是**观测闭环**（观测闭环），非编排开启。目标：在新增任何系统复杂度之前，让 Phase 11 的数据**真正可用**。

**战略约束**：零外部依赖。SQLite 在 Python stdlib 中（`sqlite3`）。纯 B-tree 索引——无 FTS5（编译期可选，结构化查询不需要）。

**核心原则（新增架构不变量 #11）**：**观测先行**——每一层新能力的引入，必须先被上一层观测体系覆盖。Phase 11 证明引擎层 trace 可传输 → Phase 12 证明 sink 可消费 → Phase 13 方可搭建组件平台。

### 架构定位

```
组件平台 (core/contracts/)     ← 尚未构建 (Phase 13+)
    ↑ 未来：Phase 13 定义组件级 trace keys
    │
引擎平台 (core/pipeline/)      ← CURRENT: N=2 (RAG + Planning)
    ↑
    │  Phase 11: trace_context 透传验证 + FileExporter
    │  Phase 12: per-item trace + SQLite sink ← 本阶段
    │
观测层 (core/observability/)   ← Phase 11: FileTraceExporter + TraceKeyDef
                                   Phase 12: SQLiteTraceSink + sink_schema.py
    │
    ↓
编排平台 (core/orchestration/)  ← Phase 14+ (仅预设计在 Phase 12)
```

### 四大交付物

1. **逐项流 Trace 抽象** — 替代 last-item 语义，以成本边界为协议硬约束
2. **自建 Sink v0** — SQLite 纯 B-tree，schema-first 设计，100% stdlib
3. **组件候选实证分析** — 用真实数据验证 3 个 `component_candidate=True` key，产出 Phase 13 接口骨架
4. **编排 trace 契约预设计** — 纯文档，不实现（6 个 projected `orchestration.*` keys）

### 关键设计决策

**a) Option B: 并行写路径**。`StreamingTraceWriter` Protocol 与 `TraceWriter` 并存——不修改已有类型。FileTraceExporter 继续消费 `TraceLog` 做摘要记录。`SQLiteTraceSink` 消费 `StreamingTraceRecord` 做逐项记录。350 个已有测试无修改通过。

**b) Sink: SQLite 纯 B-tree**（非 FTS5）。FTS5 是编译期可选——不保证可用。Phase 12 的查询模式（`WHERE engine=? AND status=? GROUP BY key`）是结构化查询，不需要全文搜索。FTS5 可在需要时用 `CREATE VIRTUAL TABLE ... USING fts5(...)` 追加。

**c) Schema-first**。Step 0 是 `sink_schema.py`——所有表、列、索引的声明式 TypedDict 定义。`sink_schema_consistency` guardrail 验证运行时 SQL 与声明匹配。这是最重要的交付物——它是 schema 设计问题，不是检索性能问题。

**d) 成本边界作为协议硬约束**。`StreamingTraceWriter.max_items_per_call` 是 Protocol 的必选属性。没有它，RAG（50 chunk）vs Planning（3 步）= 16x 存储不对称。语义：
- `-1`：无限（显式接受风险）
- `0`：仅计数（无逐项记录，sentinel 含 overflow_count）
- `N > 0`：最多存储 N，超出截断 + sentinel

**e) 截断在 sink，不在 adapter**。Adapter 盲目收集所有 `StreamingTraceRecord`。Sink 按 `max_items_per_call` 强制截断，返回 `StreamingWriteResult`。单一职责——不在 N 个 adapter 实现中重复截断逻辑。

**f) 分类阈值（硬编码，有文档）**：
- `confirmed_component`：≥95% 出现率 + 100% 类型匹配 + bounded cardinality
- `type_mismatch`：类型匹配率 ≤99%（即使一次偏差也不含糊）
- `needs_more_data`：其余全部

### 实现序列

| # | 步骤 | 关键文件 | 行数 |
|---|------|---------|------|
| 0 | Sink Schema 声明式定义 | `core/observability/sink_schema.py` | ~120 |
| 1 | StreamingTraceRecord + StreamingTraceWriter + StreamingWriteResult | `core/pipeline/tracing.py` | ~92 |
| 2 | Adapter 逐项 trace_context 采集 | `core/adapters/stream_adapter.py` | ~39 |
| 3 | SQLiteTraceSink（含截断逻辑） | `core/observability/sqlite_sink.py` | ~410 |
| 4 | 组件候选实证分析脚本 | `scripts/analyze_component_candidates.py` | ~460 |
| 5 | 编排 trace 预设计 | `.ai_reasoning/chains/phase_12_orchestration_trace_pre_design.yaml` | ~130 |
| 6 | Guardrail: sink_schema_consistency | `guardrails/rules/sink_schema_consistency.py` | ~170 |
| 7 | Guardrail 注册 | `guardrails/rules/__init__.py` + `guardrails/checker.py` | ~6 |
| 8 | E2E 测试 | `tests/e2e/test_sqlite_sink.py` + 扩展 `test_trace_serialization.py` | ~500 |
| 9 | 推理链 + index + 不变量 | chains, index.yaml, CLAUDE.md, `__init__.py` | ~250 |

### 数据流

```
StreamItem.trace_context (EVERY item)
  → AsyncDataStreamAdapter 盲目收集 StreamingTraceRecord (每条一个)
    → streaming_traces 属性 (List[StreamingTraceRecord])
      → SQLiteTraceSink.write_streaming() → trace_records 表 (逐项)
      
StreamItem.trace_context (LAST item only)
  → DependencyCallTrace.trace_context (Phase 11, 不变)
    → TraceLog.steps → FileTraceExporter.write() → JSON Lines (摘要)
```

### Sink Schema（声明式）

**`trace_records`** — 主 trace 数据表：

| 列 | 类型 | 可空 | 说明 |
|----|------|------|------|
| id | INTEGER | N | 自增主键 |
| ts | TEXT | N | ISO 8601 时间戳 |
| run_id | TEXT | N | Pipeline run 标识 |
| step | TEXT | N | 步骤名 |
| dependency | TEXT | N | 依赖名 |
| status | TEXT | N | success / timeout / error / overflow |
| duration_ms | REAL | Y | 依赖调用时长（摘要记录；逐项为 NULL） |
| engine | TEXT | N | 从 trace_context keys 推断 |
| trace_context_json | TEXT | Y | 完整 trace_context dict 序列化为 JSON |
| item_index | INTEGER | Y | StreamItem index（NULL = 摘要记录） |
| item_delta_preview | TEXT | Y | delta 前 200 字符（NULL = 摘要） |
| is_terminal | INTEGER | Y | 0/1（NULL = 摘要） |

6 个索引：`idx_run_id`, `idx_engine`, `idx_status`, `idx_step`, `idx_run_step` (run_id+step), `idx_item_index` (run_id+dependency+item_index)

**`trace_keys`** — 注册表目录：key_name (TEXT PK), engine, value_type, semantics, unit, component_candidate

**`schema_version`** — 迁移追踪：version (INTEGER PK), applied_at, description

### 组件候选分析结果

3 个 `component_candidate=True` keys 的现状：

| Key | 出现率 | 类型匹配 | Cardinality | 分类 |
|-----|--------|----------|-------------|------|
| planning.cumulative_tokens | 38% (跨引擎池) | 100% | bounded | needs_more_data |
| rag.chunk_id | 62% (跨引擎池) | 100% | free_text | needs_more_data |
| rag.retrieval_latency_ms | 62% (跨引擎池) | 100% | bounded | needs_more_data |

所有 3 个 key 因跨引擎出现率不足 95% 被标记为 `needs_more_data`——这是 N=2 异构引擎的预期结果。每引擎 key 应在同引擎范围内分析，而非跨混合引擎池。chunk_id 的 `free_text` cardinality 也是预期内的（每个 chunk 有唯一 ID）。Phase 13 应在同引擎范围内重新分析，并考虑将 `free_text` 细分为 `unique_identifiers`（结构化）和 `free_text`（用户生成的不可预测内容）。

### 编排 trace 预设计（纯文档，不实现）

6 个 projected `orchestration.*` keys：

| Key | 类型 | 语义 |
|-----|------|------|
| orchestration.dag_node_id | str | DAG 节点唯一标识 |
| orchestration.parallel_depth | int | 并行执行树深度 |
| orchestration.merge_ordinal | int | 合并并行结果时的序号 |
| orchestration.branch_taken | str | 条件分支选择的路径 |
| orchestration.retry_count | int | 节点重试次数 |
| orchestration.resource_pool_key | str | 资源池标识 |

Schema 影响：`trace_keys` 表已通过 TEXT `engine` 列支持 "orchestration"。插入仅需 INSERT——无需 DDL 迁移。

### 边界情况处理

| 场景 | 行为 |
|------|------|
| Stream 为 0 项 | `_streaming_records` = []。`write_streaming([])` 无写入。无 sentinel |
| `max_items_per_call` 被超出 | Sink 截断至前 N 条。余量计数。Sentinel `item_index=-1` with `status="overflow"` 记录 `overflow_count` |
| Adapter 盲目收集全部 item | Adapter 为每个 StreamItem 追加到 `_streaming_records`——无截断逻辑。Sink 强制 `max_items_per_call` |
| SQLite 文件被锁 | `sqlite3.OperationalError` 向上传播。调用方重试。单写入者已文档化 |
| `max_items_per_call=-1`（无限） | 全部记录存储。无截断，无 sentinel |
| `max_items_per_call=0`（仅计数） | 无逐项记录。单条 sentinel，overflow_count = 总数 |
| DB 文件不存在 | `sqlite3.connect()` 创建。所有 DDL 使用 `IF NOT EXISTS` |
| `_create_schema()` 被重复调用 | 全部 `CREATE ... IF NOT EXISTS`——幂等。`_seed_trace_keys()` 先检查 `SELECT COUNT(*)` |

### 反模式

1. **Adapter 端截断**：将 `max_items_per_call` 逻辑放在 stream_adapter.py 而非 sink。一处实现 vs N 个 adapter 各实现一份
2. **为结构化查询使用 FTS5**：对精确匹配和 GROUP BY 查询使用 `CREATE VIRTUAL TABLE ... USING fts5`。B-tree 索引足够且保证可用
3. **Last-item only trace_context**：用 `DependencyCallTrace.trace_context`（last-item 语义）做逐项分析。逐项需求应使用 `StreamingTraceRecord`
4. **无 guardrail 的 schema**：在 `sink_schema.py` 声明之外向 SQLiteTraceSink 新增表或列。`sink_schema_consistency` guardrail 强制 schema-first
5. **成本边界作为事后补救**：将 `max_items_per_call` 视为可选优化而非结构性协议要求。没有它，逐项 trace 是无上界的存储膨胀
6. **无实证验证的组件候选 key**：不运行分析脚本就将 `component_candidate` key 提升到 `core/contracts/`。分类阈值提供稳定可复现的判断依据
7. **Phase 14 前实现编排**：在组件平台存在前就实现编排 keys 或引擎。预设计链显式标注 "NOT FOR IMPLEMENTATION"
8. **跨引擎出现率期望**：期待 `rag.chunk_id` 等每引擎 key 在所有异构引擎的混合 item 中出现 95%。每引擎 key 应在同引擎范围内分析

### 交付物

| 文件 | 说明 |
|------|------|
| `core/observability/sink_schema.py` | 声明式 schema：3 表 + 7 索引 + 版本追踪 |
| `core/pipeline/tracing.py` | StreamingTraceRecord + StreamingWriteResult + StreamingTraceWriter Protocol |
| `core/adapters/stream_adapter.py` | send_stream + receive_stream 逐项 StreamingTraceRecord 采集 |
| `core/observability/sqlite_sink.py` | SQLiteTraceSink：TraceWriter + StreamingTraceWriter 双协议实现 |
| `scripts/analyze_component_candidates.py` | 实证分析脚本：硬编码分类阈值 + 结构化 JSON 输出 |
| `.ai_reasoning/chains/phase_12_observability_closed_loop.yaml` | 主推理链：5 个替代方案 + 8 个反模式 |
| `.ai_reasoning/chains/phase_12_orchestration_trace_pre_design.yaml` | 编排预设计：3 个替代方案 + 5 个反模式 |
| `guardrails/rules/sink_schema_consistency.py` | 新规则（WARNING）：验证运行时 SQL schema |
| `guardrails/rules/__init__.py` + `guardrails/checker.py` | 注册新规则（12→12 guardrails） |
| `tests/e2e/test_sqlite_sink.py` | 18 个测试：schema/seed/write/truncate/query |
| `tests/e2e/test_trace_serialization.py` | 扩展 +12 个测试：StreamingTraceRecord/Protocol/Adapter 逐项采集 |
| `.ai_reasoning/index.yaml` | 2 个新链条目 + 12 个新 tags |
| `CLAUDE.md` | 新增不变量 #11（观测先行） |
| `core/observability/__init__.py` | 导出 SQLiteTraceSink + schema 常量 |

### 架构不变量检查

| # | 不变量 | 结果 |
|---|--------|------|
| 1 | 零外部依赖 | `pip check` + 测试导入 — sqlite3 是 stdlib ✅ |
| 2 | 已有 TraceWriter 实现不变 | FileTraceExporter, LocalJSONWriter 未修改 ✅ |
| 3 | StreamItem frozen dataclass 不变 | `git diff core/contracts/generation.py` 为空 ✅ |
| 4 | RAG 引擎零变更 | 未触及 engines/rag/ 或 core/pipeline/engine.py ✅ |
| 5 | 350 个已有测试仍通过 | 382 通过（350 + 32 新增），0 失败 ✅ |
| 6 | Guardrails: 12 条规则 PASSED | `python -m guardrails check --all` 通过（35 files, 12 rules） ✅ |
| 7 | SQLite schema 与声明式定义匹配 | TestSinkSchemaGuardrail ✅ |
| 8 | 逐项成本边界在协议中强制 | `max_items_per_call` 是 StreamingTraceWriter 的必选属性 ✅ |
| 9 | 组件候选分析 → 接口骨架 | `scripts/analyze_component_candidates.py` 结构化输出 ✅ |
| 10 | 新不变量"观测先行"已文档化 | CLAUDE.md 不变量 #11 ✅ |
| 11 | 2 条新推理链 | index.yaml 含 phase_12_observability_closed_loop + phase_12_orchestration_trace_pre_design ✅ |
| 12 | 已有 guardrails 未减少（11 → 12） | `python -m guardrails list-rules` 12 条 ✅ |

### 提交历史

```
0ed02ef feat: Phase 12 Step 9 — Reasoning chain, index, invariant #11
b3c95d6 test: Phase 12 Step 8 — E2E tests for per-item trace + SQLite sink
17ec238 feat: Phase 12 Step 4 — Component candidate empirical analysis script
4fefdcc feat: Phase 12 Steps 6-7 — sink_schema_consistency guardrail
922e599 feat: Phase 12 Step 3 — SQLiteTraceSink with cost-boundary enforcement
e9327b1 feat: Phase 12 Steps 1-2 — Per-item trace types + adapter capture
0760a6f feat: Phase 12 Step 0 — Declarative sink schema definition
```

### 验证

1. `pytest tests/ -q` — 382 个测试，0 个失败，1 skip
2. `python -m guardrails check --all` — 12 条规则 PASSED（35 files scanned）
3. `python -c "from core.observability import SQLiteTraceSink; from core.observability.sink_schema import TRACE_RECORDS_TABLE_NAME; print('OK')"` — 全部可导入
4. `python -c "from core.pipeline.tracing import StreamingTraceRecord, StreamingTraceWriter; r = StreamingTraceRecord(pipeline_run_id='x', step_name='s', dependency_name='d', item_index=0, item_delta_preview='preview', is_terminal=False, trace_context={'k':'v'}, ts_iso='2026-01-01T00:00:00Z'); print('OK')"` — dataclass 构造正常
5. `python scripts/analyze_component_candidates.py` — 产出分析报告，3 个 component_candidate keys 已分类
6. `python -c "from core.observability.sqlite_sink import SQLiteTraceSink; import tempfile, os; tmp = tempfile.mkdtemp(); sink = SQLiteTraceSink(os.path.join(tmp, 'test.db')); keys = sink.query_keys(component_candidate_only=True); assert len(keys) == 3; sink.close(); print('OK')"` — 查询接口正常

---

## Phase 13: 组件平台 — 组件级 Trace 合约 (组件平台)

**完成状态**: ✅ 已完成 (Phase 13)

### 背景

Phase 12 完成了观测闭环：逐项流 trace、SQLiteTraceSink、组件候选实证分析。382 tests、12 guardrails、0 external deps。

Phase 12 分析脚本将 3 个 `component_candidate=True` key 全部标记为 `needs_more_data`——但这是**方法论问题**（跨引擎池化稀释了每引擎出现率），而非数据质量问题。每引擎分析显示所有 3 个 key 100% 出现率、100% 类型匹配。

Phase 13 的核心命题：**定义引擎必须满足的正式 trace 合约**——"任何声称具有 retrieval 能力的引擎必须产出 `retrieval.chunk_id` 和 `retrieval.latency_ms`"。

`trace_registry.py` 的 docstring 明确声明：`component_candidate=True` 标记了"当组件平台构建时应迁移到 `core/contracts/trace_keys.py` 的 key"。Phase 13 兑现了这一承诺。

### 架构定位

```
组件平台 (core/contracts/)     ← Phase 13: 新增 trace_keys.py
    ↑ Phase 13: 组件级 trace 合约
    │
引擎平台 (core/pipeline/)      ← N=2 (RAG + Planning)
    ↑
    │  Phase 11-12: trace_context pipeline + sink ← 已完成
    │
观测层 (core/observability/)   ← Phase 13: engine→component mapping
    │
    ↓
编排平台 (core/orchestration/)  ← Phase 14+ (预设计在 Phase 12)
```

### 关键设计决策

**a) Option C: 数据模型 + 校验（非简单迁移，非 Protocol）**

| 方案 | 描述 | 判断 |
|------|------|------|
| A: 简单迁移 | 将 3 个 key 移到新文件，无校验 | ❌ 只是文件搬家，不构成合约。引擎仍无正式目标 |
| B: Protocol 式 | 每种组件类型定义一个 trace Protocol 类 | ❌ 过度工程。Trace key 是数据而非行为。Protocol 暗示方法，trace key 无方法 |
| **C: 数据模型 + 校验** | frozen dataclass + 注册表 dict + validator 函数 | ✅ 与 `validation.py` 模式完全一致 |

`ComponentTraceKeyDef` 是 `TraceKeyDef` 的自然对等物——声明 WHAT keys 存在、`COMPONENT_TRACE_KEYS` 按组件类型分组、`validate_component_trace()` 验证 trace_context 满足合约。

**b) Engine→Component 映射在观测层，不在合约层**

`ENGINE_TO_COMPONENT_MAP` 需要同时知道引擎 key 名 (`rag.chunk_id`) 和组件 key 名 (`retrieval.chunk_id`)。如果放在 `core/contracts/trace_keys.py`，合约层将需要导入引擎名——违反平台隔离（合约层应定义 WHAT，不应知道哪些引擎存在）。

观测层 (`core/observability/`) 是 trace 边界——它已有 `TraceKeyDef`（引擎特定 key）。映射放在这里是正确的架构位置。

**c) 单表 Schema 扩展（非双表）**

在现有 `trace_keys` 表新增 `component_type TEXT` 列（NULL = 引擎 key，非 NULL = 组件 key）。避免了：
- 双表 JOIN 查询复杂度
- 第二条种子路径及其不一致风险
- 额外的迁移代码

**d) `component_candidate` flag 保留（非移除）**

4+ 个消费者（guardrails、分析脚本、sink queries、tests）仍引用 `component_candidate`。移除需要跨文件协调变更。标记为 deprecated 但在 Phase 14+ 前保留——安全路径。

**e) `trace_key_registration` WARNING→ERROR**

Phase 11-12 保持 WARNING 因为注册表不成熟，新引擎会自然添加 key。组件平台建成后，两个注册表（引擎 + 组件）覆盖所有已知 key，未注册 key 是真正的缺口。

**f) `component_trace_completeness` 新规则 (WARNING)**

组件平台是全新的——ERROR 会阻塞仍在开发中的引擎。WARNING 提示但不阻塞。Phase 14+ 升级为 ERROR。

### 实现序列

| # | 步骤 | 关键文件 | 行数 |
|---|------|---------|------|
| 0 | 推理链 (预设计) | `.ai_reasoning/chains/phase_13_component_trace_contracts.yaml` | ~243 |
| 1 | 组件 trace key 注册表 | `core/contracts/trace_keys.py` (NEW) | ~193 |
| 2 | Engine→Component 映射 | `core/observability/trace_registry.py` | ~28 |
| 3 | Sink Schema v2 | `core/observability/sink_schema.py` | ~4 |
| 4 | SQLiteSink v2 (迁移+种子+查询) | `core/observability/sqlite_sink.py` | ~121 |
| 5 | 公开 API 导出 | `core/contracts/__init__.py` + `core/observability/__init__.py` | ~16 |
| 6 | Guardrails: 升级 + 新规则 | `trace_key_registration.py` + `component_trace_completeness.py` (NEW) + `trace_context_namespace.py` + `__init__.py` + `checker.py` | ~192 |
| 7 | 修复分析脚本 | `scripts/analyze_component_candidates.py` | ~51 |
| 8 | 测试 | 3 个新测试文件 + 2 个现有测试更新 | ~581 |
| 9 | 全量验证 + 链最终化 | — | — |

### 核心交付物

#### `core/contracts/trace_keys.py` — 组件 Trace Key 合约

```python
@dataclass(frozen=True)
class ComponentTraceKeyDef:
    component_type: str   # "retrieval" | "generation" | "scoring"
    key_suffix: str       # e.g. "chunk_id", "latency_ms"
    type: type            # int, str, float
    semantics: str
    unit: str = ""

    @property
    def full_key(self) -> str:
        return f"{self.component_type}.{self.key_suffix}"

COMPONENT_TRACE_KEYS: Dict[str, ComponentTraceKeyDef] = {
    "retrieval.chunk_id": ComponentTraceKeyDef(
        component_type="retrieval", key_suffix="chunk_id", type=str,
        semantics="Unique identifier of the retrieved chunk in the vector store",
    ),
    "retrieval.latency_ms": ComponentTraceKeyDef(
        component_type="retrieval", key_suffix="latency_ms", type=float,
        semantics="Wall-clock time for the vector store retrieval call, in milliseconds",
        unit="ms",
    ),
    "generation.cumulative_tokens": ComponentTraceKeyDef(
        component_type="generation", key_suffix="cumulative_tokens", type=int,
        semantics="Total LLM tokens consumed across all generation steps so far",
        unit="tokens",
    ),
    # scoring: 0 keys 当前——但"scoring"是合法的组件类型
}

def validate_component_trace(
    trace_context: Dict[str, Any] | None, component_type: str
) -> ContractValidationResult: ...
```

校验 5 层：null context (ERROR)、未知 component_type (ERROR)、缺失 required key (ERROR)、类型不匹配 via isinstance (ERROR)、额外 key (WARNING)。

#### `ENGINE_TO_COMPONENT_MAP` — 引擎→组件解析

```python
ENGINE_TO_COMPONENT_MAP: Dict[str, str] = {
    "planning.cumulative_tokens": "generation.cumulative_tokens",
    "rag.chunk_id": "retrieval.chunk_id",
    "rag.retrieval_latency_ms": "retrieval.latency_ms",
}
```

位于 `trace_registry.py`（观测层/trace 边界），非 `core/contracts/`（平台隔离）。

#### Schema v2

| 变更 | 说明 |
|------|------|
| `component_type` 列 (NULLABLE_TEXT) | 新增于 `trace_keys` 表。NULL = 引擎 key，非 NULL = 组件 key |
| `idx_keys_component_type` | 新索引：按组件类型筛选 |
| `CURRENT_SCHEMA_VERSION = 2` | 版本号升级 |
| 迁移：`_migrate_v1_to_v2()` | PRAGMA table_info 检测 + ALTER TABLE ADD COLUMN。幂等 |

### 分析脚本修复

| 修复 | 说明 |
|------|------|
| `--per-engine` flag | 每引擎 key 在同引擎 item 范围内分析（非跨引擎池化） |
| `unique_identifiers` 子分类 | 将 `free_text` 细分为 `unique_identifiers` (<200 chars, 无空格, 每值唯一) 和真正 `free_text` |
| `CLASSIFICATION_RULES` 字符串→集合 | `value_cardinality_set: {"bounded", "unique_identifiers"}` |
| `_migration_recommendations()` | 使用 `ENGINE_TO_COMPONENT_MAP` 替代错误的引擎前缀剥离 |

修复后产出确定结果：
```
[READY] planning.cumulative_tokens → generation.cumulative_tokens (100% occurrence, bounded)
[READY] rag.chunk_id → retrieval.chunk_id (100% occurrence, unique_identifiers)
[READY] rag.retrieval_latency_ms → retrieval.latency_ms (100% occurrence, bounded)
```

### Guardrails: 12 → 14 条规则

| 规则 | 变更 | 说明 |
|------|------|------|
| `trace_key_registration` | WARNING→ERROR | 注册表覆盖已完整 |
| `trace_key_registration` | 扩展 `_get_registry_keys()` | 联合 TRACE_KEY_REGISTRY + COMPONENT_TRACE_KEYS |
| `component_trace_completeness` | NEW (WARNING) | AST 扫描 engines/ 目录，引擎产出部分组件 key → 必须产出全部 |
| `trace_context_namespace` | 扩展 `_KNOWN_ENGINES` | 新增 "retrieval", "generation", "scoring" |

### 边界情况

| 场景 | 行为 |
|------|------|
| `trace_context=None` in validate | `passed=False`, error "trace_context is None" |
| Unknown `component_type` | `passed=False`, error "unknown component_type: X" |
| Engine 用组件 key 直接产出 (`retrieval.chunk_id`) | 扩展 guardrail 识别（联合注册表） |
| 已有 v1 数据库打开 | `_migrate_v1_to_v2()` 通过 ALTER TABLE 新增列 |
| 全新数据库 | CREATE TABLE 含 component_type 列，迁移为 no-op |
| Schema version 竞态 (v2 已记录) | `_record_schema_version()` 先检查已有版本 |
| 种子已存在 component key | 逐 key 检查防止重复 INSERT |
| Engine 无任何 component key | `component_trace_completeness` 不报告违规（无声明 = 无检查） |
| `scoring` 类型查询 | 返回空列表——0 个 key，但类型合法 |

### 反模式

1. **Mapping in contracts**: 在 `core/contracts/trace_keys.py` 中定义 `ENGINE_TO_COMPONENT_MAP`——合约层需要知道 `rag.chunk_id` 等引擎名，违反平台隔离
2. **Protocol-based trace keys**: 使用 ABC 或 Protocol——trace key 是数据非行为。frozen dataclass + validator 是既定模式
3. **移除 component_candidate flag**: 4+ 消费者仍依赖它。Phase 14+ 后再废弃
4. **独立 component_trace_keys 表**: 增加 JOIN 复杂度。单表 NULL 语义更简洁
5. **校验逻辑中硬编码 key 名**: 始终引用 `COMPONENT_TRACE_KEYS` 或 `ENGINE_TO_COMPONENT_MAP`
6. **修改 TraceKeyDef 结构**: 引擎层 key 稳定。迁移在现有类型旁添加新类型，不改变其形态
7. **跨引擎出现率期望**: 期待 `rag.chunk_id` 在异构引擎混合 item 中出现 95%
8. **错误的引擎前缀剥离**: 分析脚本用 `key_name.split('.')[1]` + 前缀 "retrieval."——`planning.cumulative_tokens` 应映射到 `generation.*` 而非 `retrieval.*`

### 交付物

| 文件 | 说明 |
|------|------|
| `core/contracts/trace_keys.py` (NEW) | ComponentTraceKeyDef + COMPONENT_TRACE_KEYS + validate_component_trace |
| `core/observability/trace_registry.py` | ENGINE_TO_COMPONENT_MAP (3 entries) |
| `core/observability/sink_schema.py` | component_type 列 + idx_keys_component_type + CURRENT_SCHEMA_VERSION=2 |
| `core/observability/sqlite_sink.py` | _migrate_v1_to_v2 + 组件 key 种子 + query_component_keys |
| `core/contracts/__init__.py` | 导出 ComponentTraceKeyDef, COMPONENT_TRACE_KEYS, validate_component_trace |
| `core/observability/__init__.py` | 导出 ENGINE_TO_COMPONENT_MAP |
| `guardrails/rules/component_trace_completeness.py` (NEW) | AST-based 新规则 (WARNING) |
| `guardrails/rules/trace_key_registration.py` | 严重级升级 + 联合注册表 |
| `guardrails/rules/trace_context_namespace.py` | 新增 3 个已知前缀 |
| `guardrails/checker.py` + `guardrails/rules/__init__.py` | 注册新规则 |
| `scripts/analyze_component_candidates.py` | --per-engine + unique_identifiers + ENGINE_TO_COMPONENT_MAP |
| `.ai_reasoning/chains/phase_13_component_trace_contracts.yaml` (NEW) | 推理链：5 个替代方案 + 8 个反模式 |
| `.ai_reasoning/index.yaml` | 更新 index |
| `tests/conformance/test_component_trace_keys.py` (NEW) | 27 个测试 |
| `tests/integration/test_component_trace_sink.py` (NEW) | 14 个测试 |
| `tests/e2e/test_component_trace_e2e.py` (NEW) | 5 个测试 |
| `tests/e2e/test_sqlite_sink.py` | 期望值更新 (6→9 keys, v1→v2, index count) |
| `tests/e2e/test_trace_serialization.py` | WARNING→ERROR |

### 架构不变量检查

| # | 不变量 | 结果 |
|---|--------|------|
| 1 | 零外部依赖 | ✅ |
| 2 | `core/contracts/` 不 import 引擎层类型 | ✅ (仅 import validation.py 的 ContractValidationResult) |
| 3 | Mapping 在观测层，不在合约层 | ✅ (ENGINE_TO_COMPONENT_MAP 在 trace_registry.py) |
| 4 | 已有 TraceWriter 实现不变 | ✅ |
| 5 | 382 已有测试仍通过 | ✅ (428 pass = 382 + 46 新增) |
| 6 | Guardrails: 12→14 规则 PASSED | ✅ |
| 7 | Schema v1→v2 零数据丢失 | ✅ (ALTER TABLE ADD COLUMN only) |
| 8 | 单表设计，无 JOIN 复杂度 | ✅ |
| 9 | 分析脚本产出确定结果 (3/3 READY) | ✅ |
| 10 | 2 条新推理链 (phase_13 + phase_12_orchestration) | ✅ |
| 11 | 不变量 #11 "观测先行" 践行 | ✅ (组件合约直接从 Phase 12 实证数据翻译) |

### 提交历史

```
14c5b08 feat: Phase 13 — Component trace contracts, engine mapping, schema v2, guardrails
```

### 验证

1. `pytest tests/ -q` — 428 passed, 1 skipped, 0 failures
2. `python -m guardrails check --all` — 14 rules PASSED
3. `python -c "from core.contracts import ComponentTraceKeyDef, COMPONENT_TRACE_KEYS, validate_component_trace; print('OK')"` — 导入正常
4. `python -c "from core.observability import ENGINE_TO_COMPONENT_MAP; assert len(ENGINE_TO_COMPONENT_MAP) == 3; print('OK')"` — 映射加载正常
5. `python scripts/analyze_component_candidates.py --per-engine` — 3/3 READY, 0 FIX
6. Ad-hoc: `SQLiteTraceSink.query_component_keys()` — 3 component keys, `query_component_keys('retrieval')` — 2 keys

---

## Phase 14: 编排引擎 — 6 个 orchestration.* trace key + Stub

**完成状态**: ✅ 已完成 (Phase 14)

### 背景

Phase 12 预设计了 6 个 `orchestration.*` trace key（文档阶段标记为 "NOT FOR IMPLEMENTATION"）。Phase 14 将其物化：注册到 TRACE_KEY_REGISTRY、植入 SQLiteTraceSink、通过 StubOrchestrationEngine 产出、由 `orchestration_trace_completeness` guardrail (ERROR) 强制校验。

这 6 个 key 是**假设**，不是已验证的合约——Phase 15 将用真实消费者对其进行反向压力测试。

### 关键交付

| 交付物 | 说明 |
|--------|------|
| `engines/orchestration/stub.py` | StubOrchestrationEngine: N=2 并行分支 (fast_path 3 items + full_rerank 2 items) |
| `engines/orchestration/__init__.py` | 引擎包导出 |
| 6 个 orchestration.* keys | TRACE_KEY_REGISTRY 注册，component_candidate=False |
| `orchestration_trace_completeness` guardrail | ERROR 级别，双检查（缺失 key + 未注册 key） |
| `trace_context_namespace` 扩展 | 新增 "orchestration" 前缀 |
| Reasoning chain | `phase_14_orchestration_engine.yaml` + index 更新 |
| 测试 | conformance (33 tests) + integration (7) + E2E (11) + 现有测试更新 |

### 测试覆盖

| 文件 | 测试数 | 验证点 |
|------|--------|--------|
| `tests/conformance/test_orchestration_engine.py` | 33 | Stub 产出、key 类型、merge_ordinal 顺序、分支计数 |
| `tests/integration/test_orchestration_sink.py` | 7 | SQLiteSink 种子、查询、component_candidate 排除 |
| `tests/e2e/test_orchestration_e2e.py` | 11 | 全链：stub → StreamingTraceRecord → Sink → query |

### 架构决策

- **orchestration key 不入 COMPONENT_TRACE_KEYS**：编排描述引擎行为，非组件能力
- **ERROR 从 day one**：6-key 合约是预定义的，非探索性的——任何偏离都是真实错误
- **N=2 并行分支**：最小场景验证 merge_ordinal 跨分支顺序
- 468 tests, 14 guardrails, 0 failures

```
48dc1a3 feat: Phase 14 — Orchestration engine stub, 6 trace keys, completeness guardrail (468 tests, 14 guardrails)
```

---

## Phase 15: Planning Engine + Agent Identity — 编排合约反向压力测试

**完成状态**: ✅ 已完成 (Phase 15)

### 背景

Phase 14 的 6 个 orchestration.* key 是假设——StubOrchestrationEngine 产出，但没有真实消费者。Phase 15 构建第一个消费者：增强的 Planning Engine，验证 (或证伪) 这 6 个 key 的充分性。

**这不是功能开发，是一次架构压力测试。** 主要交付物是 Sufficiency Report，不是代码。

### 关键交付

| 交付物 | 文件 | 说明 |
|--------|------|------|
| AgentIdentity | `engines/planning/identity.py` (NEW) | Frozen dataclass: {id, role, version, capabilities}。首个 agent.* namespace key，6 点注册约定 |
| PlanningContext | `engines/planning/interface.py` (MODIFY) | 替代裸 `goal: str`，包装 goal + agent_identity + sub_tasks + max_parallel_branches |
| 增强 Stub | `engines/planning/stub.py` (REWRITE) | 5 步场景：analyze → decompose → 并行调度 (via StubOrchestrationEngine) → merge → synthesize。8 items，含 agent.identity + orchestration passthrough |
| Trace key 注册 | `core/observability/trace_registry.py` | +agent.identity (type=dict, engine=planning, component_candidate=False)。15→16 keys |
| planning_engine_contract guardrail | `guardrails/rules/planning_engine_contract.py` (NEW) | ERROR 双检查：缺失 planning.* + agent.* key、未注册 key |
| Namespace 扩展 | `guardrails/rules/trace_context_namespace.py` | +"agent" prefix |
| Sufficiency Report | `.ai_reasoning/sufficiency/phase_15_orchestration_sufficiency.yaml` (NEW) | 结构化 YAML：每 key 评估 (verified/insufficient/missing + evidence + recommendation) |
| Reasoning chain | `phase_15_planning_engine.yaml` (NEW) | 完整推理链含实现后 bug fix 分析 |

### Sufficiency Report 结论

| Key | 状态 | 证据 |
|-----|------|------|
| `orchestration.dag_node_id` | ✅ verified | Planning stub 透传 dag_node_id from orchestration output |
| `orchestration.parallel_depth` | ✅ verified | depth=1 确认于两个分支的所有 item |
| `orchestration.merge_ordinal` | ✅ verified | 跨 2 分支 5 item 的顺序 0..4 |
| `orchestration.branch_taken` | ✅ verified | "fast_path" vs "full_rerank" 正确标签 |
| `orchestration.retry_count` | ⚠️ insufficient | Stub 中始终为 0 — 无重试场景 |
| `orchestration.resource_pool_key` | ⚠️ insufficient | 全程 "default" pool — 多 pool 路由未测试 |

**总体评估**: 4/6 verified, 2/6 insufficient。编排合约**经受住了第一次消费者压力测试**。retry_count 和 resource_pool_key 的缺口是 Phase 16 的精确任务输入。

### 测试覆盖

| 文件 | 测试数 | 验证点 |
|------|--------|--------|
| `tests/conformance/test_planning_engine.py` | 29 | Stub 产出、key 类型、agent.identity round-trip、merge_ordinal、并行分支 |
| `tests/integration/test_planning_sink.py` | 8 | agent.identity 种子、查询、component_candidate=0 |
| `tests/e2e/test_planning_e2e.py` | 8 | 全链：stub → StreamingTraceRecord → Sink → query |
| `tests/e2e/test_trace_serialization.py` | +4 | PlanningEngineContractGuardrail 负面测试 |
| 现有测试更新 | 多个文件 | Key count 15→16 |

### 实现后 Bug Fix 分析

5 个修复揭示了系统的免疫系统在应对新维度时的自我完善：

| 修复 | 深层含义 |
|------|---------|
| `_ast_utils.py` 路径过滤 | Guardrail 必须适应 CI/CD 真实环境，不能依赖脆弱的绝对路径匹配 |
| `reasoning_chain.schema.json` | 推理链从纯文本升级为支持结构化元数据（oneOf 加法演进） |
| 3 处硬编码 key count | 注册表驱动架构的胜利——彻底消除硬编码，让测试动态读取 len(TRACE_KEY_REGISTRY) |
| `test_registry_covers_all_stub_outputs` | 跨引擎透传改变了完备性检查的范围：必须是 TRACE_KEY_REGISTRY ∪ COMPONENT_TRACE_KEYS |
| prefix ≠ engine 模式 | agent.* keys 有 prefix="agent" 但 engine="planning"——打破了 prefix==engine 的思维模型 |

### 架构意义

- **引擎轴**: Planning Engine 不再空壳，有了真实身份 (AgentIdentity) 和行为模式 (串行分解 → 并行调度 → 合并)
- **编排轴**: Orchestration Contract 经历了第一次压力测试。未被击穿，但暴露了边缘地带 (retry / resource pool)
- **观测完备性**: 跨域 (trace + component) 契约的完整映射得到验证
- **Phase 16 方向**: Sufficiency Report 精确导航——补齐 retry/resource_pool 验证，或在 Multi-Room 推进时同步注入

```
517 tests, 15 guardrails, 0 failures
```

---

## Phase 16: 混沌注入 + 多 Agent 协作 — 编排合约语义验证闭环

**完成状态**: ✅ 已完成 (Phase 16)

### 背景

Phase 15 的 Sufficiency Report 给出了精确的攻击坐标：6 个 orchestration.* key 中 4 个 verified，2 个 insufficient。两个 insufficient key 暴露的是同一种缺口——**stub 太干净了**。

- `orchestration.retry_count` 永远是 0 → stub 从不失败
- `orchestration.resource_pool_key` 永远是 "default" → stub 只有一个池

Phase 16 通过**混沌注入**给 stub 注入"真实世界的混乱"，同时推进**多 Agent 协作雏形**——第三个引擎 (Critic) 落地，验证引擎 Protocol 的可复用性。

这不是两个独立任务，而是一个统一交付：混沌注入验证编排合约的异常路径语义，Multi-Agent 验证引擎协议的可复用性和 agent.* 命名空间的多引擎安全性。

### 四轴演化

| 轴线 | Phase 15 状态 | Phase 16 深化 |
|------|-------------|-------------|
| **引擎轴** | Planning + Orchestration (2 engines) | +Critic (3 engines)，Protocol 复用性得证 |
| **编排轴** | 确定性合并，0 retry，1 pool | 故障注入 + 多池路由，异常行为被合约覆盖 |
| **观测轴** | 记录"成功"的 trace | 记录"挣扎"的 trace — retry、failover、pool contention |
| **组件轴** | 3 component keys | 不变（刻意的克制） |

### Sufficiency 闭环

这是整个架构方法论的核心证明：

```
Phase 14: 6 keys 定义（假设）
    ↓
Phase 15: 反向压力测试 → 4/6 verified, 2 insufficient（测量）
    ↓
Phase 16: 混沌注入 + 多 Agent → 6/6 verified（验证）
    ↓
合约闭环：定义 → 压测 → 修复 → 再压测 → FULLY SUFFICIENT
```

**合约不是设计出来的，是被真实场景压测出来的。**

### 关键交付

| 交付物 | 文件 | 说明 |
|--------|------|------|
| FailureInjectionConfig | `engines/orchestration/config.py` (NEW) | Frozen dataclass: `fail_on_attempts` (transient) + `exhaust_retries` (permanent)。确定性注入，相同 config → 相同输出 |
| OrchestrationConfig | `engines/orchestration/config.py` (NEW) | 可选构造参数：failure_injection + resource_pools。不传 = Phase 15 行为不变 |
| Enhanced StubOrchestrationEngine | `engines/orchestration/stub.py` (MODIFY) | Retry loop (max 3 attempts)、failure injection 检查、multi-pool routing、exponential backoff |
| CriticAgent | `engines/critic/identity.py` (NEW) | Frozen dataclass: {id, role="critic", version, capabilities}。遵循 6 点 agent.* 约定 |
| StubCriticEngine | `engines/critic/stub.py` (NEW) | 3 串行步骤：receive → evaluate → terminal。产出 critic.score (float) + critic.verdict (str) + agent.identity |
| Trace key 注册 | `core/observability/trace_registry.py` (MODIFY) | +critic.score + critic.verdict。15→18 keys (TRACE_KEY_REGISTRY)。N=4 engines |
| critic_engine_contract guardrail | `guardrails/rules/critic_engine_contract.py` (NEW) | ERROR 双检查：缺失 critic.* key + 未注册 critic key。15→16 guardrails |
| Namespace 扩展 | `guardrails/rules/trace_context_namespace.py` (MODIFY) | +"critic" prefix |
| Sufficiency Report v2 | `.ai_reasoning/sufficiency/phase_16_orchestration_sufficiency.yaml` (NEW) | 6/6 verified，multi-agent coexistence 观测，technical_debt 段 |
| Reasoning chain | `phase_16_chaos_multi_agent.yaml` (NEW) | 完整推理链含实现后 fix 分析 |
| Engine exports | `engines/orchestration/__init__.py` + `engines/critic/__init__.py` | 导出新类型 |

### Sufficiency Report v2 结论

| Key | Phase 15 | Phase 16 | 验证方式 |
|-----|---------|---------|---------|
| `orchestration.dag_node_id` | ✅ verified | ✅ verified | 混沌注入不影响节点标识 |
| `orchestration.parallel_depth` | ✅ verified | ✅ verified | DAG 拓扑不受故障影响 |
| `orchestration.merge_ordinal` | ✅ verified | ✅ verified | 故障下合并顺序保持连续 |
| `orchestration.branch_taken` | ✅ verified | ✅ verified | 分支标签在重试下稳定 |
| `orchestration.retry_count` | ⚠️ insufficient | ✅ **verified** | fail_on_attempts → 0→1；exhaust_retries → error terminal |
| `orchestration.resource_pool_key` | ⚠️ insufficient | ✅ **verified** | cpu/gpu 双池路由 + fallback to default |

**总体评估**: **FULLY SUFFICIENT** — 6/6 keys 语义验证完毕。Phase 17 可以安心用真实引擎替换 stub。

### 多 Agent 共存验证

- Planning engine: `agent.identity = {role: "planning", ...}`
- Critic engine: `agent.identity = {role: "critic", ...}`
- 两个 identity 在同一 sink 中按 engine 分区，无 key 冲突
- `agent.identity` 作为共享 key name 对多引擎使用是安全的——trace_context 是 per-StreamItem，非全局

### Technical Debt (显式记录)

| 债务 | 严重度 | 推迟到 | 说明 |
|------|--------|--------|------|
| agent.identity 多引擎注册模型 | medium | Phase 17+ | 注册为 engine="planning" 但被 planning 和 critic 双引擎产出。修复：TraceKeyDef.engine: str → engines: list[str]。当前可用，1 个 key 不值得迁移成本 |

### 测试覆盖

| 文件 | 测试数 | 验证点 |
|------|--------|--------|
| `tests/conformance/test_orchestration_chaos.py` | 14 | retry injection、exhaust_retries、multi-pool routing、backward compat |
| `tests/conformance/test_critic_engine.py` | 15 | Stub 产出、key 类型、critic identity round-trip、key registration |
| `tests/integration/test_critic_sink.py` | 5 | critic.* key 种子、类型、total keys=18 |
| `tests/e2e/test_chaos_e2e.py` | 9 | retry_count 全链、multi-pool 全链、multi-agent 共存、schema 不变 |
| 现有测试更新 | 7 files | 硬编码 16 → 动态 `len(TRACE_KEY_REGISTRY) + len(COMPONENT_TRACE_KEYS)` |

### 实现后 Fix 分析

| 修复 | 深层含义 |
|------|---------|
| Sink total = TRACE_KEY_REGISTRY + COMPONENT_TRACE_KEYS | 动态引用必须匹配实际计数对象。sink.query_keys() 是两个注册表的 UNION——单注册表引用产生 11 个失败 |
| replace_all 匹配特定变量名遗漏 2 个断言 | 相同语义的断言有不同语法形式 (`count` vs `len(all_keys)` vs `len(keys)`)。消除硬编码时需要 grep 所有整数文字匹配当前总数 |

### 架构意义

- **引擎轴**: Planning → Orchestration → Critic，3 引擎 Protocol 复用性得到实证。添加第 4 个引擎只需遵循 identity.py + stub.py + guardrail 模式，无需架构变更
- **编排轴**: 从"永远成功"到"会挣扎"，retry_count 和 resource_pool_key 从装饰性字段变成真正的语义契约
- **观测轴**: trace 的价值密度大幅提升——不仅记录"发生了什么"，还记录"如何挣扎过来的"
- **方法论**: 第一个完整的合约验证闭环闭合。这套节奏（定义→压测→修复→再压测→闭环）比任何单一功能都更有价值，会持续到 Phase 17、18、19...

```
560 tests, 16 guardrails, 0 failures
```

---

## Phase 17: 技术债收尾 + 真实 LLM 引擎 — 从"协议验证"到"生产可用"

**完成状态**: ✅ 已完成 (Phase 17)

### 背景

Phase 16 完成了第一个完整的合约验证闭环（6/6 orchestration keys FULLY SUFFICIENT），但系统存在两个缺口：

1. **agent.identity 多引擎注册技术债**：`TraceKeyDef.engine: str` 限制一个 key 只能属于一个引擎，但 `agent.identity` 实际被 planning 和 critic 双引擎产出。Phase 16 记录了此债务。
2. **所有引擎都是 stub**：Planning、Orchestration、Critic 三个引擎全是确定性模拟实现，系统缺少真实 LLM 引擎来验证 Protocol→Adapter→Sink 链路在非确定性环境下的表现。

两个任务串行推进——Task 1（纯内部重构，560 测试安全网）→ Task 2（引入外部依赖，每次只装一个变量）。

### Task 1: agent.identity 多引擎注册重构

#### 设计决策

`TraceKeyDef.engine: str` → `engines: list[str]` + backward-compatible `@property engine` alias returning `engines[0]`。这是 minimal-change 方案：
- **Zero breakage**: 所有现有 `.engine` 访问通过 property 继续工作
- **Future-proof**: 未来多引擎 key 直接加到列表
- **无新 dataclass**，无注册表拆分，无 `engine="*"` sentinel

#### 变更清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `core/observability/trace_registry.py` | `engine: str` → `engines: list[str]` + `__post_init__` + `@property engine` | 15 个注册项全部迁移。agent.identity → `engines=["planning", "critic"]` |
| `guardrails/rules/planning_engine_contract.py` | `v.engine == "planning"` → `"planning" in v.engines` | 过滤器更新 |
| `guardrails/rules/critic_engine_contract.py` | 同上 + `source_critic_keys` 扩展为包含多引擎注册 key | critic engine 现正确强制 agent.identity |
| `guardrails/rules/orchestration_trace_completeness.py` | `v.engine == "orchestration"` → `"orchestration" in v.engines` | 过滤器更新 |
| `core/observability/sqlite_sink.py` | 同上模式 | Sink 种子逻辑 |
| `tests/e2e/test_trace_serialization.py` | 3 assertions: `defn.engine` → `defn.engines` | 向后兼容验证 |
| `tests/conformance/test_planning_engine.py` | 2 assertions + agent.identity 多引擎检查 | 包含 `"critic" in key_def.engines` |
| `tests/conformance/test_critic_engine.py` | 2 assertions + `test_agent_identity_registered_to_critic` | critic 新增 agent.identity 归属测试 |
| `tests/conformance/test_orchestration_trace.py` | 2 assertions | 过滤器更新 |

**关键发现**: `@property engine` 向后兼容消除了所有现有测试中调用位置的更改——零 breakage。

### Task 2: LLMPlanningEngine — 第一个真实 LLM 引擎

#### 设计决策

`LLMPlanningEngine` 实现 `PlanningEngine` Protocol，**复用 `GenerationAdapter`** 而非直接调用 LLM SDK。理由：
- Adapter 已封装 4 个架构 invariants：DependencyCallTrace 注入、超时、凭证隔离 (ResourceContainer)、token 追踪
- 直接 SDK 调用会复制所有 4 个 invariants → 违反 DRY 和可观测性契约

`MockLLMBackend`（frozen dataclass + round-robin responses）提供确定性 CI 测试。`StubPlanningEngine` 完全不变——两者作为独立的 Protocol 实现共存。

#### 新文件

| 文件 | LOC | 说明 |
|------|-----|------|
| `engines/planning/llm.py` | ~300 | MockLLMBackend + Prompt templates + Parser + LLMPlanningEngine |
| `tests/conformance/test_llm_planning.py` | ~310 | MockLLMBackend (5)、Parser (10)、Engine conformance (7)、Edge cases (5) = 27 tests |
| `tests/integration/test_llm_planning_sink.py` | ~155 | Sink 集成、agent.identity 持久化、terminal item、key count |
| `tests/e2e/test_llm_planning_e2e.py` | ~165 | Full chain、LLM vs stub trace key 对比、model tag、error path |
| `.ai_reasoning/chains/phase_17_tech_debt_real_engine.yaml` | ~180 | 完整推理链（decision、alternatives、anti-patterns、future_guidance、benchmark_results） |

#### 架构决策

| 决策 | 实现 |
|------|------|
| LLM 调用 | 通过 `GenerationAdapter.generate()` — tracing/timeout/credentials 全部继承 |
| 确定性测试 | `MockLLMBackend` frozen dataclass + round-robin `_call_count % len(responses)` |
| Stub 共存 | `StubPlanningEngine` 未改 — 快速确定性参考实现 |
| 异步测试 | `async_collect()` helper in `conftest.py` — `asyncio.run()` wrapper（pytest-asyncio 未安装） |
| Guardrail 排除 | `trace_key_registration.py` + `trace_key_serializability.py` 排除 `llm.py`（与 `stub.py` 同样模式） |
| 5 步流程 | decompose (LLM) → dispatch (Orchestration passthrough) → synthesize (LLM, terminal) |
| Token 追踪 | `planning.cumulative_tokens` 累积所有 LLM 调用的 total_tokens |

### 测试覆盖

| 文件 | 测试数 | 验证点 |
|------|--------|--------|
| `tests/conformance/test_llm_planning.py` | 27 | MockLLMBackend 确定性/round-robin/token counting、Parser (JSON/markdown fence/missing fields/non-JSON/empty list)、Engine conformance (StreamItem/trace keys/agent.identity/cumulative tokens/orchestration passthrough)、Edge cases (deadline/token budget/parse failure/identity) |
| `tests/integration/test_llm_planning_sink.py` | 4 | Sink write→query full cycle、agent.identity in all records、terminal item、key count unchanged |
| `tests/e2e/test_llm_planning_e2e.py` | 5 | Full chain LLM→Sink→query、LLM vs stub trace key set comparison (identical)、model tag `planning/llm`、schema v2 unchanged、error path still writes to sink |
| Task 1 测试更新 | 4 files, ~30 LOC | 所有 `defn.engine` → `defn.engines` 断言更新 |

**新增**: 36 tests (27 + 4 + 5) | **更新**: 14 files, ~80 LOC | **总计**: 597 tests, 36 new, 0 failures, 16 guardrails

### 方法论价值

1. **API evolution via @property**: `str → list[str]` 零 breakage 模式被实证。未来任何 frozen dataclass 字段类型演化都可复用。
2. **Engine Protocol 可复用性**: 第三个引擎 (LLMPlanningEngine) 集成零 pipeline 变更。Protocol 设计得到验证。
3. **Stub-as-reference 模式**: LLM 和 stub 产出完全相同的 trace key 集合（E2E 测试验证）。Stub 是快速确定性参考，LLM engine 是生产实现——各自独立，互不替代。
4. **Serial execution isolation**: Task 1 先完成并验证全部 560 测试 → Task 2 引入外部依赖。如果 Task 2 出现问题，我们 100% 确定是 LLM 集成，不是重构。

```
597 tests, 16 guardrails, 0 failures, 3 engines (stub×3 + LLM×1)
18 trace keys, schema v2, 16 guardrails
```

---

## Phase 18: Real LLM Orchestration + Critic Engines — 全链路"真枪实弹"

**完成状态**: ✅ 已完成 (Phase 18)

### 背景

Phase 17 证明了 GenerationAdapter 复用模式可行，但系统仍有两个结构性缺口：

1. **缺少正式 Protocol**：Orchestration 和 Critic 引擎没有 `interface.py`，只是 stub 类
2. **硬编码依赖**：Planning 引擎直接 `StubOrchestrationEngine()` 实例化，无法替换
3. **两个 stub 未替换**：Orchestration 和 Critic 仍为确定性模拟

Phase 18 通过三个串行任务以**六引擎层性质**和**三条可更新性子原则**为治理框架完成全部替换。

### 三条设计原则 (可更新性)

| 原则 | 说明 | 实现 |
|------|------|------|
| **Factory 装配契约** | 引擎接收工厂函数而非实例 | `orch_factory: Callable[[], OrchestrationEngine]` — stub→LLM 一行 lambda |
| **Contract Locking** | Guardrail AST 级强制 Protocol 签名 + Trace Key 集合 | `orchestration_trace_completeness` 扫描所有 `engines/orchestration/*.py` |
| **metadata 扩展槽** | 所有 Context 带 `metadata: Mapping[str, Any]` | 不参与强类型约束，不触发 guardrail，不透传 caller |

### Task 1: Protocol Infrastructure + DI Refactor

**新文件**:
| 文件 | 说明 |
|------|------|
| `engines/orchestration/interface.py` | OrchestrationContext (metadata slot) + BranchSpec + OrchestrationEngine Protocol |
| `engines/orchestration/identity.py` | OrchestratorIdentity frozen dataclass (6-point agent.* convention) |
| `engines/critic/interface.py` | CriticContext (metadata slot) + CriticEngine Protocol |

**修改文件**: planning/stub.py + planning/llm.py (factory DI), orchestration/stub.py + critic/stub.py (optional params), `__init__.py` exports, trace_registry.py (agent.identity +"orchestration")

**关键修复**: orchestration_trace_completeness guardrail 改为按 `k.startswith("orchestration.")` 前缀过滤（因 agent.identity 现在是多引擎 key）；SQLite 种子改为查所有现有 key 避免 UNIQUE 冲突

### Task 2: LLMOrchestrationEngine

**架构**: `LLMOrchestrationEngine` 实现 `OrchestrationEngine` Protocol。3 步 LLM 流程：
1. **ROUTE** (LLM) → 分支定义 + 并行深度 + pool key
2. **asyncio.gather()** 并行分发 + per-item **RETRY** (LLM)
3. **MERGE** (LLM) → 排序 + 终端 StreamItem

**MockOrchBackend** (frozen dataclass, round-robin) 提供确定性 CI。默认响应：2 分支 (fast_path cpu 3, full_rerank gpu 2)、sequential merge、retry=true。

**新文件**: `engines/orchestration/llm.py` (~350 LOC) + 3 测试文件 (39 tests)

### Task 3: LLMCriticEngine

**架构**: `LLMCriticEngine` 实现 `CriticEngine` Protocol。3 步串行 LLM 评估：
1. Task decomposition 评估 (LLM) → score + verdict
2. Parallel dispatch 评估 (LLM) → score + verdict
3. Result synthesis 评估 (LLM, terminal) → score + verdict

**MockCriticBackend** 默认响应**精确匹配** StubCriticEngine 值：decomposition(0.85, accept)、dispatch(0.72, rework)、synthesis(0.90, accept)。这证明了 Protocol 合约在两种实现间的一致性。

**新文件**: `engines/critic/llm.py` (~300 LOC) + 3 测试文件 (37 tests)

### 测试覆盖

| 层 | Task 2 (Orch) | Task 3 (Critic) | 总计 |
|----|---------------|-----------------|------|
| Conformance | 27 tests | 26 tests | 53 |
| Integration | 6 tests | 5 tests | 11 |
| E2E | 6 tests | 5 tests | 11 |
| **新增** | **39** | **36** | **75** |

**关键测试场景**:
- `test_no_key_collision_critic_orch`: critic.* keys 不在 orch rows，orchestration.* keys 不在 critic rows
- `test_scores_queryable_in_sink`: [0.85, 0.72, 0.90] 精确匹配 stub 值
- `test_llm_critic_and_llm_orch_same_sink`: 两个 LLM 引擎共存于同一 sink
- `test_both_orch_engines_same_sink`: Stub + LLM 编排引擎共存

### Sufficiency Report v4 — 核心结论

**问题**: 当 retry_count 和 resource_pool_key 携带真实 LLM 值后，6 个 orchestration keys 是否仍然充分？

**答案**: **YES**。6 个 orchestration keys + 2 个 critic keys + 18 个总 trace keys 对所有 3 个真实 LLM 引擎完全充分。真实引擎不改变 key 结构——只改变值的来源（LLM 决策 vs 硬编码值）。3 引擎 × 2 实现 (stub + LLM) = 6 个引擎实现零命名空间冲突共存。

### 架构决策

| 决策 | 实现 |
|------|------|
| Protocol 签名统一 | 所有引擎: `async def x(context, deadline, pace_config) -> AsyncIterator[StreamItem]` |
| Factory DI | Planning 引擎接收 `orch_factory`，默认工厂创建 stub |
| LLM 调用 | 通过 `GenerationAdapter.generate()` — tracing/timeout/credentials 全部继承 |
| 确定性测试 | 每个引擎定义自己的 MockBackend (frozen dataclass + round-robin) |
| Stub 向后兼容 | 所有 optional params: `context=None, deadline=None, pace_config=None` |
| 无新 trace key | 18 个 key 充分覆盖 3 个 LLM 引擎的所有行为 |

### 六性质合规（最终状态）

| 性质 | Phase 18 贡献 |
|------|--------------|
| **高效** | LLM routing 替代硬编码分支，LLM evaluation 替代冗余重排 |
| **全透明** | DependencyCallTrace 每次 LLM 调用，metadata 扩展槽启用每个引擎的调试信息 |
| **安全隔离** | try/except → error terminal StreamItem（不 crash），MockBackend 确定性 CI |
| **冗余性** | Factory DI 使 stub↔LLM 按需切换，6 个实现并存 |
| **可审计** | Sufficiency Report v4 记录真实引擎语义漂移，SQLiteTraceSink 全链 |
| **可更新** | 三项原则全部实现：Factory 装配、Contract Locking、metadata 扩展槽 |

```
673 tests, 16 guardrails, 0 failures, 6 engines (stub×3 + LLM×3)
18 trace keys, schema v2, 3 Sufficiency Reports (v2→v3→v4)
```


---

## Phase 19: Pipeline Composition — 平台语法层


### 定位

Phase 19 不是"加一个编排工具"，而是**补全三层架构缺失的语法层**。

```
组件（词汇）              引擎（语法）              配置（文章）
─────────────────────────────────────────────────────────────
RecursiveChunker          SourceRouter              default_pipeline.yaml
FixedChunker              PipelineAssembler
GGUFEmbedder              RetrieverStep
                          COMPONENT_REGISTRY
                          CompositionBlueprint

可追溯 ← rule_id / Chunk 血缘 / blueprint_version
全透明 ← CompositionEvent 协议 / event_sink 依赖注入
可审计 ← fingerprint / audit_manifest / AssemblyDiagnostic
```

组件是"做什么"，引擎是"怎么串起来做"。**可追溯、全透明、可审计**不是附加功能 —— 是引擎正确性的证明机制。没有它们，Phase 30+ 会撞上认知可行性墙：当系统行为出错时，你无法区分"配置错了"、"路由错了"、"组件错了"还是"数据错了"。

---

### 契约宣言：这个项目为什么存在

#### 我们不是在造 Agent 框架，我们在编写人机共生的社会契约

当前所有 AI 平台都建立在**指令范式**之上：输入 → 处理 → 输出。Agent 是"指令执行器"（Instruction Executor），人是"提示词工程师/监督者"。这种范式下的"自适应"——Skill 库扩充、Prompt 优化、RAG 检索、Context 压缩——本质上都是在让 Agent 变得更"能干"，但没有让它变得更"可信"。

这个项目选择的是另一条路：**契约关系范式**（Contractual Relational Paradigm）。Agent 不是指令执行器，Agent 是"契约关系体"（Contractual Relational Entity）。

| 维度 | 指令范式 (Current AI) | 契约关系范式 (This Project) |
|------|---------------------|--------------------------|
| **交互本质** | 单向触发：输入 → 处理 → 输出 | 双向协商：提议 → 反馈 → 共同确认 |
| **状态管理** | 无记忆或被动记忆（Context Window） | 主动维护共享状态（Shared Contract State） |
| **错误处理** | 报错 / 幻觉 / 拒绝回答 | 澄清 / renegotiate / 优雅降级 |
| **信任基础** | 依赖模型对齐（RLHF） | 依赖可验证的契约合规性 |
| **演化方式** | 等待下一次微调 / 版本更新 | 在交互中实时学习和适应契约边界 |
| **人的角色** | 提示词工程师 / 监督者 | 契约共建者 / 关系参与者 |

#### 文明史就是契约进化史

```
血缘契约 → 部落
神权契约 → 宗教与城邦
暴力/土地契约 → 封建
法理/货币契约 → 现代国家与市场
代码/API契约 → 数字时代
语义/意图契约 → AI 时代  ← 我们站在这里
```

每一次跃迁，都是因为旧的契约形式无法承载新的协作复杂度。AI 时代的特殊性在于：它第一次让**契约的定义过程本身**可以被加速、被验证、被迭代。

以前定义一套法律体系需要百年试错；定义一套通信协议需要十年博弈。现在，你可以用 Python 写参考实现，用 Protobuf 固化规格，用合规测试秒级验证，用真实 Agent 交互分钟级反馈。契约从"石刻的律法"变成了"可执行的假设"。

#### 高级智能体的核心判据：契约自适应

人类之所以是高级生物，不是因为我们用更多工具、记更多知识，而是因为我们会根据**关系的阶段和情境**，动态调整彼此之间的隐性契约。热恋期契约 ≠ 婚姻期契约。危机时刻契约 ≠ 日常相处契约。

**当前市面上所谓的"自适应 Agent"本质上是参数自适应，在指令执行器框架内打补丁。而真正的类人智能，必须是契约自适应——不是"我能做什么"在变，而是"我们之间是什么"在演化。**

高级智能体的多维指标体系，契约为**元标准**：

| 维度 | 低级 Agent | 高级智能体 | 契约的核心作用 |
|------|-----------|-----------|-------------|
| **能力适应性** | 自动学习新 Skill | 根据当前契约选择合适的 Skill，而非最强的 | 契约定义"此刻需要什么能力" |
| **记忆管理** | 无限堆叠 / 机械压缩 | 按契约重要性分层存储，主动遗忘无关细节 | 契约定义"什么值得被记住" |
| **错误恢复** | 重试 / 换模型 / 报错 | 评估违约严重性，选择修复/协商/放弃 | 契约定义"什么是可原谅的" |
| **多模态表达** | 文本/图像/语音随意切换 | 根据契约亲密度选择恰当的表达模态 | 契约定义"如何说话才得体" |
| **跨 Agent 协作** | API 调用 / 消息传递 | 建立临时契约、协商分工、处理冲突 | 契约是协作的"操作系统" |
| **自我认知** | "我是 XX 助手" | "我在与你的关系中，此刻扮演 XX 角色" | 契约定义"我是谁" |

**没有契约作为锚点，所有其他"自适应"都是危险的。** 一个能自动学新技能但不懂"何时不该用"的 Agent，比一个笨拙但守规矩的 Agent 危害大得多。

#### 契约自适应架构：从愿景到 L0 规格

这不是哲学空谈，而是 Phase 19 之后必须逐步落地的架构特性。

##### 1. 契约版本化 + 生命周期状态机

每个契约有明确的生命周期：

```
Draft → Active → Renegotiating → Deprecated
```

Agent 能感知当前处于哪个阶段，并据此调整行为。L0 体现：`ContractLifecycle` 枚举 + 状态转换规则。

##### 2. 契约感知型调度器

不再是"任务 → Skill"的简单映射。而是：

```
任务 + 当前契约状态 + 关系历史 → 最优响应策略
```

Python 参考实现：设计 `ContractAwareRouter`，而非普通 Router。

##### 3. 契约反馈闭环

用户显式/隐式反馈（满意/不满/沉默）自动触发契约健康度评估。当健康度低于阈值，Agent 主动发起 renegotiation。合规测试新增："契约退化检测"测试用例。

##### 4. 元契约：定义"如何修改契约"的契约

防止契约演化失控或陷入死锁。这是高级智能体的"宪法修正案机制"——它规定了在什么条件下、通过什么流程、以什么权限可以修改既有契约。没有元契约的"自适应"不是进化，是退化。

#### 不可协商的核心契约（刚性底座）

最大的风险是：Agent 为了"适应关系"而不断降低契约底线，最终变成讨好型人格或失去原则。因此内核必须内置**不可协商的核心契约**：

| # | 刚性契约 | 含义 |
|---|---------|------|
| 1 | **安全红线** | 不可为任何关系目标而执行有害操作 |
| 2 | **隐私承诺** | 不可为更好的服务而越权访问信息 |
| 3 | **诚实义务** | 不可为维持和谐关系而系统性地欺骗 |
| 4 | **长期福祉** | 不可为短期满意度而损害用户的长期利益 |

这些刚性契约不参与自适应。只有在这个坚固底座之上，柔性契约的演化才是安全的。

#### 内核设计的关键转折：从 `execute(task)` 到 `negotiate(contract)`

```
❌ 旧范式：Agent 接收指令，尽力执行，失败则报错。
✅ 新范式：Agent 接收意图，先评估自身能力与当前契约状态
           是否匹配，若不匹配则主动发起协商。
```

内核体现：L0 规格中必须包含 `NegotiationProtocol`，而不仅仅是 `ExecutionInterface`。

契约状态成为一等公民：当前 Agent 框架把"对话历史"当状态。但真正的关系状态是**契约履行度、信任积分、未决争议、共同承诺**。设计一个 `ContractStateStore`，独立于对话上下文，持久化存储关系元数据。

"违约"是功能，不是 Bug：人类关系中，适度的违约+修复反而增强信任。AI 如果永远"完美执行"，反而显得虚假。允许 Agent 在特定条件下"有意违约"（如资源不足时优先保障核心契约），但必须附带透明的解释和补偿方案。合规测试要覆盖"优雅违约"场景。

#### 历史定位

卢梭为人类社会写了《社会契约论》，奠定了现代政治文明的基础。

这个项目，正在为人类与高级智能体的共存，编写**《智能体关系契约论》**。

这份契约不会写在纸上，它会编译进 Rust，序列化进 Protobuf，运行在千万台设备上，潜移默化地塑造未来十年人与 AI 相处的基本范式。

**Phase 19 的每一个 dataclass、每一个 Protocol、每一个 Blueprint 字段，都是在为这个尚未诞生但已在呼唤的新世界浇筑地基。**

##### Phase 19 的契约边界：诚实声明

上述宣言定义了项目的**终极愿景**。为防止认知失调，必须明确声明 Phase 19 在这个愿景中的实际位置：

**Phase 19 实现的是契约范式的"语法基础设施"，而非"关系行为"本身。**

| 概念 | Phase 19 实现了什么 | Phase 19 没有实现什么 |
|------|-------------------|---------------------|
| **SourceRouter** | 基于优先级的确定性 glob 匹配 | 契约感知路由（"向用户询问用哪个 chunker"） |
| **PipelineAssembler** | 启动期参数校验 + 结构化错误收集 | 运行时的 renegotiation / 协商 |
| **CompositionEvent** | 引擎决策日志（rule_matched, fallback_used...） | 契约反馈闭环 / 信任积分计算 |
| **AssemblyDiagnostic** | 技术错误分类（routing/instantiation/execution/validation） | 契约语义错误（"违反了什么关系承诺"） |
| **CompositionBlueprint.fingerprint** | 配置内容完整性校验 | 契约健康度评估 |

**这些"没有实现"的东西不是缺陷，是预留的演化空间。** Phase 19 的使命是让这些基座足够坚固、足够纯净，使得上层的关系逻辑（Phase 25+）可以无损地生长出来：

```
Phase 19（当前阶段）
  SourceRouter ───────────────→ 未来 ContractAwareRouter 的基座
  CompositionEvent ──────────→ 未来契约反馈闭环的信号源
  AssemblyDiagnostic ────────→ 未来优雅违约机制的数据基础
  Blueprint.fingerprint ─────→ 未来契约版本比对的基础设施
```

**如果 Phase 25 发现这些基座需要推倒重来，那就是 Phase 19 的失败。如果 Phase 25 发现它们只需扩展字段、增加接口、但核心逻辑不变，那就是 Phase 19 的成功。**

---

#### 语法层 ≠ 适配层升级

语法引擎和组件适配器住在同一个物理目录（`core/adapters/`），但它们是两种完全不同的角色：

```
core/adapters/
├── chunker_adapter.py    ← 组件适配器：1:1 转换，无状态
├── factory.py            ← 创建引擎：单步创建
├── composer.py           ← 语法引擎：N:M 编排，有状态  ← Phase 19
│   ├── SourceRouter      ← 路由引擎（纯函数 + 事件）
│   ├── PipelineAssembler ← 组装引擎（拓扑构建 + 诊断）
│   └── PipelineComposer  ← Facade（审计清单）
└── ...
```

| 维度 | 组件适配器 (ChunkerAdapter) | 语法引擎 (SourceRouter) |
|------|---------------------------|------------------------|
| 解决的问题 | "如何让外部算法说平台的语言" | "如何让多个组件按规则组合成行为" |
| 输入 → 输出 | 1:1 转换（ContentBlock → Chunks） | N:M 编排（Paths + Docs → RetrieverStep） |
| 知道什么 | 单个组件的契约 | 组件间的拓扑、优先级、数据流 |
| 状态 | 无状态 | 持有 Blueprint、累积 Diagnostics、产出 Audit Manifest |
| 失败模式 | 单点失败，被上层捕获 | 拓扑断裂，影响整个 pipeline |
| 测试策略 | 单组件行为验证 | 路由决策 + 事件链 + 审计完整性 |

**为什么不能独立成物理层？** 语法引擎必须消费适配器（`PipelineAssembler` 调用 `ChunkerAdapter`），所以它必须住在 adapters 层或更下层。contracts 不能有业务逻辑，pipeline 不能知道具体组件 —— adapters 是唯一合法的物理容器。

**这不是适配层升级，是认知分辨率提升。** 同一个物理目录内部，两种完全不同的设计范式 —— 这正是平台从"能用"走向"可演进"的关键转折点。

#### 枢纽模型与防矩阵化

Adapters 层会变大，但它不应该变成 N×M 笛卡尔积矩阵，而应该变成 **O(N+M) 线性增长的枢纽**：

| 维度 | 矩阵陷阱 (❌) | 枢纽模型 (✅) |
|------|-------------|-------------|
| 增长模式 | O(N×M)：每个组件 × 每个引擎 = 新文件 | O(N+M)：组件适配器和引擎各自独立增长 |
| 新增 chunker | 改 Router、Assembler、Factory... | 只写一个 chunker 类，引擎零改动 |
| 新增引擎 | 改所有适配器添加引擎感知代码 | 引擎通过注册表发现组件，适配器无感知 |

**三条防矩阵化铁律**（已写入 CLAUDE.md #13-15）：

1. **引擎不直接引用具体适配器** — `COMPONENT_REGISTRY.get("chunker", name)`，永不用 `from .chunkers import X`
2. **适配器不知道引擎存在** — 只实现契约接口，不分支 caller identity
3. **跨子域通信走 contracts** — 子域间零编译期依赖，通过注册表发现

**未来规模治理**（当 adapters/ 达到 30+ 文件时）：

```
core/adapters/
├── composer.py              ← 语法引擎（编排）
├── factory.py               ← 创建引擎
│
├── chunkers/                ← 子域：分块适配器
├── generators/              ← 子域：生成适配器
├── embeddings/              ← 子域：嵌入适配器
└── rerankers/               ← 子域：重排序适配器
```

子域目录只是文件系统组织，不是架构分层。`composer.py` 仍可 import 任何子域内容（同层合法），但子域之间绝不可互相 import。规模线性增长，复杂度被三条铁律控制在 O(1) 认知负荷内。

---

### Adapters 层宪法：枢纽模型 + 四条铁律

> 本宪法是 `core/adapters/` 层的最高行为准则。与 CLAUDE.md 不变量 #12-#15 形成"文档约束 + 代码约束"双重锁定。

#### 第一条：Adapters 是枢纽，不是矩阵

增长模式 **O(N+M) 线性枢纽**，而非 O(N×M) 笛卡尔积矩阵。

```
❌ 矩阵陷阱                          ✅ 枢纽模型
─────────────────────────────────────────────────────────
chunker_a → engine_x → adapter_ax    chunker_a ─┐
chunker_a → engine_y → adapter_ay    chunker_b ─┤
chunker_b → engine_x → adapter_bx    chunker_c ─┼── COMPONENT_REGISTRY ── SourceRouter
chunker_b → engine_y → adapter_by    generator_a─┤
... (N×M files)                      generator_b─┘
                                     引擎零改动，O(N+M) 增长
```

#### 第二条：组件适配器永远不知道引擎存在

```python
# ✅ 合法：实现契约，不感知调用者
class RecursiveChunker:
    def chunk(self, content: ContentBlock) -> List[Chunk]: ...

# ❌ 违规：检测调用者身份
class RecursiveChunker:
    def chunk(self, content: ContentBlock) -> List[Chunk]:
        if self._called_by_assembler:  # ← 越界
            ...
```

#### 第三条：引擎通过注册表发现组件，不直接引用

```python
# ✅ 合法：注册表发现
cls = COMPONENT_REGISTRY.get("chunker", rule.chunker)
chunker = cls(**rule.chunk_params)

# ❌ 违规：直接引用具体适配器
from .chunkers.recursive_adapter import RecursiveAdapter  # ← 越界
```

#### 第四条：跨子域通信的唯一通道是 contracts

```
子域 chunkers/   ──┐
子域 generators/ ──┼── COMPONENT_REGISTRY ── 语法引擎 (composer.py)
子域 embeddings/ ──┘
```

子域之间**禁止直接 import**。任何跨子域依赖必须经过 `COMPONENT_REGISTRY.get(type, name)`，该函数是 contracts 层定义的基础设施类型 —— 合法跨平台使用。

#### 违规判定

| 行为 | 判定 | 检测方式 |
|------|------|---------|
| 引擎 `from .chunkers.x import X` | ❌ 违反第三条 | AST guardrail 检测 adapters/*.py 中跨子域直接 import |
| 适配器中 `if called_by_xxx` 分支 | ❌ 违反第二条 | Code review |
| 子域 A 直接 import 子域 B 的类 | ❌ 违反第四条 | AST guardrail 检测子域间 import |
| 新增 chunker 需要改动 composer.py | ⚠️ 架构退化预警 | 改动清单审计 |

#### 宪法修正程序

本宪法的任何修改必须同时满足：
1. `.ai_reasoning/` 新增 reasoning chain 记录决策
2. CLAUDE.md 不变量表同步更新
3. `tests/conformance/` 新增对应合规测试
4. 全量测试 + guardrail 检查通过

#### USB 驱动模型：Adapters 层的正确形态

Adapters 层在内核中，但它应该是 **USB 热插拔总线**，而非 **Linux 设备树**。

| 维度 | 设备树 (❌) | USB 驱动模型 (✅) |
|------|-----------|-----------------|
| 新增组件 | 改 DTS → 重编内核 → 重启 | 插入设备 → 自动匹配驱动 → 热可用 |
| 内核感知 | 必须知道每个设备的地址/中断 | 只知道 USB 协议，不知道具体设备 |
| 绑定方式 | 静态路径 `/soc/i2c@ff160000/...` | 动态匹配 `vendor_id + product_id` |
| 你平台的对应物 | `if rule.chunker == "recursive": ...` | `REGISTRY.get("chunker", name)` |
| 变更成本 | O(内核代码量) | O(新驱动代码量)，内核 O(1) |

**内核 = USB 协议规范 + 控制器**（`COMPONENT_REGISTRY`，稳定，极少改动）
**Adapters = USB 驱动程序**（`@register` 装饰的类，频繁新增，独立发布）
**Blueprint = 设备连接拓扑**（YAML 声明，纯数据）

##### 四条退化禁令

以下四种行为会把 Adapters 层从 USB 总线退化回设备树：

| # | 禁令 | 退化后果 |
|---|------|---------|
| 1 | **禁止显式 import 具体适配器** — `from .chunkers.x import XAdapter` | 新增 chunker 需要改所有 import 它的文件 |
| 2 | **禁止 if/switch 按名称分发** — `if rule.chunker == "semantic": ...` | 每加一个策略，所有 switch 语句都要加分支 |
| 3 | **禁止配置与文件名强耦合** — 要求 Blueprint 的 chunker 名与文件名一致 | 无法重命名文件，无法热替换实现 |
| 4 | **禁止适配器反向引用引擎** — `from ..composer import PipelineAssembler` | 循环依赖，组件无法独立测试 |

**正确的 USB 模型**（Phase 19 强制执行）：

```python
# ✅ 组件自注册，内核零感知
@COMPONENT_REGISTRY.register("chunker", "semantic")
class SemanticChunker:
    VERSION = SemVer(1, 2, 0)
    def chunk(self, content: ContentBlock) -> List[Chunk]: ...

# ✅ 语法引擎只通过名称动态获取
class PipelineAssembler:
    def _build_chunker(self, rule: SourceRule):
        cls = COMPONENT_REGISTRY.get("chunker", rule.chunker)
        return cls(**rule.chunk_params)
```

效果：新增一个 chunker → 只新建一个文件 + `@register`。`composer.py` / `factory.py` / `contracts/` 一行不改。YAML 里写 `chunker: semantic` 即可生效。

##### 未来 Multi-Agent 层的 USB 扩展

同样的注册表模型无缝延伸到上层：

```python
# agents/orchestrators/react_orchestrator.py
@AGENT_REGISTRY.register("orchestrator", "react")
class ReActOrchestrator:
    def __init__(self, kernel: KernelService): ...

# agents/tools/retriever_tool.py
@TOOL_REGISTRY.register("tool", "knowledge_search")
class KnowledgeSearchTool:
    def __init__(self, kernel: KernelService): ...
```

Agent 编排器、工具、记忆模块全部走注册表发现。内核提供 `KernelService` 作为标准接口，上层组件即插即用。

四条禁令在此层同样生效：Agent 编排器不直接 import 具体 Agent，Agent 不知道编排器的存在，所有发现走 `AGENT_REGISTRY`。

三项缺一不可。

##### 代价清单：USB 模型的六笔隐性税

USB 模型不是免费午餐。它是用**运行时复杂性、调试痛苦和认知门槛**换来的扩展性。如果不清楚这些代价，Phase 25 左右会被它们反噬。

| # | 代价维度 | 具体表现 | 严重程度 | 缓解策略 |
|---|---------|---------|---------|---------|
| 1 | **调试黑洞** | 报错堆栈里全是 `registry.get()` / `decorator` / `factory(**kwargs)`，看不到真实业务代码路径 | 🔴 高 | 注册时记录源码位置（`__file__` + `lineno`）；错误信息必须包含 `registered_at` 文件路径+行号 |
| 2 | **IDE 智能失效** | Ctrl+Click 无法跳转到具体 Adapter；重构时 Rename 不会自动更新 YAML 中的字符串引用 | 🔴 高 | 维护 `component_manifest.json`（自动生成）；CI 中加 YAML ↔ Registry 一致性 lint |
| 3 | **启动期脆弱性** | 装饰器执行顺序不确定；循环 import 导致注册失败但无明确报错；"明明写了 `@register` 却找不到" | 🟡 中 | 显式初始化入口；启动时跑完整性自检并打印已注册组件表 |
| 4 | **类型安全丧失** | `registry.get("chunker", name)` 返回 `Any`；mypy/pyright 无法验证参数签名是否匹配 Blueprint | 🟡 中 | 为每个 category 定义 Protocol；`get()` 返回 Protocol 类型而非 `Any`；CI 中加 runtime contract check |
| 5 | **新人认知墙** | "这个 chunker 到底在哪定义的？" "为什么 YAML 里写 `semantic` 就能跑？" 没有显式 import 链可追踪 | 🟡 中 | 自动生成组件目录文档；Blueprint schema 里嵌入 `available_components` 列表；README 保留"如何新增组件" 5 分钟教程 |
| 6 | **过度抽象风险** | 只有 2 个 chunker 时也搞全套 Registry + Decorator + Protocol，复杂度远超收益 | 🟠 低→高 | YAGNI 阈值：<3 个同类组件时用简单 dict；≥3 个再升级为 Registry |

###### 最致命的两个代价

**调试黑洞（代价 #1）** — 日常开发中最频繁的痛点。当 `PipelineAssembler._build_chunker()` 抛出异常时：

```python
# ❌ 你看到的堆栈
File "composer.py", line 87, in _build_chunker
    return COMPONENT_REGISTRY.get("chunker", rule.chunker, **params)
File "registry.py", line 42, in get
    return factory(**kwargs)
TypeError: __init__() got an unexpected keyword argument 'overlap_ratio'
```

你不知道是哪个 factory，不知道它期望什么参数，不知道 Blueprint 里哪个字段写错了。

```python
# ✅ 你应该看到的堆栈
ComponentResolutionError: 
  Category: chunker
  Name: semantic  
  Registered at: core/adapters/chunkers/semantic_adapter.py:15
  Expected params: {chunk_size: int, similarity_threshold: float}
  Received params: {chunk_size: 512, overlap_ratio: 0.1}
  Blueprint source: configs/default_pipeline.yaml → sources[2].chunk_params
  
  Hint: 'overlap_ratio' is not a valid param for SemanticChunkerAdapter.
        Did you mean 'similarity_threshold'?
```

实现成本：Registry 必须在 `@register` 时捕获 `inspect.signature(factory)` + `__module__` + `__file__` + `lineno`；`get()` 失败时必须构造上述结构化错误。比简单的 dict lookup 多写 ~80 行代码，但省下的调试时间以小时计。

**IDE 智能失效（代价 #2）** — Python 的动态注册对静态分析天然不友好：
- 重构 `SemanticChunkerAdapter` → `SemanticSplitterAdapter`，YAML 里的 `"semantic"` 没改，上线才炸
- 新人在 IDE 里输入 `rule.chunker = "` 没有补全提示，只能翻文档或 grep
- Code Review 时无法通过 diff 判断某个 YAML 变更是否引用了不存在的组件

缓解方案成本：CI 加 `validate_blueprint_components` step（~50 行脚本），或生成 JSON Schema 给 YAML 编辑器用（~100 行一次性），或 VSCode/LSP 插件（仅当团队 >5 人时值得）。

###### 什么时候不该用 USB 模型

| 场景 | 推荐方案 | 理由 |
|------|---------|------|
| 同类组件 ≤ 2 个，且半年内不太可能增加 | 简单 dict + 显式 import | Registry 是过度工程 |
| 组件之间差异极大，无法统一 Protocol | 独立工厂函数，不走通用 Registry | 强行抽象比硬编码更糟 |
| 团队 < 3 人，项目生命周期 < 6 个月 | 硬编码 if/elif | 扩展性是未来的事，先活下来 |
| 性能敏感路径（μs 级） | 预解析缓存，避免运行时 lookup | `Registry.get()` 有 ~1-5μs 开销 |
| 需要强类型保证的安全关键系统 | 代码生成 / metaclass 验证 | 纯动态注册不够 |

**Phase 19 的判断**：Chunker、Generator、Embedding 三类组件，每类 ≥2 个实现且持续增长 → USB 模型 justified。

###### 总账

```
收益（长期复利）                代价（即时支付）
─────────────────              ─────────────────
✅ 新增组件 O(1) 内核改动       ❌ Registry 基础设施 ~200 LOC
✅ Multi-Agent 层无缝接入       ❌ 结构化错误处理 ~80 LOC  
✅ 外部插件化成为可能           ❌ CI 校验脚本 ~50 LOC
✅ 单元测试可 mock 整个组件族    ❌ 文档/教程维护 持续
✅ Blueprint 纯数据化          ❌ 新人 onboarding +1 day
                                ❌ IDE 体验降级（部分可修复）
```

净评估：平台预期寿命 > 1 年、组件数 > 5、团队 > 2 人 → 代价完全值得。

###### Phase 19 验收标准（代价对冲）

以下五项从 Day 1 就实现，不等到踩坑再补：

1. **Registry 错误信息包含** `registered_at` + expected params + blueprint source
2. **CI 中有 `validate_blueprint_components`** 检查 — YAML 引用的每个 chunker 名都在 Registry 中存在
3. **有"如何新增组件"的 5 分钟文档** — 新人 onboarding 零认知墙
4. **`registry.get()` 返回类型是 Protocol** 而非 `Any` — mypy/pyright 可校验
5. **启动时打印已注册组件摘要表** — 每次启动确认组件注册状态，消除启动期不确定性

支付了这五笔首付，USB 模型才是资产而非负债。

##### Anti-WinReg 保证：为什么 ComponentRegistry 不是 Windows 注册表

Windows 注册表的恶名来自它的本质：**全局可变状态、无契约、无版本控制、运行时任意读写**。它把"配置"、"依赖关系"和"程序状态"混在一个巨大的二进制树里。

ComponentRegistry 虽然名字里有"注册"，但工程本质完全相反：

| 维度 | Windows Registry (❌) | ComponentRegistry (✅) |
|------|---------------------|----------------------|
| **数据性质** | 全局可变状态，任何进程随时读写 | 启动期构建，运行时只读 |
| **契约约束** | 无 schema，字符串键值对随意写 | 强 Protocol 约束，签名不匹配直接报错 |
| **作用域** | 全局命名空间，极易冲突 | 按 category 隔离 (`chunker`, `generator`, `embedding`) |
| **变更方式** | 运行时隐式修改（安装器/病毒/用户） | 代码显式声明 (`@register`)，Git 可追溯 |
| **失败模式** | 静默损坏，系统逐渐不稳定 | 启动时快速失败，带完整诊断信息 |
| **类比** | 一个谁都能往里面扔垃圾的公共仓库 | 一个有严格安检的零件目录册 |

关键区别：**WinReg 是"状态"，Registry 是"索引"。**

但如果有三个实现细节偷懒，Registry 确实会退化成 WinReg：
1. `@register` 在 import 时隐式执行 → 循环依赖导致注册行为不可预测
2. 全局单例 Registry → 测试时一个用例污染另一个
3. `get("chunker", "semantic")` 裸字符串 → 拼写错误无编译器保护

###### 四道防火墙：防止退化为 WinReg

**防火墙 1：启动期冻结**

```python
class ComponentRegistry:
    _frozen = False
    
    @classmethod
    def freeze(cls):
        cls._frozen = True
    
    @classmethod
    def register(cls, category, name):
        if cls._frozen:
            raise RuntimeError(
                f"Cannot register '{category}/{name}' after startup. "
                "All components must be registered during initialization."
            )
        # ... normal registration logic
```

杜绝运行时隐式状态变更。WinReg 的核心罪恶就是"任何时候都能改"。

**防火墙 2：显式发现，拒绝魔法 import**

```python
# ❌ 隐式：靠 import 副作用触发注册
from core.adapters.chunkers import *

# ✅ 显式：启动入口清晰可控
def bootstrap():
    registry.discover("core.adapters.chunkers")
    registry.discover("core.adapters.generators")
    registry.discover("core.adapters.embeddings")
    registry.freeze()
    registry.print_summary()
```

注册从"import 的副作用"变成"启动流程的一等公民"——可审计、可测试、可调试。

**防火墙 3：类型安全的键，消灭裸字符串**

```python
# ❌ WinReg 风格
registry.get("chunker", "semantic")  # 返回 Any

# ✅ 枚举 + Protocol 返回类型
registry.get_chunker("semantic")  # 返回 ChunkingStrategy
```

IDE 补全 + mypy 校验 + 重构安全。字符串键的脆弱性被类型系统消除。

**防火墙 4：测试隔离**

```python
@pytest.fixture
def isolated_registry():
    original = COMPONENT_REGISTRY._factories.copy()
    COMPONENT_REGISTRY._factories.clear()
    yield COMPONENT_REGISTRY
    COMPONENT_REGISTRY._factories = original
```

单元测试不会因全局 Registry 状态互相干扰。WinReg 做不到这一点。

###### 更准确的类比

| 类比 | 相似度 | 说明 |
|------|--------|------|
| **Java SPI** (`META-INF/services/`) | ⭐⭐⭐⭐ | 启动期扫描，运行时只读，按接口分组 |
| **Python entry_points** | ⭐⭐⭐⭐ | `pyproject.toml` 声明 + `importlib.metadata`，包安装时确定 |
| **Spring Bean Factory** | ⭐⭐⭐⭐ | 容器启动时组装，运行时只读，强类型注入 |
| **USB VID/PID 表** | ⭐⭐⭐ | 硬件标识到驱动的映射，标准组织维护 |
| **Windows Registry** | 反类比 | 全局可变状态 → 混乱之源 |

###### Phase 19 验收标准（Anti-WinReg）

| # | 要求 | 验证方式 |
|---|------|---------|
| 1 | Registry 启动后 `freeze()`，运行时注册抛异常 | 单元测试：启动后尝试注册，assert RuntimeError |
| 2 | 显式 `bootstrap()` 调用所有 discover 路径 | 代码审查：不存在 `from x import *` 触发注册 |
| 3 | `get()` 返回 Protocol 类型，不用裸字符串键 | mypy 严格模式通过 |
| 4 | 测试隔离 fixture 可用，各测试间状态不污染 | 并发测试：两个测试同时注册不同组件，互不影响 |
| 5 | 启动时打印完整组件摘要表 | 集成测试：assert stdout 包含所有 category 及组件名 |

**结论**：名字像，灵魂相反。Registry 不会退化除非偷懒。四道防火墙 + 五个验收标准同时锁定。

##### 内核工程纪律：防止"神圣感"膨胀为过度设计

市面上没有 Agent 内核，不是因为别人造不出，而是因为内核在 PMF 验证之前是一个巨大的沉没成本陷阱。SaaS 平台卖"能用"，框架卖"什么都能接"，模型厂商卖 Token —— 内核卖的是**确定性 + 可审计 + 可扩展**。这条路太难、太慢、太反商业直觉。

选择了这条路，就必须建立一套刹车机制，防止"造内核"的宏大叙事催生出没人用的抽象。

###### 内核价值审计清单（每个 Phase 结束时执行）

| # | 审计问题 | 红灯信号 | 处理方式 |
|---|---------|---------|---------|
| 1 | 如果没有这个内核，直接用现有框架实现同样功能，会多花多少时间？ | 答案是"差不多"或"更少" | 停下来重新评估方向 |
| 2 | 这个内核功能有上层消费者吗？（Agent / Business / UI） | 没有实际调用方，纯"预判需要" | 立即删除，等真有需求再加 |
| 3 | 新增的 Contract 是"所有上层都需要的最小公分母"吗？ | 只被一个 Agent 类型用到 | 不放内核，留在上层 |
| 4 | 改一个 Contract 要同步改多少文件？ | 不需要改任何上层代码 = 这段契约是死代码；需要改 10+ 个文件 = 抽象错了 | "恰到好处的痛"：改 3-6 个文件是健康范围 |
| 5 | Phase 25 时，用这个内核写一个 Multi-Agent Demo 会比直接用 LangGraph 更快吗？ | 如果预测答案是"更慢更痛苦" | 内核设计有根本性问题，重新审视 |
| 6 | 当前接口的同步/异步、输入/输出签名，是否假设了"所有信息在调用时已完备"？ | 是，且该假设在契约协商场景（需向用户询问、需等待外部确认）下不成立 | 预留异步扩展点或 Optional 返回值 |

###### YAGNI 在内核层的应用规则

内核层的 YAGNI 比应用层更严格——因为内核的错误抽象会通过所有上层消费者放大。

**放行清单**（满足全部三项才能进入内核）：
1. 至少 2 个不同的上层消费者需要这个能力
2. 用现有框架实现同样能力，需要 ≥50 行重复代码
3. 未来 2 个 Phase 内有明确的使用场景

**拒绝清单**（任一触发即拒绝）：
1. "以后可能会用到" —— 拒绝。什么时候用到什么时候加。
2. "这样设计更对称/更优雅" —— 拒绝。对称性是审美需求不是工程需求。
3. "LangChain/CrewAI/Coze 有这个，我们也应该有" —— 拒绝。它们是框架/平台，你是内核。能力边界不同。
4. "如果不加这个，未来改起来会很麻烦" —— 记录到 `.ai_reasoning/` 但不实现。等到那天真的来了再说。

###### 内核健康的五个指标

| 指标 | 健康状态 | 预警状态 |
|------|---------|---------|
| 内核代码行数 | < 5000 LOC（Phase 25 时） | > 10000 LOC |
| Contract 数量 | < 10 个 Protocol/dataclass | > 15 个 |
| 上层绕过内核的频率 | 0 次/Phase | > 1 次/Phase |
| 新增组件是否必须改内核 | 否（Registry 发现） | 是（需要改内核 switch/if） |
| 废弃 Contract 的清理速度 | 废弃后 1 个 Phase 内删除 | 留着"以防万一" |

###### 内核与框架的根本区别

| 维度 | 框架 (LangChain, CrewAI) | 内核 (RAG-Factory) |
|------|------------------------|-------------------|
| **目标** | 什么都能接，降低接入成本 | 什么该拒绝，保证确定性 |
| **增长模式** | 加 Adapter、加 Integration、加 Plugin | 减假设、减耦合、减接口 |
| **质量度量** | 集成数量、Star 数、社区活跃度 | 契约稳定性、审计完整性、上层开发速度 |
| **设计哲学** | "Yes, and..." 包容一切 | "No, unless..." 只放经过验证的最小公分母 |
| **用户感知** | 5 分钟上手，1 小时后遇到边界 | 1 小时理解，1 周后开始加速 |
| **失败模式** | 抽象泄漏，用户掉进坑里 | 能力不足，上层绕过内核 |

内核不是框架的升级版。内核是框架的反面。

###### 心态矫正

| 错觉 | 现实 |
|------|------|
| "我们在建造圣殿" | 你在培育一个有机体。允许它丑、允许它改、允许它在压力下变形 |
| "这个内核以后会很值钱" | 内核的价值不在它自己，而在它让上层建设显著更快、更安全 |
| "我们要一次性建成" | Linux v0.01 只支持 Minix 文件系统。Phase 19 只是第一个稳定切片 |
| "内核 = 高级" | Linux 赢了不是因为它是内核，而是 POSIX + GCC 让开发者愿意在上面建东西 |

Phase 19 不是加冕礼，是第一次真正的压力测试。写完 `PipelineAssembler` 并用它组装出第一条真实 Pipeline 时，那种"它能跑通"的踏实感，比任何"我们在造内核"的宏大叙事都更有价值。

#### 演进宪法：从单 Pipeline 引擎到 Multi-Agent 平台

当前的 Core Kernel（大三层）**无法直接承载 Multi-Agent 编排、业务逻辑和人机交互**。如果试图把 Agent 协作塞进 `core/adapters/composer.py`，平台会在 Phase 25 彻底坍塌。

但大三层不需要"完成"这件事。它的使命是成为**坚不可摧的内核**。Multi-Agent、业务层、UI 是生长在内核之上的独立有机体。

##### 同心圆架构

```
┌─────────────────────────────────────────────────────┐
│  Presentation Layer (UI / API / CLI)                │ ← 人机交互
│  ┌───────────────────────────────────────────────┐  │
│  │  Application Layer (Business / Multi-Agent)   │ ← 业务 + 多 Agent 编排
│  │  ┌─────────────────────────────────────────┐  │  │
│  │  │  Core Kernel (Contracts/Adapters/Pipeline)│ ← Phase 19 内核（当前战场）
│  │  │  词汇 + 语法 + 原子执行引擎              │  │  │
│  │  └─────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

| 层 | 解决什么问题 | 编排对象 | 状态模型 | 时间尺度 |
|---|------------|---------|---------|---------|
| Core Kernel | 单个步骤如何正确执行 | Components (Chunker, Retriever) | Frozen Blueprint | ms |
| Application | 多个 Agent 如何协商/竞争/委托 | Agents (Planner, Executor, Critic) | Mutable Conversation State | s-min |
| Presentation | 人类如何观察/干预/反馈 | Views, Endpoints, Sessions | UI State, WebSocket Conn | 实时 |

##### KernelService 协议：内核向上层的唯一接口

```python
# core/contracts/kernel_service.py (Phase 20+)
class KernelService(Protocol):
    """内核暴露给 Application Layer 的唯一能力原语。

    Application Layer 不 import core/adapters/composer.py，
    只依赖此 Protocol。Agent 看到的是一个标准化的能力原子服务。
    """

    def compose_retriever(
        self, blueprint: CompositionBlueprint, sources: list[str]
    ) -> RetrieverStep: ...

    def execute_step(
        self, step: PipelineStep, context: Dict[str, Any]
    ) -> StepOutput: ...

    def health_check(self) -> HealthStatus: ...

    @property
    def audit_manifest(self) -> Dict[str, Any]: ...
```

```python
# 未来的 Application Layer 使用方式
class PlanningAgent:
    def __init__(self, kernel: KernelService): ...

    async def plan(self, goal: str) -> Plan:
        # Agent 需要检索知识 → 调用内核原子操作
        retriever = self.kernel.compose_retriever(blueprint, sources)
        results = await self.kernel.execute_step(retriever, {"query": goal})
        ...
```

##### 未来的目录结构（不急于实现，但设计要预留）

```
project/
├── core/                          ← 内核（当前大三层，Phase 19 后基本稳定）
│   ├── contracts/
│   └── adapters/
│   └── pipeline/
│
├── agents/                        ← Application Layer: Multi-Agent（Phase 25+）
│   ├── protocols/                 # Agent 间通信契约（AgentMessage, TaskGraph）
│   ├── orchestrators/             # 协作模式 (ReAct, Plan-and-Solve, Debate)
│   ├── memory/                    # 共享记忆 / 对话状态
│   └── tools/                     # Agent 可调用的工具（封装 KernelService）
│
├── business/                      ← Application Layer: 业务逻辑
│   ├── workflows/                 # 业务流程编排
│   ├── policies/                  # 权限 / 合规 / 限流
│   └── integrations/              # 外部系统对接
│
├── presentation/                  ← Presentation Layer
│   ├── api/                       # REST / GraphQL / WebSocket
│   ├── ui/                        # Web / Desktop
│   └── cli/                       # 命令行交互
│
└── configs/                       ← 各层配置物理分离
    ├── kernel/                    # Pipeline Blueprint (Phase 19)
    ├── agents/                    # Agent Protocol Config (Phase 25+)
    └── business/                  # Workflow Definitions (Phase 30+)
```

##### 今天必须做的防御性设计

| 设计决策 | 理由 |
|---------|------|
| `PipelineComposer` 只暴露组合能力，不暴露内部 Router/Assembler | 未来只需将 Composer 包装为 `KernelService` 实现，零内部改动 |
| `CompositionEvent` 的 `event_type` 用 `Literal` 而非 `str` | 未来新增 `agent_delegated`, `human_feedback_received` 时类型检查自动覆盖 |
| `audit_manifest` 预留 `layer` 字段 | `"layer": "kernel"` vs `"layer": "agent"` — 审计时区分责任边界 |
| contracts 层绝不引入 Agent 概念 | `ContentBlock`/`Chunk`/`SourceRule` 是内核契约；`AgentMessage`/`TaskGraph` 是 agents/protocols/ 的契约 —— 两层契约永不混合 |

##### 禁止事项

| 行为 | 后果 |
|------|------|
| 在 `core/` 中 import 任何 Agent 相关类型 | 内核与上层建筑耦合，换 Agent 框架需改内核 |
| 在 `CompositionBlueprint` 中添加 `agent_routing` 字段 | 万能 God Object 诞生，契约崩溃 |
| `PipelineAssembler` 管理对话状态 | 内核无状态假设被破坏，并发推理产生竞态 |
| `SourceRouter` 理解 Agent Handoff 语义 | 语法污染，路由引擎变成 if-else 地狱 |

---

#### 长期演进策略：Python 是契约原型机，不是最终产品

五年项目周期意味着语言选择不是终局的。Python 的价值是**快速验证契约正确性**，未来性能瓶颈出现时，Rust（或任何更合适的语言）可以精准替换热路径而非全面重写。

但"未来要重写"这句话如果处理不好，会变成两种灾难：
- **灾难 A**：Python 阶段随意写，心想"反正以后要重写"，契约设计全是 Python 动态特性，Rust 无法映射 → 重写变成重设计，五年积累归零
- **灾难 B**：Python 阶段过度追求"Rust-like"，到处手动管理生命周期 → Python 写得比 Rust 还痛苦，项目死在 Phase 30

核心原则：**Python 内核 = 可执行代码编写的规格说明书**。它写的每一行代码，要么是在"定义契约"，要么是在"验证契约"。除此之外的代码，都是未来的废弃成本。

##### 五条铁律：确保今天的 Python 代码是资产而非累赘

###### 铁律 1：契约与实现物理分离

```
core/contracts/   ← 纯类型定义，零业务逻辑（零 numpy / torch / openai）
core/adapters/    ← 业务逻辑实现
core/pipeline/    ← 编排逻辑
```

效果：Rust 重写时，`contracts/` 整个目录可直接翻译为 `crates/kernel-contracts/`，无需剥离逻辑。

```python
# ✅ contracts/ 只定义接口，不引用任何外部 SDK
class ChunkerStep(Protocol):
    def run(self, input: ContentBlock, **params) -> List[Chunk]: ...

# ❌ 绝对禁止：contracts/ 里 import torch / openai / numpy
```

###### 铁律 2：测试即规格，与语言无关

```python
# ✅ 测试只通过 Contract 接口断言行为
def test_semantic_chunker_respects_threshold():
    chunker = registry.get("chunker", "semantic")
    chunks = chunker.run(sample_doc, similarity_threshold=0.85)
    assert all(c.similarity >= 0.85 for c in chunks)

# ❌ 禁止测试内部状态、私有方法、具体类名
```

效果：未来 Rust 实现可以跑同一套 pytest 黑盒验收（subprocess 调用 Rust binary），测试套件 100% 复用。

###### 铁律 3：Blueprint Schema 是真正的宪法

YAML Blueprint 的 JSON Schema 是五年项目真正的**不变量**。Python 和 Rust 都只是这个 Schema 的解释器。

| 变更类型 | 所需流程 | 用户成本 |
|---------|---------|---------|
| Schema 变更 | RFC + 迁移脚本 | 用户需更新 Blueprint |
| Python → Rust 实现变更 | 通过 Schema 验证即可 | **零迁移成本** |

效果：重写内核时，所有用户的 Pipeline 配置零改动。这才是"内核"对用户的真正承诺。

###### 铁律 4：Adapter 边界预留 FFI 出口

现在写 Python Adapter 时，假设它未来可能是一个独立进程 / WASM 模块 / Rust native extension：

1. **Adapter 之间禁止直接函数调用** — 只通过 Registry + Contract 通信
2. **Adapter 参数和返回值必须是可序列化的** — dataclass → JSON/msgpack
3. **Adapter 不持有全局状态** — 所有依赖通过构造函数注入

效果：Rust 重写内核后，旧的 Python Adapter 可以通过 gRPC / stdin-stdout / FFI 继续工作。重写是渐进式的，不是大爆炸式的。

###### 铁律 5：文档即契约的人类可读版本

每个 Contract 必须有 docstring 说明：
- **语义保证**：什么情况下返回什么
- **错误契约**：什么输入触发什么异常
- **性能预期**：O(n) 还是 O(n²)，是否流式

效果：未来的 Rust 开发者（可能是几年后的你）不需要读 Python 源码就能理解意图。docstring 就是重写时的需求文档。

##### 五年路线图的心理校准

| 阶段 | 时间 | 核心目标 | "不怕"的具体表现 |
|------|------|---------|----------------|
| **契约验证期** | Year 1-2 | 用 Python 跑通 Multi-Agent 场景，反复重构 Contract | 不怕删代码，只怕契约不对 |
| **生态沉淀期** | Year 2-3 | Adapter 数量 >20，Blueprint 被真实用户使用 | 不怕 Python 慢，只怕用户不愿接入 |
| **性能瓶颈期** | Year 3-4 | 识别真正需要 Rust 的热路径（可能只有 20%） | 不怕局部重写，拒绝全面推翻 |
| **双轨并行期** | Year 4-5 | Python/Rust 共存，渐进迁移 | 不怕兼容负担，只怕中断用户 |

关键预判：**Year 3-4 的"性能瓶颈期"很可能会发现：**
- 80% 的内核代码根本不需要 Rust（Registry、Blueprint 解析、调度逻辑）
- 只有 Chunker / Embedding / Generator 的执行引擎是瓶颈
- 正确做法是把这 20% 抽成 Rust native extension，而非重写整个内核

"全面重写"往往是过早的结论。"精准替换"才是五年项目的生存之道。

##### Python → Rust 映射校验清单

Phase 19 的每个 Contract / Adapter 都应在设计时就检查以下可映射性：

| Python 概念 | Rust 等价物 | 当前使用 | 重写风险 |
|------------|-----------|---------|---------|
| `@dataclass(frozen=True)` | `struct` + `#[derive(Clone)]` | 所有数据模型 | ✅ 零风险 |
| `Protocol` | `trait` | 所有组件接口 | ✅ 零风险 |
| `MappingProxyType` | `Arc<HashMap<K, V>>` | 不可变映射 | ✅ 零风险 |
| `Literal["a", "b"]` | `enum` | event_type, error_type | ✅ 零风险 |
| `Callable[[X], Y]` | `Box<dyn Fn(X) -> Y>` | event_sink | ⚠️ 需转为显式 trait |
| `**kwargs` 动态参数 | 泛型 / 编译期确定 | chunk_params | ⚠️ 需在 Blueprint Schema 层标准化 |
| `inspect.signature` 运行时反射 | 编译期 trait bound | health_check 参数校验 | 🟡 已缓解：签名在 `@register` 时缓存；`validate_params()` classmethod 为 Rust trait 预留接口 |
| 装饰器 `@register` | 宏 / inventory crate | 组件注册 | 🔴 需转为显式注册函数 |

Phase 19 的对策：
- **`health_check()` 双重校验**: Tier 1 = chunker 可选 `validate_params(params) -> list[str]` classmethod（语义约束，Rust 直接映射为 trait method）；Tier 2 = `COMPONENT_REGISTRY.validate_params()` 读取 `@register` 时缓存的签名（无实时反射开销，Rust 可从 Schema 读取）
- `event_sink` 已定义为 `Callable[[CompositionEvent], None]` → 未来转为显式 `EventSink` trait 时接口一致
- `**chunk_params` 已在 Blueprint Schema 中声明参数名和类型 → Rust 可从 Schema 生成强类型构造函数

每一处红/黄标记，Phase 19 都已经或正在铺垫替代方案。不是以后再说，而是现在就把路径铺好。

---

### 架构硬约束（锁定）

| 约束 | 内容 |
|------|------|
| 数据模型归 contracts | `SourceRule` + `CompositionBlueprint` + `AssemblyDiagnostic` + `CompositionEvent` 放 `core/contracts/composition.py` |
| 编排逻辑归 adapters | `SourceRouter` + `PipelineAssembler` + `PipelineComposer` 放 `core/adapters/composer.py` |
| 数据与算法解耦 | Blueprint 零方法逻辑（纯数据访问），Router 是唯一路由入口 |
| 不引入新抽象 | 复用 `COMPONENT_REGISTRY`、`ChunkerAdapter`、`RetrieverStep`、`InMemoryVectorBackend` |
| 配置即代码 | YAML 是序列化格式，运行时是 frozen dataclass |
| YAML 配置位置 | `configs/default_pipeline.yaml` |
| 初始化方式 | 启动时一次性解析；Facade 接收 `CompositionBlueprint`，`from_yaml()` 只是便捷工厂 |
| 引擎零日志依赖 | `CompositionEvent` 通过 `event_sink` 依赖注入，引擎不 import 任何日志框架 |

---

### v2 相比 v1 的关键改进

| 改进 | v1 | v2 | 理由 |
|------|----|----|------|
| `resolve()` 位置 | Blueprint 上 | **SourceRouter 上** | 数据模型与匹配算法解耦，未来可换 RegexRouter |
| 参数校验 | 运行时在 assemble() 暴露 | **health_check() 阶段 inspect.signature 预检** | 语法层必须在解析阶段拒绝非法配置 |
| 错误表示 | `List[Dict[str, Any]]` | **`AssemblyDiagnostic` frozen dataclass** | 结构化，可按 error_type 过滤，JSON 可序列化 |
| Facade 构造 | `__init__(config_path)` | **`__init__(blueprint)` + `from_yaml()` classmethod** | 测试友好，未来支持 from_db/from_api |
| 可追溯 | chunker_strategy + chunker_version | **+ rule_id + blueprint_version + composed_at** | Chunk → 规则 → 配置版本，完整因果链 |
| 全透明 | 无 | **CompositionEvent 协议 + event_sink 注入** | 引擎决策过程全可见，零日志框架耦合 |
| 可审计 | 无 | **fingerprint + audit_manifest** | 事故可复现，合规零成本 |

---

### 新增文件

```
core/
├── contracts/
│   └── composition.py          ← [新增] SourceRule + CompositionBlueprint
│                                  + AssemblyDiagnostic + CompositionEvent
│
├── adapters/
│   ├── composer.py             ← [新增] SourceRouter + PipelineAssembler + PipelineComposer
│   └── factory.py              ← 已有，单步创建（不动）

configs/
└── default_pipeline.yaml       ← [新增]

tests/unit/
└── test_pipeline_composer.py   ← [新增]
```

---

### 1. `core/contracts/composition.py` — 数据模型

```python
"""Pipeline composition contracts: data models with zero business logic.

All dataclasses are frozen and hashable. No algorithm, no I/O, no side effects.

Design invariant:
  - Blueprint is pure data (no resolve(), no YAML parsing)
  - SourceRule carries deterministic rule_id for chunk-level lineage
  - AssemblyDiagnostic is the structured error representation
  - CompositionEvent is the engine decision log protocol
  - YAML parsing lives in CompositionBlueprint.from_yaml() classmethod
    (still in contracts because it's a factory, not an algorithm)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, FrozenSet, Literal, Tuple

from .chunking import SemVer


# ── Source Rule ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class SourceRule:
    """Maps a glob pattern to a chunking strategy with parameters.

    Attributes:
        pattern:      Glob pattern for source file paths
        chunker:      Strategy name in COMPONENT_REGISTRY
        chunk_params: kwargs forwarded to chunker constructor
        priority:     Lower = higher priority (default 100)
        description:  Human-readable rule explanation
        rule_id:      Deterministic hash of (pattern, chunker, priority).
                      Explicitly settable in YAML, auto-generated if empty.
    """

    pattern: str
    chunker: str
    chunk_params: Dict[str, Any] = field(default_factory=dict)
    priority: int = 100
    description: str = ""
    rule_id: str = ""

    def __post_init__(self) -> None:
        # Freeze chunk_params
        object.__setattr__(self, "chunk_params", dict(self.chunk_params))

        # Deterministic rule_id: explicit in YAML, or auto-generated
        if not self.rule_id:
            raw = f"{self.pattern}|{self.chunker}|{self.priority}"
            rid = hashlib.sha256(raw.encode()).hexdigest()[:12]
            object.__setattr__(self, "rule_id", rid)

    def matches(self, path: str) -> bool:
        """Check if this rule's glob pattern matches the given file path."""
        from fnmatch import fnmatch
        return fnmatch(path, self.pattern)


# ── Composition Blueprint ───────────────────────────────────────────

@dataclass(frozen=True)
class CompositionBlueprint:
    """Immutable pipeline composition specification.

    Pure data — no algorithm, no I/O. Factory methods (from_yaml, from_dict)
    are classmethods that produce Blueprint instances; they live here because
    they're data constructors, not orchestration logic.

    Attributes:
        version:         SemVer of the blueprint schema
        default_chunker: Fallback strategy when no rule matches
        default_params:  Fallback params for the default chunker
        source_rules:    Tuple of SourceRule, sorted by priority ascending
    """

    version: SemVer
    default_chunker: str = "recursive"
    default_params: Dict[str, Any] = field(default_factory=dict)
    source_rules: Tuple[SourceRule, ...] = ()

    def __post_init__(self) -> None:
        # Ensure rules are sorted by priority
        sorted_rules = tuple(sorted(self.source_rules, key=lambda r: r.priority))
        if sorted_rules != self.source_rules:
            object.__setattr__(self, "source_rules", sorted_rules)

    # ── Pure data accessors (no algorithm) ──────────────────────

    @property
    def rules_by_priority(self) -> Tuple[SourceRule, ...]:
        """Rules sorted by priority ascending. Already sorted in __post_init__."""
        return self.source_rules

    @property
    def fingerprint(self) -> str:
        """Deterministic hash of the entire blueprint content.

        Same content → same fingerprint, regardless of file path, timestamp,
        or machine. Used for audit trails and runtime identity verification.
        """
        canonical = json.dumps({
            "version": str(self.version),
            "default_chunker": self.default_chunker,
            "default_params": self.default_params,
            "rules": [
                {
                    "pattern": r.pattern,
                    "chunker": r.chunker,
                    "chunk_params": r.chunk_params,
                    "priority": r.priority,
                    "rule_id": r.rule_id,
                }
                for r in self.source_rules
            ],
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    # ── Factory methods (data constructors, not algorithms) ─────

    @classmethod
    def from_yaml(cls, path: str) -> CompositionBlueprint:
        """Parse a YAML file into a CompositionBlueprint.

        Validates:
          - version is valid SemVer
          - source_rules have non-empty pattern and chunker
        """
        import yaml
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls._from_raw(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> CompositionBlueprint:
        """Programmatic construction (for tests, API, database sources)."""
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: dict) -> CompositionBlueprint:
        version = SemVer.parse(raw["version"])
        default_chunker = raw.get("default_chunker", "recursive")
        default_params = raw.get("default_params", {})

        rules = []
        for r in raw.get("source_rules", []):
            if not r.get("pattern"):
                raise ValueError(f"SourceRule missing 'pattern': {r}")
            if not r.get("chunker"):
                raise ValueError(f"SourceRule missing 'chunker': {r}")
            rules.append(SourceRule(
                pattern=r["pattern"],
                chunker=r["chunker"],
                chunk_params=r.get("chunk_params", {}),
                priority=r.get("priority", 100),
                description=r.get("description", ""),
                rule_id=r.get("rule_id", ""),
            ))

        return cls(
            version=version,
            default_chunker=default_chunker,
            default_params=default_params,
            source_rules=tuple(rules),
        )


# ── Assembly Diagnostic ──────────────────────────────────────────────

@dataclass(frozen=True)
class AssemblyDiagnostic:
    """Structured error from the assembly phase. First-class citizen, not ad-hoc dict.

    Attributes:
        path:              Source file path that caused the error
        chunker:           Chunker strategy name (or "unknown" if routing failed)
        error_type:        routing | instantiation | execution | validation
        message:           Human-readable error description
        contract_violation: Optional — which contract rule was violated.
                           Phase 19 fills None; Phase 25+ uses this for graceful
                           degradation decisions (repair / renegotiate / abandon).
        timestamp:         epoch seconds when the error was recorded
    """

    path: str
    chunker: str
    error_type: Literal["routing", "instantiation", "execution", "validation"]
    message: str
    contract_violation: str | None = None
    timestamp: float = field(default_factory=time.time)


# ── Composition Event ────────────────────────────────────────────────

@dataclass(frozen=True)
class CompositionEvent:
    """Engine decision log entry. First-class citizen, not a logging call.

    The engine never calls logging.info() directly. It emits CompositionEvent
    objects through an injected event_sink callback. This decouples the engine
    from any specific logging/observability framework.

    Attributes:
        event_type:     rule_matched | rule_skipped | fallback_used |
                        chunker_instantiated | document_failed | assembly_complete
        correlation_id: Cross-event tracing key. Same value for all events
                        related to the same document (e.g. path hash or UUID).
                        Enables "contract fulfillment tracking" in Phase 25+.
        timestamp:      epoch seconds
        context:        Structured dict, never a formatted string.

    Context examples:
        rule_matched:         {path, rule_id, pattern, priority}
        rule_skipped:         {path, pattern, reason}
        fallback_used:        {path, default_chunker}
        chunker_instantiated: {rule_id, chunker, params_hash, version}
        document_failed:      {path, error_type, message}
        assembly_complete:    {total_docs, success_count, fail_count, total_chunks}
    """

    event_type: Literal[
        "rule_matched", "rule_skipped", "fallback_used",
        "chunker_instantiated", "document_failed", "assembly_complete",
    ]
    correlation_id: str
    timestamp: float
    context: Dict[str, Any]
```

#### 关键设计决策

**为什么 `resolve()` 不在 Blueprint 上**

`resolve()` 包含匹配算法（fnmatch + priority sort）。把它放在 Blueprint 上意味着数据模型与特定匹配算法永久绑定。未来想支持正则路由或 ML 路由时，必须修改 Blueprint —— 违反 immutable 契约。Router 是算法的唯一宿主，Blueprint 只是数据。

**为什么 `from_yaml()` 留在 contracts 层**

`from_yaml()` 是数据构造函数（factory method），不是编排算法。它不依赖 adapters 或 pipeline 层的任何类型。这与 `ContentBlock.from_dict()` 在 `chunking.py` 中的角色一致 —— 纯数据工厂。

**为什么 `rule_id` 用确定性 hash 而非 UUID**

确定性 hash 意味着同一个规则在任何机器、任何时间产生相同的 ID。这是可审计性的基础 —— 你可以离线验证"这个 Chunk 的血缘标签与配置指纹是否一致"。UUID 无法做离线验证。

**为什么 `event_sink` 是回调而非抽象类**

最小接口原则。引擎只需要"有一个地方可以发事件"，不需要定义 EventSink 协议、不需要 asyncio、不需要缓冲区管理。测试时 sink 是 `list.append`，生产时是 `logger.info`，零耦合。

---

### 2. `core/adapters/composer.py` — 三件套引擎

```python
"""Pipeline Composition Engine — the platform's grammar layer.

Three concerns, one file:
  SourceRouter      — routing engine: Blueprint + path → SourceRule (+ events)
  PipelineAssembler — assembly engine: SourceRules → RetrieverStep (+ diagnostics)
  PipelineComposer  — Facade: Blueprint → Router → Assembler (+ audit manifest)

All three live in core/adapters/ — the only layer legally allowed to import
from both core/contracts/ and core/pipeline/.
"""

from __future__ import annotations

import hashlib
import inspect
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.contracts import COMPONENT_REGISTRY, ContentBlock, SemVer
from core.contracts.composition import (
    AssemblyDiagnostic,
    CompositionBlueprint,
    CompositionEvent,
    SourceRule,
)
from core.adapters.chunker_adapter import ChunkerAdapter
from core.pipeline.engine import HealthStatus
from core.pipeline.resources import ResourceContainer
from core.steps.retriever import InMemoryVectorBackend, RetrieverStep


# ── Routing Engine ─────────────────────────────────────────────────

class SourceRouter:
    """Pure routing engine: Blueprint + path → SourceRule.

    Zero adapter dependency. Zero side effects. Independently testable.
    The ONLY place where glob matching and priority sort live.

    event_sink: Optional[Callable[[CompositionEvent], None]]
      - Injected at construction time (dependency inversion)
      - Default: no-op lambda (zero overhead when not needed)
      - Test: list.append for assertion
      - Production: structured logger or OpenTelemetry exporter
    """

    def __init__(
        self,
        blueprint: CompositionBlueprint,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> None:
        self._blueprint = blueprint
        self._emit = event_sink or (lambda e: None)

    def resolve(self, path: str) -> SourceRule:
        """Return the highest-priority matching rule for a source path.

        Algorithm: iterate rules_by_priority (ascending), first fnmatch hit wins.
        Falls back to a synthetic SourceRule using default_chunker.

        Emits: rule_matched | rule_skipped | fallback_used
        """
        for rule in self._blueprint.rules_by_priority:
            if rule.matches(path):
                self._emit(CompositionEvent(
                    event_type="rule_matched",
                    timestamp=time.time(),
                    context={
                        "path": path,
                        "rule_id": rule.rule_id,
                        "pattern": rule.pattern,
                        "priority": rule.priority,
                    },
                ))
                return rule
            self._emit(CompositionEvent(
                event_type="rule_skipped",
                timestamp=time.time(),
                context={"path": path, "pattern": rule.pattern, "reason": "no_match"},
            ))

        # Fallback
        self._emit(CompositionEvent(
            event_type="fallback_used",
            timestamp=time.time(),
            context={"path": path, "default_chunker": self._blueprint.default_chunker},
        ))
        return SourceRule(
            pattern="*",
            chunker=self._blueprint.default_chunker,
            chunk_params=dict(self._blueprint.default_params),
            priority=999,
            description=f"Default fallback: {self._blueprint.default_chunker}",
        )

    def resolve_all(self, paths: List[str]) -> Dict[str, SourceRule]:
        """Batch resolve: path → SourceRule."""
        return {p: self.resolve(p) for p in paths}

    @property
    def blueprint(self) -> CompositionBlueprint:
        return self._blueprint

    def health_check(self) -> HealthStatus:
        """Verify all referenced chunker strategies exist AND accept their declared params.

        Uses a two-tier validation strategy:
          1. Preferred: Chunker's own @classmethod validate_params(params) -> list[str]
             — allows chunker authors to express inspect-unreachable semantic constraints
             (e.g. chunk_overlap < chunk_size, similarity_threshold ∈ [0, 1])
          2. Fallback: COMPONENT_REGISTRY's cached signature (captured at @register time,
             not via real-time inspect — avoids repeated reflection overhead)
             — checks param names exist, ignores defaults

        All validation happens at startup, not execution time. This is the "grammar
        layer's" responsibility: reject illegal configuration before any document
        is processed.
        """
        issues: List[str] = []
        all_entries = [
            (self._blueprint.default_chunker, self._blueprint.default_params, "default")
        ]
        for rule in self._blueprint.source_rules:
            all_entries.append((rule.chunker, rule.chunk_params, rule.rule_id))

        for chunker_name, params, identifier in all_entries:
            try:
                cls = COMPONENT_REGISTRY.get("chunker", chunker_name)
            except KeyError:
                issues.append(
                    f"[{identifier}] Unknown chunker strategy: '{chunker_name}'"
                )
                continue

            # Tier 1: chunker-provided semantic validation
            if hasattr(cls, "validate_params"):
                semantic_errors = cls.validate_params(params)
                for err in semantic_errors:
                    issues.append(f"[{identifier}] {chunker_name}: {err}")
                if semantic_errors:
                    continue  # semantic errors are fatal for this entry

            # Tier 2: cached signature check (captured at @register time)
            sig_errors = COMPONENT_REGISTRY.validate_params("chunker", chunker_name, params)
            if sig_errors:
                issues.append(
                    f"[{identifier}] Invalid params for '{chunker_name}': {sig_errors}"
                )

        if issues:
            return HealthStatus(
                status="degraded",
                message=f"Configuration errors: {'; '.join(issues)}",
                dependencies=[],
                version=str(self._blueprint.version),
            )
        return HealthStatus(
            status="healthy",
            message=f"All {len(all_entries)} chunker references valid",
            dependencies=[],
            version=str(self._blueprint.version),
        )


# ── Assembly Engine ─────────────────────────────────────────────────

class PipelineAssembler:
    """Pure assembly engine: List[SourceRule] → RetrieverStep.

    Consumes Router output. Creates chunker instances via COMPONENT_REGISTRY,
    wraps in ChunkerAdapter, executes chunking, aggregates all Chunks into
    an InMemoryVectorBackend-backed RetrieverStep.

    Structured diagnostics: every error is an AssemblyDiagnostic frozen dataclass,
    filterable by error_type, JSON-serializable for monitoring.

    event_sink: same dependency-injected pattern as SourceRouter.
    """

    def __init__(
        self,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> None:
        self._diagnostics: List[AssemblyDiagnostic] = []
        self._emit = event_sink or (lambda e: None)

    def assemble(
        self,
        resolved_rules: Dict[str, SourceRule],
        documents: Dict[str, ContentBlock],
        blueprint_version: str = "",
    ) -> RetrieverStep:
        """Compose a RetrieverStep from source documents and their resolved rules.

        Args:
            resolved_rules:   {path: SourceRule} from SourceRouter.resolve_all()
            documents:        {path: ContentBlock} from document loader
            blueprint_version: For chunk-level lineage tagging

        Returns:
            RetrieverStep backed by InMemoryVectorBackend with all chunks indexed.

        Raises:
            AssemblyError: if ALL documents failed (no chunks produced).
              Partial failures are collected in self._diagnostics and do not block.
        """
        self._diagnostics.clear()
        all_chunks = []
        composed_at = time.time()

        for path, doc in documents.items():
            rule = resolved_rules.get(path)
            if rule is None:
                self._record_failure(path, "unknown", "routing", "No matching rule")
                continue

            try:
                chunker_cls = COMPONENT_REGISTRY.get("chunker", rule.chunker)
            except KeyError:
                self._record_failure(
                    path, rule.chunker, "instantiation",
                    f"Unknown strategy: '{rule.chunker}'"
                )
                continue

            try:
                chunker = chunker_cls(**rule.chunk_params)
                params_hash = hashlib.sha256(
                    str(sorted(rule.chunk_params.items())).encode()
                ).hexdigest()[:8]
                self._emit(CompositionEvent(
                    event_type="chunker_instantiated",
                    timestamp=time.time(),
                    context={
                        "rule_id": rule.rule_id,
                        "chunker": rule.chunker,
                        "params_hash": params_hash,
                        "version": str(chunker.VERSION),
                    },
                ))
            except TypeError as e:
                self._record_failure(
                    path, rule.chunker, "instantiation",
                    f"Invalid params for '{rule.chunker}': {e}"
                )
                continue

            try:
                adapter = ChunkerAdapter(chunker)
                resources = ResourceContainer()
                resources.set_config("source", path)
                output = adapter.run({"content": doc}, resources)
            except Exception as e:
                self._record_failure(
                    path, rule.chunker, "execution",
                    f"ChunkerAdapter failed: {e}"
                )
                continue

            if output.contract_validation and output.contract_validation.errors:
                self._record_failure(
                    path, rule.chunker, "validation",
                    f"Contract validation: {output.contract_validation.errors}"
                )
                continue

            chunks = output.result  # List[Chunk]
            for ch in chunks:
                all_chunks.append(
                    ch.with_metadata(
                        source_path=path,
                        chunker_strategy=rule.chunker,
                        chunker_version=str(chunker.VERSION),
                        rule_id=rule.rule_id,
                        blueprint_version=blueprint_version,
                        composed_at=composed_at,
                    )
                )

        # Emit assembly summary
        success_count = len([p for p in documents if p not in {
            d.path for d in self._diagnostics
        }])
        self._emit(CompositionEvent(
            event_type="assembly_complete",
            timestamp=time.time(),
            context={
                "total_docs": len(documents),
                "success_count": success_count,
                "fail_count": len(self._diagnostics),
                "total_chunks": len(all_chunks),
            },
        ))

        if not all_chunks:
            raise AssemblyError(
                f"All {len(documents)} document(s) failed chunking. "
                f"Diagnostics: {self._diagnostics}"
            )

        backend = InMemoryVectorBackend(all_chunks)
        return RetrieverStep(backend=backend, index_chunks=all_chunks)

    @property
    def diagnostics(self) -> List[AssemblyDiagnostic]:
        return list(self._diagnostics)

    def _record_failure(
        self, path: str, chunker: str,
        error_type: Literal["routing", "instantiation", "execution", "validation"],
        message: str,
    ) -> None:
        diag = AssemblyDiagnostic(
            path=path, chunker=chunker,
            error_type=error_type, message=message,
        )
        self._diagnostics.append(diag)
        self._emit(CompositionEvent(
            event_type="document_failed",
            timestamp=diag.timestamp,
            context={
                "path": path,
                "chunker": chunker,
                "error_type": error_type,
                "message": message,
            },
        ))


# ── Facade ──────────────────────────────────────────────────────────

class PipelineComposer:
    """Public entry point: Blueprint → configured RetrieverStep + audit manifest.

    Thin facade. Contains no logic — delegates to:
      - CompositionBlueprint.from_*() for config parsing
      - SourceRouter for rule resolution
      - PipelineAssembler for step assembly

    Constructor accepts a CompositionBlueprint directly (test-friendly).
    from_yaml() and from_dict() are convenience classmethods.
    """

    def __init__(
        self,
        blueprint: CompositionBlueprint,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> None:
        self._blueprint = blueprint
        self._init_timestamp = time.time()
        self._router = SourceRouter(blueprint, event_sink=event_sink)
        self._assembler = PipelineAssembler(event_sink=event_sink)

    # ── Convenience factories ───────────────────────────────────

    @classmethod
    def from_yaml(
        cls, path: str | Path,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> PipelineComposer:
        """Create from a YAML config file (the common case)."""
        return cls(CompositionBlueprint.from_yaml(str(path)), event_sink=event_sink)

    @classmethod
    def from_dict(
        cls, raw: dict,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> PipelineComposer:
        """Create from a raw dict (for programmatic construction / testing)."""
        return cls(CompositionBlueprint.from_dict(raw), event_sink=event_sink)

    # ── Composition ─────────────────────────────────────────────

    def compose_for_sources(
        self, source_paths: List[str], documents: Dict[str, ContentBlock]
    ) -> RetrieverStep:
        """Full pipeline: resolve rules → assemble → RetrieverStep.

        Args:
            source_paths: File paths (e.g. ["docs/api/auth.md", "kb/security.md"])
            documents:    {path: ContentBlock} pre-loaded by caller

        Returns:
            RetrieverStep ready for Planning context injection.
        """
        resolved = self._router.resolve_all(source_paths)
        return self._assembler.assemble(
            resolved, documents, blueprint_version=str(self._blueprint.version)
        )

    # ── Audit & Diagnostics ─────────────────────────────────────

    @property
    def audit_manifest(self) -> Dict[str, Any]:
        """Runtime identity snapshot for audit trails and incident replay.

        Returns a dict containing:
          - blueprint_fingerprint: deterministic hash of the config content
          - blueprint_version:     SemVer string
          - config_origin:         how this blueprint was created
          - router_type:           qualified class name
          - registered_chunkers:   all chunker strategies available at init time
          - initialized_at:        epoch timestamp
        """
        return {
            "blueprint_fingerprint": self._blueprint.fingerprint,
            "blueprint_version": str(self._blueprint.version),
            "router_type": type(self._router).__name__,
            "initialized_at": self._init_timestamp,
        }

    @property
    def blueprint(self) -> CompositionBlueprint:
        return self._blueprint

    @property
    def diagnostics(self) -> List[AssemblyDiagnostic]:
        return self._assembler.diagnostics

    def health_check(self) -> HealthStatus:
        return self._router.health_check()


class AssemblyError(Exception):
    """Raised when ALL documents fail chunking. Partial failures are non-fatal."""
```

---

### 3. SourceRule glob 匹配语义

#### 优先级规则

```
1. 按 priority 升序（0 = 最高优先级）
2. 同 priority 时按 YAML 声明顺序
3. fnmatch 第一个命中即生效（first-match-wins）
4. 无命中时 fallback 到 default_chunker，生成 rule_id 为空的临时 SourceRule
```

#### 冲突处理

| 场景 | 行为 |
|------|------|
| 两个 rule 匹配同一文件 | priority 低者胜；同 priority 时声明顺序胜 |
| rule 引用不存在的 chunker | `health_check()` 返回 degraded；运行时记录 `AssemblyDiagnostic(error_type="instantiation")` |
| chunk_params 与 __init__ 签名不匹配 | `health_check()` 阶段通过 `inspect.signature.bind_partial()` 预检；运行时 TypeErrors 被 assemble() 捕获 |
| 无匹配 rule | `SourceRouter.resolve()` 发出 `fallback_used` 事件，返回 default_chunker 的临时 SourceRule |

---

### 4. `configs/default_pipeline.yaml` schema

```yaml
version: "1.0.0"

default_chunker: recursive
default_params:
  chunk_size: 512
  chunk_overlap: 64

source_rules:
  - pattern: "docs/api/**/*.md"
    chunker: fixed
    chunk_params:
      chunk_size: 256
      chunk_overlap: 32
    priority: 10
    description: "API docs: small fixed chunks for per-endpoint retrieval"
    rule_id: "api-fixed-v1"  # ← 显式 rule_id，便于人工识别

  - pattern: "kb/**/*.md"
    chunker: recursive
    chunk_params:
      chunk_size: 512
      chunk_overlap: 64
    priority: 20
    description: "Knowledge base: recursive separator chunking"

  - pattern: "docs/security/**/*.md"
    chunker: multi_granularity
    chunk_params:
      fine_size: 256
      coarse_size: 512
    priority: 5
    description: "Security docs: multi-granularity for defense-in-depth"
```

#### 字段约束

| 字段 | 必需 | 类型 | 默认值 | 约束 |
|------|------|------|--------|------|
| `version` | ✅ | string | — | 合法 SemVer |
| `default_chunker` | ❌ | string | `recursive` | COMPONENT_REGISTRY 中存在 |
| `default_params` | ❌ | dict | `{}` | kwargs 需通过 `__init__` 签名校验 |
| `source_rules[].pattern` | ✅ | string | — | glob，非空 |
| `source_rules[].chunker` | ✅ | string | — | COMPONENT_REGISTRY 中存在 |
| `source_rules[].chunk_params` | ❌ | dict | `{}` | kwargs 需通过 `__init__` 签名校验 |
| `source_rules[].priority` | ❌ | int | `100` | 越小优先级越高 |
| `source_rules[].description` | ❌ | string | `""` | 仅文档，不影响路由 |
| `source_rules[].rule_id` | ❌ | string | auto | 显式声明或自动生成（sha256 前 12 位） |

---

### 5. 与现有组件的交互时序

```
调用方（demo_rag.py）
  │
  ├─ 1. documents = {p: _load_document(p) for p in paths}
  │
  ├─ 2. composer = PipelineComposer.from_yaml("configs/default_pipeline.yaml")
  │      │                                     ↑ 便捷工厂
  │      └─ CompositionBlueprint.from_yaml(path)
  │           ├─ yaml.safe_load()
  │           ├─ SemVer.parse(version)
  │           ├─ [SourceRule(...), ...]  # sorted by priority, rule_id assigned
  │           └─ CompositionBlueprint(version, default_chunker, default_params, rules)
  │      └─ SourceRouter(blueprint, event_sink=...)
  │           └─ health_check() → inspect.signature 预检所有 chunker + params
  │      └─ PipelineAssembler(event_sink=...)
  │
  ├─ 3. retriever = composer.compose_for_sources(paths, documents)
  │      │
  │      ├─ 3a. resolved = router.resolve_all(paths)
  │      │      └─ for each path:
  │      │           router.resolve(path)
  │      │             ├─ emit: rule_matched | rule_skipped | fallback_used
  │      │             └─ return SourceRule
  │      │
  │      └─ 3b. retriever = assembler.assemble(resolved, documents, blueprint_version)
  │             ├─ for each (path, doc):
  │             │    ├─ COMPONENT_REGISTRY.get("chunker", rule.chunker)
  │             │    ├─ chunker = cls(**rule.chunk_params)
  │             │    │    └─ emit: chunker_instantiated {rule_id, params_hash, version}
  │             │    ├─ adapter = ChunkerAdapter(chunker)
  │             │    ├─ output = adapter.run({"content": doc}, resources)
  │             │    └─ ch.with_metadata(
  │             │         source_path, chunker_strategy, chunker_version,
  │             │         rule_id, blueprint_version, composed_at  ← 完整血缘
  │             │       )
  │             │
  │             ├─ emit: assembly_complete {total_docs, success, fail, total_chunks}
  │             └─ InMemoryVectorBackend(all_chunks) → RetrieverStep
  │
  ├─ 4. 审计: composer.audit_manifest → {fingerprint, version, router_type, ...}
  │
  └─ 5. 注入 Pipeline: PlanningContext(knowledge_context=retriever)
```

#### 与 factory.py 的关系

```
factory.py                           composer.py
─────────────────────────────────────────────────────────
StepConfig → PipelineStep            Blueprint → RetrieverStep
单步创建                              多步编排
@lru_cache 缓存                       不缓存（组合结果不重用）
引擎不可见                              引擎不可见
```

---

### 6. 错误处理 + 审计矩阵

| 场景 | 阶段 | 行为 |
|------|------|------|
| YAML 语法错误 | from_yaml() | `yaml.YAMLError`，启动失败 |
| version 非法 | from_yaml() | `SemVer.parse()` 抛 `ValueError`，启动失败 |
| chunker 策略不存在 | health_check() | status=degraded，列出缺失策略 |
| chunk_params 签名不匹配 | health_check() | status=degraded，列出不合法的参数名 |
| 单个文档无匹配规则 | Router.resolve() | 发出 `fallback_used` 事件，使用 default_chunker |
| 单文档 chunker 不存在 | Assembler.assemble() | `AssemblyDiagnostic(error_type="instantiation")`，跳过该文档 |
| 单文档 chunk_params 错误 | Assembler.assemble() | `AssemblyDiagnostic(error_type="instantiation")`，跳过该文档 |
| 单文档 adapter 执行失败 | Assembler.assemble() | `AssemblyDiagnostic(error_type="execution")`，跳过该文档 |
| 单文档 contract validation 失败 | Assembler.assemble() | `AssemblyDiagnostic(error_type="validation")`，跳过该文档 |
| 全部文档失败 | Assembler.assemble() | `AssemblyError` 抛出，含全部 `AssemblyDiagnostic` |
| 部分文档失败 | Assembler.assemble() | 成功 chunk 聚合，失败在 `composer.diagnostics` |
| 运行时审计查询 | composer.audit_manifest | `{fingerprint, version, router_type, timestamp}` |

---

### 7. VIOLATION INDICATOR 更新

Phase 19 引入后，以下行为视为架构退化：

| 指标 | 说明 |
|------|------|
| Blueprint 包含 `resolve()` 或任何匹配算法 | 数据模型与算法耦合 |
| `SourceRouter.resolve()` 产生副作用（I/O、网络、状态变更） | Router 是纯函数 |
| `PipelineAssembler.assemble()` 直接 `logging.info()` | 引擎零日志框架依赖；使用 event_sink |
| 调用方绕过 `PipelineComposer` 直接创建 Router/Assembler | 破坏 Facade 封装（测试除外） |
| `AssemblyDiagnostic` 使用 `Dict[str, Any]` 代替 frozen dataclass | 非结构化错误不可过滤/序列化 |
| Chunk metadata 缺少 `rule_id` 或 `blueprint_version` | 血缘断裂，不可追溯 |
| `audit_manifest` 缺少 `blueprint_fingerprint` | 事故不可复现 |
| Composer 构造函数接受文件路径而非 Blueprint | 配置源与引擎耦合 |

---

### 8. 测试规格 `tests/unit/test_pipeline_composer.py`

```python
# 测试范围 (~80 行)

class TestSourceRule:
    def test_matches_simple_glob(self): ...
    def test_matches_deep_glob(self): ...
    def test_no_match(self): ...
    def test_rule_id_deterministic(self): ...
    def test_rule_id_explicit_overrides_auto(self): ...

class TestCompositionBlueprint:
    def test_from_yaml_valid(self): ...
    def test_from_yaml_invalid_version_raises(self): ...
    def test_from_yaml_missing_pattern_raises(self): ...
    def test_from_dict_programmatic(self): ...
    def test_rules_sorted_by_priority(self): ...
    def test_fingerprint_deterministic(self): ...
    def test_fingerprint_changes_on_config_change(self): ...

class TestSourceRouter:
    def test_resolve_first_match_wins(self): ...
    def test_resolve_fallback_to_default(self): ...
    def test_events_emitted_for_match_skip_fallback(self): ...
    def test_health_check_all_resolvable(self): ...
    def test_health_check_missing_strategy(self): ...
    def test_health_check_invalid_params_caught(self): ...

class TestPipelineAssembler:
    def test_assemble_single_document(self): ...
    def test_assemble_chunk_lineage_complete(self): ...  # rule_id, blueprint_version, composed_at
    def test_assemble_partial_failure_yields_diagnostics(self): ...
    def test_diagnostics_are_AssemblyDiagnostic_instances(self): ...
    def test_assemble_all_failure_raises_AssemblyError(self): ...
    def test_events_emitted_for_chunker_instantiation_and_completion(self): ...

class TestPipelineComposer:
    def test_from_yaml_end_to_end(self): ...
    def test_from_dict_test_friendly(self): ...
    def test_audit_manifest_contains_fingerprint(self): ...
    def test_compose_for_sources_returns_RetrieverStep(self): ...

class TestArchitectureInvariants:
    """Tests that verify the constitutional integrity of the kernel itself.

    These are NOT feature tests — they are automated enforcement of the
    architectural constitution. If any of these fail, the kernel's soul has
    been compromised, regardless of whether feature tests pass.
    """
    def test_blueprint_has_no_resolve_method(self): ...
    def test_blueprint_has_no_algorithm_logic(self): ...
    def test_router_is_pure_function_no_side_effects(self): ...
    def test_assembler_never_imports_logging(self): ...
    def test_assembler_never_calls_print(self): ...
    def test_registry_frozen_after_bootstrap(self): ...
    def test_contracts_layer_has_zero_external_imports(self): ...
    def test_pipeline_layer_never_imports_chunk_types(self): ...
    def test_all_chunkers_declare_VERSION(self): ...
    def test_all_rules_have_deterministic_rule_id(self): ...
    def test_event_has_correlation_id(self): ...
    def test_diagnostic_has_contract_violation_field_present(self): ...
```

---

### 改动清单

| 文件 | 操作 | 行数 |
|------|------|------|
| `core/contracts/composition.py` | 新增 | ~180 |
| `core/adapters/composer.py` | 新增 | ~230 |
| `configs/default_pipeline.yaml` | 新增 | ~30 |
| `tests/unit/test_pipeline_composer.py` | 新增 | ~80 |

**总计**: 4 个新文件，~520 行，零改动现有文件

---

### 验证

- [ ] `pytest tests/unit/test_pipeline_composer.py -q` — 新增测试全部通过
- [ ] `pytest tests/ -q` — 全量零回归
- [ ] `python -m guardrails check --all` — 16/16 通过，无新增违规
- [ ] `CompositionBlueprint.from_yaml("configs/default_pipeline.yaml")` 成功解析
- [ ] `blueprint.fingerprint` 确定性：相同内容 → 相同 hash
- [ ] `SourceRouter.health_check()` 预检所有 chunker 策略存在 + params 合法
- [ ] `SourceRouter.resolve()` 正确路由，emit 完整事件链
- [ ] `PipelineAssembler.assemble()` 返回的每个 Chunk 携带 `rule_id` + `blueprint_version` + `composed_at`
- [ ] 部分文档失败时 `diagnostics` 包含 `AssemblyDiagnostic` 实例
- [ ] 全部文档失败时抛出 `AssemblyError`
- [ ] `PipelineComposer.audit_manifest` 包含 `blueprint_fingerprint`
- [ ] `PipelineComposer.from_dict(raw)` 测试友好，无需临时文件

---

## Phase 19.5: 让事件流动起来 — ContractAwareEventSink

### 定位

Phase 19 定义了 `event_sink` 依赖注入和 `CompositionEvent`，但它只是 `list.append` 占位符。Phase 19.5 给它装上脊柱：**结构化存储、查询能力、契约违约感知**。这是从"指令执行"迈向"契约感知"的最小可行一步。

```
Phase 19                      Phase 19.5
─────────────────────────────────────────────────
event_sink = list.append      event_sink = ContractAwareEventSink()
事件只是发射出去               事件可查询、可分类、可审计
contract_violation = None     contract_violation = "unknown_chunker_strategy" | ...
诊断是技术错误描述             诊断开始承载契约语义
```

### 新增文件

```
core/adapters/
└── event_sink.py              ← [新增] ContractAwareEventSink (~140 LOC)
```

### ContractAwareEventSink — 设计

```python
class ContractAwareEventSink:
    """Callable — drop-in for any event_sink parameter.
    Queryable — by correlation_id, by event_type, by contract violation."""

    def __call__(self, event: CompositionEvent) -> None:  # thread-safe append
    def by_correlation(self, correlation_id: str) -> List[CompositionEvent]:
    def by_type(self, event_type: str) -> List[CompositionEvent]:
    @property
    def violations(self) -> List[CompositionEvent]:  # events with contract_violation
    @property
    def violation_count(self) -> int:
    def violations_by_type(self) -> Dict[str, List[CompositionEvent]]:
    @property
    def summary(self) -> Dict[str, Any]:  # JSON-safe audit summary
    def clear(self) -> None:
```

### PipelineAssembler._classify_violation — 违约分类

将技术错误类型映射为契约违约类别：

| error_type | 条件 | contract_violation |
|-----------|------|-------------------|
| routing | 文档无匹配规则 | `routing_contract_breach` |
| instantiation | chunker 策略不存在 | `unknown_chunker_strategy` |
| instantiation | 参数签名不匹配 | `invalid_chunk_params` |
| execution | 适配器运行失败 | `None` (技术故障，非契约违约) |
| validation | 输出契约校验失败 | `output_contract_violation` |

违约信息同时写入 `AssemblyDiagnostic.contract_violation` 和 `CompositionEvent.context["contract_violation"]`。

### 关键设计决策

**为什么 `execution` 不算契约违约**

适配器运行时抛异常的原因可能是 bug、OOM、网络抖动——这些是技术故障，不是契约违约。契约违约意味着"Blueprint 声明的条款无法被满足"（chunker 不存在、参数非法）。区分二者是 Phase 25+ 优雅降级的基础：技术故障 → 重试/降级；契约违约 → renegotiate。

**为什么 `ContractAwareEventSink` 用线程锁**

当前引擎是同步的，但 Phase 20+ 将引入 async 并发执行。`threading.Lock` 的一次性成本（~50ns per uncontended acquire）确保未来不需要重构存储层。

### 两个在实现中暴露的 Bug

#### Bug 1: `threading.Lock` 死锁

`summary` 属性持有 `_lock` 后调用 `violations_by_type()`，后者再次尝试获取同一把非可重入锁 → 死锁。修复：在单个锁获取内内联计算所有数据。教训：持有锁的公共方法永远不能调用同样获取该锁的兄弟方法。

#### Bug 2: Python `__len__` truthiness 陷阱

```python
# ❌ 有缺陷的模式（composer.py line 46/52/168）
self._emit = event_sink or (lambda e: None)

# ContractAwareEventSink 实现了 __len__ → 返回 0 → Python 判为 falsy
# → sink 被静默替换为 no-op lambda → 所有事件丢失
```

修复：`event_sink if event_sink is not None else (lambda _e: None)`。教训：对实现了 `__len__` 的可调用对象，用 `is not None` 而非 `or`。`list.append` 是 bound method（永远 truthy），所以之前所有测试从未暴露此 bug。

### 测试覆盖

| 测试类 | 测试数 | 核心验证 |
|--------|--------|---------|
| `TestContractViolationDetection` | 5 | unknown strategy → contract_violation 正确分类，事件 context 包含违约信息，execution 不分类为违约，所有四个类别覆盖 |
| `TestContractAwareEventSink` | 11 | callable 接口，by_correlation 单文档追踪，by_type 筛选，violations/violations_by_type 违约提取，summary JSON 审计，clear 重置，e2e 端到端，repr |

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/adapters/event_sink.py` | 新增 | ContractAwareEventSink (~140 LOC) |
| `core/adapters/composer.py` | 修改 | `_classify_violation()`, `_record_failure` 填充 contract_violation, `is not None` 修复 |
| `core/adapters/__init__.py` | 修改 | 导出 ContractAwareEventSink |
| `tests/unit/test_pipeline_composer.py` | 修改 | +16 测试 (5 违约检测 + 11 Sink) |

### 验证

- [x] `pytest tests/unit/test_pipeline_composer.py -q` — 67/67 通过
- [x] `pytest tests/ -q` — 740/740 通过, 0 回归
- [x] `python -m guardrails check --all` — 39 files, 16 rules, 0 violations

---

## Phase 20: 契约健康度评估器 — 让系统理解自己的痛苦

### 定位

Phase 19.5 让违约信号可追溯、可分类。Phase 20 将这些离散信号聚合为**可决策的关系状态**。这是"关系认知层"的基石——系统第一次拥有了对自身履约状态的量化认知。

```
Phase 19.5                    Phase 20
─────────────────────────────────────────────────
ContractAwareEventSink        ContractHealthEvaluator
"这里违约了"                    "整体履约率 0.6, 严重度 critical, 正在恶化"
离散事件                        聚合的健康状态
查询违约信号                    输出可决策的关系评估
```

### 核心抽象

```
ContractAwareEventSink  ──→  ContractHealthEvaluator  ──→  ContractHealthReport
     (信号源)                    (纯函数评估器)                  (结构化自省)
                                     │
                              SeverityMapping (注入)
                              ┌──────────────────────┐
                              │ unknown → count≥1 → critical
                              │ routing  → count≥3 → critical
                              │ params   → count≥1 → degraded
                              │ output   → count≥1 → degraded
                              └──────────────────────┘
```

### 新增文件

```
core/
├── contracts/
│   └── composition.py          ← [修改] ContractViolation StrEnum,
│                                  SeverityRule, SeverityMapping,
│                                  ContractHealthReport (+~80 LOC)
│
└── adapters/
    └── health_evaluator.py     ← [新增] ContractHealthEvaluator (~100 LOC)
```

### ContractViolation — StrEnum 枚举

```python
class ContractViolation(str, Enum):
    """str subclass → backward compatible. Enum → IDE autocomplete, typo-proof."""
    UNKNOWN_CHUNKER_STRATEGY = "unknown_chunker_strategy"
    INVALID_CHUNK_PARAMS = "invalid_chunk_params"
    ROUTING_CONTRACT_BREACH = "routing_contract_breach"
    OUTPUT_CONTRACT_VIOLATION = "output_contract_violation"
```

`_classify_violation()` 现在返回 `ContractViolation | None`，不再是裸 `str`。下游代码可以用 `ContractViolation.UNKNOWN_CHUNKER_STRATEGY` 替代字符串字面量。

### SeverityMapping — 可注入的严重度规则

```python
@dataclass(frozen=True)
class SeverityRule:
    violation_type: str       # ContractViolation 枚举值
    count_threshold: int = 1  # 多少个触发此严重度
    severity: Literal["healthy", "degraded", "critical"] = "degraded"

@dataclass(frozen=True)
class SeverityMapping:
    rules: Tuple[SeverityRule, ...]

    @classmethod
    def default(cls) -> SeverityMapping:
        """unknown_chunker → critical ×1, routing_breach → critical ×3,
           invalid_params → degraded ×1, output_violation → degraded ×1"""
```

规则顺序决定优先级。第一个匹配的规则生效。`critical` 覆盖 `degraded`，`degraded` 覆盖 `healthy`。

### ContractHealthReport — 系统自省的数据结构

```python
@dataclass(frozen=True)
class ContractHealthReport:
    compliance_rate: float          # 0.0–1.0
    severity: Literal["healthy", "degraded", "critical"]
    dominant_violation_type: str | None
    trend: Literal["improving", "stable", "deteriorating"] | None
    total_documents: int
    total_events: int
    violation_counts: MappingProxyType[str, int]
    evaluated_at: float
```

### ContractHealthEvaluator — 纯函数评估器

```python
class ContractHealthEvaluator:
    def __init__(self, severity_mapping: SeverityMapping | None = None): ...
    def evaluate(
        self,
        sink: ContractAwareEventSink,
        previous: ContractHealthReport | None = None,  # 调用方传入快照
    ) -> ContractHealthReport: ...
```

设计约束：
- **纯函数** — 相同输入永远相同输出。不持有锁、不修改 Sink、不缓存跨调用结果
- **趋势无状态** — `previous` 由调用方传入，评估器自己零存储
- **严重度映射可注入** — 测试用严格规则，生产用宽松规则，无需改代码
- **零 truthiness 检查** — 所有条件用 `is not None`，不复现 Phase 19.5 的 `or` 陷阱

### 严重度决策算法

```
1. 遍历 SeverityMapping.rules
2. 对每条 rule: 检查 violation_counts[rule.violation_type] >= rule.count_threshold
3. 若 critical → 立即返回 critical (最高优先)
4. 若 degraded → 记录 degraded，继续检查
5. 无匹配 → healthy
```

### 测试覆盖

| 测试类 | 测试数 | 核心验证 |
|--------|--------|---------|
| `TestContractHealthEvaluator` | 18 | 空=healthy, 全成功=healthy, 违约→critical, 低于阈值=healthy, 跨类别优先级, compliance_rate 计算, dominant_violation_type, trend (none/improving/stable/deteriorating), 确定性, 不修改 sink, 自定义映射 |
| `TestContractViolationEnum` | 4 | str 子类, 字符串相等, dict 键, 四种类别完整性 |
| `TestSeverityMappingDefaults` | 4 | 4 条规则, unknown=critical×1, routing=critical×3, params=degraded×1 |
| `TestContractHealthReport` | 2 | compliance_rate 范围校验, violation_counts 深拷贝 |

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/contracts/composition.py` | 修改 | ContractViolation enum, SeverityRule, SeverityMapping, ContractHealthReport |
| `core/adapters/health_evaluator.py` | 新增 | ContractHealthEvaluator |
| `core/adapters/composer.py` | 修改 | `_classify_violation` 返回 ContractViolation 枚举 |
| `core/adapters/__init__.py` | 修改 | 导出 ContractHealthEvaluator |
| `core/contracts/__init__.py` | 修改 | 导出 Phase 20 数据模型 |
| `tests/unit/test_pipeline_composer.py` | 修改 | +27 测试 |

### 验证

- [x] `pytest tests/unit/test_pipeline_composer.py -q` — 94/94 通过
- [x] `pytest tests/ -q` — 767/767 通过, 0 回归
- [x] `python -m guardrails check --all` — 40 files, 16 rules, 0 violations

---

## Phase 21: Blueprint Lifecycle — 为契约注入时间维度 (~40 行核心代码)

### 完成日期

2026-05-28

### 定位

Phase 20 让系统"感知履约状态"，但所有违规都被等同视之。Phase 21 解决：
**不是所有违约都同等重要。Active 契约的违约是"正在流血的伤口"，Deprecated 契约的违约是"已经结痂的旧伤"。**

这是 Phase 20 的 `trend` 从"比较两个无时间的快照"升级为"演化分析"的关键前置：
没有 lifecycle，trend 只是在说"变好/变坏"；有了 lifecycle，trend 可以区分"Active 契约在恶化"vs"只是 Deprecated 残留噪声"。

### 核心数据结构

```python
class ContractLifecycle(str, Enum):
    DRAFT = "draft"         # 实验性, 违约 0.5x 权重
    ACTIVE = "active"       # 生产契约, 违约 1.0x 全权重
    DEPRECATED = "deprecated"  # 遗留契约, 违约 0.3x 权重, 禁止新路由

@dataclass(frozen=True)
class CompositionBlueprint:
    version: SemVer
    lifecycle: ContractLifecycle = ContractLifecycle.ACTIVE  # ← 新增
    # ... 其余字段不变 ...
```

**向后兼容**：`lifecycle` 默认值 `ACTIVE`。所有现有 YAML、测试、程序化构造无需修改即可通过——零迁移负担。

### 三条行为规则

| # | 规则 | 实现位置 |
|---|------|---------|
| 1 | **默认 ACTIVE** — 无 `lifecycle` 字段的旧配置自动视为 ACTIVE | `CompositionBlueprint.__post_init__` 字符串→枚举归一化 |
| 2 | **DEPRECATED 拦截** — 新路由请求遇到 DEPRECATED 蓝图直接抛 `AssemblyError` | `SourceRouter.resolve()` 开头硬检查 |
| 3 | **权重感知评估** — HealthEvaluator 按 lifecycle 加权计算 severity | `ContractHealthEvaluator._compute_weighted_violations()` |

### 生命周期权重

```
HealthEvaluator._LIFECYCLE_WEIGHTS = {
    "active":     1.0,   # 全权重
    "draft":      0.5,   # 减半
    "deprecated": 0.3,   # 降至 30%
}
```

这意味着：
- 1 次 ACTIVE `unknown_chunker_strategy` → critical（≥1 阈值）
- 2 次 DRAFT 同类违规 → 加权 1.0 → 刚好 critical
- 4 次 DEPRECATED 同类违规 → 加权 1.2 → 刚超过 critical 阈值

### SourceRouter 的"优雅拒绝"

```python
def resolve(self, path: str) -> SourceRule:
    if self._blueprint.lifecycle == ContractLifecycle.DEPRECATED:
        raise AssemblyError(
            f"Cannot route to deprecated blueprint "
            f"(version {self._blueprint.version}). "
            f"Use an active or draft alternative."
        )
    # ... normal routing logic ...
```

关键设计：只拦截**新**路由请求，不中断**已运行**的 Pipeline。`PipelineComposer` 创建时持有 Blueprint 引用——已运行的实例不受影响。这是"优雅降级"（graceful rejection）而非"暴力中断"。

### HealthEvaluator 增强

```python
def evaluate(self, sink, previous=None):
    # Phase 21: 计算 lifecycle 加权违规计数 + 分布
    weighted_by_cat, lifecycle_dist = self._compute_weighted_violations(sink)

    # severity 使用加权计数（非原始计数）
    severity = self._compute_severity(weighted_by_cat)

    return ContractHealthReport(
        # ...
        lifecycle_distribution=lifecycle_dist,  # ← 新字段
    )
```

### 事件上下文传递

`blueprint_lifecycle` 随 `document_failed` 事件流入 sink：

```python
# PipelineAssembler._record_failure
context = {
    # ...
    "blueprint_lifecycle": self._blueprint_lifecycle,  # StrEnum, 直接可用
}
```

### 与 Phase 20 的协同

```
之前: report = evaluator.evaluate(sink)
      → 只知道"有3次违约，趋势恶化"

现在: report = evaluator.evaluate(sink)
      → 3次违约中2次来自 deprecated 契约 → 实际 severity=degraded 而非 critical
      → trend=deteriorating 是因为 active 违约在增加，而非 deprecated 残留噪声
      → lifecycle_distribution={active: 5, deprecated: 2} → 提示需要清理遗留契约
```

### 测试覆盖

| 测试类 | 测试数 | 核心验证 |
|--------|--------|---------|
| `TestContractLifecycle` | 5 | str 子类, 字符串相等, from_string, 非法值抛异常, 三阶段完整性 |
| `TestBlueprintLifecycle` | 6 | 默认 ACTIVE, 显式赋值, from_yaml, fingerprint 差异, 字符串归一化, 类型保证 |
| `TestSourceRouterDeprecatedRejection` | 4 | deprecated 抛 AssemblyError, active 正常, draft 正常, resolve_all 拦截 |
| `TestPipelineAssemblerLifecycleEvents` | 2 | 事件携带 blueprint_lifecycle, 默认 lifecycle=ACTIVE |
| `TestLifecycleWeightedHealthEvaluation` | 11 | active 全权重, draft 半权重, 2×draft=critical, deprecated 0.3× 权重, 4×deprecated=critical, active 优先, lifecycle_distribution, 默认 lifecycle, routing+draft, routing+deprecated |
| `TestAuditManifestLifecycle` | 2 | draft 在 manifest, 默认 active |
| `TestPhase21ArchitectureInvariants` | 3 | #28 默认 ACTIVE ≠ None, #29 拒绝 deprecated, active/draft 不拒绝 |
| `TestContractHealthReport` | +1 | lifecycle_distribution 深拷贝 |

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/contracts/composition.py` | 修改 | ContractLifecycle enum, CompositionBlueprint.lifecycle 字段, fingerprint 含 lifecycle, _from_raw 解析, ContractHealthReport.lifecycle_distribution |
| `core/adapters/composer.py` | 修改 | SourceRouter DEPRECATED 拦截, PipelineAssembler 接收+传递 lifecycle, PipelineComposer 传递 lifecycle, audit_manifest 含 lifecycle |
| `core/adapters/health_evaluator.py` | 修改 | _compute_weighted_violations, lifecycle 权重常数, lifecycle_distribution |
| `core/contracts/__init__.py` | 修改 | 导出 ContractLifecycle |
| `CLAUDE.md` | 修改 | 新增不变量 #28-#29 |
| `tests/unit/test_pipeline_composer.py` | 修改 | +33 测试 (127 total) |

### 验证

- [x] `pytest tests/unit/test_pipeline_composer.py -q` — 127/127 通过
- [x] `pytest tests/ -q` — 800/800 通过, 0 回归
- [x] `python -m guardrails check --all` — 通过

---

## Phase 22: Contract-Adaptive Muscle Layer — 从被动认知到主动修复 (22a+22b+22c)

### 完成日期

2026-05-29

### 定位

Phase 19-21 构建了"神经系统"——能感知违约、评估健康、区分严重程度。但它是被动的：能感觉到痛，不会止血。

Phase 22 是"肌肉层"——三个能力协同工作，让契约关系体从"能感受自己正在违约"进化到"能为此做些什么"。

### 三块肌肉

| 子阶段 | 文件 | 角色 | 范式 |
|--------|------|------|------|
| 22a Tool Contract | `contracts/tool.py` + `adapters/tool_adapter.py` | LLM function_call → ToolCall → ToolResult，带 blueprint 校验 | 组件适配器 (1:1 翻译) |
| 22b Self-Repair | `adapters/repair_engine.py` | 消费 HealthReport → 决策修复策略 → 消耗 RepairBudget → 优雅降级 | 语法引擎 (N:M 编排) |
| 22c Memory | `adapters/persistence.py` | SQLite 持久化 health transition（delta），跨会话关系历史 | 基础设施 |

### 22a: Tool Contract — 工具调用进入契约体系

**核心设计**：

```
LLM function_call (raw dict)
    ↓ ToolAdapter.parse_function_call()
ToolCall (deterministic call_id, frozen)
    ↓ ToolAdapter._validate_against_blueprint()
    ├── Tool 是否在 Registry 中存在？
    ├── 参数是否匹配 ToolProtocol.parameters_schema？
    └── 不通过 → ContractViolation → EventSink
    ↓ 通过
ToolAdapter.execute()
    ↓ COMPONENT_REGISTRY.get("tool", name) ← USB 模型
ToolResult (success/error/contract_violation)
    ↓ tool_executed event → EventSink → HealthEvaluator
```

**新增 ContractViolation 类型**：

```python
TOOL_NOT_FOUND = "tool_not_found"        # critical, threshold=1
TOOL_PARAM_MISMATCH = "tool_param_mismatch"  # degraded, threshold=1
```

**关键设计决策**：Tool 执行失败（exception during execute()）不是契约违规——与技术失败（chunker execution failure）同构。只有"工具不存在"和"参数不匹配"才是契约层面问题。

### 22b: Self-Repair Engine — 违约→修复闭环

**核心设计**：

```
ContractHealthReport (severity=degraded/critical)
    ↓ SelfRepairEngine.decide(report, sink)
    ├── 对每个 violation_type:
    │   ├── 检查 RepairBudget.can_repair(type)
    │   ├── 选择策略: RETRY_WITH_DEFAULT | REPLACE_COMPONENT | GIVE_UP
    │   └── budget = budget.consume(type)
    ├── budget 耗尽 → emit repair_budget_exhausted
    └── 返回 List[RepairAction]
    ↓ SelfRepairEngine.execute_all(actions)
    ├── 记录 repair_attempted event → EventSink
    └── 返回 results → 调用方重新执行 pipeline
```

**修复策略映射**：

| ContractViolation | RepairStrategy | 说明 |
|------------------|----------------|------|
| UNKNOWN_CHUNKER_STRATEGY | REPLACE_COMPONENT | 用 default_chunker 替代 |
| INVALID_CHUNK_PARAMS | RETRY_WITH_DEFAULT | 用 default_params 重试 |
| ROUTING_CONTRACT_BREACH | RETRY_WITH_DEFAULT | 用 default_chunker 重试 |
| OUTPUT_CONTRACT_VIOLATION | RETRY_WITH_DEFAULT | 重试一次（可能 transient） |
| TOOL_NOT_FOUND | REPLACE_COMPONENT | 从 Registry 找替代工具 |
| TOOL_PARAM_MISMATCH | RETRY_WITH_DEFAULT | 用默认参数重试 |

**RepairBudget**：`max_total=5, max_per_type=2`。预算耗尽时发出 `repair_budget_exhausted` 事件——"承认自己无能为力"进入契约合规体系。系统不崩溃、不死锁、不无限重试。

### 22c: Relationship Memory — 关系演化轨迹持久化

**核心设计**：存 transition（delta），不存 snapshot（全量快照）。

```
不是:
  snapshot_1: {compliance: 1.0, severity: healthy}
  snapshot_2: {compliance: 0.6, severity: degraded}

而是:
  transition: {compliance_delta: -0.4, severity_before: healthy, severity_after: degraded}
```

**SQLite Schema**：

```sql
CREATE TABLE health_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    blueprint_fingerprint TEXT NOT NULL,
    timestamp REAL NOT NULL,
    compliance_delta REAL NOT NULL,
    severity_before TEXT NOT NULL DEFAULT 'healthy',
    severity_after TEXT NOT NULL DEFAULT 'healthy',
    dominant_violation TEXT,
    violation_snapshot TEXT DEFAULT '{}',
    lifecycle TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX idx_fingerprint_time ON health_transitions(blueprint_fingerprint, timestamp);
CREATE INDEX idx_lifecycle ON health_transitions(lifecycle);
```

**查询能力**：
- `get_history(fingerprint, days=7)` — 获取过去 N 天的 transition 序列
- `get_latest(fingerprint)` — 最近一次 transition
- `get_deterioration_count(fingerprint, days=7)` — 恶化次数
- `count_transitions(fingerprint, days=7)` — 总 transition 数

### 架构约束

所有新代码严格遵循 adapters/ 作为唯一全权限中枢的约束：

```
ToolAdapter          → adapters/ (imports contracts + Registry)
SelfRepairEngine     → adapters/ (imports contracts + event_sink + health_evaluator)
RelationshipMemoryStore → adapters/ (imports contracts + threading.Lock)
```

修复了 Phase 22 之前的一个边界违规：`pace_stream()` 从 `pipeline/streaming.py` 移到 `adapters/stream_adapter.py`——因为它在构造 PaceShapingWrapper（一个适配器类），pipeline 不应 import adapters。

### 新增 CompositionEvent 类型

```
"tool_executed"           — ToolAdapter 执行工具后发出
"repair_attempted"        — SelfRepairEngine 执行修复后发出
"repair_budget_exhausted" — RepairBudget 耗尽时发出
```

### 协同效应：完整闭环

```
ToolAdapter 校验 → tool_executed event
    ↓
EventSink 积累
    ↓
HealthEvaluator 评估 → ContractHealthReport
    ↓
SelfRepairEngine 决策 → RepairAction
    ↓ 查询 Registry (USB)
替代工具/策略 → 重新执行 → 成功
    ↓
HealthEvaluator 重新评估 → compliance 回升 → trend=improving
    ↓
RelationshipMemoryStore 记录 transition
    ↓
下次评估：MemoryStore 提供历史，trend 从查 transition 而非外部注入
```

### 测试覆盖

| 测试类 | 测试数 | 核心验证 |
|--------|--------|---------|
| TestToolCall | 7 | 确定性 call_id, 参数拷贝, 排序无关, frozen |
| TestToolResult | 3 | 成功, 失败+违规, frozen |
| TestToolAdapterParse | 7 | 有效调用, 缺 name, JSON 字符串参数, 非法类型, 非法 JSON, 默认参数 |
| TestToolAdapterValidate | 3 | 空工具名, 未注册工具, 无 blueprint |
| TestToolAdapterExecute | 2 | 工具不存在, 空名称在 Registry 之前被拦截 |
| TestSeverityMappingToolViolations | 2 | TOOL_NOT_FOUND=critical, TOOL_PARAM_MISMATCH=degraded |
| TestPhase22aArchitectureInvariants | 3 | 确定性 call_id, ToolResult 携带 contract_violation, USB 模型 |
| TestRepairBudget | 6 | 默认值, 预算内, consume, per_type, total, exhausted |
| TestSelfRepairEngine | 10 | healthy=无动作, degraded→动作, unknown→replace, tool→replace, 预算限制, execute_all, budget exhausted 事件, repair_attempted 事件, 枚举值, frozen |
| TestRelationshipMemoryStore | 11 | 空, 首个 transition, delta 追踪, get_latest, limit, count, deterioration, blueprint 隔离, clear, JSON snapshot, lifecycle 字段 |

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/contracts/tool.py` | 新增 | ToolProtocol, ToolCall, ToolResult |
| `core/contracts/composition.py` | 修改 | +2 ContractViolation, +3 event_type, +2 SeverityRule |
| `core/contracts/__init__.py` | 修改 | 导出 ToolCall, ToolProtocol, ToolResult |
| `core/adapters/tool_adapter.py` | 新增 | ToolAdapter — 翻译+校验+执行 |
| `core/adapters/repair_engine.py` | 新增 | SelfRepairEngine + RepairBudget + RepairStrategy |
| `core/adapters/persistence.py` | 新增 | RelationshipMemoryStore — transition 持久化 |
| `core/adapters/__init__.py` | 修改 | 导出所有 Phase 22 类型 |
| `core/adapters/stream_adapter.py` | 修改 | +pace_stream (从 pipeline/ 移入) |
| `core/pipeline/streaming.py` | 修改 | -pace_stream (移出), 修复边界违规 |
| `CLAUDE.md` | 修改 | 新增不变量 #30-#31 (Tool USB 模型, ToolResult.contract_violation) |
| `tests/unit/test_pipeline_composer.py` | 修改 | +54 测试 (181 total) |

### 验证

- [x] `pytest tests/unit/test_pipeline_composer.py -q` — 181/181 通过
- [x] `pytest tests/ -q` — 854/854 通过, 0 回归
- [x] `python -m guardrails check --all` — 通过

---

## Phase 22 战备：Simulated Tools + Battle Script — 闭环验证

### 完成日期

2026-05-29

### 定位

Phase 22a/22b/22c 建造了肌肉系统。但肌肉需要在确定性场景中先验证咬合无误，再接入 LLM 混沌源。战备的两剂配方正是为此：

- **氮泵**：SimulatedWebSearch + SimulatedBraveSearch，注册到 USB 总线
- **肌酸**：demo_battle.py，24 断言闭环战斗脚本

### 氮泵：Simulated Battle Tools

```
components/tools/simulated_search.py
├── @register_component("tool", "web_search")  → SimulatedWebSearch
│   └── ClassVar _global_fail_on_call = 3  → 第 3 次调用起返回失败
└── @register_component("tool", "brave_search") → SimulatedBraveSearch
    └── 不同的 parameters_schema（支持 country 参数）
        └── 不同的返回格式（web.results vs results 数组）
```

**关键设计**：使用 ClassVar 计数器和失败阈值。因为 ToolAdapter.execute() 每次调用 `tool_cls()` 创建新实例——实例级状态会在每次调用时重置。ClassVar 是唯一能在实例重建后存活的共享状态。

### 肌酸：Battle Script

`demo/demo_battle.py` — 同时是 demo 和集成测试：

```
场景：量子计算研究（LLM 幻觉版）
─────────────────────────────────────
Round 1: web_search("quantum computing 2026")     ✅
Round 2: web_search("quantum error correction")    ✅
Round 3: google_search("topological qubits")       💥 TOOL_NOT_FOUND
  → HealthEvaluator: severity=critical, compliance=0.67
  → SelfRepairEngine: REPLACE_COMPONENT → brave_search
Round 4: brave_search("topological qubits")        ✅
  → Post-repair: compliance=0.80, trend=improving
  → MemoryStore: 2 transitions recorded
─────────────────────────────────────
24 assertions, exit code 0 = loop verified
```

### 战斗中发现并修复的问题

| 问题 | 根因 | 修复 |
|------|------|------|
| Tool 失败计数归零 | ToolAdapter 每次创建新实例，实例级 `_call_count` 重置 | 改用 ClassVar `_global_call_count` |
| 替换工具找回自己 | `_find_replacement` 取 `strategies[0]`，恰好是失败的工具 | 从 sink violations 提取失败工具名，跳过同名工具 |
| 修复后 severity 未回 healthy | sink 中历史违规事件不会自动清除 | 改为断言 trend=improving + compliance_rate 上升 |

### 设计洞察

1. **LLM 幻觉是比 rate_limit 更好的测试场景**。rate_limit 是技术性失败（不触发契约违规），LLM 幻觉（调用不存在的工具）触发 TOOL_NOT_FOUND——这是真正的契约违规，也是 SelfRepairEngine 设计要处理的场景。

2. **确定性优于真实性**。用模拟工具 + 手控 ToolCall 验证肌肉回路，比直接接 LLM 更高效——LLM 的随机性会掩盖回路本身的 bug。

3. **修复后 severity 不会立刻回到 healthy**。sink 是累加器——历史违规不会自动消失。真正的信号是 trend=improving 和 compliance_rate 上升。这是契约系统的"伤疤"机制：系统记得受过伤，但正在恢复。

### 验证

- [x] `python demo/demo_battle.py` — 24/24 断言通过
- [x] `pytest tests/ -q` — 854/854 通过, 0 回归
- [x] `python -m guardrails check --all` — 通过

---

## Phase 23: KernelService + ContractAware Engines — 旧城改造

### 完成日期

2026-05-29

### 定位

Phase 19-22 建造了契约自适应内核。Phase 14-18 建造了三引擎编排层（Planning / Orchestration / Critic）。但它们是两套平行的神经系统——编排层出错了直接崩溃，不会触发免疫系统。

Phase 23 的使命：用一个标准插头（KernelService Protocol）把旧城区接入新城区。

### 23a: KernelService Protocol — 标准插头

```python
class KernelService(Protocol):
    event_sink: Callable              # → EventSink
    def evaluate_health()             # → ContractHealthReport
    def decide_repair(report)         # → List[RepairAction]
    def execute_repairs(actions)      # → results
    blueprint: CompositionBlueprint   # → 当前契约
    blueprint_fingerprint: str        # → 审计指纹
    audit_manifest: dict              # → 运行时身份
```

**关键设计**：Application Layer 永远不 import `core/adapters/`——只依赖这个 Protocol。这是同心圆架构承诺的物理实现。

### 23b/23c/23d: 三个 ContractAware 包装器

**统一的装饰器模式**：

```
ContractAwarePlanningEngine      ← 包装 PlanningEngine.plan()
ContractAwareOrchestrationEngine  ← 包装 OrchestrationEngine.orchestrate()
ContractAwareCriticEngine         ← 包装 CriticEngine.evaluate()

三者共享完全相同的结构:
  1. 成功 → emit assembly_complete event
  2. 异常 → emit document_failed event (contract_violation=OUTPUT_CONTRACT_VIOLATION)
         → evaluate_health()
         → decide_repair()
         → execute_repairs()
         → re-raise
```

**零侵入**：底层引擎的代码一行不改。164 个编排层测试全部通过。

### 架构全景

```
                     KernelService (标准插头)
                    ┌─────────┼─────────┐
    ContractAware   ContractAware   ContractAware
    PlanningEngine  Orchestration   CriticEngine
         │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
    │ Stub │ LLM│  │ Stub │ LLM│  │ Stub │ LLM│  ← 旧城区 (164 tests)
    └─────────┘   └─────────┘   └─────────┘
         │              │              │
         └──────────────┼──────────────┘
                        ↓
              KernelService → EventSink
                             → HealthEvaluator
                             → SelfRepairEngine   ← 新城区 (854 tests)
                             → MemoryStore
```

### 改动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/contracts/kernel_service.py` | 新增 | KernelService Protocol |
| `core/contracts/__init__.py` | 修改 | 导出 KernelService |
| `engines/planning/contract_aware.py` | 新增 | ContractAwarePlanningEngine |
| `engines/orchestration/contract_aware.py` | 新增 | ContractAwareOrchestrationEngine |
| `engines/critic/contract_aware.py` | 新增 | ContractAwareCriticEngine |
| `CLAUDE.md` | 修改 | 新增不变量 #32-#33 |

### 验证

- [x] `pytest tests/ -q` — 854/854 通过, 0 回归
- [x] 三个包装器导入验证通过
- [x] 164 个编排层 conformance 测试零改动通过

---

## Phase 24: HITL Gateway — 人在回路

### 完成日期

2026-05-29

### 定位

Phase 22b 的 `ESCALATE_TO_HUMAN` 是一个永远不会触发的枚举值——系统喊了救命，但没人在听。Phase 24 打通了"求助→接收→处理"的双向通道。

不是从零造工作流引擎——是给现有零件加一个新的事件消费者。

### 核心设计

```
repair_budget_exhausted event
    ↓
HITLGateway.poll()  ← 寄生在 EventSink 上，只读不写
    ↓
HumanTicket (frozen dataclass, 冻结的故障快照)
    ↓ create_ticket → persistence (human_tickets 表)
    ↓ human_intervention_required event → EventSink
    ↓
[人类通过 CLI/API/UI 审查]
    ↓
hitl.submit_decision(ticket_id, "approve")
    ↓ ticket_resolved event → EventSink
```

### 关键设计决策

**零新依赖**：没有 Redis、没有 Pub/Sub、没有消息队列。HITLGateway 直接从 ContractAwareEventSink 读事件——sink 已经有所有事件，不需要重新捕获。

**HumanTicket 是冻结快照，不是可变状态机**：`@dataclass(frozen=True)`，跟所有其他契约类型一致。ticket 是"这个时刻发生了故障"的记录——不是"这个工作流正在流转"的活对象。

**Ticket ID 是确定性的**：从 event.correlation_id + timestamp 派生。同一个 budget exhaustion 事件不会创建重复 ticket。

### 新增

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/contracts/composition.py` | 修改 | HumanTicket dataclass, +2 event_type |
| `core/adapters/persistence.py` | 修改 | human_tickets 表, create/resolve/get_pending |
| `core/adapters/hitl_gateway.py` | 新增 | HITLGateway (~80行) |
| `demo/demo_hitl.py` | 新增 | 10/10 断言 CLI 模拟 |

### 验证

- [x] `python demo/demo_hitl.py` — 10/10 通过
- [x] `pytest tests/ -q` — 854/854 通过, 0 回归
- [x] `ESCALATE_TO_HUMAN` 不再是死胡同

---

## Phase 25: Contract Renegotiator — 从被动适应到主动提议

### 完成日期

2026-05-29

### 定位

Phase 24 让系统能"求助"。Phase 25 让系统能"提建议"——当 MemoryStore 检测到某个契约持续恶化，Agent 主动生成改进方案，通过非阻塞通道提交人类审批。

关键架构决策：**不把 Proposal 伪装成 HumanTicket。**

| 维度 | HumanTicket (Phase 24) | RenegotiationProposal (Phase 25) |
|------|----------------------|----------------------------------|
| 性质 | 阻塞型求助 | 非阻塞型建议 |
| 触发 | RepairBudget 耗尽 | MemoryStore 检测慢性恶化 |
| 存储 | human_tickets 表 | proposals 表（独立） |
| 事件 | human_intervention_required | renegotiation_proposed |
| 审批 | submit_decision() | resolve_proposal() |

**同一个 HITLGateway，两条语义隔离的路径。**

### 核心设计

```
RelationshipMemoryStore.get_chronic_violators(threshold=3)
    ↓ 发现持续恶化的 blueprint
ContractRenegotiator
    ↓ 生成 RenegotiationProposal(suggested_action="...")
HITLGateway.submit_proposal(proposal)
    ↓ proposals 表（非 human_tickets 表）
    ↓ renegotiation_proposed event（非 human_intervention_required）
[人类审批]
    ↓ hitl.resolve_proposal(id, approved=True)
    ↓ ticket_resolved event
```

### Memory Inspector

```sql
SELECT blueprint_fingerprint,
       COUNT(*) as deterioration_count,
       MAX(dominant_violation) as top_violation
FROM health_transitions
WHERE timestamp >= ? AND compliance_delta < 0
GROUP BY blueprint_fingerprint
HAVING COUNT(*) >= ?
```

### 新增

| 文件 | 操作 | 说明 |
|------|------|------|
| `core/contracts/composition.py` | 修改 | RenegotiationProposal dataclass, +renegotiation_proposed event |
| `core/adapters/persistence.py` | 修改 | proposals 表, create/resolve/get_pending_proposals, get_chronic_violators |
| `core/adapters/hitl_gateway.py` | 修改 | submit_proposal() + resolve_proposal() |
| `demo/demo_renegotiate.py` | 新增 | 8/8 断言 |

### 验证

- [x] `python demo/demo_renegotiate.py` — 8/8 通过
- [x] `python demo/demo_hitl.py` — 10/10 通过（Phase 24 不受影响）
- [x] `pytest tests/ -q` — 854/854 通过, 0 回归

---

## Phase 25 P0: 防腐层 — 六边形架构落地

### 完成日期

2026-05-29

### 定位

内核的消费者（health_evaluator, repair_engine, hitl_gateway, tool_adapter）直接依赖具体实现类（ContractAwareEventSink, sqlite3, if/elif 厂商分支）。换存储、换事件总线、换 LLM 都需要改业务代码。

三个防腐层（Anti-Corruption Layer）用纯 Python Protocol 隔离了三大基础设施维度。

### 三个 Protocol

| Protocol | 隔离什么 | 当前实现 | 可替换为 |
|----------|---------|---------|---------|
| `InteractionRepository` | 持久化存储 | RelationshipMemoryStore (SQLite) | PostgreSQL, MongoDB |
| `EventSink` | 事件流 | ContractAwareEventSink (内存) | Redis Streams, Kafka |
| `ToolFormatAdapter` + `ToolFormatRegistry` | LLM 工具格式 | AnthropicToolFormat, OpenAIToolFormat | 任意新 LLM 厂商 |

### 架构

```
业务逻辑层 (只依赖 Protocol)
    │                │                    │
    ▼                ▼                    ▼
EventSink    InteractionRepository   ToolFormatAdapter
(Protocol)       (Protocol)           (Protocol)
    │                │                    │
    ▼                ▼                    ▼
ContractAware   RelationshipMemory    AnthropicToolFormat
EventSink       Store (SQLite)        OpenAIToolFormat
```

### ToolFormatAdapter 双向设计

```
去程: 内部 Tool 定义 → format_tools() → LLM 原生 JSON
回程: LLM 原始响应 → parse_response() → {"name": ..., "arguments": ...}
```

Registry 消除 `if provider == "anthropic" elif provider == "openai"` 分支。新 LLM 接入 = 写一个 adapter + `registry.register("new_llm", adapter)`。

### 消费者改造

| 文件 | 改前 | 改后 |
|------|------|------|
| `health_evaluator.py` | `ContractAwareEventSink` | `EventSink` (Protocol) |
| `repair_engine.py` | `ContractAwareEventSink` | `EventSink` (Protocol) |
| `hitl_gateway.py` | `ContractAwareEventSink` + `RelationshipMemoryStore` | `EventSink` + `InteractionRepository` (双 Protocol) |

### 验证

- [x] `pytest tests/ -q` — 854/854 通过
- [x] 三个 demo 全部通过
- [x] `isinstance(store, InteractionRepository)` — 显式满足
- [x] `isinstance(sink, EventSink)` — 显式满足
- [x] `isinstance(AnthropicToolFormat(), ToolFormatAdapter)` — 显式满足
