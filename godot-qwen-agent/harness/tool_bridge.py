"""
V9 Tool Bridge — 工具总线桥接器 (APB 级)

硬件对标: APB Bridge (PSEL + PENABLE + PREADY + PRDATA)
职责: HAL 查表 + 参数校验 + MAC 层执行 + 失败 → 跨总线事件转发

协议依赖（全部冻结）:
  ToolMetadata      — 工具注册元数据 (不含 is_idempotent — 业务层留给 Track C)
  ToolBridgeConfig  — 总线物理参数
  BusResponse       — 统一总线响应
  EventBridge.emit  — 同步入队，非阻塞
  DataPolicy        — 内核产出的约束张量

关键设计决策:
  - Bridge 只做 MAC 层网络重试 (ConnectionError)。不做业务重试。
  - 幂等性判断是 Track C 的事 — 不是 Bridge 的事。
  - Semaphore 获取有超时 — 防止死锁。
  - 安全拦截是显式 POLICY_VIOLATION — 不静默删除参数。
"""

from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass
from types import MappingProxyType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 配置与元数据
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ToolMetadata:
    """工具注册元数据。Tool Registry (HAL) 的每个条目。

    注意: 不含 is_idempotent 或 max_retries。
    幂等性判断是 Track C 的业务逻辑 — 不是 Bridge 的责任。
    Bridge 只看网络层：连接断了 → 重试一次。超时/业务异常 → 不重试。
    """
    name: str
    description: str = ""
    timeout_ms: int = 10000           # 工具自声明超时
    required_params: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolBridgeConfig:
    """工具总线物理参数。"""
    max_concurrency: int = 5                    # asyncio.Semaphore 上限
    semaphore_acquire_timeout_ms: int = 5000    # 排队超时 — 防死锁
    default_timeout_ms: int = 10000             # 工具未声明超时时的 fallback
    network_retries: int = 1                    # MAC 层重试 (仅限 ConnectionError)
    retry_delay_ms: int = 500                   # 重试退避延迟


# ═══════════════════════════════════════════════════════════════
# 输出契约（复用，与 LLM Bridge 共用 BusResponse）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BusResponse:
    """统一总线响应。"""
    op_id: str
    status: str             # "OK" | "ERROR" | "TIMEOUT" | "POLICY_VIOLATION"
    payload: dict
    latency_ms: float
    bus_id: str


# ═══════════════════════════════════════════════════════════════
# Tool Bridge
# ═══════════════════════════════════════════════════════════════

