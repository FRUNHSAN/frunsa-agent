"""
L3 Power MCU — 生命周期管理 (V9.3 实现，V9.2a 占位)。

对标硬件: 主板电源管理芯片 (Power Management Controller)。
职责: 开机/休眠/强制关机、心跳检测、熔断保护。

V9.2a: 仅 Dummy — 永不宕机。
V9.3:  心跳 emit → Event Bus, 熔断策略, 优雅关机。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class PowerController(Protocol):
    """L3 电源管理协议。

    V9.2a: 仅定义 Protocol。
    V9.3:  实现心跳、熔断、强制关机。
    """

    def is_healthy(self) -> bool:
        """系统健康状态。False → 内核可能触发 WAIT 或 EMERGENCY_STOP。"""
        ...

    def heartbeat(self) -> float:
        """返回距上次心跳的秒数。> 阈值 → Event Bus emit POWER_FAULT。"""
        ...

    def emergency_stop(self, reason: str) -> None:
        """强制停机。保存遥测缓冲区后立即退出。"""
        ...


class DummyPowerMCU:
    """V9.2a 占位: 永不宕机。V9.3 替换为真实实现。"""

    def is_healthy(self) -> bool:
        return True

    def heartbeat(self) -> float:
        return 0.0  # 永远准时

    def emergency_stop(self, reason: str) -> None:
        pass  # 不关机
