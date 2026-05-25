"""Orchestration engine configuration — Phase 16.

FailureInjectionConfig: deterministic fault injection for retry validation.
OrchestrationConfig: optional constructor parameter for StubOrchestrationEngine.

No config = Phase 15 behavior unchanged (backward compatible).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class FailureInjectionConfig:
    """Describes which items should fail, and on which attempts.

    Deterministic: same config → same output. No random failure rates.

    Attributes:
        fail_on_attempts: (chunk_id, attempt_number) pairs that fail.
            The chunk succeeds on the NEXT attempt after the specified one.
            Example: (("c003", 1),) → c003 fails on attempt 1, succeeds on 2.
        exhaust_retries: chunk_ids that fail on ALL attempts (1, 2, 3),
            producing an error terminal StreamItem.
            Example: ("c005",) → c005 never succeeds.
    """

    fail_on_attempts: tuple[tuple[str, int], ...] = ()
    exhaust_retries: tuple[str, ...] = ()


@dataclass(frozen=True)
class OrchestrationConfig:
    """Optional configuration for StubOrchestrationEngine.

    Attributes:
        failure_injection: If set, the stub simulates failures per the config.
            None = all branches always succeed (Phase 15 behavior).
        resource_pools: branch_name → pool_key mapping for multi-pool routing.
            None or missing branch = "default" pool.
            Example: {"fast_path": "cpu", "full_rerank": "gpu"}
    """

    failure_injection: FailureInjectionConfig | None = None
    resource_pools: Mapping[str, str] | None = None

    def __post_init__(self):
        if self.resource_pools is not None and not isinstance(self.resource_pools, MappingProxyType):
            object.__setattr__(self, "resource_pools", MappingProxyType(dict(self.resource_pools)))
