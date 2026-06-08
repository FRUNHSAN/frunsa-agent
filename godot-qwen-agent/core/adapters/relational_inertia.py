"""DEPRECATED_BY_V5 — 外科手术拆分为 selection_pressure_accumulator.py

PLAN3/4 的"关系惯性"被 V5 拆分为两部分：
  ✅ 信任 EMA + 贝叶斯方差 + 基线漂移 → selection_pressure_accumulator.py
  ❌ 能量/紧迫度平滑 → 被 tracking_error.py 的自适应增益调度替代
  ❌ 语气阻尼 → char-level 约束，不属关系度量层

信任在 V5 中的本体论地位已修正：
  旧：信任 = "用户是否喜欢 Agent"（心理读心术）
  新：信任 = 用户历史行为反馈构成的选择压力累积度量（达尔文选择压力）

命名即认知：SelectionPressureAccumulator，不是 RelationalHistory。
"""

raise ImportError(
    "relational_inertia is DEPRECATED_BY_V5. "
    "It has been surgically split into selection_pressure_accumulator.py. "
    "The trust EMA + Bayesian variance + baseline drift are preserved there "
    "as SelectionPressureAccumulator. "
    "Energy/urgency/tone smoothing have been superseded by "
    "tracking_error.TrackingErrorEstimator (adaptive gain scheduling). "
    "See PLAN8.md and .ai_reasoning/BRAINSTORM_TRUE_ADAPTIVE.md."
)
