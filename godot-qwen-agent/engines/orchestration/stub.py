"""Minimal Orchestration engine stub — Phase 14 + Phase 16 chaos injection.

Simulates N=2 parallel retrieval branches merging into a single output
stream. Uses asyncio.gather() to match PipelineRunner._arun_impl()'s
concurrency model.

Phase 16: accepts optional OrchestrationConfig for failure injection
(retry_count 0→1) and multi-pool routing (cpu vs gpu). No config =
Phase 15 behavior unchanged.

Each StreamItem.trace_context carries TWO layers:
  - Component keys (consumed): retrieval.chunk_id, retrieval.latency_ms
  - Orchestration keys (produced): all 6 orchestration.* keys
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import AsyncIterator, List

from core.contracts.generation import StreamItem
from engines.orchestration.config import FailureInjectionConfig, OrchestrationConfig


class StubOrchestrationEngine:
    """Simulates parallel retrieval branches + merge orchestration.

    Branch model:
      - branch_a ("fast_path"): 3 chunks, ~5ms each
      - branch_b ("full_rerank"): 2 chunks, ~15ms each

    Both branches run concurrently via asyncio.gather(). After both
    complete, results are merged into a single output stream with
    sequential merge_ordinal.

    Phase 16: accepts optional OrchestrationConfig for:
      - Failure injection: deterministic (chunk_id, attempt) tuples
      - Multi-pool routing: branch_name → pool_key mapping
    """

    def __init__(self, config: OrchestrationConfig | None = None) -> None:
        self._config = config
        self._failure_config = config.failure_injection if config else None

    async def orchestrate(self) -> AsyncIterator[StreamItem]:
        goal_hash = hashlib.sha256(b"phase_14_orch").hexdigest()[:8]

        pools = self._config.resource_pools if self._config else None

        results = await asyncio.gather(
            self._simulate_branch(
                branch="fast_path",
                chunk_ids=["c001", "c002", "c003"],
                latency_ms=[5.2, 4.8, 6.1],
                resource_pool_key=_resolve_pool(pools, "fast_path"),
            ),
            self._simulate_branch(
                branch="full_rerank",
                chunk_ids=["c004", "c005"],
                latency_ms=[14.3, 15.7],
                resource_pool_key=_resolve_pool(pools, "full_rerank"),
            ),
        )

        # ── Sequential merge ──
        merged: List[dict] = []
        for branch_result in results:
            merged.extend(branch_result)

        total = len(merged)

        for merge_idx, item in enumerate(merged):
            is_error = item.get("error") is not None
            yield StreamItem(
                delta=item.get("delta", f"[{item['branch']}] chunk {item['chunk_id']} "
                       f"(latency={item['latency_ms']}ms)"),
                index=merge_idx,
                model="orchestration/stub",
                is_terminal=(merge_idx == total - 1),
                finish_reason=(
                    "retry_exhausted" if is_error
                    else "stop" if merge_idx == total - 1
                    else None
                ),
                trace_context={
                    "retrieval.chunk_id": item["chunk_id"],
                    "retrieval.latency_ms": item["latency_ms"],
                    "orchestration.dag_node_id": f"merge_{goal_hash}",
                    "orchestration.parallel_depth": 1,
                    "orchestration.merge_ordinal": merge_idx,
                    "orchestration.branch_taken": item["branch"],
                    "orchestration.retry_count": item.get("attempts", 1) - 1,
                    "orchestration.resource_pool_key": item["resource_pool_key"],
                },
            )

    async def _simulate_branch(
        self,
        branch: str,
        chunk_ids: List[str],
        latency_ms: List[float],
        resource_pool_key: str = "default",
    ) -> List[dict]:
        results: List[dict] = []
        for cid, lat in zip(chunk_ids, latency_ms):
            for attempt in range(1, 4):
                await asyncio.sleep(lat / 1000.0)
                if self._should_fail(cid, attempt):
                    if attempt == 3:
                        results.append({
                            "chunk_id": cid,
                            "latency_ms": lat,
                            "branch": branch,
                            "attempts": attempt,
                            "resource_pool_key": resource_pool_key,
                            "error": "retry_exhausted",
                            "delta": f"[{branch}] chunk {cid} RETRY_EXHAUSTED after {attempt} attempts",
                        })
                        break
                    await asyncio.sleep(0.01 * (2 ** (attempt - 1)))
                    continue
                results.append({
                    "chunk_id": cid,
                    "latency_ms": lat,
                    "branch": branch,
                    "attempts": attempt,
                    "resource_pool_key": resource_pool_key,
                })
                break
        return results

    def _should_fail(self, chunk_id: str, attempt: int) -> bool:
        if self._failure_config is None:
            return False
        if chunk_id in self._failure_config.exhaust_retries:
            return True
        return (chunk_id, attempt) in self._failure_config.fail_on_attempts


def _resolve_pool(pools, branch: str) -> str:
    if pools is None:
        return "default"
    return pools.get(branch, "default")
