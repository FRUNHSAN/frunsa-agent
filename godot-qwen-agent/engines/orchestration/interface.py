"""Orchestration engine contract: data model and engine protocol.

Phase 18 defines the SHAPE of an Orchestration engine — zero implementation.
OrchestrationContext bundles branch specs, agent identity, merge strategy,
and retry parameters. metadata slot follows Principle 3 (extension slot).

Protocol signature uniformity: async def orchestrate(context, deadline, pace_config)
-> AsyncIterator[StreamItem] — same shape as PlanningEngine.plan().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, Mapping, Protocol

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.orchestration.identity import OrchestratorIdentity


@dataclass(frozen=True)
class BranchSpec:
    """A single branch in the orchestration DAG.

    Fields:
        name: Branch identifier (e.g. "fast_path", "full_rerank").
        pool: Resource pool key for capacity routing (e.g. "cpu", "gpu").
        items: Expected number of items from this branch.
    """

    name: str
    pool: str = "default"
    items: int = 0


@dataclass(frozen=True)
class OrchestrationContext:
    """Input context for the Orchestration engine.

    Bundles branch specifications, agent identity, merge strategy,
    retry parameters, and resource pool routing.

    Principle 3: metadata is an opaque extension slot — not a trace key,
    not guardrail-enforced. Engine developers instrument it with debug
    info (routing decisions, timing, fallback reasons) without touching
    the core contract surface.

    Fields:
        branches: Branch specs describing parallel execution lanes.
        agent_identity: Orchestrator identity carrying id, role, version.
        merge_strategy: How to merge branch results ("sequential", "interleave").
        max_retries: Maximum retry attempts per branch item.
        resource_pools: branch_name -> pool_key mapping (None = all "default").
        metadata: Opaque extension slot (Principle 3).
    """

    branches: tuple[BranchSpec, ...]
    agent_identity: OrchestratorIdentity
    merge_strategy: str = "sequential"
    max_retries: int = 3
    parallel_depth: int = 1  # V6.1: max concurrent branches (1=serial)
    resource_pools: Mapping[str, str] | None = None
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

class OrchestrationEngine(Protocol):
    """Protocol that every Orchestration engine must implement.

    Produces an async stream of StreamItems, each carrying 6 orchestration.*
    trace_context keys + component pass-through keys + agent.identity.

    Consumers (planning engines) treat the stream as opaque — they augment
    items with planning keys without inspecting orchestration internals.

    Args:
        context: OrchestrationContext bundling branches, identity, merge
            strategy, retry params, and resource pools.
        deadline: Operation-level deadline in seconds (duration).
        pace_config: QoS parameters.

    Yields:
        StreamItem with trace_context containing:
        {
            "orchestration.dag_node_id": str,
            "orchestration.parallel_depth": int,
            "orchestration.merge_ordinal": int,
            "orchestration.branch_taken": str,
            "orchestration.retry_count": int,
            "orchestration.resource_pool_key": str,
            "agent.identity": dict,
            # + component pass-through keys
        }
    """

    async def orchestrate(
        self,
        context: OrchestrationContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        ...
