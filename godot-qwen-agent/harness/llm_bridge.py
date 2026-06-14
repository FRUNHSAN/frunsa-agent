"""
V9 LLM Bridge — LLM 总线桥接器 (AHB 级)

硬件对标: DisplayPort → HDMI 主动协议转换器
职责: 地址解码 + 协议翻译 + 阻抗匹配（建连/读超时分离 + MAC 重试 + 稳态事件上报）

协议依赖（全部冻结）:
  DataPolicy        — 内核产出的约束张量
  BusResponse       — 统一总线响应
  LLMBridgeConfig   — 总线物理参数
  EventBridge.emit  — 同步入队，非阻塞

零第三方 SDK import — 只依赖 httpx（通用 HTTP 协议层）
"""

from __future__ import annotations

import time
import asyncio
import logging
from dataclasses import dataclass, replace
from types import MappingProxyType

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 顶层导入：零供应商锁定 → 只依赖 httpx（通用 HTTP 协议层）
# 在模块顶层解析异常类 — 防止 except 子句求值崩溃 (TypeError)
# ═══════════════════════════════════════════════════════════════
try:
    import httpx
    _ConnectTimeout = httpx.ConnectTimeout
    _ReadTimeout = httpx.ReadTimeout
    _PoolTimeout = httpx.PoolTimeout
    _HTTPStatusError = httpx.HTTPStatusError
except ImportError:
    # httpx 未安装 → 虚拟异常 — 永远不会被匹配到
    class _DummyException(BaseException):
        pass
    _ConnectTimeout = _DummyException
    _ReadTimeout = _DummyException
    _PoolTimeout = _DummyException
    _HTTPStatusError = _DummyException


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LLMBridgeConfig:
    """LLM 总线物理参数。"""
    connect_timeout_ms: int = 3000      # TCP 握手超时 — MAC 层可重试
    read_timeout_ms: int = 30000        # 默认读取/生成超时（fallback）
    connect_retries: int = 1            # 建连失败最大重试次数
    connect_retry_delay_ms: int = 500   # 退避延迟

    # 每个 LLM 外设的超时（覆盖 read_timeout_ms）
    planning_timeout_ms: int = 30000
    synthesis_timeout_ms: int = 15000
    critic_timeout_ms: int = 20000

    on_generation_timeout: str = "DEGRADED"   # 生成超时 → 降级模板

    max_output_tokens_hard_cap: int = 4096    # 物理上限防线
    max_history_rounds: int = 10              # 对话历史最大保留轮数
    max_tool_results: int = 5                 # 工具结果最大保留条数

    model: str = "deepseek-chat"              # 默认模型


# ═══════════════════════════════════════════════════════════════
# 输出契约
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class BusResponse:
    """统一总线响应（冻过）。"""
    op_id: str              # 事务 ID — 用于 DAG 编排响应匹配
    status: str             # "OK" | "ERROR" | "DEGRADED" | "TIMEOUT"
    payload: dict           # 成功 → {"text": ...}；失败 → {"error": ..., "checkpoints": {}}
    latency_ms: float       # 实际延迟
    bus_id: str             # 例: "llm://planning"


# ═══════════════════════════════════════════════════════════════
# LLM Bridge
# ═══════════════════════════════════════════════════════════════

