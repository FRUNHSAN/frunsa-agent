"""
L3 Sensor Hub — 系统级内部感知 (V9.3 实现，V9.2a 占位)。

对标硬件: 主板温度探头、电压调节器、风扇转速计。
感知对象: LLM 延迟、Event Queue 深度、Token 预算、总线吞吐量。

与 L4 Observer 严格区分:
  - L4 Observer: 外部感知 — 用户语义/情绪/意图 (摄像头 + 麦克风)
  - L3 Sensor Hub: 内部感知 — 系统健康指标 (温度探头 + 电压表)

两路信号在 KernelInput.event_queue 汇合。
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class SystemSensor(Protocol):
    """L3 内部感知协议。

    任何实现此协议的对象可挂载到 Mainboard，每轮采集系统指标。
    V9.2a: 仅定义 Protocol，不实现真实逻辑。
    V9.3:  实现 LLM 延迟/队列深度/Token 预算监控。
    """

    def read_metrics(self) -> dict[str, float]:
        """采集当前系统指标。

        Returns:
            dict 示例: {
                "llm_latency_ms": 450.0,
                "event_queue_depth": 3,
                "token_budget_remaining": 800,
                "bus_throughput_rps": 2.1,
            }
        """
        ...


class DummySensorHub:
    """V9.2a 占位: 系统永远健康。V9.3 替换为真实实现。"""

    def read_metrics(self) -> dict[str, float]:
        return {}
