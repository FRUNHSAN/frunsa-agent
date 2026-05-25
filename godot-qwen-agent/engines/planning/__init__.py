"""Planning engine: step-by-step reasoning with hierarchical trace context.

Phase 10: Minimal stub implementation for adapter contract validation.
Phase 11+: Real LLM-backed planning with tool orchestration.
Phase 15: Agent identity, PlanningContext, and parallel branch dispatch.
Phase 17: LLMPlanningEngine — first real LLM-backed engine. MockLLMBackend
    for deterministic CI testing.
"""

from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext, PlanningEngine, PlanningStep
from engines.planning.llm import LLMPlanningEngine, MockLLMBackend

__all__ = [
    "AgentIdentity", "PlanningContext", "PlanningEngine", "PlanningStep",
    "LLMPlanningEngine", "MockLLMBackend",
]
