"""
V9 Plugin SDK: 核心协议与契约 (ABI)
==================================
此文件是整个插件系统的宪法。

修改铁律:
  1. 任何方法签名变更 → Major 版本 bump (9.x → 10.0)
  2. 新增可选参数 (带默认值) → Minor bump
  3. 新增 Slot 类型或扩展 Protocol → Minor bump
  4. 标记废弃方法 → Patch bump + deprecated_methods 清单

绝对禁止:
  - 在此文件中编写任何业务逻辑或默认实现
  - 使用 pass 替代 ... (Ellipsis)
  - 漏掉 @runtime_checkable 装饰器
  - 修改已发布的方法参数名 (参数名是 ABI 的一部分)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ═══════════════════════════════════════════════════════════════
# 协议版本常量
# ═══════════════════════════════════════════════════════════════

PROTOCOL_VERSION: str = "9.2.0"

SUPPORTED_SLOT_TYPES: frozenset[str] = frozenset({
    "tool", "prompt", "track", "observer", "event",
})

# ═══════════════════════════════════════════════════════════════
# 1. 插件清单 (PluginManifest) — 插件的身份证
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PluginManifest:
    """每个插件必须携带的元数据。一旦注册，不可变。

    Attributes:
        name:               注册 key (如 "write_file", "planning_prompt")
        slot_type:          槽类型 — 必须是 SUPPORTED_SLOT_TYPES 之一
        version:            此插件的 SemVer 字符串 (如 "1.0.0")
        protocol_version:   目标协议版本 — 挂载时与 PROTOCOL_VERSION 比对
        description:        人类可读描述
        dependencies:       依赖的其他插件名
        deprecated_methods: 已废弃方法清单 — Minor 兼容时打 warning
        stateless:          True=每次 get_executor() 构造新实例; False=注册表单例
        cancellable:        True=支持 cancellation_token; False=不可取消
        capabilities:       显式声明的可选能力 (如 "dry_run", "streaming")
                            Harness 调用前必须 registry.has_capability(name, cap)
    """

    name: str
    slot_type: str
    version: str
    protocol_version: str = "9.2.0"
    description: str = ""
    dependencies: tuple[str, ...] = ()
    deprecated_methods: tuple[str, ...] = ()
    stateless: bool = True
    cancellable: bool = True
    capabilities: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.slot_type not in SUPPORTED_SLOT_TYPES:
            raise ValueError(
                f"Unknown slot_type '{self.slot_type}'. "
                f"Supported: {SUPPORTED_SLOT_TYPES}"
            )


# ═══════════════════════════════════════════════════════════════
# 2. 五大核心插槽协议 (Slot Protocols)
# ═══════════════════════════════════════════════════════════════

@runtime_checkable
class ToolSlot(Protocol):
    """L3 工具插槽: 执行具体动作。

    所有工具必须实现此 Protocol。
    execute() 返回 JSON 结构化字符串 — 永远不抛异常。
    cancellable=True 的工具必须定期检查 cancellation_token.is_set()。
    """

    manifest: PluginManifest

    async def execute(
        self,
        params: dict[str, Any],
        cancellation_token: threading.Event | None = None,
    ) -> str:
        """执行工具。

        Args:
            params: 工具参数字典 (如 {"path": "/tmp/out.txt", "content": "hello"})
            cancellation_token: 取消信号 — 工具应定期检查 token.is_set()，
                               若已设置则尽快安全退出。不支持取消的工具声明
                               manifest.cancellable=False。

        Returns:
            JSON 结构化字符串:
              成功: {"status": "ok", "tool": "<name>", "data": "<result>"}
              失败: {"status": "error", "tool": "<name>", "code": "<err>", "message": "..."}
        """
        ...


@runtime_checkable
class PromptSlot(Protocol):
    """L3 提示词插槽: 提供 LLM 系统/用户提示词模板。

    替换 llm_bridge._prompts 硬编码字典。
    prompt_id 对应 LLM target (如 "planning", "synthesis", "critic", "tool_resolver")。
    """

    manifest: PluginManifest
    prompt_id: str

    def build(self, context: dict[str, Any] | None = None) -> str:
        """构建系统提示词。

        Args:
            context: 可选上下文 (如 {"user_query": "...", "tool_results": [...]})

        Returns:
            完整的系统提示词字符串。
        """
        ...


@runtime_checkable
class TrackSlot(Protocol):
    """L3 轨道插槽: 定义多步执行管道。

    如 Track C (Tool → Critic)、Track D (DAG 拓扑) 等。
    Harness 根据内核决策选择对应 track 执行。
    """

    manifest: PluginManifest
    track_id: str

    async def run(
        self,
        user_text: str,
        policy: Any,               # DataPolicy — 内核产出的约束张量
        tool_calls: tuple[dict[str, Any], ...],
        round_count: int,
        llm_bridge: Any,
        tool_bridge: Any,
        event_bridge: Any,
    ) -> dict[str, Any]:
        """执行管道。

        Returns:
            {"text": "<response>", "track": "C", ...}
        """
        ...


@runtime_checkable
class ObserverSlot(Protocol):
    """L4 观察器插槽: 感知外部环境/用户状态。

    与 L3 Sensor Hub (内部感知) 严格区分:
      - L4 Observer: 用户语义/情绪/意图 (对标摄像头+麦克风)
      - L3 Sensor:   系统健康指标 (对标温度探头+电压表)
    """

    manifest: PluginManifest
    observer_id: str

    async def observe(self, text: str) -> Any:
        """观察用户输入。

        Args:
            text: 原始用户输入字符串。

        Returns:
            ObservationResult — 来自 protocol/v9_types.py 的冻结类型。
        """
        ...


@runtime_checkable
class EventTypeSlot(Protocol):
    """跨层事件插槽: 定义强类型的事件结构。

    替换 event_bridge.PRIORITY 硬编码映射表。
    每个注册的事件类型声明其优先级和合并行为。
    """

    manifest: PluginManifest
    event_type: str
    priority: int           # 0 = NMI 级, 数字越小优先级越高
    unmergeable: bool = False  # True = 不合并同类型事件

    def validate_payload(self, payload: dict[str, Any]) -> bool:
        """验证事件载荷是否符合此事件类型的 schema。

        Returns:
            True 如果 payload 合法。
        """
        ...


# ═══════════════════════════════════════════════════════════════
# 3. 策略插槽协议 (L2 — 已存在于 mpc_kernel/slots/policy_slots.py)
# ═══════════════════════════════════════════════════════════════
#
# BoundaryPolicy / CostPolicy / ValuePolicy 已在 policy_slots.py 中定义。
# 此处不重复定义。PluginRegistry 通过 L2 manifest.json 发现策略插件。
#
# 引用:
#   from mpc_kernel.slots.policy_slots import (
#       BoundaryPolicy, CostPolicy, ValuePolicy, validate_slot
#   )


# ═══════════════════════════════════════════════════════════════
# 4. 协议版本检查 (供 validator.py 使用)
# ═══════════════════════════════════════════════════════════════

def check_protocol_version(
    plugin_version: str,
    harness_version: str = PROTOCOL_VERSION,
) -> tuple[bool, str]:
    """比对插件声明的协议版本与 Harness 当前版本。

    Args:
        plugin_version: 插件 manifest.protocol_version
        harness_version: Harness 的 PROTOCOL_VERSION

    Returns:
        (is_compatible, reason)
        - Major 不匹配 → (False, "拒绝挂载")
        - Minor 不匹配 → (True, "挂载 + 警告 + 能力协商")
        - Patch 不匹配 → (True, "静默通过")
    """
    def _parse(v: str) -> tuple[int, int, int]:
        parts = v.split(".")
        return (
            int(parts[0]) if len(parts) > 0 else 0,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )

    p_major, p_minor, p_patch = _parse(plugin_version)
    h_major, h_minor, h_patch = _parse(harness_version)

    if p_major != h_major:
        return False, (
            f"Major 版本不匹配: 插件 {plugin_version}, "
            f"Harness {harness_version}。拒绝挂载。"
        )
    if p_minor != h_minor:
        return True, (
            f"Minor 版本不匹配: 插件 {plugin_version}, "
            f"Harness {harness_version}。挂载成功，请检查 capabilities。"
        )
    return True, "版本兼容。"
