"""Orchestration engine — bridges component trace and orchestration trace.

Phase 14: stub only. The stub simulates N=2 parallel retrieval branches,
merges results, and emits StreamItems with both component-level trace keys
(consumed) and orchestration-level trace keys (produced).

Phase 16: OrchestrationConfig + FailureInjectionConfig for chaos injection
and multi-pool routing validation.
"""

from engines.orchestration.config import FailureInjectionConfig, OrchestrationConfig
from engines.orchestration.stub import StubOrchestrationEngine

__all__ = ["FailureInjectionConfig", "OrchestrationConfig", "StubOrchestrationEngine"]
