# Plan: 组件平台 + 引擎平台 — 高度分化，转译层连通

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
