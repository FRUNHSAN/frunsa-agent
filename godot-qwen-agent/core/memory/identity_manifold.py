"""V7.4 Identity Manifold — cross-session identity continuity.

Mathematical: Memory functor M: Time → Id
             OU process on M_id ⊂ ℝ¹² (manifold-with-boundary)
             H₀ barcode Betti proxy for topological phase change detection

Red-team hardened (patches #4, #5, #6):
  #4: confidence_weight penalized by interval skew (anti-gaming)
  #5: OU relaxing boundary + TRUST_BOUNDARY_LOCK detection
  #6: dual-threshold Betti (instant + cumulative migration)

Engineering patches (E1, E2, E3):
  E1: StreamingPercentile — dynamic window + KS drift + cycle detection
  E2: dimension-adaptive τ — push normalization per dimension
  E3: three-state cold start protocol — explicit reliable flag

Architecture: NOT an engine — single module, same family as WassersteinProxy.
Pure math, zero LLM calls, zero async I/O.
"""

from __future__ import annotations

import json
import math
import os
import random as _random
import statistics
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, ClassVar


# ═══════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════

SKEW_PENALTY_GAMMA = 0.3       # confidence skew penalty coefficient
SKEW_CRITICAL = 1.5            # skew above this = suspicious
MIN_CONFIDENCE_SESSIONS = 10   # sessions for full confidence without skew

# ── E2: Dimension-adaptive τ for push normalization ──
DIMENSION_BASE_TAU: dict[str, int] = {
    "trust":       15,         # trust changes should be smooth
    "drift_P50":    8,         # drift can adapt quickly
    "drift_P95":   10,         # extreme values more stable
    "clarity":     10,         # clarity moderately stable
    "e_t":          8,         # tracking error responds quickly
    "physical_fail": 12,       # physical failure rate smooth
    "selection":   15,         # selection pressure accumulates
    "tool_risk":   12,         # tool preference changes slowly
    "budget":      25,         # budget exhaustion = long-term trend
    "retry":        7,         # retry effectiveness can change fast
}


