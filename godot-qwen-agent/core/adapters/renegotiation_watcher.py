"""DEPRECATED_BY_V5 — moved to .ai_reasoning/archive/renegotiation_watcher.py

This module implements PLAN2 "agent intentionally violates contract to show
agency, then proposes renegotiation." V5 rejects this premise:
the agent does NOT negotiate — it is SELECTED BY user behavior feedback.

The counting of INTENTIONAL_VIOLATION events has been superseded by
tracking_error.py (behavior-gap measurement) and meta_adapt_trigger.py
(selection threshold relaxation).

See PLAN8.md for the current paradigm.
"""

raise ImportError(
    "renegotiation_watcher is DEPRECATED_BY_V5. "
    "It has been moved to .ai_reasoning/archive/. "
    "Use tracking_error.TrackingErrorEstimator for behavior-gap measurement, "
    "or meta_adapt_trigger.MetaAdaptTrigger for selection threshold adaptation."
)