class ToolBridge:
    """工具总线桥接器 — APB 级。

    地址空间: tool://write_file | tool://search_web | tool://mcp:*

    架构边界:
      • 不判断幂等性 — 那是 Track C 的事
      • MAC 层重试仅针对 ConnectionError（网络断连），不针对 TimeoutError 或业务异常
      • 安全拦截是显式中断，不静默修改参数
      • Semaphore 获取有超时 — 防死锁
    """

    NAMESPACE = "tool://"

    def __init__(
        self,
        registry,           # ToolRegistry — HAL。get_metadata(name) + get_executor(name)
        event_bridge,       # EventBridge — emit() 同步入队
        config: ToolBridgeConfig = ToolBridgeConfig(),
    ):
        self.registry = registry
        self.event = event_bridge
        self.cfg = config
        self._semaphore = asyncio.Semaphore(config.max_concurrency)

    # ── 地址解码 ────────────────────────────────────────

    def can_handle(self, target: str) -> bool:
        return target.startswith(self.NAMESPACE)

    # ── 公共接口 ────────────────────────────────────────

    async def execute(
        self,
        target: str,        # tool://write_file | tool://search_web | tool://mcp:*
        params: dict,       # 工具参数 — 由 Track C / ControlFrame.tool_calls 提供
        policy,             # DataPolicy — 约束张量
        op_id: str,         # 事务 ID
    ) -> BusResponse:
        """执行一次工具事务。

        Args:
            target: 工具地址
            params: 工具参数
            policy: DataPolicy (safety_threshold, forbidden_patterns)
            op_id:  事务追踪 ID

        Returns:
            BusResponse — 永远返回，不抛异常（状态保全宪法）。
        """
        t0 = time.perf_counter()

        # ── 1. 地址解码 + HAL 查表 ──
        tool_name = target.replace(self.NAMESPACE, "")
        metadata = self.registry.get_metadata(tool_name)
        if metadata is None:
            return self._error(op_id, target, t0, f"Unknown tool: {tool_name}")

        # ── 2. 参数校验 + DataPolicy 安全拦截 ──
        validated, violation = self._validate(metadata, params, policy, tool_name, op_id)
        if violation:
            return self._error(op_id, target, t0, violation)

        timeout_s = (metadata.timeout_ms or self.cfg.default_timeout_ms) / 1000.0
        executor = self.registry.get_executor(tool_name)

        # ── 3. 背压限流（带超时 — 防死锁）──
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.cfg.semaphore_acquire_timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            self.event.emit("BRIDGE_OVERLOAD", MappingProxyType({
                "tool": tool_name, "op_id": op_id,
            }))
            return self._error(op_id, target, t0, "Bridge overload: semaphore acquire timeout")
        except asyncio.CancelledError:
            raise

        # ── 4. MAC 层执行 ──
        last_error = None

        try:
            for attempt in range(self.cfg.network_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        executor.execute(validated),
                        timeout=timeout_s,
                    )
                    latency = (time.perf_counter() - t0) * 1000
                    return BusResponse(
                        op_id=op_id, status="OK",
                        payload={"result": result},
                        latency_ms=latency, bus_id=target,
                    )

                except asyncio.CancelledError:
                    raise

                except asyncio.TimeoutError:
                    # 业务超时：绝不重试（不是网络问题）
                    last_error = "EXECUTION_TIMEOUT"
                    logger.error(f"[{target}] 执行超时 ({timeout_s}s)")
                    break

                except ConnectionError:
                    # 网络断连 → MAC 层重试
                    last_error = "NETWORK_ERROR"
                    if attempt < self.cfg.network_retries:
                        logger.warning(
                            f"[{target}] 网络断连 (attempt {attempt + 1}/"
                            f"{self.cfg.network_retries + 1})"
                        )
                        await asyncio.sleep(self.cfg.retry_delay_ms / 1000.0)
                        continue
                    break

                except Exception as e:
                    # 业务异常 / 未知异常 → 不重试
                    last_error = f"{type(e).__name__}: {e}"
                    logger.exception(f"[{target}] 业务/未知异常")
                    break

        finally:
            self._semaphore.release()  # 绝对释放 — 防止死锁

        # ── 5. 稳态失败 → 跨总线事件转发 ──
        self.event.emit("TOOL_FAILURE", MappingProxyType({
            "tool": tool_name,
            "op_id": op_id,
            "error": last_error,
        }))

        return self._error(op_id, target, t0, last_error)

    # ── 参数校验 ────────────────────────────────────────

    def _validate(
        self, metadata: ToolMetadata, params: dict, policy,
        tool_name: str, op_id: str,
    ) -> tuple[dict | None, str | None]:
        """校验工具参数。注入 DataPolicy 约束。

        返回: (合法参数字典, None) 或 (None, 错误描述)。

        安全拦截是显式的 POLICY_VIOLATION — 不静默删除参数。
        拦截记录通过 Event Bus 发射，进入审计链。
        """
        # 必填参数检查
        for p in metadata.required_params:
            if p not in params:
                return None, f"Missing required param: {p}"

        # 显式安全拦截 — 不静默删除
        for forbidden in policy.forbidden_patterns:
            if forbidden in params:
                self.event.emit("POLICY_VIOLATION", MappingProxyType({
                    "tool": tool_name,
                    "param": forbidden,
                    "op_id": op_id,
                }))
                return None, f"Policy violation: forbidden param '{forbidden}'"

        validated = dict(params)

        # θ 收紧 → 非幂等操作标记高安全模式
        if policy.safety_threshold > 0.65:
            validated["_high_safety_mode"] = True

        return validated, None

    # ── 内部辅助 ────────────────────────────────────────

    def _error(self, op_id: str, target: str, t0: float, msg: str) -> BusResponse:
        return BusResponse(
            op_id=op_id, status="ERROR",
            payload={"error": msg},
            latency_ms=(time.perf_counter() - t0) * 1000,
            bus_id=target,
        )
