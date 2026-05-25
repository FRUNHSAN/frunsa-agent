"""Declarative trace key registry: engine-private dialect snapshot.

Phase 11: N=2 engine stubs only. NOT a cross-engine semantic standard.
Phase 14: orchestration engine keys added (N=3 engines).
Phase 15: agent.identity key added (first agent.* namespace key).
Phase 16: critic.score + critic.verdict added (N=4 engines, 18 keys).
Phase 17: engine: str → engines: list[str] — multi-engine key registration.
    agent.identity engines=["planning", "critic"]. Backward-compat @property.
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
    engines: list[str]
    unit: str = ""
    component_candidate: bool = False
    # True = this key's semantics belong to a component capability
    # (retrieval, generation, scoring), not to the engine itself.
    # Phase 13: migrated to core/contracts/trace_keys.py.
    # See ENGINE_TO_COMPONENT_MAP for the engine→component resolution.

    def __post_init__(self):
        assert len(self.engines) > 0, (
            f"TraceKeyDef.engines must be non-empty, got: {self.engines}"
        )
        object.__setattr__(self, "engines", tuple(dict.fromkeys(self.engines)))

    @property
    def engine(self) -> str:
        """Backward-compatible alias. Returns the primary (first) engine."""
        return self.engines[0]


TRACE_KEY_REGISTRY: Dict[str, TraceKeyDef] = {
    # ── Planning engine keys (engine-internal) ──
    "planning.step_index": TraceKeyDef(
        type=int,
        semantics="Ordinal position (0-based) within the current planning chain",
        engines=["planning"],
    ),
    "planning.reasoning_depth": TraceKeyDef(
        type=int,
        semantics="Depth in the reasoning tree (0=root, terminal step=max depth)",
        engines=["planning"],
    ),
    "planning.parent_step_id": TraceKeyDef(
        type=str,
        semantics="step_id of the parent node in the reasoning tree; None for root",
        engines=["planning"],
    ),

    # ── Planning engine keys (component-candidate: LLM generation) ──
    "planning.cumulative_tokens": TraceKeyDef(
        type=int,
        semantics="Total LLM tokens consumed across all reasoning steps so far",
        engines=["planning"],
        unit="tokens",
        component_candidate=True,
    ),

    # ── RAG engine keys (component-candidate: retrieval) ──
    "rag.chunk_id": TraceKeyDef(
        type=str,
        semantics="Unique identifier of the retrieved chunk in the vector store",
        engines=["rag"],
        component_candidate=True,
    ),
    "rag.retrieval_latency_ms": TraceKeyDef(
        type=float,
        semantics="Wall-clock time for the vector store retrieval call, in milliseconds",
        engines=["rag"],
        unit="ms",
        component_candidate=True,
    ),

    # ── Orchestration engine keys (Phase 14) ────────────────────────
    # All 6 keys projected in Phase 12 pre-design. component_candidate=False
    # because orchestration describes engine behavior, not component capability.
    "orchestration.dag_node_id": TraceKeyDef(
        type=str,
        semantics="Unique identifier of the DAG node currently executing",
        engines=["orchestration"],
    ),
    "orchestration.parallel_depth": TraceKeyDef(
        type=int,
        semantics="Current depth in the parallel execution tree (0=root)",
        engines=["orchestration"],
    ),
    "orchestration.merge_ordinal": TraceKeyDef(
        type=int,
        semantics="Ordinal position when merging results from parallel branches",
        engines=["orchestration"],
    ),
    "orchestration.branch_taken": TraceKeyDef(
        type=str,
        semantics="Identifier of which branch was selected for conditional branching",
        engines=["orchestration"],
    ),
    "orchestration.retry_count": TraceKeyDef(
        type=int,
        semantics="Number of retries attempted for this node (0=first attempt)",
        engines=["orchestration"],
    ),
    "orchestration.resource_pool_key": TraceKeyDef(
        type=str,
        semantics="Resource pool identifier for capacity tracking",
        engines=["orchestration"],
    ),

    # ── Agent identity key (Phase 15) ─────────────────────────────────
    # First agent.* namespace key. component_candidate=False: agent identity
    # describes WHO is running, not WHAT component capability is provided.
    # Phase 17: engines=["planning", "critic"] — first multi-engine key.
    "agent.identity": TraceKeyDef(
        type=dict,
        semantics="Structured agent identity carrying id, role, version, and capabilities manifest",
        engines=["planning", "critic"],
        component_candidate=False,
    ),

    # ── Critic engine keys (Phase 16) ─────────────────────────────────
    "critic.score": TraceKeyDef(
        type=float,
        semantics="Quality score assigned by critic agent (0.0-1.0)",
        engines=["critic"],
    ),
    "critic.verdict": TraceKeyDef(
        type=str,
        semantics="Critic verdict: accept, reject, or rework",
        engines=["critic"],
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
