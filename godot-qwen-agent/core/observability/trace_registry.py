"""Declarative trace key registry: engine-private dialect snapshot.

Phase 11: N=2 engine stubs only. NOT a cross-engine semantic standard.
component_candidate=True flags keys that belong to component semantics
(retrieval, generation, scoring), not to the engine itself. These should
migrate to core/contracts/trace_keys.py when the component platform is
built (Phase 13+).
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
    # When the component platform is built, these keys should be
    # migrated to component-level trace contracts (e.g. "retrieval.*"
    # instead of "rag.*").


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
}
