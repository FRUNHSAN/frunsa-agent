"""Minimal Orchestration engine stub — Phase 14.

Simulates N=2 parallel retrieval branches merging into a single output
stream. Uses asyncio.gather() to match PipelineRunner._arun_impl()'s
concurrency model.

Each StreamItem.trace_context carries TWO layers:
  - Component keys (consumed): retrieval.chunk_id, retrieval.latency_ms
  - Orchestration keys (produced): all 6 orchestration.* keys

This is the first engine to bridge both trace layers.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import AsyncIterator, List

from core.contracts.generation import StreamItem


class StubOrchestrationEngine:
    """Simulates parallel retrieval branches + merge orchestration.

    Branch model:
      - branch_a ("fast_path"): 3 chunks, ~5ms each
      - branch_b ("full_rerank"): 2 chunks, ~15ms each

    Both branches run concurrently via asyncio.gather(). After both
    complete, results are merged into a single output stream with
    sequential merge_ordinal.

    Each StreamItem carries all 6 orchestration.* keys + consumed
    component keys (retrieval.chunk_id, retrieval.latency_ms).
    """

    async def orchestrate(self) -> AsyncIterator[StreamItem]:
        """Execute parallel retrieval + merge with full trace context.

        Returns an async iterator of StreamItems suitable for
        AsyncDataStreamAdapter per-item capture.
        """
        goal_hash = hashlib.sha256(b"phase_14_orch").hexdigest()[:8]

        # ── Parallel execution: both branches run concurrently ──
        results = await asyncio.gather(
            self._simulate_branch(
                branch="fast_path",
                chunk_ids=["c001", "c002", "c003"],
                latency_ms=[5.2, 4.8, 6.1],
            ),
            self._simulate_branch(
                branch="full_rerank",
                chunk_ids=["c004", "c005"],
                latency_ms=[14.3, 15.7],
            ),
        )

        # ── Sequential merge: deterministic order across branches ──
        merged: List[dict] = []
        for branch_result in results:
            merged.extend(branch_result)

        total = len(merged)

        for merge_idx, item in enumerate(merged):
            yield StreamItem(
                delta=f"[{item['branch']}] chunk {item['chunk_id']} "
                      f"(latency={item['latency_ms']}ms)",
                index=merge_idx,
                model="orchestration/stub",
                is_terminal=(merge_idx == total - 1),
                finish_reason="stop" if merge_idx == total - 1 else None,
                trace_context={
                    # ── Component keys (consumed by orchestration engine) ──
                    "retrieval.chunk_id": item["chunk_id"],
                    "retrieval.latency_ms": item["latency_ms"],

                    # ── Orchestration keys (produced by orchestration engine) ──
                    "orchestration.dag_node_id": f"merge_{goal_hash}",
                    "orchestration.parallel_depth": 1,
                    "orchestration.merge_ordinal": merge_idx,
                    "orchestration.branch_taken": item["branch"],
                    "orchestration.retry_count": 0,
                    "orchestration.resource_pool_key": "default",
                },
            )

    async def _simulate_branch(
        self,
        branch: str,
        chunk_ids: List[str],
        latency_ms: List[float],
    ) -> List[dict]:
        """Simulate one retrieval branch producing chunks with latency.

        Each chunk is delayed by its latency to mimic real I/O.
        Returns a list of dicts with chunk metadata for merging.
        """
        results: List[dict] = []
        for cid, lat in zip(chunk_ids, latency_ms):
            await asyncio.sleep(lat / 1000.0)  # convert ms to seconds
            results.append({
                "chunk_id": cid,
                "latency_ms": lat,
                "branch": branch,
                "attempts": 1,
            })
        return results
