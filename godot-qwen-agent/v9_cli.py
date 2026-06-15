"""V9.0 CLI — 最小入口。5 行连接全链路。"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Load .env if present
_env_path = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_path):
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

from protocol.v9_types import KernelInput, KernelState, SystemMode, TrustDynamics
from mpc_kernel.kernel import kernel_step
from observer.observer import SemanticTrustObserver, ObservationResult
from mainboard.cpu.adapter import adapter_step, AdapterState
from mainboard.bus.event import EventBridge
from mainboard.bus.telemetry import TelemetryBus, TelemetryConfig
from mainboard.bus.llm import LLMBridge, LLMBridgeConfig
from mainboard.bus.tool import ToolBridge, ToolBridgeConfig, ToolMetadata
from mainboard.orchestrate.harness import Harness


class AdapterWrapper:
    """包装 adapter_step 纯函数为 Harness 期望的接口。"""
    def __init__(self):
        self.state = AdapterState()

    def step(self, **kwargs) -> tuple:
        # Harness 传了 adapter_state（首轮为 None）→ 用 wrapper 的初始 state
        adapter_state = kwargs.pop("adapter_state", None) or self.state
        result = adapter_step(adapter_state, **kwargs)
        sv, signals, events, self.state = result
        return result


class KernelWrapper:
    """包装 kernel_step 纯函数为 Harness 期望的接口。"""
    def __init__(self):
        self.state = None

    def step(self, state, input, signals) -> tuple:
        if state is None:
            # 冷启动 — 初始化 KernelState
            from protocol.v9_types import StateVector
            sv = StateVector(data=tuple([0.30, 0.0, 0.5, 1.0, 0.5, 0.5, 1.0, 1.0] + [0.0]*8))
            state = KernelState(
                prev_state_vector=sv, prev_raw_state_vector=sv,
                current_mode=SystemMode.NORMAL, round_count=0,
            )
        return kernel_step(state, input, signals)


class MockToolRegistry:
    """最小 Tool Registry — 提供 write/read 工具。"""
    def get_metadata(self, name):
        return ToolMetadata(name=name, timeout_ms=10000)

    def get_executor(self, name):
        class WriteFile:
            async def execute(self, params):
                path = params.get("path", "/tmp/out.txt")
                content = params.get("content", "")
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                return f"写入: {path} ({len(content)} bytes)"
        return WriteFile()


async def main():
    # ── Provider (真实 DeepSeek) ──
    try:
        from LLM.deepseek import DeepSeekClient
        provider = DeepSeekClient(model="deepseek-chat").client
        print("[OK] DeepSeek Provider")
    except ImportError:
        print("[FAIL] LLM/deepseek.py 不可用。请检查 API key。")
        return

    # ── 四条总线 ──
    event_bridge = EventBridge()
    telemetry = TelemetryBus(TelemetryConfig(storage_path="./v9_telemetry.jsonl"))
    await telemetry.start()

    llm_bridge = LLMBridge(provider, event_bridge)
    tool_bridge = ToolBridge(MockToolRegistry(), event_bridge)

    # ── Observer + Adapter + Kernel ──
    observer = SemanticTrustObserver(semantic_engine=None)
    adapter = AdapterWrapper()
    kernel = KernelWrapper()

    # ── Harness ──
    harness = Harness(
        observer, adapter, kernel,
        llm_bridge, tool_bridge, event_bridge, telemetry,
    )
    print("[OK] V9.0 Harness 已启动")
    print("输入 'quit' 退出\n")

    # ── CLI 主循环 ──
    while True:
        try:
            text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit", "q"):
            break

        print("Agent: ", end="", flush=True)
        resp = await harness.step(text)
        safe_content = resp.content.encode("gbk", errors="replace").decode("gbk", errors="replace")
        print(safe_content)
        print(f"  [gate={resp.metadata.get('gate', '?')}]  [track={resp.metadata.get('track', '?')}]")
        print()

    await telemetry.stop()
    print("再见。")

if __name__ == "__main__":
    asyncio.run(main())