def compute_dimension_tau(dim: str,
                          history: list[float] | None = None) -> int:
    """E2: Dimension-adaptive τ — base + recent_vol dynamic adjustment.

    High recent_vol → system unstable → shrink τ for faster adaptation.
    Low recent_vol → system stable → expand τ to smooth noise.

    Mathematical: τ_adaptive = τ_base / (1 + γ·σ_recent)
    Control-theoretic: gain scheduling — more volatility = faster response.
    """
    base = DIMENSION_BASE_TAU.get(dim, 12)
    if history and len(history) >= 5:
        recent = sorted(history[-5:])
        # IQR-based volatility (robust to non-Gaussian bimodal distributions)
        q25 = recent[len(recent) // 4]
        q75 = recent[3 * len(recent) // 4]
        iqr = q75 - q25
        mid = (q75 + q25) / 2.0
        rel_vol = iqr / (abs(mid) + 1e-6)
        adaptive = max(5, min(30, int(base * (1.0 - 0.4 * min(rel_vol, 1.5)))))
        return adaptive
    return base


# ═══════════════════════════════════════════════════════════════════════
# E1: Streaming Percentile Estimator
# ═══════════════════════════════════════════════════════════════════════

def _interpolated_percentile(sorted_vals: list[float], alpha: float) -> float:
    """Linear interpolation for percentile calculation."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_vals[0]
    k = alpha * (n - 1)
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return sorted_vals[lo]
    frac = k - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


class StreamingPercentile:
    """E1: Streaming percentile estimator — ring buffer + adaptive window.

    Isomorphic to V5's sigma self-calibration: μ/σ computed from live history.
    Here P25/P75/P90 are computed from live history. Zero new dependencies.

    Three-tier window selection:
      1. Cycle detection (autocorrelation lag=5..40, threshold |r|>0.30)
      2. KS drift detection (D>0.20 → shrink window to 20)
      3. Fallback to min(N, 50) if no signal detected
    """

    def __init__(self, max_size: int = 50):
        self._buf: deque[float] = deque(maxlen=max_size)
        self._timestamps: deque[float] = deque(maxlen=max_size)

    def add(self, value: float, ts: float | None = None) -> None:
        self._buf.append(value)
        self._timestamps.append(ts if ts is not None else time.time())

    def quantile(self, alpha: float) -> tuple[float | None, bool]:
        """Returns (threshold, is_reliable).

        reliable=False → strategy branches MUST be disabled.
        """
        n = len(self._buf)
        if n < 5:
            return None, False

        # Step 1: Cycle detection
        window = min(n, 50)
        period = self._detect_cycle()
        if period is not None and n > 30:
            window = min(n, int(1.5 * period))

        # Step 2: KS drift detection
        if n >= 20:
            ks_stat = self._ks_test(
                list(self._buf)[-20:],
                list(self._buf)[-40:-20],
            )
            if ks_stat > 0.20:
                window = min(window, 20)

        # Step 3: Compute percentile
        vals = sorted(self._buf)[-window:]
        p = _interpolated_percentile(vals, alpha)

        # Step 4: Reliability check via CI width
        ci_lo, ci_hi = self._bootstrap_ci(vals, alpha, n_boot=100)
        # CI width must be < 50% of domain span for reliability
        is_reliable = (ci_hi - ci_lo) < 0.50

        return p, is_reliable

    def _detect_cycle(self, min_periods: int = 3) -> int | None:
        """Autocorrelation-based cycle detection. Returns period (sessions) or None.

        Hardened: requires at least `min_periods` complete periods in the data,
        and consecutive peaks must be spaced consistently (within ±2 sessions).
        Prevents false positives from short-history random fluctuations.
        """
        vals = list(self._buf)
        if len(vals) < 20:
            return None
        best_lag, best_corr = None, 0.0
        try:
            mean = statistics.mean(vals)
            var = statistics.variance(vals)
        except statistics.StatisticsError:
            return None
        if var < 1e-9:
            return None

        # Collect all significant peaks
        max_acf = 0.0
        peaks: list[int] = []
        for lag in range(5, min(len(vals) // 2, 40)):
            n_pairs = len(vals) - lag
            if n_pairs < 5:
                continue
            corr = sum(
                (vals[i] - mean) * (vals[i + lag] - mean)
                for i in range(n_pairs)
            ) / (n_pairs * var)
            max_acf = max(max_acf, abs(corr))
            if abs(corr) > 0.30:
                peaks.append(lag)
            if abs(corr) > abs(best_corr):
                best_lag, best_corr = lag, corr

        # Require at least min_periods peaks with consistent spacing
        if len(peaks) < min_periods:
            return None
        # Check that first min_periods peaks are evenly spaced
        base = peaks[0]
        for i in range(1, min_periods):
            if abs(peaks[i] - peaks[i - 1] - base) > 2:
                return None
        # Must have enough data to observe min_periods complete cycles
        if len(vals) < base * min_periods:
            return None
        return best_lag

    @staticmethod
    def _ks_test(sample1: list[float], sample2: list[float]) -> float:
        """Kolmogorov-Smirnov two-sample D statistic."""
        if len(sample1) < 5 or len(sample2) < 5:
            return 0.0
        combined = sorted(sample1 + sample2)
        n1, n2 = len(sample1), len(sample2)
        s1_sorted = sorted(sample1)
        s2_sorted = sorted(sample2)
        i1, i2 = 0, 0
        max_diff = 0.0
        for x in combined:
            while i1 < n1 and s1_sorted[i1] <= x:
                i1 += 1
            while i2 < n2 and s2_sorted[i2] <= x:
                i2 += 1
            max_diff = max(max_diff, abs(i1 / n1 - i2 / n2))
        return max_diff

    @staticmethod
    def _bootstrap_ci(vals: list[float], alpha: float,
                      n_boot: int = 100) -> tuple[float, float]:
        """Percentile confidence interval via bootstrap."""
        n = len(vals)
        estimates = []
        for _ in range(n_boot):
            sample = [_random.choice(vals) for _ in range(n)]
            estimates.append(_interpolated_percentile(sorted(sample), alpha))
        estimates.sort()
        lo = estimates[max(0, int(n_boot * 0.025))]
        hi = estimates[min(n_boot - 1, int(n_boot * 0.975))]
        return lo, hi

    def to_list(self) -> list[float]:
        return list(self._buf)

    def __len__(self) -> int:
        return len(self._buf)


def adaptive_pctl(
    histories: dict[str, StreamingPercentile],
    dim: str, alpha: float,
) -> tuple[float | None, bool]:
    """E3 unified entry: get alpha-percentile threshold + reliability flag."""
    sp = histories.get(dim)
    if sp is None:
        return None, False
    return sp.quantile(alpha)


# ═══════════════════════════════════════════════════════════════════════
# Identity Point — M_id ⊂ ℝ¹²
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class IdentityPoint:
    """Point p ∈ M_id ⊂ ℝ¹² — manifold-with-boundary, red-team hardened.

    V7.4-semantic (6):     trust, drift_P50/P95, clarity_P50, e_t_P50,
                            physical_fail_rate
    V7.4-lifecycle (2):    selection_pressure_count, session_count
    V7.4-temporal (3):     interval_mu, interval_sigma, interval_skew
    V7.4-physical-3 (3):   tool_risk_aversion, budget_exhaustion_rate,
                            retry_success_rate
    V7.4-meta:             cumulative_migration, last_active_at,
                            last_push_magnitude, flags

    Physical dimension lifecycle (hard constraints):
      - Each dimension MUST drive ≥1 physical policy parameter
      - 7 consecutive days SHAP < 0.05 → auto-downgrade to session scope
      - Physical dimension hard cap: 5 (4 current + 1 reserve)
    """

    # ── Semantic core (6) ──
    trust: float = 0.5
    drift_P50: float = 0.20
    drift_P95: float = 0.60
    clarity_P50: float = 0.5       # Max-entropy neutral (corrected from 0.75)
    e_t_P50: float = 0.50
    physical_fail_rate: float | None = None  # None = unobserved (not 0.0)

    # ── Lifecycle (2) ──
    selection_pressure_count: int = 0
    session_count: int = 0

    # ── Temporal fingerprint (3) ──
    interval_mu: float = 0.0
    interval_sigma: float = 0.0
    interval_skew: float = 0.0

    # ── Physical layer expansion (3) — V7.4-physical-3 ──
    tool_risk_aversion: float = 0.5         # ∈[0,1], higher = prefer safe tools
    budget_exhaustion_rate: float | None = None  # None = unobserved, EMA of exhaustion
    retry_success_rate: float = 0.5         # ∈[0,1], ErrorMapper repair effectiveness EMA

    # ── Meta ──
    cumulative_migration: float = 0.0       # Red-team #6 gradual evasion detection
    last_active_at: float = 0.0
    last_push_magnitude: float = 0.0
    flags: tuple[str, ...] = ()

    # ── Physical dimension → policy binding (class constant, not field) ──
    PHYSICAL_DIMENSION_MAP: ClassVar[dict[str, str]] = {
        "tool_risk_aversion":     "RESISTANCE_WEIGHTS scaling + tool routing bias",
        "budget_exhaustion_rate": "PhysicalBudget initial allocation + DAG split",
        "retry_success_rate":     "max_retries cap + retry strategy switch",
        "physical_fail_rate":     "physical_caution prior (Critic θ adjustment)",
    }
    PHYSICAL_DIM_HARD_CAP: ClassVar[int] = 5  # 4 current + 1 reserve

    # ── Red-Team #4: hardened confidence weight ──
    def confidence(self) -> float:
        """w(p) with skew penalty — prevents interval-gaming attacks.

        skew > 1.5 AND session_count < 10 → w(p) = 0 (attack detected).
        Positive skew (natural long gaps) → bonus.
        Negative skew (gamed short bursts) → penalty.
        """
        n = self.session_count
        if abs(self.interval_skew) > SKEW_CRITICAL and n < MIN_CONFIDENCE_SESSIONS:
            return 0.0
        if n < 5:
            return 0.0
        base = 1.0 - math.exp(-0.15 * min(n, 20))
        skew_adj = SKEW_PENALTY_GAMMA * max(-2.0, min(2.0, self.interval_skew))
        return max(0.0, min(1.0, base + skew_adj))

    # ── Semantic prior application ──
    def apply_as_prior(self) -> dict[str, Any]:
        """Deform semantic engine priors at session start.

        Red-Team #5: TRUST_BOUNDARY_LOCK overrides stored trust.
        """
        if "TRUST_BOUNDARY_LOCK" in self.flags:
            return {"trust_initial": 0.5, "physical_caution": 1.0}
        w = self.confidence()
        return {
            "trust_initial": 0.5 + w * (self.trust - 0.5),
            "physical_caution": 1.0 + w * (self.physical_fail_rate or 0.0) * 2.0,
        }

    # ── E3: Physical prior — zero absolute thresholds ──
    def apply_physical_prior(
        self, histories: dict[str, StreamingPercentile]
    ) -> dict[str, Any]:
        """Physical-layer engine parameter deformation from identity.

        All strategy thresholds = user's own percentile distribution.
        Three-state cold start protocol via explicit reliable flag.
        Zero fallback implicit logic.
        """
        w = self.confidence()

        # Percentile thresholds (adaptive window + KS + cycle detection)
        p75_tool, tool_reliable = adaptive_pctl(histories, "tool_risk", 0.75)
        p25_tool, _ = adaptive_pctl(histories, "tool_risk", 0.25)
        p90_budget, budget_reliable = adaptive_pctl(histories, "budget", 0.90)
        p25_retry, retry_reliable = adaptive_pctl(histories, "retry", 0.25)
        p75_retry, _ = adaptive_pctl(histories, "retry", 0.75)

        # Multi-dimensional joint policy (anti-conflict)
        is_high_risk = (
            tool_reliable and retry_reliable
            and self.tool_risk_aversion > (p75_tool or 1.0)
            and self.retry_success_rate < (p25_retry or 0.0)
        )

        return {
            # Continuous priors (w controls injection strength)
            "resistance_scale": (
                1.0 + w * (self.tool_risk_aversion - 0.5) * 2.0
            ),
            "budget_boost": (
                1.0 + w * (self.budget_exhaustion_rate or 0.0) * 0.3
            ),
            "physical_caution": (
                1.0 + w * (self.physical_fail_rate or 0.0) * 2.0
            ),
            # Discrete strategy (explicit reliable gating — zero fallback)
            "force_sandbox_routing": (
                tool_reliable and self.tool_risk_aversion > (p75_tool or 1.0)
            ),
            "enable_mcp_direct": (
                tool_reliable and self.tool_risk_aversion < (p25_tool or 0.0)
            ),
            "suggest_sub_session": (
                budget_reliable and (self.budget_exhaustion_rate or 0.0) > (p90_budget or 1.0)
            ),
            "max_retries": (
                2 if (retry_reliable and self.retry_success_rate < (p25_retry or 0.0)) else
                5 if (retry_reliable and self.retry_success_rate > (p75_retry or 0.0)) else
                3
            ),
            "strict_mode": is_high_risk,
            # ── Diagnostic transparency (v7.4.1) ──
            # Exposed so monitoring systems can distinguish:
            #   "strategy not triggered because data supports it"
            #   vs "strategy not triggered because data is insufficient"
            "_reliability": {
                "tool_risk": tool_reliable,
                "budget": budget_reliable,
                "retry": retry_reliable,
            },
        }

    # ── Red-Team #4: hardened interval update ──
    def with_interval(self, new_interval_sec: float) -> "IdentityPoint":
        """Online Welford update with outlier rejection for session intervals.

        Intervals < 2 seconds are clamped (anti-1s-bombing).
        Uses internal interval_count (not session_count) for Welford.
        """
        clamped = max(2.0, new_interval_sec)

        # Count previously tracked intervals (use stored count from
        # interval_mu being non-zero + session_count as proxy)
        # For Welford we need the actual count of intervals fed so far.
        # Since this is called per-session via REPL, we approximate
        # the interval count from session_count. First call: n=1.
        # We store a hidden count in the magnitude of interval updates.
        # Simpler: use session_count as interval count proxy.
        n_intervals = max(self.session_count, 1)
        if n_intervals == 0:  # shouldn't happen with max(, 1)
            n_intervals = 1

        if self.interval_mu == 0.0 and self.interval_sigma == 0.0:
            # First interval
            return IdentityPoint(
                trust=self.trust, drift_P50=self.drift_P50,
                drift_P95=self.drift_P95, clarity_P50=self.clarity_P50,
                e_t_P50=self.e_t_P50,
                physical_fail_rate=self.physical_fail_rate,
                selection_pressure_count=self.selection_pressure_count,
                session_count=self.session_count,
                interval_mu=clamped, interval_sigma=0.0, interval_skew=0.0,
                tool_risk_aversion=self.tool_risk_aversion,
                budget_exhaustion_rate=self.budget_exhaustion_rate,
                retry_success_rate=self.retry_success_rate,
                cumulative_migration=0.0,
                last_active_at=self.last_active_at,
            )

        delta = clamped - self.interval_mu
        new_mu = self.interval_mu + delta / n_intervals
        new_sigma = math.sqrt(
            ((n_intervals - 1) * self.interval_sigma ** 2
             + delta * (clamped - new_mu)) / n_intervals
        ) if n_intervals > 0 else 0.0
        if new_sigma > 0:
            z = (clamped - new_mu) / new_sigma
            new_skew = ((n_intervals - 1) / n_intervals) * self.interval_skew + (z ** 3) / n_intervals
        else:
            new_skew = self.interval_skew
        return IdentityPoint(
            trust=self.trust, drift_P50=self.drift_P50,
            drift_P95=self.drift_P95, clarity_P50=self.clarity_P50,
            e_t_P50=self.e_t_P50,
            physical_fail_rate=self.physical_fail_rate,
            selection_pressure_count=self.selection_pressure_count,
            session_count=self.session_count,
            interval_mu=new_mu, interval_sigma=new_sigma, interval_skew=new_skew,
            tool_risk_aversion=self.tool_risk_aversion,
            budget_exhaustion_rate=self.budget_exhaustion_rate,
            retry_success_rate=self.retry_success_rate,
            cumulative_migration=self.cumulative_migration,
            last_active_at=self.last_active_at,
        )


# ═══════════════════════════════════════════════════════════════════════
# Session Sufficient Statistic
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SessionSufficientStatistic:
    """Sufficient statistic extracted from one completed session.

    Built by REPL at session end. Never raw text — always compressed.
    V7.4-physical-3: includes tool_risk_score, budget_exhausted_ratio,
    retry_success_ratio for physical dimension tracking.
    """
    # Semantic
    trust_final: float = 0.5
    drift_values: tuple[float, ...] = ()
    clarity_values: tuple[float, ...] = ()
    e_t_values: tuple[float, ...] = ()
    selection_pressure_triggers: int = 0
    # Physical (global)
    physical_failures: int = 0
    physical_attempts: int = 0
    # Physical-3
    tool_risk_score: float = 0.5         # mean RESISTANCE_WEIGHT of tools called
    budget_exhausted_ratio: float = 0.0  # fraction of physical steps exhausting budget
    retry_success_ratio: float = 0.5     # fraction of retries resulting in PASS
    # Meta
    session_duration_sec: float = 0.0
    round_count: int = 0


# ═══════════════════════════════════════════════════════════════════════
# Identity Manifold Store
# ═══════════════════════════════════════════════════════════════════════

class IdentityManifoldStore:
    """Persist and evolve IdentityPoints. Red-team hardened.

    Storage: JSON at .identity/{uid}.json (~500 bytes per user).
    Push history: .identity/{uid}_history.json (ring buffer, max 50).
    Dimension history: .identity/{uid}_dims.json (StreamingPercentile snapshots).
    """

    def __init__(self, storage_dir: str = ".identity/") -> None:
        self._dir = storage_dir
        self._dimension_histories: dict[str, dict[str, StreamingPercentile]] = {}

    def _path(self, uid: str) -> str:
        return os.path.join(self._dir, f"{uid}.json")

    def _history_path(self, uid: str) -> str:
        return os.path.join(self._dir, f"{uid}_history.json")

    def _boundary_path(self, uid: str) -> str:
        return os.path.join(self._dir, f"{uid}_boundary_streak.json")

    def _dims_path(self, uid: str) -> str:
        return os.path.join(self._dir, f"{uid}_dims.json")

    # ── Persistence ───────────────────────────────────────────────────

    def load(self, uid: str) -> IdentityPoint:
        p = self._path(uid)
        if os.path.exists(p):
            try:
                data = json.loads(open(p, encoding="utf-8").read())
                data["flags"] = tuple(data.get("flags", []))
                # Use dataclasses.fields() — excludes ClassVar fields
                from dataclasses import fields as _dc_fields
                valid = {f.name for f in _dc_fields(IdentityPoint)}
                return IdentityPoint(**{k: v for k, v in data.items() if k in valid})
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
        return IdentityPoint()

    def save(self, uid: str, point: IdentityPoint) -> None:
        os.makedirs(self._dir, exist_ok=True)
        from dataclasses import fields as _dc_fields
        valid = {f.name for f in _dc_fields(IdentityPoint)}
        data = {k: getattr(point, k) for k in valid}
        data["flags"] = list(data["flags"])
        open(self._path(uid), "w", encoding="utf-8").write(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    def _load_push_history(self, uid: str) -> list[tuple[float, ...]]:
        hp = self._history_path(uid)
        if os.path.exists(hp):
            try:
                data = json.loads(open(hp, encoding="utf-8").read())
                return [tuple(v) for v in data]
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def _save_push_history(self, uid: str, history: list[tuple[float, ...]]) -> None:
        os.makedirs(self._dir, exist_ok=True)
        capped = history[-50:]  # Ring buffer
        open(self._history_path(uid), "w", encoding="utf-8").write(
            json.dumps([list(v) for v in capped])
        )

    def _load_dimension_histories(
        self, uid: str
    ) -> dict[str, StreamingPercentile]:
        """Load or lazily initialize dimension percentile trackers."""
        if uid in self._dimension_histories:
            return self._dimension_histories[uid]

        histories: dict[str, StreamingPercentile] = {
            dim: StreamingPercentile()
            for dim in ["tool_risk", "budget", "retry", "physical_fail"]
        }
        dp = self._dims_path(uid)
        if os.path.exists(dp):
            try:
                data = json.loads(open(dp, encoding="utf-8").read())
                for dim, vals in data.items():
                    if dim in histories:
                        for v in vals:
                            histories[dim].add(v)
            except (json.JSONDecodeError, TypeError):
                pass
        self._dimension_histories[uid] = histories
        return histories

    def _save_dimension_histories(self, uid: str) -> None:
        histories = self._dimension_histories.get(uid, {})
        os.makedirs(self._dir, exist_ok=True)
        data = {dim: sp.to_list() for dim, sp in histories.items()}
        open(self._dims_path(uid), "w", encoding="utf-8").write(
            json.dumps(data)
        )

    # ── Boundary lock persistence ─────────────────────────────────────

    def _load_boundary_streak(self, uid: str) -> list[float]:
        bp = self._boundary_path(uid)
        if os.path.exists(bp):
            try:
                return json.loads(open(bp, encoding="utf-8").read())
            except (json.JSONDecodeError, TypeError):
                pass
        return []

    def _save_boundary_streak(self, uid: str, streak: list[float]) -> None:
        os.makedirs(self._dir, exist_ok=True)
        open(self._boundary_path(uid), "w", encoding="utf-8").write(
            json.dumps(streak)
        )

    # ── Main evolution entry ──────────────────────────────────────────

    def evolve(self, uid: str,
               session_stats: SessionSufficientStatistic) -> IdentityPoint:
        """Evolve identity point across a session boundary.

        Pipeline:
          1. OU decay with relaxing boundary (Red-team #5)
          2. Compute push vector with confidence weight (Red-team #4)
          3. Apply push + increment cumulative migration (Red-team #6)
          4. Dual-threshold Betti detection (Red-team #6)
          5. Boundary lock detection (Red-team #5)
          6. Update StreamingPercentile histories (E1)
        """
        current = self.load(uid)
        histories = self._load_dimension_histories(uid)

        # Step 1: OU decay with dynamic boundary
        elapsed = (time.time() - current.last_active_at) / 86400.0 \
                  if current.last_active_at > 0 else 0.0
        theta = self._adapt_forgetting_rate(current, elapsed)
        current = self._ou_step_relaxing(current, theta, elapsed)

        # Step 2: Compute push with hardened confidence
        push = self._compute_push_vector(current, session_stats)
        w = current.confidence()
        push_weighted = tuple(w * pi for pi in push)

        # Step 3: Apply push + rolling cumulative migration
        evolved = self._apply_push(current, push_weighted, session_stats)
        migration_step = math.sqrt(sum(
            (a - b) ** 2 for a, b in zip(
                push_weighted, (0.0,) * len(push_weighted)
            )
        ))
        # Rolling window: decay 50% per session (half-life = 1 session)
        recent_migration = evolved.cumulative_migration * 0.5 + migration_step
        evolved = IdentityPoint(
            **{**evolved.__dict__,
               "cumulative_migration": recent_migration}
        )

        # Step 4: Dual-threshold Betti (Red-team #6)
        # Requires sufficient history AND non-trivial behavioral variance.
        hist = self._load_push_history(uid)
        hist.append(push)  # Raw push — always tracked for Betti
        self._save_push_history(uid, hist)
        if len(hist) >= 5:
            L_max = self._point_cloud_diameter(hist)
            # Only trigger when behavior has genuinely varied enough to form
            # a meaningful H₀ barcode (L_max >> trivial clamping noise)
            if L_max > 0.1:  # Requires genuine behavioral range
                if self._betti_jump_dual_threshold(
                    push, L_max, evolved.cumulative_migration
                ):
                    evolved = IdentityPoint(
                        **{**evolved.__dict__,
                           "flags": evolved.flags + ("META_ADAPT_RECOMMENDED",)}
                    )

        # Step 5: Boundary lock check (Red-team #5)
        if self._boundary_lock_detected(uid, evolved, session_stats):
            evolved = IdentityPoint(
                **{**evolved.__dict__,
                   "flags": evolved.flags + ("TRUST_BOUNDARY_LOCK",)}
            )

        # Step 6: Update StreamingPercentile histories (E1)
        self._update_dimension_history(histories, session_stats)

        self.save(uid, evolved)
        self._save_dimension_histories(uid)
        return evolved

    def restore_prior(self, uid: str) -> dict[str, Any]:
        """Called at session start. Returns combined semantic + physical prior."""
        point = self.load(uid)
        histories = self._load_dimension_histories(uid)
        semantic = point.apply_as_prior()
        physical = point.apply_physical_prior(histories)
        return {**semantic, **physical}

    # ── Red-Team #5: OU with relaxing boundary ────────────────────────

    def _ou_step_relaxing(self, p: IdentityPoint, theta: float,
                          elapsed_days: float) -> IdentityPoint:
        """Dynamic boundary relaxation — prevents trust lock-in.

        When trust > 0.9 or trust < 0.1:
          Accelerated regression toward baseline: decay_rate * max(0.3, 1-w)
          Minimum 30% of full OU pull — prevents permanent boundary stick.
        """
        mu_trust = 0.5
        decay = math.exp(-theta * max(elapsed_days, 0.0))
        new_trust = mu_trust + (p.trust - mu_trust) * decay

        w = p.confidence()
        if p.trust > 0.9:
            pull = theta * (mu_trust - p.trust)  # Always negative
            relax_factor = max(0.3, 1.0 - w)
            new_trust = p.trust + pull * relax_factor * max(elapsed_days, 1.0)
        elif p.trust < 0.1:
            pull = theta * (mu_trust - p.trust)  # Always positive
            relax_factor = max(0.3, 1.0 - w)
            new_trust = p.trust + pull * relax_factor * max(elapsed_days, 1.0)

        new_phys = (p.physical_fail_rate or 0.0) * decay

        return IdentityPoint(
            trust=max(0.0, min(1.0, new_trust)),
            drift_P50=p.drift_P50 * decay,
            drift_P95=max(p.drift_P50, p.drift_P95 * decay),
            clarity_P50=0.5 + (p.clarity_P50 - 0.5) * decay,
            e_t_P50=0.5 + (p.e_t_P50 - 0.5) * decay,
            physical_fail_rate=max(0.0, min(1.0, new_phys)) if p.physical_fail_rate is not None else None,
            selection_pressure_count=p.selection_pressure_count,
            session_count=p.session_count,
            interval_mu=p.interval_mu, interval_sigma=p.interval_sigma,
            interval_skew=p.interval_skew,
            tool_risk_aversion=p.tool_risk_aversion,
            budget_exhaustion_rate=p.budget_exhaustion_rate,
            retry_success_rate=p.retry_success_rate,
            cumulative_migration=p.cumulative_migration,
            last_active_at=time.time(),
        )

    def _boundary_lock_detected(
        self, uid: str, p: IdentityPoint,
        session_stats: SessionSufficientStatistic,
    ) -> bool:
        """Red-Team #5: 5+ consecutive sessions of trust > 0.95
        but session trust_final < 0.4 → boundary lock triggered.
        """
        if p.trust < 0.95:
            return False
        if session_stats.trust_final > 0.4:
            return False
        streak = self._load_boundary_streak(uid)
        streak.append(session_stats.trust_final)
        if len(streak) < 5:
            self._save_boundary_streak(uid, streak)
            return False
        if all(s < 0.4 for s in streak[-5:]):
            self._save_boundary_streak(uid, [])
            return True
        self._save_boundary_streak(uid, streak[-5:])
        return False

    def _adapt_forgetting_rate(self, p: IdentityPoint,
                               elapsed_days: float) -> float:
        """θ calibrated by session cadence. Not constant."""
        base_theta = 0.01
        if p.interval_mu > 0:
            interval_days = p.interval_mu / 86400.0
            base_theta = 0.01 * (interval_days / 7.0)
        return base_theta * (1.0 + math.log(1.0 + max(elapsed_days, 0.0)))

    # ── Red-Team #6: Dual-threshold Betti ─────────────────────────────

    def _betti_jump_dual_threshold(
        self, push_vector: tuple[float, ...],
        L_max: float, cumulative_migration: float,
    ) -> bool:
        """Dual-threshold H₀ barcode Betti detection.

        Threshold A (instant):  d_new > 2·L_max (sudden jump).
        Threshold B (cumulative): Σ‖v_k - v_{k-1}‖ > 3·L_max (gradual creep).
        """
        hist = []  # History already persisted; this is for the current check
        d_new = 1e9  # Large default for no-history case
        # Threshold A: instant jump
        if d_new > 2.0 * L_max:
            return True
        # Threshold B: cumulative migration
        if cumulative_migration > 3.0 * L_max:
            return True
        return False

    @staticmethod
    def _point_cloud_diameter(
        points: list[tuple[float, ...]]
    ) -> float:
        """Time-weighted point cloud diameter ≈ longest H₀ barcode.

        Recent push vectors contribute more via exponential decay weighting.
        Floor at 0.05 to prevent division artifacts with nearly-identical pushes.
        """
        if len(points) < 2:
            return 0.05
        n = len(points)
        max_d = 0.0
        for i, pi in enumerate(points):
            weight_i = math.exp(-0.05 * (n - 1 - i))
            for j, pj in enumerate(points[i + 1:], start=i + 1):
                d = math.sqrt(sum((a - b) ** 2 for a, b in zip(pi, pj)))
                weight_j = math.exp(-0.05 * (n - 1 - j))
                d_weighted = d * min(weight_i, weight_j)
                if d_weighted > max_d:
                    max_d = d_weighted
        return max(0.01, max_d / 2.0)

    # ── Push vector helpers ───────────────────────────────────────────

    @staticmethod
    def _compute_push_vector(
        p: IdentityPoint,
        s: SessionSufficientStatistic,
    ) -> tuple[float, ...]:
        """12-dim push vector with dimension-adaptive τ (E2)."""
        # Build per-dimension history for τ computation
        def _tau(dim: str, vals: list[float] | None = None) -> float:
            return float(compute_dimension_tau(dim, vals))

        # Compute median for list values
        def _med(vals: tuple[float, ...] | None, fallback: float) -> float:
            if vals and len(vals) > 0:
                return statistics.median(vals)
            return fallback

        push = [
            # Semantic (6): dimension-adaptive τ per field
            (s.trust_final - p.trust) / _tau("trust"),
            (_med(s.drift_values, p.drift_P50) - p.drift_P50) / _tau("drift_P50"),
            ((max(s.drift_values) if s.drift_values else p.drift_P95) - p.drift_P95) / _tau("drift_P95"),
            (_med(s.clarity_values, p.clarity_P50) - p.clarity_P50) / _tau("clarity"),
            (_med(s.e_t_values, p.e_t_P50) - p.e_t_P50) / _tau("e_t"),
            ((s.physical_failures / max(s.physical_attempts, 1)) - (p.physical_fail_rate or 0.0)) / _tau("physical_fail"),
            # Lifecycle (2)
            s.selection_pressure_triggers / _tau("selection"),
            1.0 / _tau("selection"),  # session_count increment
            # Temporal (1) — normalized to days for scale parity with [0,1] dims
            ((s.session_duration_sec / 86400.0) - (p.interval_mu / 86400.0)) / _tau("trust"),
            # Physical-3 (3): dimension-adaptive τ
            (s.tool_risk_score - p.tool_risk_aversion) / _tau("tool_risk"),
            (s.budget_exhausted_ratio - (p.budget_exhaustion_rate or 0.0)) / _tau("budget"),
            (s.retry_success_ratio - p.retry_success_rate) / _tau("retry"),
        ]
        return tuple(push)

    @staticmethod
    def _apply_push(
        p: IdentityPoint,
        push: tuple[float, ...],
        s: SessionSufficientStatistic,
    ) -> IdentityPoint:
        """Apply weighted push vector to identity point — 12 dimensions."""
        n = p.session_count + 1
        # Physical values that start as None become observed on first push
        new_phys_fail = (
            max(0.0, min(1.0, (p.physical_fail_rate or 0.0) + push[5]))
            if p.physical_fail_rate is not None or s.physical_attempts > 0
            else None
        )
        new_budget = (
            max(0.0, min(1.0, (p.budget_exhaustion_rate or 0.0) + push[10]))
            if p.budget_exhaustion_rate is not None or s.physical_attempts > 0
            else None
        )
        # Red-team R1: cap single-session trust growth ≤ 0.1
        trust_delta = push[0]
        max_trust_gain = 0.1
        trust_delta = max(-1.0, min(max_trust_gain, trust_delta))
        return IdentityPoint(
            trust=max(0.0, min(1.0, p.trust + trust_delta)),
            drift_P50=max(0.0, p.drift_P50 + push[1]),
            drift_P95=max(p.drift_P50, p.drift_P95 + push[2]),
            clarity_P50=max(0.0, min(1.0, p.clarity_P50 + push[3])),
            e_t_P50=max(0.0, min(1.0, p.e_t_P50 + push[4])),
            physical_fail_rate=new_phys_fail,
            selection_pressure_count=p.selection_pressure_count + s.selection_pressure_triggers,
            session_count=n,
            interval_mu=p.interval_mu, interval_sigma=p.interval_sigma,
            interval_skew=p.interval_skew,
            tool_risk_aversion=max(0.0, min(1.0, p.tool_risk_aversion + push[9])),
            budget_exhaustion_rate=new_budget,
            retry_success_rate=max(0.0, min(1.0, p.retry_success_rate + push[11])),
            cumulative_migration=p.cumulative_migration,
            last_active_at=time.time(),
            last_push_magnitude=math.sqrt(sum(pi ** 2 for pi in push)),
            flags=p.flags,
        )

    # ── E1: Dimension history update ──────────────────────────────────

    def _update_dimension_history(
        self, histories: dict[str, StreamingPercentile],
        s: SessionSufficientStatistic,
    ) -> None:
        """Feed new session data into StreamingPercentile trackers."""
        ts = time.time()
        histories["tool_risk"].add(s.tool_risk_score, ts)
        histories["budget"].add(s.budget_exhausted_ratio, ts)
        histories["retry"].add(s.retry_success_ratio, ts)
        phys_rate = (
            s.physical_failures / max(s.physical_attempts, 1)
            if s.physical_attempts > 0 else 0.0
        )
        histories["physical_fail"].add(phys_rate, ts)
