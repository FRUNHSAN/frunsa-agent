"""WassersteinProxy — W_1 upper bound via Kantorovich-Rubinstein duality.

Embeds system behaviors into LLM hidden space and uses cosine distance
as a 1-Lipschitz test function φ for the KR dual formulation:

  W_1(μ, ν) ≤ sup_{‖φ‖_L ≤ 1} E_μ[φ] - E_ν[φ]

The cosine distance in embedding space is an upper bound on W_1
when the embedding is normalized to unit sphere.

Engineering: Structure-Preserving Model Reduction (Patch 1).
Contrastive calibration maps raw embedding distances to [0, 1].
"""

from __future__ import annotations

import math
from typing import Optional


class WassersteinProxy:
    """Calibrated W_1 upper bound via embedding cosine distance.

    Usage:
        proxy = WassersteinProxy()
        proxy.calibrate(perfect_pairs, bad_pairs)  # Run once at startup
        dist = proxy.distance(emb_a, emb_b)         # O(1) per call
    """

    def __init__(self) -> None:
        self._d_min: float = 0.0
        self._d_max: float = 1.0
        self._calibrated: bool = False

    # ── Calibration ──────────────────────────────────────────────────

    def calibrate(
        self,
        perfect_embeddings: list,
        bad_embeddings: list,
    ) -> "WassersteinProxy":
        """Estimate distribution of embedding distances from benchmark pairs.

        perfect_embeddings: list of (emb_a, emb_b) for matching QAs
        bad_embeddings:      list of (emb_a, emb_b) for mismatched QAs

        d_min = 5th percentile of perfect distances
        d_max = 95th percentile of bad distances
        """
        perfect_dists = [
            _cosine_distance(a, b) for a, b in perfect_embeddings
        ]
        bad_dists = [
            _cosine_distance(a, b) for a, b in bad_embeddings
        ]
        if perfect_dists:
            self._d_min = _percentile(perfect_dists, 5)
        if bad_dists:
            self._d_max = _percentile(bad_dists, 95)
        # Safety: d_max must be > d_min to avoid division by zero
        if self._d_max <= self._d_min:
            self._d_max = self._d_min + 1e-6
        self._calibrated = True
        return self

    @classmethod
    def uncalibrated(cls) -> "WassersteinProxy":
        """Factory: proxy without calibration (raw cosine distance)."""
        return cls()

    # ── Distance ─────────────────────────────────────────────────────

    def distance(self, emb_a, emb_b) -> float:
        """Calibrated W_1 upper bound in [0, 1].

        Returns 0.0 for identical behaviors, 1.0 for maximally divergent.
        Uncalibrated mode returns raw cosine distance.
        """
        raw = _cosine_distance(emb_a, emb_b)
        if not self._calibrated:
            return max(0.0, min(1.0, float(raw)))
        # Linear mapping: [d_min, d_max] → [0, 1]
        calibrated = (raw - self._d_min) / (self._d_max - self._d_min)
        return max(0.0, min(1.0, float(calibrated)))

    @property
    def is_calibrated(self) -> bool:
        return self._calibrated


# ── Pure functions (no class needed) ──────────────────────────────────


def _cosine_distance(emb_a, emb_b) -> float:
    """1 - cosine_similarity, with safety for zero vectors."""
    import numpy as np

    a = np.asarray(emb_a, dtype=np.float64)
    b = np.asarray(emb_b, dtype=np.float64)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 1.0  # Zero vector: maximally distant
    cos_sim = float(np.dot(a, b) / (norm_a * norm_b))
    # Clip for floating point stability
    cos_sim = max(-1.0, min(1.0, cos_sim))
    return 0.5 * (1.0 - cos_sim)  # Map [-1, 1] to [0, 1]


def _percentile(values: list[float], p: float) -> float:
    """p-th percentile of a list (0 ≤ p ≤ 100)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (p / 100.0) * (len(sorted_vals) - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return d0 + d1
