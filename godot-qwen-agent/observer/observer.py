"""
V9 Observer — 语义翻译层 (Layer 4)

硬件对标: 传感器阵列 + 中断控制器前端
职责: 自然语言 → ObservationResult（结构化信号）

数学背板: 层论截面 on S³⁸³ (V7.7)
  σ_i: U_i → F  — 局部截面定义在开集 U_i ⊂ E 上
  ⊥ = E \\ ∪ U_i — 所有命令域的补集，"我不理解"是几何不是标签
  Angular distance (geodesic) on hypersphere

协议依赖:
  ObservationResult — 冻结的标准化输出
  ObservedEvent     — 带 payload 的离散事件

关键设计:
  - 纯函数: observe(text) → ObservationResult
  - 无状态: 不维护对话历史
  - ML 推理异步 offload: run_in_executor → 不阻塞事件循环
  - 数据流分工:
      → confidence, text_tokens, 三个 bool, discrete_events  → Adapter → Kernel
      → emotion_vector, extracted_entities → Harness 持有 → Prompt/工具参数
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from functools import partial
from types import MappingProxyType
from typing import Any, Mapping

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Observer 输出契约（冻结）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ObservedEvent:
    """Observer 直接检测到的离散事件。带 payload。"""
    event_type: str
    payload: Mapping[str, Any]   # 运行时传入 MappingProxyType


@dataclass(frozen=True)
class ObservationResult:
    """Observer 的标准化输出。

    Harness 拆分:
      → Adapter 接收: confidence, text_tokens, is_social_query,
                       escalation_flag, relaxation_flag, discrete_events
      → Harness 持有: emotion_vector, extracted_entities
    """

    confidence: float
    text_tokens: tuple[str, ...]

    is_social_query: bool = False
    escalation_flag: bool = False
    relaxation_flag: bool = False

    discrete_events: tuple[ObservedEvent, ...] = ()

    # Harness 直接持有 — 不进适配层，不进内核
    emotion_vector: tuple[float, ...] = ()
    extracted_entities: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )


# ═══════════════════════════════════════════════════════════════
# Observer 接口
# ═══════════════════════════════════════════════════════════════

class Observer:
    """语义观测器 — Layer 4。"""

    async def observe(self, text: str) -> ObservationResult:
        """自然语言 → 结构化信号。纯函数。无副作用。"""
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════
# V9 默认实现 — 封装现有 semantic_trust.py (V7.7)
# ═══════════════════════════════════════════════════════════════

class SemanticTrustObserver(Observer):
    """基于 V7.7 层论截面的默认 Observer。

    ⊥ 开集: null_region → is_social_query=True (我不理解 → 直接 A)
    ML 推理: loop.run_in_executor → 线程池隔离，不阻塞 asyncio 事件循环
    """

    def __init__(self, semantic_engine=None):
        self._engine = semantic_engine

    async def observe(self, text: str) -> ObservationResult:
        """执行语义观测。"""
        tokens = self._tokenize(text)
        is_social = self._is_social_fallback(text)

        if self._engine is None:
            return ObservationResult(
                confidence=0.5,
                text_tokens=tokens,
                is_social_query=is_social,
            )

        # ML 推理 → 线程池隔离（不阻塞事件循环）
        try:
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(
                None, partial(self._engine.observe, text)
            )
        except Exception:
            logger.exception("Observer ML 引擎崩溃 — 降级回退")
            return ObservationResult(
                confidence=0.3,
                text_tokens=tokens,
                escalation_flag=True,
                discrete_events=(
                    ObservedEvent("ENGINE_CRASH", MappingProxyType({})),
                ),
            )

        # 翻译 V7.7 → V9
        raw_conf = getattr(raw, "confidence", 0.5)
        raw_null = getattr(raw, "null_region", False)
        raw_gap = getattr(raw, "gap_region", False)
        raw_emo = tuple(getattr(raw, "emotion_scores", []) or [])

        raw_entities = getattr(raw, "entities", {}) or {}
        entities = (
            raw_entities if isinstance(raw_entities, MappingProxyType)
            else MappingProxyType(raw_entities)
        )

        # ⊥ 开集 → 社交通道
        if raw_null:
            return ObservationResult(
                confidence=raw_conf,
                text_tokens=tokens,
                is_social_query=True,
                discrete_events=(
                    ObservedEvent("NULL_REGION", MappingProxyType({
                        "confidence": raw_conf,
                    })),
                ),
                emotion_vector=raw_emo,
                extracted_entities=entities,
            )

        # 歧义区 → 标记
        gap_events = ()
        if raw_gap:
            gap_events = (
                ObservedEvent("GAP_REGION", MappingProxyType({
                    "candidates": len(getattr(raw, "command_candidates", []) or []),
                })),
            )

        return ObservationResult(
            confidence=raw_conf,
            text_tokens=tokens,
            is_social_query=is_social,
            escalation_flag=raw_gap,
            discrete_events=gap_events,
            emotion_vector=raw_emo,
            extracted_entities=entities,
        )

    # ── 辅助 ──────────────────────────────────────────

    @staticmethod
    def _tokenize(text: str) -> tuple[str, ...]:
        return tuple(text.split())

    @staticmethod
    def _is_social_fallback(text: str) -> bool:
        text_lower = text.lower().strip()
        return any(p in text_lower for p in (
            "你好", "再见", "拜拜", "谢谢", "早上好", "晚安",
            "hello", "hi", "bye", "thanks", "good morning", "good night",
        ))


# ═══════════════════════════════════════════════════════════════
# V9.2b: PluginManifest + 工厂函数 — 接入 PluginRegistry
# ═══════════════════════════════════════════════════════════════

from mainboard.plugin_sdk.protocol import PluginManifest

_SEMANTIC_TRUST_MANIFEST = PluginManifest(
    name="semantic_trust",
    slot_type="observer",
    version="1.0.0",
    protocol_version="9.2.0",
    description="L4 Semantic Trust Observer — ML-based sheaf theory (V7.7)",
)

# 注入 manifest 到已有的类 (不改变类定义，避免破坏现有 import)
SemanticTrustObserver.manifest = _SEMANTIC_TRUST_MANIFEST
SemanticTrustObserver.observer_id = "semantic_trust"


def get_instance() -> SemanticTrustObserver:
    """工厂函数 — LazyPluginLoader 的无参构造入口。"""
    return SemanticTrustObserver(semantic_engine=None)
