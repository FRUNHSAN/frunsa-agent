"""
Track C Plugin — 两阶段点火适配器。

阶段 1 (Discovery): 无参构造 — LazyPluginLoader 安全加载。
阶段 2 (Inject):   接收 llm_bridge/tool_bridge/event_bridge — Bootloader 注入。
"""

from typing import Any

from mainboard.plugin_sdk.protocol import PluginManifest, TrackSlot
from mainboard.track.track_c import RealTrackC

_MANIFEST = PluginManifest(
    name="real_track_c",
    slot_type="track",
    version="1.0.0",
    protocol_version="9.2.0",
    description="V9 Track C — Tool Execution → Critic pipeline",
    stateless=False,  # 有状态 — Registry 持单例
)


class RealTrackCPlugin:
    """两阶段 Track C 包装器。

    LazyPluginLoader 调用 cls() → 阶段 1 无参构造。
    Bootloader inject_context() → 阶段 2 注入依赖。
    Harness 调用 run() → 委托给真实实现。
    """

    manifest = _MANIFEST
    track_id = "C"

    # 声明饥饿感 — inject_context() 据此喂食
    requires = frozenset({"llm_bridge", "tool_bridge", "event_bridge"})

    def __init__(self) -> None:
        self._core: RealTrackC | None = None
        self._injected: bool = False

    def inject(self, context: dict[str, Any]) -> None:
        """阶段 2: 接收依赖注入。Bootloader 在 Freeze 后调用。"""
        missing = self.requires - frozenset(context.keys())
        if missing:
            raise ValueError(
                f"Track C inject: missing dependencies {missing}"
            )

        self._core = RealTrackC(
            llm_bridge=context["llm_bridge"],
            tool_bridge=context["tool_bridge"],
            event_bridge=context["event_bridge"],
        )
        self._injected = True

    async def run(
        self,
        user_text: str,
        policy: Any,
        tool_calls: tuple[dict[str, Any], ...],
        round_count: int,
        llm_bridge: Any = None,
        tool_bridge: Any = None,
        event_bridge: Any = None,
    ) -> dict[str, Any]:
        """委托给已注入的真实 Track C 实现。"""
        if not self._injected or self._core is None:
            raise RuntimeError(
                "Track C: run() called before inject(). "
                "Bootloader must call registry.inject_context() after freeze."
            )
        return await self._core.run(
            user_text=user_text,
            policy=policy,
            tool_calls=tool_calls,
            round_count=round_count,
        )


def get_instance() -> RealTrackCPlugin:
    """工厂函数 — Discovery 的无参构造入口。"""
    return RealTrackCPlugin()
