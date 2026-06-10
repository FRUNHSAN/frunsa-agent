"""V7.4 Identity Manifold — cross-session identity continuity.

Exports:
  IdentityPoint              — point p ∈ M_id ⊂ ℝ¹² (frozen, manifold-with-boundary)
  SessionSufficientStatistic — compressed statistics from one completed session
  IdentityManifoldStore      — persist + evolve identity points + Betti detection
  StreamingPercentile        — dynamic-window percentile estimation
  adaptive_pctl              — unified percentile threshold accessor
"""
from core.memory.identity_manifold import (
    IdentityPoint,
    SessionSufficientStatistic,
    IdentityManifoldStore,
    StreamingPercentile,
    adaptive_pctl,
    DIMENSION_BASE_TAU,
    compute_dimension_tau,
)