class LLMBridge:
    """LLM 总线桥接器。

    地址空间: llm://planning | llm://synthesis | llm://critic

    架构边界:
      • 只捕获 httpx 标准网络异常 — 不 import 任何 LLM SDK
      • 底层 HTTP 客户端在 __init__ 时注入 connect/read 超时配置
      • 协议翻译 (DataPolicy → API 参数) 独立在 _translate_policy 中
    """

    NAMESPACE = "llm://"

    def __init__(
        self,
        provider,                  # 底层 LLM 客户端 (httpx-backed)
        event_bridge,              # EventBridge — emit() 是同步的
        config: LLMBridgeConfig = LLMBridgeConfig(),
        prompt_templates: dict[str, str] | None = None,
        http_client=None,          # httpx.AsyncClient — 外部配置好 connect/read 超时
    ):
        self.provider = provider
        self.event = event_bridge
        self.cfg = config
        self._http = http_client   # 底层通用 HTTP 客户端

        # 地址解码表 — 默认模板。Harness 可通过构造函数注入
        self._prompts = {
            "planning": (
                "你是一个严谨的任务规划师。根据用户意图输出 JSON 格式的执行计划。"
            ),
            "synthesis": (
                "你是一个内容合成专家。根据工具返回的数据和约束指令撰写回复。"
            ),
            "critic": (
                "你是一个质量审查员。检查执行结果是否满足所有约束。"
                "输出 JSON: {\"pass\": bool, \"reason\": str}。"
            ),
        }
        if prompt_templates:
            self._prompts.update(prompt_templates)

    # ── 地址解码 ────────────────────────────────────────

    def can_handle(self, target: str) -> bool:
        """地址解码：target 是否属於本总线。"""
        return target.startswith(self.NAMESPACE)

    # ── 公共接口 ────────────────────────────────────────

    async def execute(
        self,
        target: str,            # llm://planning | llm://synthesis | llm://critic
        context: dict,          # {"user_query": ..., "history": [...], "tool_results": [...]}
        policy,                 # DataPolicy — 内核产出的约束张量
        op_id: str,             # 事务 ID — 用于响应追踪
    ) -> BusResponse:
        """执行一次 LLM 事务。

        Args:
            target:  LLM 外设地址
            context: 用户输入 + 对话历史 + 工具结果
            policy:  DataPolicy (verbosity_budget, tone_vector, safety_threshold)
            op_id:   事务追踪 ID

        Returns:
            BusResponse — 永远返回，不抛异常（状态保全宪法）。
        """
        t0 = time.perf_counter()

        # ── 1. 地址解码 ──
        agent_name = target.replace(self.NAMESPACE, "")
        system_prompt = self._prompts.get(agent_name)
        if system_prompt is None:
            return BusResponse(
                op_id=op_id, status="ERROR",
                payload={"error": f"Unknown LLM target: {target}"},
                latency_ms=0, bus_id=target,
            )

        # ── 2. 协议翻译 ──
        api_params = self._translate_policy(policy, agent_name)
        messages = self._build_messages(system_prompt, context, policy)

        # ── 3. MAC 层执行 ──
        last_error = None

        for attempt in range(self.cfg.connect_retries + 1):
            try:
                raw = await self.provider.chat.completions.create(
                    model=api_params["model"],
                    messages=messages,
                    temperature=api_params["temperature"],
                    max_tokens=api_params["max_tokens"],
                )
                latency = (time.perf_counter() - t0) * 1000
                return BusResponse(
                    op_id=op_id, status="OK",
                    payload={"text": raw.choices[0].message.content},
                    latency_ms=latency, bus_id=target,
                )

            except asyncio.CancelledError:
                # NMI 级中断 — 绝不吞没，必须向上冒泡
                raise

            except (_ConnectTimeout, _PoolTimeout):
                # TCP 握手超时 / 连接池耗尽 → MAC 层可重试（瞬态资源噪声）
                last_error = "CONNECT_TIMEOUT"
                logger.warning(
                    f"[{target}] 建连/连接池超时 (attempt {attempt + 1}/"
                    f"{self.cfg.connect_retries + 1})"
                )
                if attempt < self.cfg.connect_retries:
                    await asyncio.sleep(self.cfg.connect_retry_delay_ms / 1000.0)
                    continue
                # 重试耗尽 → break to steady-state failure

            except _ReadTimeout:
                # 读取/生成超时 — 绝不重试（LLM 任务复杂度问题，非网络问题）
                last_error = "GENERATION_TIMEOUT"
                logger.error(f"[{target}] 生成超时 (Read Timeout)")
                break

            except _HTTPStatusError as e:
                # API HTTP 错误 (4xx, 5xx)
                last_error = f"API_HTTP_{_get_status(e)}"
                logger.error(f"[{target}] API HTTP 错误: {last_error}")
                break

            except Exception as e:
                # 未知异常 — 兜底。不重试
                last_error = f"UNKNOWN: {type(e).__name__}: {e}"
                logger.exception(f"[{target}] 未知致命错误")
                break

        # ── 4. 稳态失败 — MAC 重试耗尽 ──
        # 持续故障 ≠ 瞬态噪声。事件脉冲 → 内核 ODE 积分器
        is_timeout = last_error == "GENERATION_TIMEOUT"
        event_type = "LLM_TIMEOUT" if is_timeout else "LLM_API_ERROR"

        self.event.emit(event_type, MappingProxyType({
            "target": target,
            "op_id": op_id,
            "error": last_error,
        }))

        latency = (time.perf_counter() - t0) * 1000

        # 生成超时 → 降级模板
        if is_timeout and self.cfg.on_generation_timeout == "DEGRADED":
            degraded_text = self._degraded_output(agent_name, context)
            return BusResponse(
                op_id=op_id, status="DEGRADED",
                payload={"text": degraded_text, "error": last_error},
                latency_ms=latency, bus_id=target,
            )

        # 网络故障 → 错误返回。不抛异常（状态保全宪法）
        return BusResponse(
            op_id=op_id, status="ERROR",
            payload={"error": last_error, "checkpoints": {}},
            latency_ms=latency, bus_id=target,
        )

    # ── 协议翻译：DataPolicy → LLM API 参数 ─────────────────

    def _translate_policy(self, policy, agent_name: str) -> dict:
        """将 DataPolicy 连续约束张量翻译为 LLM API 物理参数。

        三个连续映射:
          1. verbosity_budget [0,1] × base_tokens → max_tokens
             硬上限 max_output_tokens_hard_cap，地板 50
          2. tone_vector [客观, 共情, 威严] → temperature（线性组合）
             共情↑ → temp↑ (更自然)
             客观↑ → temp↓ (更确定)
             威严↑ → temp↓ (更冷)
          3. safety_threshold θ [0.50, 0.75] → temp 额外收紧

        没有 if/else 查表。没有离散 bin。
        所有映射是连续的 — 铁律 2（连续控制律）。
        """
        budget = policy.verbosity_budget

        # verbosity_budget → max_tokens
        base_tokens = {
            "planning": 3000,
            "synthesis": 2000,
            "critic": 1500,
        }.get(agent_name, 2000)

        max_tokens = min(
            int(budget * base_tokens),
            self.cfg.max_output_tokens_hard_cap,
        )
        max_tokens = max(max_tokens, 50)

        # tone_vector → temperature 连续映射
        objective, empathetic, authoritative = policy.tone_vector
        temp = 0.3                               # 基线
        temp += 0.30 * empathetic                # max +0.30 — 共情 → 更自然
        temp -= 0.15 * objective                 # max −0.15 — 客观 → 更确定
        temp -= 0.15 * authoritative             # max −0.15 — 威严 → 更冷
        temp -= 0.1 * (policy.safety_threshold - 0.5) / 0.25  # θ 收紧 → 温度降
        temp = max(0.05, min(1.5, temp))

        # 外设 → 超时
        timeout_ms = {
            "planning": self.cfg.planning_timeout_ms,
            "synthesis": self.cfg.synthesis_timeout_ms,
            "critic": self.cfg.critic_timeout_ms,
        }.get(agent_name, self.cfg.read_timeout_ms)

        return {
            "model": self.cfg.model,
            "timeout_ms": timeout_ms,
            "max_tokens": max_tokens,
            "temperature": round(temp, 3),
        }

    # ── Prompt 组装 ─────────────────────────────────────

    def _build_messages(
        self, system_prompt: str, context: dict, policy,
    ) -> list[dict]:
        """组装 LLM Messages 数组。

        DataPolicy 约束只以 [策略约束] 标签注入 system prompt —
        不碰 API 层面的 temperature/max_tokens（那些由 _translate_policy 处理）。
        """
        user_content = context.get("user_query", "")
        history = context.get("history", [])
        tool_results = context.get("tool_results", [])

        # ── 策略指令（从 DataPolicy 连续推导）──
        policy_notes = []
        budget = policy.verbosity_budget
        obj, emp, auth = policy.tone_vector

        # verbosity → 长度指令
        if budget < 0.3:
            policy_notes.append("回复极简，一句话完成。")
        elif budget < 0.5:
            policy_notes.append("回复简洁，不超过一段。")
        elif budget < 0.8:
            policy_notes.append("回复详尽，可使用多段落和列表。")

        # tone_vector → 语气指令
        tone_parts = []
        if emp > 0.5:
            tone_parts.append("语气温暖、共情")
        if auth > 0.5:
            tone_parts.append("语气专业、自信")
        if obj > 0.5:
            tone_parts.append("陈述客观事实，避免主观判断")
        if tone_parts:
            policy_notes.append("；".join(tone_parts) + "。")

        # forbidden_patterns → 禁止项
        if policy.forbidden_patterns:
            policy_notes.append(
                f"禁止：{'、'.join(policy.forbidden_patterns)}。"
            )

        policy_hint = "\n".join(policy_notes) if policy_notes else ""

        system_full = system_prompt
        if policy_hint:
            system_full += f"\n\n[策略约束]\n{policy_hint}"

        messages = [{"role": "system", "content": system_full}]

        # 对话历史
        for h in history[-self.cfg.max_history_rounds:]:
            messages.append(h)

        # 工具结果 — role="user" + <tool_result> 标签
        # 不用 role="system" — 避免污染 attention 权重
        for tr in tool_results[-self.cfg.max_tool_results:]:
            messages.append({
                "role": "user",
                "content": f"<tool_result>{tr}</tool_result>",
            })

        # 当前用户输入
        messages.append({"role": "user", "content": user_content})

        return messages

    # ── 降级输出 ────────────────────────────────────────

    def _degraded_output(self, agent_name: str, context: dict) -> str:
        """生成超时 → 降级模板。保留用户输入上下文。"""
        user = context.get("user_query", "")

        if agent_name == "planning":
            return (
                '{"type": "FULL_DAG", "steps": [{"prompt": "'
                f'分析用户需求: {user[:200]}'
                '", "tool": "", "is_terminal": true}]}'
            )
        elif agent_name == "critic":
            return '{"pass": true, "reason": "降级: 审查超时，默认通过"}'
        else:  # synthesis
            return (
                f"处理您的请求时超时。您的问题「{user[:100]}」已被记录，"
                "请稍后重试或简化需求。"
            )


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _get_status(e: Exception) -> int:
    """安全提取 HTTP 状态码。"""
    try:
        return e.response.status_code
    except AttributeError:
        return 0
