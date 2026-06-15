"""
V9 L0 Bootloader — 启动自检 + 依赖注入 + 移交控制权。

启动序列:
  1. 加载 config (LLM provider, bus params, MCP servers)
  2. 实例化 L2 Kernel + L3 Mainboard + L4 Observer
  3. discover_and_freeze() — 扫描三层 slots/ manifest
  4. 注入 Dummy Sensor/Power (V9.3 替换为真实实现)
  5. 启动主循环 → mainboard.orchestrate.harness

V9.2a: 极简骨架 — 能启动就跑
V9.3:  增加优雅降级、重试机制、健康检查门控
"""

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))


def boot():
    """V9 Agent 入口。"""

    # ── 1. 加载环境 ──
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())

    # ── 2. 初始化 L2/L3/L4 ──
    from protocol.v9_types import KernelInput, KernelState, SystemMode, TrustDynamics
    from mpc_kernel.kernel import kernel_step
    from observer.observer import SemanticTrustObserver
    from mainboard.cpu.adapter import adapter_step, AdapterState
    from mainboard.bus.event import EventBridge
    from mainboard.bus.telemetry import TelemetryBus, TelemetryConfig
    from mainboard.bus.llm import LLMBridge, LLMBridgeConfig
    from mainboard.bus.tool import ToolBridge, ToolBridgeConfig
    from mainboard.orchestrate.harness import Harness
    from mainboard.sensor import DummySensorHub
    from mainboard.power import DummyPowerMCU

    # ── LLM Provider ──
    try:
        from LLM.deepseek import DeepSeekClient
        provider = DeepSeekClient(model="deepseek-chat").client
        print("[BOOT] DeepSeek Provider OK")
    except ImportError:
        print("[BOOT] FAIL: LLM/deepseek.py 不可用")
        return

    # ── 阶段 1: 唤醒海关 (PluginRegistry) ──
    from mainboard.plugin_sdk.registry import PluginRegistry
    from mainboard.plugin_sdk.discovery import discover_and_register

    registry = PluginRegistry()

    # ── 阶段 2: 扫描三层 slots/ ──
    base_dir = Path(os.path.dirname(__file__))
    results = discover_and_register(registry, base_dir)
    print(f"[BOOT] Discovery: {len(results['success'])} loaded, "
          f"{len(results['failed'])} failed")
    for err in results["failed"]:
        print(f"[BOOT]   FAIL: {err}")

    # ── 阶段 3: 锁死舱门 (Freeze) ──
    registry.freeze()

    # ── 四条总线 (注入 registry) ──
    event_bridge = EventBridge()
    telemetry = TelemetryBus(TelemetryConfig(storage_path="./v9_telemetry.jsonl"))

    llm_bridge = LLMBridge(provider, event_bridge, registry=registry)
    tool_bridge = ToolBridge(_make_mock_registry(), event_bridge)
    # V9.2a: PluginRegistry 替换 MockToolRegistry 后将自动桥接 COMPONENT_REGISTRY

    # ── Observer + Adapter + Kernel ──
    observer = SemanticTrustObserver(semantic_engine=None)
    adapter = _AdapterWrapper()
    kernel = _KernelWrapper()

    # ── Sensor + Power (V9.2a 占位) ──
    sensor = DummySensorHub()
    power = DummyPowerMCU()
    print(f"[BOOT] Sensor Hub: {sensor.read_metrics()}")
    print(f"[BOOT] Power MCU: healthy={power.is_healthy()}")

    # ── Harness ──
    harness = Harness(
        observer, adapter, kernel,
        llm_bridge, tool_bridge, event_bridge, telemetry,
    )
    print("[BOOT] V9.2 Harness 就绪")

    # ── 3. 移交控制权 ──
    return harness, telemetry, event_bridge


class _AdapterWrapper:
    """包装 adapter_step 纯函数。V9.3 移至 mainboard/cpu/。"""
    def __init__(self):
        self.state = AdapterState()

    def step(self, **kwargs):
        adapter_state = kwargs.pop("adapter_state", None) or self.state
        result = adapter_step(adapter_state, **kwargs)
        sv, signals, events, self.state = result
        return result


class _KernelWrapper:
    """包装 kernel_step 纯函数。V9.3 移至 mainboard/cpu/。"""
    def __init__(self):
        self.state = None

    def step(self, state, input, signals):
        if state is None:
            from protocol.v9_types import StateVector
            sv = StateVector(data=tuple([0.30, 0.0, 0.5, 1.0, 0.5, 0.5, 1.0, 1.0] + [0.0]*8))
            state = KernelState(
                prev_state_vector=sv, prev_raw_state_vector=sv,
                current_mode=SystemMode.NORMAL, round_count=0,
            )
        return kernel_step(state, input, signals)


def _make_mock_registry():
    """V9.2a 过渡：PluginRegistry 未就绪前的临时工具注册表。"""
    from mainboard.bus.tool import ToolMetadata

    class _MockRegistry:
        def get_metadata(self, name):
            return ToolMetadata(name=name, timeout_ms=10000)

        def get_executor(self, name):
            class _WriteFile:
                async def execute(self, params):
                    path = params.get("path", "/tmp/out.txt")
                    content = params.get("content", "")
                    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(content)
                    return f"写入: {path} ({len(content)} bytes)"
            return _WriteFile()

    return _MockRegistry()
