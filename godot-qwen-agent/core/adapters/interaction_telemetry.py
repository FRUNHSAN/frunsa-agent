"""DEPRECATED_BY_V5 — moved to .ai_reasoning/archive/interaction_telemetry.py

This module records PLAN4 "relational state" dimensions (fatigue, energy,
variance) as JSONL telemetry. V5 replaces internal-state tracking with
external behavior-gap measurement.

The fatigue/energy/variance dimensions have been superseded by:
  - tracking_error.TrackingErrorEstimator (EMA of behavior-gap e(t))
  - meta_adapt_trigger.MetaAdaptTrigger (persistence + cooldown state)

If telemetry is needed in Phase 2, rebuild it to record tracking error,
selection thresholds, and meta_adapt events — not internal emotional state.

See PLAN8.md for the current paradigm.
"""

raise ImportError(
    "interaction_telemetry is DEPRECATED_BY_V5. "
    "It has been moved to .ai_reasoning/archive/. "
    "V5 telemetry should record: tracking_error e(t), meta_adapt trigger events, "
    "selection_threshold changes, and user behavior feedback signals."
)
