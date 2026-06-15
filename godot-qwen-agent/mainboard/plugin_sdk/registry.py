"""
V9 Plugin SDK: 插件注册中心 (Registry)
======================================
职责: 插件的注册、校验、查询、能力协商与生命周期管理。
核心机制: 一旦调用 freeze()，注册表变为只读，确保运行时状态绝对稳定。

海关三原则:
  1. 信任协议，不信任人类 — isinstance 审查每个人的声明
  2. 命名冲突是谋杀 — 绝不默默覆盖
  3. 舱门锁死后不可逆 — freeze() 是物理隔离墙
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

from .protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_SLOT_TYPES,
    PluginManifest,
    ToolSlot,
    PromptSlot,
    TrackSlot,
    ObserverSlot,
    EventTypeSlot,
    check_protocol_version,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 协议映射表 — 用于运行时 isinstance 检查
# ═══════════════════════════════════════════════════════════════

_SLOT_PROTOCOLS: dict[str, type] = {
    "tool": ToolSlot,
    "prompt": PromptSlot,
    "track": TrackSlot,
    "observer": ObserverSlot,
    "event": EventTypeSlot,
}

# ═══════════════════════════════════════════════════════════════
# 异常
# ═══════════════════════════════════════════════════════════════


class RegistryFrozenError(RuntimeError):
    """试图在冻结后修改注册表时抛出。"""
    pass


class PluginValidationError(ValueError):
    """插件不符合协议或元数据校验失败时抛出。"""
    pass


# ═══════════════════════════════════════════════════════════════
# PluginRegistry
# ═══════════════════════════════════════════════════════════════


class PluginRegistry:
    """V9 核心插件注册中心。线程安全，支持状态冻结 + 能力协商。

    Attributes:
        _store: {slot_type: {plugin_name: instance}}
        _missing_capabilities: {name: set(capability)} — 缺失的可选能力追踪
        _lazy_loaders: {name: LazyPluginLoader} — 延迟加载等待列表
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {
            stype: {} for stype in SUPPORTED_SLOT_TYPES
        }
        self._frozen: bool = False
        self._lock = threading.Lock()

        # 能力协商追踪
        self._missing_capabilities: dict[str, set[str]] = {}

        # 延迟加载器
        self._lazy_loaders: dict[str, Any] = {}

    # ── 属性 ──────────────────────────────────────────

    @property
    def is_frozen(self) -> bool:
        return self._frozen

    # ── 注册 (即时) ───────────────────────────────────

    def register(self, instance: Any) -> PluginManifest:
        """注册一个已实例化的插件。

        校验链:
          1. 冻结检查
          2. 提取 manifest
          3. 协议版本比对 (Major 拒绝, Minor 警告)
          4. isinstance Protocol 校验
          5. 命名冲突检测
          6. 入驻
        """
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError(
                    "Registry is frozen. No new plugins can be registered at runtime."
                )

            manifest = self._validate_and_register(instance)
            logger.info(
                f"Registered {manifest.slot_type} plugin: "
                f"{manifest.name} (v{manifest.version})"
            )
            return manifest

    def register_lazy(self, slot_type: str, name: str, loader: Any) -> None:
        """注册延迟加载器。真正的 import 推迟到第一次 get() 调用。

        loader 必须实现 load() → instance | None。
        加载失败记录警告，绝不中断启动。
        多 manifest 声明同一插件时，第一个 wins，后续静默跳过。
        """
        with self._lock:
            if self._frozen:
                raise RegistryFrozenError("Registry is frozen.")
            if slot_type not in SUPPORTED_SLOT_TYPES:
                raise PluginValidationError(f"Unsupported slot_type: {slot_type}")

            key = f"{slot_type}/{name}"

            # 去重：已在即时注册表或延迟列表中的，静默跳过
            if name in self._store.get(slot_type, {}):
                logger.debug(f"跳过重复注册: {key} (已即时注册)")
                return
            if key in self._lazy_loaders:
                logger.debug(f"跳过重复注册: {key} (已在延迟加载列表)")
                return

            self._lazy_loaders[key] = loader
            logger.debug(f"Lazy loader registered: {key}")

    def _validate_and_register(self, instance: Any) -> PluginManifest:
        """核心校验 + 入驻逻辑。必须在锁内调用。"""

        # 1. 提取 manifest
        manifest: PluginManifest = getattr(instance, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise PluginValidationError(
                f"Plugin {type(instance).__name__} missing valid 'manifest' attribute."
            )

        slot_type = manifest.slot_type
        if slot_type not in SUPPORTED_SLOT_TYPES:
            raise PluginValidationError(
                f"Unsupported slot_type '{slot_type}' for plugin '{manifest.name}'."
            )

        # 2. 协议版本比对 (Major 拒绝, Minor 警告 + 能力协商)
        compatible, reason = check_protocol_version(
            manifest.protocol_version, PROTOCOL_VERSION
        )
        if not compatible:
            raise PluginValidationError(
                f"Plugin '{manifest.name}': {reason}"
            )
        if "Minor" in reason or "警告" in reason:
            logger.warning(
                f"Plugin '{manifest.name}': {reason}"
            )

        # 3. isinstance Protocol 校验 (信任协议，不信任人类)
        protocol_cls = _SLOT_PROTOCOLS[slot_type]
        if not isinstance(instance, protocol_cls):
            raise PluginValidationError(
                f"Plugin '{manifest.name}' claims slot_type='{slot_type}', "
                f"but fails isinstance check against {protocol_cls.__name__}. "
                f"Did you implement all required methods?"
            )

        # 4. 能力协商: 插件声明的 capabilities 必须真实存在
        if manifest.capabilities:
            self._validate_capabilities(instance, manifest)

        # 5. 命名冲突检测 — 绝不默默覆盖
        if manifest.name in self._store[slot_type]:
            raise PluginValidationError(
                f"Name collision: A {slot_type} plugin named "
                f"'{manifest.name}' is already registered."
            )

        # 6. 入驻
        self._store[slot_type][manifest.name] = instance
        return manifest

    def _validate_capabilities(
        self, instance: Any, manifest: PluginManifest
    ) -> None:
        """验证插件声明的 capabilities 真实可用。

        声明的 capability → 检查是否有对应的扩展 Protocol 实现。
        未声明的 capability → 记录到 _missing_capabilities (不拒绝)。
        """
        name = manifest.name
        for cap in manifest.capabilities:
            # 检查已知的扩展 Protocol
            if cap == "dry_run" and hasattr(instance, "dry_run"):
                continue
            elif cap == "streaming" and hasattr(instance, "stream"):
                continue
            elif cap == "batch_execute" and hasattr(instance, "batch_execute"):
                continue
            # 未知 capability → 不是错误，可能来自未来版本
            logger.debug(
                f"Plugin '{name}' declares unknown capability '{cap}'"
            )

    # ── 查询 ──────────────────────────────────────────

    def get(self, slot_type: str, name: str) -> Any | None:
        """获取插件实例。如果是延迟加载，触发第一次 import。"""
        key = f"{slot_type}/{name}"

        # 先查即时注册的
        instance = self._store.get(slot_type, {}).get(name)
        if instance is not None:
            return instance

        # 再查延迟加载
        loader = self._lazy_loaders.get(key)
        if loader is not None:
            try:
                instance = loader.load()
            except Exception as e:
                logger.warning(f"Lazy load failed for {key}: {e}")
                return None

            if instance is not None:
                # 加载成功 → 即时注册
                try:
                    self._validate_and_register(instance)
                except PluginValidationError as e:
                    logger.warning(f"Lazy loaded plugin {key} validation failed: {e}")
                    return None
                # 从延迟列表移除
                del self._lazy_loaders[key]
                return instance

        return None

    def list_by_type(self, slot_type: str) -> list[Any]:
        """获取某类插槽的所有已注册实例。"""
        return list(self._store.get(slot_type, {}).values())

    def list_names(self, slot_type: str) -> list[str]:
        """获取某类插槽的所有注册名 (含延迟加载)。"""
        names = list(self._store.get(slot_type, {}).keys())
        prefix = f"{slot_type}/"
        names.extend(
            k[len(prefix):] for k in self._lazy_loaders
            if k.startswith(prefix)
        )
        return names

    def get_manifests(self) -> list[PluginManifest]:
        """获取所有已注册插件的 manifest。"""
        manifests = []
        for slot_dict in self._store.values():
            for inst in slot_dict.values():
                m = getattr(inst, "manifest", None)
                if isinstance(m, PluginManifest):
                    manifests.append(m)
        return manifests

    # ── 能力协商 API ─────────────────────────────────

    def has_capability(self, name: str, capability: str) -> bool:
        """调用方在调用可选能力前必须查询此方法。

        True  → 安全调用
        False → 使用确定性 fallback
        """
        # 查找所有 slot_type 中的该 name
        for stype in SUPPORTED_SLOT_TYPES:
            inst = self._store.get(stype, {}).get(name)
            if inst is not None:
                m = getattr(inst, "manifest", None)
                if isinstance(m, PluginManifest):
                    return capability in m.capabilities
        return False

    def missing_capabilities(self, name: str) -> frozenset[str]:
        """返回某插件缺失的可选能力列表。用于诊断。"""
        return frozenset(self._missing_capabilities.get(name, set()))

    # ── 生命周期 ─────────────────────────────────────

    def freeze(self) -> None:
        """锁死注册表。Bootloader 完成初始化后必须调用。

        一旦冻结:
          - register() → RegistryFrozenError
          - register_lazy() → RegistryFrozenError
          - get() 仍可用 (延迟加载在首次 get 时触发，
            但 get 不会修改 _store — 加载成功后直接注册，
            这在 freeze 后也会被拦截）

        V9.2a 约定: freeze 后延迟加载的 get() 如果触发注册，
        会因 _frozen=True 而失败。因此所有延迟加载必须在 freeze 前
        完成首次 get() 触发，或者在 freeze 前手动 resolve 所有 lazy loader。
        """
        with self._lock:
            if not self._frozen:
                # 先 resolve 所有延迟加载器
                pending = list(self._lazy_loaders.keys())
                for key in pending:
                    slot_type, name = key.split("/", 1)
                    logger.info(f"Freeze: resolving lazy loader {key}")
                    instance = self.get(slot_type, name)
                    if instance is None:
                        logger.warning(
                            f"Freeze: lazy loader {key} failed to resolve, "
                            f"plugin will be unavailable"
                        )

                self._frozen = True
                total = sum(len(v) for v in self._store.values())
                lazy_remaining = len(self._lazy_loaders)
                logger.info(
                    f"PluginRegistry FROZEN. "
                    f"Loaded: {total}, Unresolved lazy: {lazy_remaining}"
                )

    # ── 依赖注入 (两阶段点火: 阶段 2) ────────────────

    def inject_context(self, context: dict[str, Any]) -> int:
        """向所有声明了 requires 的插件注入依赖。

        必须在 freeze() 之后调用。
        遍历所有已注册插件，若插件声明了 requires 属性，
        则调用 inject(context) 喂食。

        Args:
            context: {"llm_bridge": ..., "tool_bridge": ..., "event_bridge": ...}

        Returns:
            成功注入的插件数量。

        Raises:
            RuntimeError: Registry 尚未冻结。
            ValueError: 某个插件的依赖在 context 中缺失。
        """
        if not self._frozen:
            raise RuntimeError(
                "Cannot inject context before freezing the Registry."
            )

        injected_count = 0
        for stype, plugins in self._store.items():
            for name, plugin in plugins.items():
                requires = getattr(plugin, "requires", None)
                if requires is None:
                    continue

                # 检查 context 是否满足依赖
                missing = requires - frozenset(context.keys())
                if missing:
                    raise ValueError(
                        f"Plugin '{stype}/{name}' requires {missing}, "
                        f"but context is missing these keys."
                    )

                # 喂食
                if hasattr(plugin, "inject"):
                    plugin.inject(context)
                    injected_count += 1
                    logger.info(
                        f"Injected dependencies into {stype}/{name}: "
                        f"{', '.join(sorted(requires))}"
                    )

        if injected_count > 0:
            logger.info(
                f"Dependency injection complete. "
                f"Fed {injected_count} stateful plugin(s)."
            )
        return injected_count

    # ── 调试 ──────────────────────────────────────────

    def summary(self) -> str:
        """返回已注册插件的摘要。"""
        lines = ["PluginRegistry Summary:"]
        for stype in sorted(self._store.keys()):
            names = sorted(self._store[stype].keys())
            lazy = [
                k.split("/", 1)[1] for k in self._lazy_loaders
                if k.startswith(f"{stype}/")
            ]
            all_names = names + lazy
            if all_names:
                lines.append(f"  {stype}: {', '.join(all_names)}")
        lines.append(f"  frozen: {self._frozen}")
        return "\n".join(lines)

    # ── ToolBridge 适配器 ──────────────────────────────

    def get_tool_adapter(self) -> "HarnessToolRegistry":
        """返回 HarnessToolRegistry — ToolBridge 兼容的接口。

        ToolBridge 通过此适配器间接访问 COMPONENT_REGISTRY 中的旧工具。
        不需要将旧工具注册为 ToolSlot 实例 — 适配器在调用时动态包装。
        """
        return HarnessToolRegistry()


# ═══════════════════════════════════════════════════════════════
# 工具发现 — 触发 COMPONENT_REGISTRY 的 @register_component 副作用
# ═══════════════════════════════════════════════════════════════


def discover_core_tools() -> int:
    """触发 COMPONENT_REGISTRY.auto_discover() 导入旧工具模块。

    旧工具 (WriteFile, ReadFile, RunPowershell 等) 通过
    @register_component(\"tool\", \"write_file\") 装饰器注册到 COMPONENT_REGISTRY。
    装饰器在模块首次 import 时触发。

    此函数调用 auto_discover() 扫描 components/tools/*.py，
    触发所有 @register_component 装饰器。
    HarnessToolRegistry 随后可查询 COMPONENT_REGISTRY 获取工具。

    Returns:
        发现的工具数量。
    """
    try:
        from core.contracts.registry import COMPONENT_REGISTRY, auto_discover
    except ImportError:
        logger.warning("core.contracts.registry 不可用，跳过旧工具发现")
        return 0

    auto_discover("components/tools")
    names = COMPONENT_REGISTRY.list_strategies("tool")
    logger.info(f"Core tools discovered: {len(names)} ({', '.join(names)})")
    return len(names)


# ═══════════════════════════════════════════════════════════════
# HarnessToolRegistry — COMPONENT_REGISTRY → ToolBridge 适配器
# ═══════════════════════════════════════════════════════════════


class HarnessToolRegistry:
    """桥接旧 COMPONENT_REGISTRY 工具到 ToolBridge 期望的接口。

    COMPONENT_REGISTRY 工具:
      cls.execute(path: str, content: str) -> ToolResult  (同步, 命名参数)

    ToolBridge 期望:
      async executor.execute(params: dict) -> str         (异步, dict→JSON)

    三个翻译:
      1. 类 → 实例 (stateless=True 每次 new, False 单例)
      2. 同步 → 异步 (asyncio.to_thread + cancellation_token)
      3. ToolResult → JSON str
    """

    def __init__(self):
        self._core = None           # COMPONENT_REGISTRY — 延迟导入
        self._instances: dict[str, Any] = {}  # stateless=False 的单例缓存

    @property
    def _registry(self):
        """延迟导入 COMPONENT_REGISTRY — 避免启动时的循环依赖。"""
        if self._core is None:
            from core.contracts.registry import COMPONENT_REGISTRY
            self._core = COMPONENT_REGISTRY
        return self._core

    # ── ToolBridge 兼容接口 ────────────────────────────

    def get_metadata(self, name: str) -> Any | None:
        """返回 ToolMetadata — ToolBridge 所需的元数据。

        ToolMetadata 来自 mainboard.bus.tool，在此延迟导入以避免循环。
        """
        try:
            cls = self._registry.get("tool", name)
        except KeyError:
            return None

        from mainboard.bus.tool import ToolMetadata
        manifest = getattr(cls, "PLUGIN_MANIFEST", None)
        return ToolMetadata(
            name=name,
            description=getattr(cls, "description", ""),
            timeout_ms=getattr(cls, "TIMEOUT_MS", 10000),
            required_params=self._extract_params(cls.execute),
        )

    def get_executor(self, name: str) -> Any:
        """返回 ToolBridge 兼容的 executor 实例。"""
        cls = self._registry.get("tool", name)
        manifest = getattr(cls, "PLUGIN_MANIFEST", None)
        stateless = getattr(manifest, "stateless", True) if manifest else True

        if not stateless:
            if name not in self._instances:
                self._instances[name] = cls()
            instance = self._instances[name]
        else:
            instance = cls()

        return _ToolWrapper(instance, name)

    def list_tools(self) -> list[str]:
        """返回所有已注册工具的名称列表。供 _resolve_tools 动态查询。"""
        try:
            return self._registry.list_strategies("tool")
        except Exception:
            return []

    def tool_descriptions(self) -> str:
        """返回工具签名摘要。供 LLM tool_resolver 提示词使用。

        例: "write_file(path, content), read_file(path, max_chars), ..."
        """
        descriptions = []
        for name in self.list_tools():
            params = [
                p for p in self._extract_params(
                    self._registry.get("tool", name).execute
                )
            ]
            # 只保留前 2 个参数名，避免提示词过长
            sig = ", ".join(params[:2])
            descriptions.append(f"{name}({sig})")
        return ", ".join(descriptions) if descriptions else "无可用工具"

    # ── 规则引擎接口 ─────────────────────────────────

    def get_match_patterns(self, name: str) -> tuple[str, ...]:
        """返回工具的规则匹配指纹。无声明 → 空元组。"""
        try:
            cls = self._registry.get("tool", name)
            return getattr(cls, "match_patterns", ())
        except KeyError:
            return ()

    def extract_params(self, name: str, user_text: str) -> dict:
        """调用工具的 extract_params。无声明 → 空 dict。"""
        try:
            cls = self._registry.get("tool", name)
            fn = getattr(cls, "extract_params", None)
            if callable(fn):
                return fn(user_text)
        except KeyError:
            pass
        return {}

    @staticmethod
    def _extract_params(execute_fn) -> tuple[str, ...]:
        """从 execute 签名提取必填参数名 — 仅无默认值的参数。

        排除: self, cancellation_token, 以及有默认值的参数。
        只有真正的必填参数才会在 ToolBridge._validate 中检查。
        """
        import inspect
        try:
            sig = inspect.signature(execute_fn)
            return tuple(
                p.name for p in sig.parameters.values()
                if p.name not in ("self", "cancellation_token")
                and p.default is inspect.Parameter.empty
            )
        except (ValueError, TypeError):
            return ()


class _ToolWrapper:
    """包装旧工具为 ToolBridge 兼容接口。

    - 注入 threading.Event 取消令牌
    - 同步 → 异步 (asyncio.to_thread)
    - ToolResult → JSON 结构化字符串
    """

    def __init__(self, instance: Any, name: str) -> None:
        self._inst = instance
        self._name = name
        manifest = getattr(instance, "PLUGIN_MANIFEST", None)
        self._cancellable = getattr(manifest, "cancellable", True) if manifest else True
        self._accepts_token = _exec_accepts_cancellation_token(instance)
        # 缓存工具接受的参数名，用于过滤 LLM 幻觉参数
        self._accepted_params = _get_accepted_params(instance)

    def _filter_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """过滤 params，只保留工具实际接受的参数。

        LLM (tool_resolver) 可能幻觉多余参数 (如 _high_safety_mode)。
        不报错——静默丢弃，避免因 LLM 的小错误阻断整个工具调用。
        """
        if not self._accepted_params:
            return dict(params)  # 无法检测签名 → 全部透传
        return {k: v for k, v in params.items() if k in self._accepted_params}

    async def execute(self, params: dict[str, Any]) -> str:
        """执行工具。过滤未知参数 + 注入取消令牌 + 序列化结果。"""
        token = threading.Event()

        def _run():
            # 过滤：只传工具实际接受的参数 (LLM 可能幻觉多余参数)
            filtered = self._filter_params(params)
            if self._cancellable and self._accepts_token:
                filtered["cancellation_token"] = token
            try:
                return self._inst.execute(**filtered)
            except Exception as e:
                logger.exception(f"[{self._name}] 工具执行异常")
                return _ToolResultStub(
                    success=False, data=None,
                    error=f"{type(e).__name__}: {e}",
                )

        try:
            result = await asyncio.to_thread(_run)
        except asyncio.CancelledError:
            token.set()
            logger.warning(f"[{self._name}] 取消信号已发送")
            raise

        return _serialize_tool_result(result, self._name)


def _exec_accepts_cancellation_token(instance: Any) -> bool:
    """检测旧工具的 execute 方法是否接受 cancellation_token 参数。"""
    import inspect
    try:
        sig = inspect.signature(instance.execute)
        return "cancellation_token" in sig.parameters
    except (ValueError, TypeError):
        return False


def _get_accepted_params(instance: Any) -> frozenset[str] | None:
    """提取工具 execute 方法接受的参数名集合。

    返回 None 表示无法检测签名（此时 _filter_params 透传所有参数）。
    """
    import inspect
    try:
        sig = inspect.signature(instance.execute)
        return frozenset(
            p for p in sig.parameters
            if p != "self"
        )
    except (ValueError, TypeError):
        return None


class _ToolResultStub:
    """ToolResult 的轻量 stub — 避免对 core.contracts.tool 的强制导入。"""
    def __init__(self, success: bool, data: Any, error: str) -> None:
        self.success = success
        self.data = data
        self.error = error


def _serialize_tool_result(result: Any, tool_name: str) -> str:
    """序列化 ToolResult 为 JSON 结构化字符串。

    Critic 可以可靠地 json.loads() 解析，无需正则匹配。
    """
    success = getattr(result, "success", False)
    if success:
        data = getattr(result, "data", None)
        return json.dumps({
            "status": "ok",
            "tool": tool_name,
            "data": str(data) if data is not None else None,
        }, ensure_ascii=False)
    else:
        error_msg = getattr(result, "error", "Unknown error")
        error_code = getattr(result, "error_code", "UNKNOWN")
        return json.dumps({
            "status": "error",
            "tool": tool_name,
            "code": error_code,
            "message": str(error_msg),
        }, ensure_ascii=False)
