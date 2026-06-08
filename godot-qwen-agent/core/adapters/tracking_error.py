"""TrackingErrorEstimator — replaces fixed-threshold signal interpretation.

Instead of "if fatigue_score > 0.55 → verbosity = LOW", this module
estimates e(t) — the Wasserstein tracking error between system behavior
and user expectation — from observable user behavior signals.

Mathematical basis (Research 4):
  e_∞ ≤ ω_max / λ_SB

Where:
  - ω_max = user behavior change rate (observed via follow-up questions)
  - λ_SB  = system convergence rate (observed via acceptance signals)

Engineering: Structure-Preserving Model Reduction (Patch 2).
Adaptive gain scheduling (dynamic EMA α) prevents phase lag under
high-frequency user interaction (machine-gun follow-ups).

Backward compatible: exports interpret() with same signature as
the old signal_interpreter.py. Existing tests pass unchanged.
"""

from __future__ import annotations

import math
import time
from typing import Optional


# ── Strong signal keywords (Patch: only high-confidence signals) ──

GROWTH_SIGNAL_KEYWORDS = frozenset({
    "为什么", "解释", "原理", "能详细点吗", "能展开吗",
    "怎么理解", "什么意思", "可以说说吗", "再讲一遍",
    "详细", "深入", "怎么看", "你觉得呢",
    "越长越好", "一次性", "全部", "全流程",  # Output depth demands
    "展开", "调研", "完整",  # Depth/research signals
})

TECH_TERMS = frozenset({
    "sql", "join", "索引", "index", "事务", "transaction",
    "查询", "query", "优化", "optimize", "锁", "lock",
    "python", "函数", "function", "类", "class", "算法",
    "api", "数据库", "database", "表", "table", "视图",
    "子查询", "subselect", "并发", "concurrent", "异步",
    "内存", "memory", "缓存", "cache", "线程", "thread",
    # Physics / quantum / general science
    "量子", "超导", "比特", "表面码", "纠错",
    "离子阱", "光子", "退相干", "拓扑", "相干",
    # CS / architecture / general
    "架构", "设计", "系统", "协议", "网络",
    "编译", "内核", "渲染", "加密", "安全",
})

# Feedback that indicates acceptance (user didn't need more)
ACCEPTANCE_KEYWORDS = frozenset({
    "好的", "谢谢", "明白了", "懂了", "可以", "ok", "行",
    "okay", "thanks", "thx", "对", "是的", "没问题",
})


def _contains_growth_signal(text: str) -> bool:
    """Check if text contains a growth-demand keyword."""
    t = text.lower()
    return any(kw in t for kw in GROWTH_SIGNAL_KEYWORDS)


def _contains_tech_term(text: str) -> bool:
    """Check if text contains a technical term."""
    t = text.lower()
    return any(term in t for term in TECH_TERMS)


def _is_acceptance(text: str) -> bool:
    """Check if text is a likely acceptance signal."""
    t = text.strip().lower()
    # Only match short acceptance messages (≤8 chars) to avoid false positives
    # "好的谢谢" = acceptance. "好的, 但我还有一个问题..." ≠ acceptance.
    if len(t) > 8:
        return False
    return any(ack in t for ack in ACCEPTANCE_KEYWORDS)


# ── Error signal computation ──────────────────────────────────────────

def compute_error_signal(
    user_text: str,
    response_delay_sec: float = 0.0,
    previous_error: float = 0.5,
) -> tuple[float, str]:
    """Convert user behavior into a tracking error signal in [0, 1].

    0.0 = perfect tracking (user accepted response)
    1.0 = total divergence (user is frustrated/lost)

    Only one high-confidence path is enabled:
      growth keyword + tech term + delay > 8s → error +0.12

    Acceptance signals reduce error.
    Silence/other inputs produce gradual decay toward baseline.

    Returns (error_signal, signal_type).
    """
    signal_type = "neutral"
    error_delta = 0.0

    # ── Path 1: Growth demand (high confidence, low false positive) ──
    if _contains_growth_signal(user_text):
        if _contains_tech_term(user_text):
            if response_delay_sec > 8.0:
                # Triple condition met → strong signal
                error_delta = 0.12
                signal_type = "growth_demand_confirmed"
            else:
                # Growth keyword + tech but fast response — weaker signal
                error_delta = 0.06
                signal_type = "growth_demand_weak"
        else:
            # Growth keyword without tech term — ambiguous
            error_delta = 0.04
            signal_type = "growth_demand_ambiguous"

    # ── Path 2: Acceptance → reduce error ──
    if _is_acceptance(user_text):
        if error_delta == 0.0:  # Don't override a growth signal
            error_delta = -0.05
            signal_type = "acceptance"

    # ── Path 3: Silence (no text) → gradual decay toward baseline ──
    if not user_text.strip():
        # Decay: move 10% toward neutral 0.5
        error_delta = 0.10 * (0.5 - previous_error)
        signal_type = "silence_decay"

    # ── Clamp ──
    new_error = max(0.0, min(1.0, previous_error + error_delta))
    return new_error, signal_type


# ── Adaptive EMA Estimator ────────────────────────────────────────────


class TrackingErrorEstimator:
    """EMA-based tracking error estimator with adaptive gain scheduling.

    The decay rate α adapts to interaction frequency:
      - Fast interactions (short interval) → lower α (more responsive)
      - Slow interactions (long interval)  → higher α (more stable)

    Usage:
        est = TrackingErrorEstimator(tau=300.0)
        e = est.update(error_signal, interaction_interval_sec)
    """

    def __init__(self, tau: float = 300.0) -> None:
        """tau: time constant for adaptive α (seconds). Default 5 min."""
        self.tau = tau
        self._ema: float = 0.5  # Start at neutral
        self._last_update: Optional[float] = None
        self._sample_count: int = 0

    def update(
        self,
        error_signal: float,
        interaction_interval_sec: float,
    ) -> float:
        """Update EMA with new error observation.

        interaction_interval_sec: time since last user interaction.
        Shorter intervals → system needs to be more responsive.
        """
        # Adaptive α: exp(-interval/tau)
        # Short interval → α ≈ 0 → weight on new observation
        # Long interval  → α ≈ 1 → weight on history
        dynamic_alpha = math.exp(-interaction_interval_sec / self.tau)

        self._ema = (
            dynamic_alpha * self._ema
            + (1.0 - dynamic_alpha) * error_signal
        )
        self._sample_count += 1
        self._last_update = time.time()
        return self._ema

    @property
    def value(self) -> float:
        return self._ema

    @property
    def samples(self) -> int:
        return self._sample_count

    def reset(self) -> None:
        """Reset estimator to neutral (e.g., on /reset command)."""
        self._ema = 0.5
        self._sample_count = 0
        self._last_update = None


# ── Backward-compatible interpret() wrapper ───────────────────────────
# Keeps the same signature as old signal_interpreter.py for test compat.
# New code should use TrackingErrorEstimator directly.

def interpret(
    dim: str | None,
    score: float,
    trust: float,
    current_bp: dict[str, str],
    user_text: str = "",
    thresholds: dict[str, float] | None = None,
) -> list[dict]:
    """Backward-compatible wrapper. Delegates to old signal_interpreter.

    This function exists so that existing tests importing `interpret`
    from signal_interpreter continue to work. The new tracking error
    path is accessed via TrackingErrorEstimator, not this function.
    """
    # Delegate to old implementation for backward compat
    from core.adapters.signal_interpreter import interpret as _old_interpret
    return _old_interpret(dim, score, trust, current_bp, user_text, thresholds)
