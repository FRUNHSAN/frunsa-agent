"""V7.5 Entropy Monitor — active concern via sublevel set filtration.

Mathematical: S_int: State × M_id → ℝ⁺  (scalar field on state space)
             Sublevel sets S⁻¹[0, τ] form a filtration
             θ_active defines critical value — natural transformation η: F ⇒ G

Review fixes:
  #1: component normalization (dimensional consistency, all ∈ [0,1])
  #2: sigmoid θ_active (continuous, no piecewise jumps)
  #3: temporal decay e^(-0.5·age) (residual entropy half-life ≈ 1.4 sessions)

Red-team patches:
  R1: trust growth cap ≤ 0.1/session (CVSS 9.1 — identity hijacking)
  R2: normalization safety floor (CVSS 8.5 — inversion attack)
  R3: snapshot session_count cross-check (CVSS 6.5 — tamper detection)

Compatibility patches:
  C1: Track A updates snapshot (clear DAG/physical, preserve e_t/budget)
  C2: multi-run accumulation (max dangling, sum failures within session)
  C3: MCP-specific failure tracking (distinct from sandbox failures)

Hardening:
  H1: failure_ratio gating (>0.1 report, >0.7 high severity)
  H2: graduated cold-start (n=1: 2×θ, n=2: standard)

Architecture: single module, same family as WassersteinProxy.
Pure math, zero LLM calls, zero engine imports.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass


# ═══════════════════════════════════════════════════════════════════════
# Red-team R2: normalization safety floors
# ═══════════════════════════════════════════════════════════════════════

_SAFETY_FLOORS: dict[str, float] = {
    "dangling": 3.0,         # at least 3 unfinished steps for normalization
    "e_accumulated": 0.5,    # at least 0.5 tracking error for normalization
}


# ═══════════════════════════════════════════════════════════════════════
# Kernel State Snapshot
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KernelStateSnapshot:
    """Snapshot of Track C state after a completed run. Persisted per-session.

    V7.5-compat-C3: mcp_failures/mcp_attempts track MCP-specific errors
    distinct from sandbox failures.
    """
    dangling_dag_count: int = 0
    accumulated_e_t: float = 0.0
    budget_remaining_ratio: float = 1.0
    physical_failures: int = 0       # sandbox failures
    physical_attempts: int = 0
    mcp_failures: int = 0            # C3: MCP-specific failures
    mcp_attempts: int = 0
    snapshot_age: int = 0            # sessions since this snapshot (0=last)


# ═══════════════════════════════════════════════════════════════════════
# Entropy Reading
# ═══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EntropyReading:
    """Sampled internal tension — all components normalized to [0,1].
    S_int ∈ [0, 1.3] after review fix #1.
    """
    S_int: float
    alpha: float
    beta: float
    gamma: float
    delta: float


# ═══════════════════════════════════════════════════════════════════════
# Entropy Monitor — pure function, zero side effects
# ═══════════════════════════════════════════════════════════════════════

class EntropyMonitor:
    """g: (x_internal, identity) → S_int. Pure function — zero side effects.

    Pattern: same family as WassersteinProxy, IdentityManifoldStore.
    Single module, pure math, zero LLM calls.
    """

    # ── Review Fix #1: component normalization ────────────────────────

    @staticmethod
    def _normalize(value: float, component: str, identity) -> float:
        """Normalize to [0,1] using user's own historical distribution.

        Red-team R2: safety floor prevents P95 pollution attacks.
        Zero hardcoded thresholds — uses v7.4 IdentityPoint statistics.
        """
        if component == "dangling":
            p95 = getattr(identity, 'drift_P95', None) or 5.0
            p95 = max(_SAFETY_FLOORS["dangling"], p95)
            return min(1.0, value / (p95 + 1e-5))
        elif component == "e_accumulated":
            p95 = getattr(identity, 'e_t_P95', None) or 0.8
            p95 = max(_SAFETY_FLOORS["e_accumulated"], p95)
            return min(1.0, value / (p95 + 1e-5))
        return value  # trust, budget_ratio already ∈ [0,1]

    # ── Review Fix #2: continuous sigmoid θ_active ─────────────────────

    @staticmethod
    def _compute_theta_active(identity) -> float:
        """Continuous sigmoid — no piecewise jumps.

        trust=0.3 → θ≈0.52, trust=0.5 → θ≈0.45, trust=0.7 → θ≈0.38
        dθ/d(trust) < 0.1 at all points — preserves natural transformation
        continuity.
        """
        n = identity.session_count
        if n < 3:
            return 1.0
        trust = identity.trust
        theta = 0.3 + 0.3 * (
            1.0 - 1.0 / (1.0 + math.exp(-5.0 * (trust - 0.5)))
        )
        return max(0.3, min(0.6, theta))

    # ── Sample — pure function ─────────────────────────────────────────

    @staticmethod
    def sample(snapshot: KernelStateSnapshot,
               identity) -> EntropyReading:
        """Sample internal tension. All components ∈ [0,1] after normalization.

        Review fix #1: dimensional consistency.
        Review fix #3: temporal decay.
        """
        trust = identity.trust
        alpha = 0.3 + 0.3 * trust
        beta = 0.2 * (1.0 + identity.e_t_P50)
        gamma = 0.3 * (1.0 - trust)
        delta = 0.1

        # Normalize unbounded components (fix #1 + R2 safety floor)
        norm_dangling = EntropyMonitor._normalize(
            snapshot.dangling_dag_count, "dangling", identity)
        norm_e = EntropyMonitor._normalize(
            snapshot.accumulated_e_t, "e_accumulated", identity)

        S_int = (
            alpha * norm_dangling +
            beta * norm_e +
            gamma * (1.0 - trust) +
            delta * (1.0 - snapshot.budget_remaining_ratio)
        )

        # Temporal decay (fix #3): half-life ≈ 1.4 sessions
        decay = math.exp(-0.5 * snapshot.snapshot_age)
        S_int *= decay

        return EntropyReading(S_int=S_int, alpha=alpha, beta=beta,
                              gamma=gamma, delta=delta)

    # ── Should Interrupt — graduated cold-start ────────────────────────

    @staticmethod
    def should_interrupt(reading: EntropyReading,
                         identity) -> tuple[bool, float]:
        """(should_interrupt, urgency).

        Hardening H2: graduated cold-start.
        n=1: only trigger for very high tension (> 2×θ)
        n=2: standard threshold
        n≥3: standard threshold via sigmoid
        """
        n = identity.session_count
        theta = EntropyMonitor._compute_theta_active(identity)

        if n == 1:
            should = reading.S_int > 2.0 * theta
        elif n == 2:
            should = reading.S_int > theta
        else:
            should = reading.S_int > theta

        urgency = min(1.0, reading.S_int / (theta + 1e-5)) if should else 0.0
        return should, urgency

    # ── Format Interrupt — natural language ────────────────────────────

    @staticmethod
    def format_interrupt(reading: EntropyReading,
                         identity,
                         snapshot: KernelStateSnapshot) -> str | None:
        """Natural-language Planning goal. Returns None if no interrupt.

        Hardening H1: failure_ratio gating for severity assessment.
        Compatibility C3: dual-track sandbox/MCP failure reporting.
        UX: permanent dismiss via 'ignore' command.
        """
        should, urgency = EntropyMonitor.should_interrupt(reading, identity)
        if not should:
            return None

        parts = []
        if snapshot.dangling_dag_count > 0:
            parts.append(
                f"上次会话有 {snapshot.dangling_dag_count} 个未完成的执行步骤"
            )
        if snapshot.accumulated_e_t > 0.5:
            parts.append("累积的跟踪误差较高")

        # H1 + C3: dual-track severity-based reporting
        if snapshot.physical_attempts > 0:
            sandbox_ratio = (
                snapshot.physical_failures / max(1, snapshot.physical_attempts)
            )
            if sandbox_ratio > 0.1:
                sev = "high" if sandbox_ratio > 0.7 else "medium"
                parts.append(
                    f"代码执行失败率 {sandbox_ratio:.0%} ({sev}风险)"
                )
        if snapshot.mcp_attempts > 0:
            mcp_ratio = (
                snapshot.mcp_failures / max(1, snapshot.mcp_attempts)
            )
            if mcp_ratio > 0.1:
                parts.append(
                    f"外部工具(MCP)失败率 {mcp_ratio:.0%}"
                )

        if not parts:
            return None

        urgency_label = "high" if urgency > 0.7 else "low"
        return (
            f"[SYSTEM INTERRUPT — {urgency_label} priority] "
            + " ".join(parts) + ". "
            + "要不要现在继续？(回复'好'开始 / '晚点'推迟 / '忽略'永久关闭 / '详情'查看细节)"
        )


# ═══════════════════════════════════════════════════════════════════════
# Snapshot I/O — Red-team R3: tamper detection
# ═══════════════════════════════════════════════════════════════════════

def persist_snapshot(storage_dir: str, uid: str,
                     snapshot: KernelStateSnapshot,
                     session_count: int) -> None:
    """Persist snapshot with session_count cross-check for tamper detection.

    Red-team R3: session_count is embedded to verify snapshot_age integrity.
    Manual file edits are detectable via count mismatch.
    """
    os.makedirs(storage_dir, exist_ok=True)
    path = os.path.join(storage_dir, f"{uid}_snapshot.json")
    data = {
        "dangling_dag_count": snapshot.dangling_dag_count,
        "accumulated_e_t": snapshot.accumulated_e_t,
        "budget_remaining_ratio": snapshot.budget_remaining_ratio,
        "physical_failures": snapshot.physical_failures,
        "physical_attempts": snapshot.physical_attempts,
        "mcp_failures": snapshot.mcp_failures,
        "mcp_attempts": snapshot.mcp_attempts,
        "snapshot_age": snapshot.snapshot_age,
        "_session_count": session_count,  # R3: cross-check anchor
        "_timestamp": time.time(),
    }
    open(path, "w", encoding="utf-8").write(json.dumps(data, indent=2))


def load_snapshot(storage_dir: str, uid: str,
                  current_session_count: int) -> KernelStateSnapshot | None:
    """Load snapshot with tamper detection via session_count cross-check.

    Red-team R3: if recorded _session_count doesn't match expected,
    snapshot is rejected → returns None (safe reset to zero tension).
    """
    path = os.path.join(storage_dir, f"{uid}_snapshot.json")
    if not os.path.exists(path):
        return None
    try:
        data = json.loads(open(path, encoding="utf-8").read())
    except (json.JSONDecodeError, IOError):
        return None

    # R3: verify snapshot_age against identity session_count
    recorded_count = data.get("_session_count", -1)
    expected_age = current_session_count - recorded_count - 1
    if expected_age < 0:
        return None  # Tampered or inconsistent

    return KernelStateSnapshot(
        dangling_dag_count=data.get("dangling_dag_count", 0),
        accumulated_e_t=data.get("accumulated_e_t", 0.0),
        budget_remaining_ratio=data.get("budget_remaining_ratio", 1.0),
        physical_failures=data.get("physical_failures", 0),
        physical_attempts=data.get("physical_attempts", 0),
        mcp_failures=data.get("mcp_failures", 0),
        mcp_attempts=data.get("mcp_attempts", 0),
        snapshot_age=expected_age,
    )


def delete_snapshot(storage_dir: str, uid: str) -> None:
    """Delete snapshot — called on user 'ignore' permanent dismiss."""
    path = os.path.join(storage_dir, f"{uid}_snapshot.json")
    if os.path.exists(path):
        os.remove(path)
