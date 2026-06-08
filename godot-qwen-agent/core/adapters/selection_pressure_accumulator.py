"""SelectionPressureAccumulator — V5 环境选择压力的累积度量。

从 relational_inertia.py 的 PLAN3/4 "关系惯性"中外科手术提取。
只保留信任 EMA 及相关的贝叶斯方差追踪。删除所有"猜意图"残留：
  - ❌ 能量平滑 (smooth_energy) — 被 tracking_error.py 的自适应增益调度替代
  - ❌ 紧迫度平滑 (smooth_urgency) — 同上
  - ❌ 语气阻尼 (smooth_tone) — char-level 约束，不是关系度量
  - ❌ smooth() 组合调用 — 拆分为单维度调用

信任在 V5 中的本体论地位：
  信任 ≠ "用户是否喜欢 Agent"
  信任 = 用户历史行为反馈构成的选择压力累积度量
  信任高 → 用户持续选择 Agent 的行为路径 → 环境压力低
  信任低 → 用户频繁拒绝/纠正 Agent 的行为 → 环境压力高

命名即认知：这不是"关系惯性"，这是"选择压力累积器"。
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field


# ── 配置 ──────────────────────────────────────────────────────────────

@dataclass
class PressureConfig:
    """选择压力累积器的可调参数。校准自 2026-05-29 盲测数据。"""

    # 信任 EMA 的 α（0.0 = 不更新，1.0 = 即时）
    trust_alpha: float = 0.3

    # P1 心理学：非对称信任动态
    alpha_negative: float = 0.30  # 信任侵蚀快（消极偏差）
    alpha_positive: float = 0.08  # 信任建立慢（需要重复证据）

    # 贝叶斯方差衰减 γ = 0.85（每轮平静轮次方差缩小 15%）
    variance_decay_gamma: float = 0.85

    # 基线漂移
    peace_threshold: int = 5      # 连续无惊讶轮次后开始漂移
    drift_rate: float = 0.01      # 信任每轮向基线漂移的速率
    drift_target: float = 0.3     # 信任自然漂移的目标基线


# ── 累积器 ────────────────────────────────────────────────────────────

@dataclass
class SelectionPressureAccumulator:
    """用户行为选择压力的累积度量。

    用法:
        acc = SelectionPressureAccumulator()
        acc.record_trust(0.72)          # 每轮记录原始信任信号
        acc.smooth_trust(0.5)           # 返回 EMA 平滑后的信任值
        acc.bayesian_update("trust", 0.6)  # 贝叶斯均值+方差更新
        acc.apply_baseline_drift(0.0)   # 和平时期基线漂移
    """

    config: PressureConfig = field(default_factory=PressureConfig)

    # ── 核心：信任 EMA ──
    _trust_ema: float = 0.5

    # ── 贝叶斯追踪 ──
    _means: dict[str, float] = field(default_factory=lambda: {"trust": 0.5})
    _variances: dict[str, float] = field(default_factory=lambda: {"trust": 0.25})
    _alpha: float = 0.2   # 均值平滑系数（基准）
    _beta: float = 0.1    # 方差平滑系数

    # ── 基线漂移 ──
    _peace_streak: int = 0
    _round_count: int = 0

    # ═══════════════════════════════════════════════════════════════════
    # 信任 EMA — 核心指标
    # ═══════════════════════════════════════════════════════════════════

    def record_trust(self, trust: float) -> None:
        """记录一轮的原始信任信号，更新 EMA。"""
        self._round_count += 1
        self._trust_ema = (
            self.config.trust_alpha * trust
            + (1 - self.config.trust_alpha) * self._trust_ema
        )

    def smooth_trust(self, raw_trust: float) -> float:
        """返回 EMA 平滑后的信任值。"""
        return round(self._trust_ema, 4)

    @property
    def trust_ema(self) -> float:
        return round(self._trust_ema, 4)

    # ═══════════════════════════════════════════════════════════════════
    # 贝叶斯方差追踪
    # ═══════════════════════════════════════════════════════════════════

    def bayesian_update(self, dim: str, observed: float) -> tuple[float, float]:
        """贝叶斯 EMA：更新均值 AND 方差。"""
        return self._update_internal(dim, observed, surprise_score=0.0)

    def update_with_surprise(
        self, dim: str, observed: float, surprise_score: float = 0.0,
    ) -> tuple[float, float]:
        """贝叶斯 EMA + 行为惊讶注入。

        当 surprise_score > 0，强制扩展方差——防止"确认偏误"陷阱。
        """
        return self._update_internal(dim, observed, surprise_score)

    def _update_internal(
        self, dim: str, observed: float, surprise_score: float,
    ) -> tuple[float, float]:
        """核心贝叶斯 EMA 更新。

        P1 心理学：信任维度的非对称 EMA。
        消极信号（observed < current）→ 信任侵蚀快 (α=0.30)
        积极信号（observed > current）→ 信任建立慢 (α=0.08)
        """
        old_mean = self._means[dim]
        old_var = self._variances[dim]

        if dim == "trust":
            alpha = (
                self.config.alpha_negative
                if observed < old_mean
                else self.config.alpha_positive
            )
        else:
            alpha = self._alpha

        new_mean = (alpha * observed) + ((1 - alpha) * old_mean)
        error_sq = (observed - old_mean) ** 2
        augmented_error_sq = error_sq + (surprise_score ** 2)

        new_var = (self._beta * augmented_error_sq) + ((1 - self._beta) * old_var)
        new_var = max(0.01, min(new_var, 1.0))

        self._means[dim] = new_mean
        self._variances[dim] = new_var
        return new_mean, new_var

    def decay_variances(self, surprise_score: float = 0.0) -> None:
        """平静时指数衰减所有维度的方差（γ=0.85）。"""
        if surprise_score >= 0.3:
            return
        gamma = self.config.variance_decay_gamma
        for dim in self._variances:
            self._variances[dim] *= gamma
            self._variances[dim] = max(0.01, self._variances[dim])

    # ═══════════════════════════════════════════════════════════════════
    # 基线漂移 — 时间愈合信任
    # ═══════════════════════════════════════════════════════════════════

    def apply_baseline_drift(self, surprise_score: float) -> None:
        """和平时期信任自然向基线 (0.3) 漂移。

        长期无负面信号 → 基本信任自然恢复。时间会愈合伤口。
        """
        if surprise_score >= 0.3:
            self._peace_streak = 0
            return

        self._peace_streak += 1
        if self._peace_streak >= self.config.peace_threshold:
            current = self._means["trust"]
            if current < self.config.drift_target:
                self._means["trust"] = min(
                    self.config.drift_target,
                    current + self.config.drift_rate,
                )

    # ═══════════════════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════════════════

    def get_mean(self, dim: str) -> float:
        return round(self._means.get(dim, 0.5), 4)

    def get_variance(self, dim: str) -> float:
        return round(self._variances.get(dim, 0.25), 4)

    def is_uncertain(self, threshold: float = 0.5) -> bool:
        """任何核心维度方差 > 阈值 → 系统处于不确定状态。"""
        return any(v > threshold for v in self._variances.values())

    @property
    def round_count(self) -> int:
        return self._round_count

    # ═══════════════════════════════════════════════════════════════════
    # 跨会话持久化
    # ═══════════════════════════════════════════════════════════════════

    def save_state(self, db_path: str, user_id: str = "default") -> None:
        """持久化选择压力状态到 SQLite。"""
        state = {
            "means": self._means,
            "variances": self._variances,
            "peace_streak": self._peace_streak,
            "trust_ema": self._trust_ema,
            "round_count": self._round_count,
        }
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS selection_pressure
               (user_id TEXT PRIMARY KEY, state_json TEXT, updated_at REAL)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO selection_pressure VALUES (?, ?, ?)",
            (user_id, json.dumps(state), time.time()),
        )
        conn.commit()
        conn.close()

    @classmethod
    def load_state(
        cls, db_path: str, user_id: str = "default",
    ) -> SelectionPressureAccumulator | None:
        """从 SQLite 恢复选择压力状态。无保存状态时返回 None。"""
        conn = sqlite3.connect(db_path)
        conn.execute(
            """CREATE TABLE IF NOT EXISTS selection_pressure
               (user_id TEXT PRIMARY KEY, state_json TEXT, updated_at REAL)"""
        )
        row = conn.execute(
            "SELECT state_json FROM selection_pressure WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        if not row:
            return None
        state = json.loads(row[0])
        acc = cls()
        acc._means = state.get("means", acc._means)
        acc._variances = state.get("variances", acc._variances)
        acc._peace_streak = state.get("peace_streak", 0)
        acc._trust_ema = state.get("trust_ema", 0.5)
        acc._round_count = state.get("round_count", 0)
        return acc


# ═══════════════════════════════════════════════════════════════════════
# 向后兼容别名
# ═══════════════════════════════════════════════════════════════════════

# 让旧代码平滑过渡。Phase 2 完成后移除此别名。
RelationalHistory = SelectionPressureAccumulator
