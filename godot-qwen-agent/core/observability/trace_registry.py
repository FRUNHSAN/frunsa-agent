"""Declarative trace key registry: engine-private dialect snapshot.

Phase 11: N=2 engine stubs only. NOT a cross-engine semantic standard.
Phase 14: orchestration engine keys added (N=3 engines).
ENGINE_TO_COMPONENT_MAP resolves engine-specific keys to canonical
component-level keys defined in the component platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class TraceKeyDef:
    """Declarative metadata for one trace_context key.

    Does NOT participate in runtime serialization. Serves as:
    1. Input to the trace_key_registration guardrail (WARNING on unregistered keys)
    2. Schema documentation for Phase 12+ observability sink designers
    3. Disambiguation table when two engines share the same suffix
    4. Design input for the component platform: component_candidate keys
       should be migrated to component-level trace contracts when the
       component platform is built (Phase 13+).
    """

    type: type
    semantics: str
    engine: str
    unit: str = ""
    component_candidate: bool = False
    # True = this key's semantics belong to a component capability
    # (retrieval, generation, scoring), not to the engine itself.
    # Phase 13: migrated to core/contracts/trace_keys.py.
    # See ENGINE_TO_COMPONENT_MAP for the engine→component resolution.


TRACE_KEY_REGISTRY: Dict[str, TraceKeyDef] = {
    # ── Planning engine keys (engine-internal) ──
    "planning.step_index": TraceKeyDef(
        type=int,
        semantics="Ordinal position (0-based) within the current planning chain",
        engine="planning",
    ),
    "planning.reasoning_depth": TraceKeyDef(
        type=int,
        semantics="Depth in the reasoning tree (0=root, terminal step=max depth)",
        engine="planning",
    ),
    "planning.parent_step_id": TraceKeyDef(
        type=str,
        semantics="step_id of the parent node in the reasoning tree; None for root",
        engine="planning",
    ),

    # ── Planning engine keys (component-candidate: LLM generation) ──
    "planning.cumulative_tokens": TraceKeyDef(
        type=int,
        semantics="Total LLM tokens consumed across all reasoning steps so far",
        engine="planning",
        unit="tokens",
        component_candidate=True,
    ),

    # ── RAG engine keys (component-candidate: retrieval) ──
    "rag.chunk_id": TraceKeyDef(
        type=str,
        semantics="Unique identifier of the retrieved chunk in the vector store",
        engine="rag",
        component_candidate=True,
    ),
    "rag.retrieval_latency_ms": TraceKeyDef(
        type=float,
        semantics="Wall-clock time for the vector store retrieval call, in milliseconds",
        engine="rag",
        unit="ms",
        component_candidate=True,
    ),

    # ── Orchestration engine keys (Phase 14) ────────────────────────
    # All 6 keys projected in Phase 12 pre-design. component_candidate=False
    # because orchestration describes engine behavior, not component capability.
    "orchestration.dag_node_id": TraceKeyDef(
        type=str,
        semantics="Unique identifier of the DAG node currently executing",
        engine="orchestration",
    ),
    "orchestration.parallel_depth": TraceKeyDef(
        type=int,
        semantics="Current depth in the parallel execution tree (0=root)",
        engine="orchestration",
    ),
    "orchestration.merge_ordinal": TraceKeyDef(
        type=int,
        semantics="Ordinal position when merging results from parallel branches",
        engine="orchestration",
    ),
    "orchestration.branch_taken": TraceKeyDef(
        type=str,
        semantics="Identifier of which branch was selected for conditional branching",
        engine="orchestration",
    ),
    "orchestration.retry_count": TraceKeyDef(
        type=int,
        semantics="Number of retries attempted for this node (0=first attempt)",
        engine="orchestration",
    ),
    "orchestration.resource_pool_key": TraceKeyDef(
        type=str,
        semantics="Resource pool identifier for capacity tracking",
        engine="orchestration",
    ),
}

# ── Engine-to-Component Key Mapping (Phase 13) ─────────────────────
# Maps engine-level keys (engine.* prefix) to component-level keys
# (component.* prefix). Used by sinks and analysis tools to resolve
# trace_context keys to their canonical component contract defined
# in core/contracts/trace_keys.py.
#
# Lives here (observability layer, the trace border) rather than in
# core/contracts/ because the mapping requires knowledge of both engine
# key names and component key names. Contracts must not know about
# specific engines.
ENGINE_TO_COMPONENT_MAP: Dict[str, str] = {
    "planning.cumulative_tokens": "generation.cumulative_tokens",
    "rag.chunk_id": "retrieval.chunk_id",
    "rag.retrieval_latency_ms": "retrieval.latency_ms",
}
