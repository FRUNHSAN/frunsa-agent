"""Engine Pipeline runner — sync wrapper bridging async generators to Streamlit.

Zero-intrusion design: imports engines/core from parent project, wraps async
generators in a Thread+Queue sync bridge for Streamlit's event loop safety.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any, Dict, Generator

# Ensure parent project is on sys.path so engines/core imports resolve
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig
from core.observability.sqlite_sink import SQLiteTraceSink
from core.pipeline.tracing import StreamingTraceRecord
from engines.critic.identity import CriticAgent
from engines.critic.interface import CriticContext
from engines.planning.identity import AgentIdentity
from engines.planning.interface import PlanningContext

# ── Sync wrapper: Thread + Queue bridge ──────────────────────────────────


def _run_async_gen(agen):
    """Run an async generator in a daemon thread, yielding items through Queue.

    Solves Streamlit's "asyncio.run() cannot be called from a running event
    loop" by isolating the asyncio event loop in a dedicated thread.
    """
    q: Queue = Queue()
    _error: list[Exception] = []

    def _target() -> None:
        try:
            async def _collect():
                async for item in agen:
                    q.put(("item", item))
                q.put(("done", None))
            asyncio.run(_collect())
        except Exception as exc:
            _error.append(exc)
            q.put(("error", exc))

    t = Thread(target=_target, daemon=True)
    t.start()

    while True:
        kind, payload = q.get()
        if kind == "done":
            break
        if kind == "error":
            raise RuntimeError(f"Engine thread crashed: {payload}") from payload
        yield payload


# ── Pipeline orchestrator ────────────────────────────────────────────────

DB_PATH = str(_PARENT / "demo" / "demo_trace.db")


def run_engine_pipeline(
    goal: str,
    use_mock: bool = True,
    db_path: str | None = None,
) -> Generator[Dict[str, Any], None, None]:
    """Run Planning → Orchestration → Critic pipeline, yielding each item.

    Each yielded dict has:
      delta, engine, index, is_terminal, model, finish_reason,
      trace_context (dict), timestamp (float, demo-layer), item_type

    The final yield includes a ``stats`` key with aggregate metrics.

    Orchestration is invoked internally by the planning engine (factory pattern).
    Critic evaluates the concatenated plan output independently.
    """
    db = db_path or DB_PATH
    start_ts = time.perf_counter()
    rag_items: list[dict] = []

    # ── Phase 0: RAG knowledge retrieval ─────────────────────────────
    from demo.demo_rag import retrieve as rag_retrieve
    rag_result = rag_retrieve(goal)
    for i, chunk in enumerate(rag_result["reranked"]):
        item = {
            "delta": f"[RAG 召回 #{chunk['rank']}] score={chunk['score']:.3f} | source={chunk['source']}\n{chunk['text'][:150]}",
            "engine": "rag",
            "index": i,
            "is_terminal": False,
            "model": "retriever/reranker",
            "finish_reason": "",
            "trace_context": {
                "rag.query": goal,
                "rag.retrieved_count": len(rag_result["retrieved"]),
                "rag.reranked_count": len(rag_result["reranked"]),
                "rag.elapsed_ms": rag_result["elapsed_ms"],
                "rag.kb_size": rag_result["knowledge_base_size"],
            },
            "timestamp": time.time(),
            "item_type": "rag",
        }
        rag_items.append(item)
        yield item

    # Build knowledge context for planning
    knowledge_context = "\n".join(
        c["text"][:200] for c in rag_result["reranked"]
    )

    identity = AgentIdentity(
        id="planner-v1", role="planning", version="1.0.0",
        capabilities=("task_decomposition", "parallel_planning"),
    )
    context = PlanningContext(
        goal=goal,
        agent_identity=identity,
        sub_tasks=(
            "fast_path: keyword-based retrieval",
            "full_rerank: semantic reranking",
        ),
        max_parallel_branches=2,
    )
    deadline = start_ts + 60.0
    pace = PaceConfig()

    # ── Phase 1: Planning (covers orchestration internally) ──────────
    if use_mock:
        from engines.planning.stub import StubPlanningEngine
        planner = StubPlanningEngine()
    else:
        from core.adapters.generator_adapter import GenerationAdapter
        from engines.planning.llm import (
            DEFAULT_DECOMPOSE_RESPONSE,
            DEFAULT_SYNTHESIZE_RESPONSE,
            LLMPlanningEngine,
            MockLLMBackend,
        )
        adapter = GenerationAdapter(
            MockLLMBackend(responses=(DEFAULT_DECOMPOSE_RESPONSE, DEFAULT_SYNTHESIZE_RESPONSE)),
            dependency_name="mock_planning",
        )
        planner = LLMPlanningEngine(adapter=adapter)

    plan_items: list[StreamItem] = []
    for item in _run_async_gen(planner.plan(context, deadline, pace)):
        plan_items.append(item)
        ctx = dict(item.trace_context) if item.trace_context else {}
        # Detect orchestration items by their trace_context keys
        is_orch = any(k.startswith("orchestration.") for k in ctx)
        yield {
            "delta": item.delta,
            "engine": "orchestration" if is_orch else "planning",
            "index": item.index,
            "is_terminal": item.is_terminal,
            "model": item.model,
            "finish_reason": item.finish_reason,
            "trace_context": ctx,
            "timestamp": time.time(),
            "item_type": "planning",
        }

    # ── Phase 2: Critic evaluation ───────────────────────────────────
    plan_output = "\n".join(
        f"[step {i.index}] {i.delta}" for i in plan_items
    )
    critic_agent = CriticAgent(
        id="critic-v1", role="critic", version="1.0.0",
        capabilities=("result_evaluation", "quality_scoring"),
    )
    critic_ctx = CriticContext(plan_output=plan_output, agent_identity=critic_agent)

    if use_mock:
        from engines.critic.stub import StubCriticEngine
        critic = StubCriticEngine(agent=critic_agent)
    else:
        from core.adapters.generator_adapter import GenerationAdapter
        from engines.critic.llm import (
            DEFAULT_DECOMPOSITION_RESPONSE,
            DEFAULT_DISPATCH_RESPONSE,
            DEFAULT_SYNTHESIS_RESPONSE,
            LLMCriticEngine,
            MockCriticBackend,
        )
        critic_adapter = GenerationAdapter(
            MockCriticBackend(responses=(
                DEFAULT_DECOMPOSITION_RESPONSE,
                DEFAULT_DISPATCH_RESPONSE,
                DEFAULT_SYNTHESIS_RESPONSE,
            )),
            dependency_name="mock_critic",
        )
        critic = LLMCriticEngine(adapter=critic_adapter)

    critic_items: list[StreamItem] = []
    for item in _run_async_gen(critic.evaluate(critic_ctx, deadline, pace)):
        critic_items.append(item)
        yield {
            "delta": item.delta,
            "engine": "critic",
            "index": item.index,
            "is_terminal": item.is_terminal,
            "model": item.model,
            "finish_reason": item.finish_reason,
            "trace_context": dict(item.trace_context) if item.trace_context else {},
            "timestamp": time.time(),
            "item_type": "critic",
        }

    # ── Write to SQLite sink ─────────────────────────────────────────
    run_id = f"demo-{int(time.time())}"
    all_items = plan_items + critic_items
    records = [
        StreamingTraceRecord(
            pipeline_run_id=run_id,
            step_name="demo_pipeline",
            dependency_name=item.model,
            item_index=item.index,
            item_delta_preview=item.delta[:200],
            is_terminal=item.is_terminal,
            trace_context=dict(item.trace_context) if item.trace_context else None,
            ts_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            engine=_infer_engine_from_model(
                item.model,
                trace_context=dict(item.trace_context) if item.trace_context else None,
            ),
        )
        for item in all_items
    ]

    sink = SQLiteTraceSink(db)
    sink.write_streaming(records)

    # ── Final stats ──────────────────────────────────────────────────
    elapsed = time.perf_counter() - start_ts
    total_tokens = sum(
        len(item.delta) // 4 for item in all_items
    )
    yield {
        "delta": "",
        "engine": "stats",
        "index": -1,
        "is_terminal": True,
        "model": "",
        "finish_reason": "stop",
        "trace_context": {},
        "timestamp": time.time(),
        "item_type": "stats",
        "stats": {
            "total_items": len(all_items),
            "rag_items": len(rag_items),
            "planning_items": len(plan_items),
            "critic_items": len(critic_items),
            "orchestration_items": sum(
                1 for i in plan_items
                if any(k.startswith("orchestration.") for k in (i.trace_context or {}))
            ),
            "total_tokens": total_tokens,
            "duration_seconds": round(elapsed, 3),
            "db_path": db,
            "knowledge_context_preview": knowledge_context[:200],
        },
    }


def _infer_engine_from_model(model: str, trace_context: dict | None = None) -> str:
    if trace_context:
        if any(k.startswith("orchestration.") for k in trace_context):
            return "orchestration"
    if "planning" in model:
        return "planning"
    if "orchestration" in model:
        return "orchestration"
    if "critic" in model:
        return "critic"
    return "unknown"
