"""Real LLM-backed Orchestration Engine with deterministic MockOrchBackend.

Phase 18: Second real engine — replaces hardcoded routing/merge/retry with
LLM decisions via GenerationAdapter. MockOrchBackend provides deterministic
CI testing. StubOrchestrationEngine remains the fast reference.

Architecture:
  LLMOrchestrationEngine implements OrchestrationEngine Protocol.
  Uses GenerationAdapter for LLM calls (tracing, timeout, credentials).
  MockOrchBackend implements GenerationBackend Protocol with pre-canned responses.
  Branch simulation follows stub pattern (asyncio.sleep for latency).

Engine flow:
  0. Receive OrchestrationContext with metadata slot
  1. LLM Route Decision -> branch assignments, parallel_depth, pool keys
  2. asyncio.gather() parallel dispatch (same concurrency model as stub)
  3. Per-item yield: all 6 orchestration.* keys + component pass-through + agent.identity
  4. LLM Retry Decision on failure -> retry_count incremented, resource_pool_key tracked
  5. LLM Merge Synthesis -> ordering per merge_strategy
  6. Terminal yield
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, AsyncIterator, List

from core.adapters.generator_adapter import GenerationAdapter
from core.contracts.generation import GenerationResult, StreamItem
from core.contracts.streaming_protocol import PaceConfig
from engines.orchestration.identity import OrchestratorIdentity
from engines.orchestration.interface import OrchestrationContext


# ── Mock LLM Backend ───────────────────────────────────────────────────

@dataclass(frozen=True)
class MockOrchBackend:
    """Deterministic LLM backend for orchestration CI testing.

    Uses pre-canned responses in round-robin order. Frozen dataclass with
    _call_count mutation via object.__setattr__ (Phase 7 pattern).

    Three response slots per cycle: route -> merge -> retry.
    """

    responses: tuple[str, ...]
    _call_count: int = field(default=0, repr=False)

    def generate(
        self, prompt: str, context: List[Any], **params: Any
    ) -> GenerationResult:
        idx = self._call_count % len(self.responses)
        text = self.responses[idx]
        object.__setattr__(self, "_call_count", self._call_count + 1)

        prompt_tokens = max(1, len(prompt) // 4)
        completion_tokens = max(1, len(text) // 4)
        return GenerationResult(
            text=text,
            model="mock/orchestration",
            finish_reason="stop",
            usage=MappingProxyType({
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }),
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)


# ── Prompt Templates ───────────────────────────────────────────────────

ROUTE_PROMPT = """\
You are an orchestration agent. Route the following branches for parallel execution.

Branches to orchestrate: {branches}
Merge strategy: {merge_strategy}
Max retries per item: {max_retries}

Return a JSON object with:
- "branches": array of objects, each with "name" (string), "pool" (string), "items" (integer)

Note: concurrency depth is determined by the DAG topology, not by this decision.
Respond with ONLY the JSON object, no other text."""

MERGE_PROMPT = """\
Synthesize merge ordering for the following branch execution results.

Results:
{results}

Merge strategy: {strategy}

Return a JSON object with:
- "strategy": string (the merge strategy: "sequential", "interleave", or "priority")

Respond with ONLY the JSON object, no other text."""

RETRY_PROMPT = """\
Decide whether to retry a failed branch item.

Branch: {branch}
Chunk ID: {chunk_id}
Attempt: {attempt} of {max_retries}
Error: {error}

Return a JSON object with:
- "retry": boolean (true to retry, false to give up)
- "reason": string (brief explanation)

Respond with ONLY the JSON object, no other text."""

# Default mock responses per the plan
DEFAULT_ROUTE_RESPONSE = (
    '{"branches": [{"name": "fast_path", "pool": "cpu", "items": 3}, '
    '{"name": "full_rerank", "pool": "gpu", "items": 2}]}'
)

DEFAULT_MERGE_RESPONSE = '{"strategy": "sequential"}'

DEFAULT_RETRY_RESPONSE = '{"retry": true, "reason": "Transient error detected"}'


# ── Default Backend Factory ────────────────────────────────────────────

def _default_mock_backend() -> MockOrchBackend:
    """Create the default mock backend for CI testing.

    Three responses: route, merge, retry. Engine call order is:
    1. Route decision (before dispatch)
    2. Merge synthesis (after all branches complete)
    3. Retry decisions (per failure, uses round-robin from this pool)

    Retry response is duplicated to handle multiple retry decisions
    without running out of responses.
    """
    return MockOrchBackend(responses=(
        DEFAULT_ROUTE_RESPONSE,
        DEFAULT_MERGE_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
        DEFAULT_RETRY_RESPONSE,
    ))


# ── Output Parsers ─────────────────────────────────────────────────────

def _parse_route_decision(raw_text: str) -> dict:
    """Parse LLM route decision into a dict with branches and parallel_depth."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse route decision as JSON: {e}\n"
            f"Raw (first 500 chars): {raw_text[:500]}"
        )

    if not isinstance(data, dict):
        raise ValueError(
            f"Expected JSON object, got {type(data).__name__}"
        )
    if "branches" not in data:
        raise ValueError("Route decision missing 'branches' key")
    return data


def _parse_merge_decision(raw_text: str) -> dict:
    """Parse LLM merge decision into a dict with strategy."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse merge decision as JSON: {e}\n"
            f"Raw (first 500 chars): {raw_text[:500]}"
        )
    return data


def _parse_retry_decision(raw_text: str) -> dict:
    """Parse LLM retry decision into a dict with retry and reason."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )
        text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse retry decision as JSON: {e}\n"
            f"Raw (first 500 chars): {raw_text[:500]}"
        )
    return data


# ── LLM Orchestration Engine ────────────────────────────────────────────


class LLMOrchestrationEngine:
    """Real LLM-backed Orchestration Engine using GenerationAdapter.

    Implements OrchestrationEngine Protocol. Flow:
      0. Receive OrchestrationContext with metadata slot
      1. LLM Route Decision -> branch assignments, parallel_depth, pool keys
      2. asyncio.gather() parallel dispatch
      3. Per-item yield: all 6 orchestration.* keys + pass-through + agent.identity
      4. LLM Retry Decision on failure
      5. LLM Merge Synthesis
      6. Terminal yield

    Principle 1 (Assembly Contract): injectable via orch_factory in planning
    engines. Principle 2 (Contract Locking): all 6 orchestration keys on
    every StreamItem, enforced by guardrail.
    """

    identity = OrchestratorIdentity(
        id="orchestrator-llm-v1",
        role="orchestration",
        version="1.0.0",
        capabilities=(
            "parallel_dispatch", "result_merge", "llm_backed",
        ),
    )

    def __init__(
        self,
        adapter: GenerationAdapter,
        route_temperature: float = 0.3,
        merge_temperature: float = 0.3,
        retry_temperature: float = 0.2,
        kernel: Any | None = None,  # KernelService Protocol (Phase 5 decoupling)
    ) -> None:
        self._adapter = adapter
        self._kernel = kernel
        self._route_temp = route_temperature
        self._merge_temp = merge_temperature
        self._retry_temp = retry_temperature

    async def orchestrate(
        self,
        context: OrchestrationContext,
        deadline: float,
        pace_config: PaceConfig,
    ) -> AsyncIterator[StreamItem]:
        """Execute LLM-backed orchestration with parallel branch dispatch.

        Args:
            context: OrchestrationContext with branches, identity, merge strategy.
            deadline: Operation-level deadline in seconds (duration).
            pace_config: QoS parameters.
        """
        start = time.perf_counter()
        goal_hash = hashlib.sha256(
            b"phase_18_orch_llm"
        ).hexdigest()[:8]
        identity_value = self.identity.to_trace_value()
        max_retries = context.max_retries

        # ── Step 1: LLM Route Decision ─────────────────────────
        branch_specs = ", ".join(
            f"{b.name}(pool={b.pool}, items={b.items})"
            for b in context.branches
        )
        route_prompt = ROUTE_PROMPT.format(
            branches=branch_specs,
            merge_strategy=context.merge_strategy,
            max_retries=max_retries,
        )

        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Orchestration deadline exceeded before route decision: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )

        try:
            route_result = await self._adapter.generate(
                route_prompt, [],
                temperature=self._route_temp,
            )
            route_data = _parse_route_decision(route_result.text)
        except Exception as e:
            yield StreamItem(
                delta=f"LLM route decision failed: {e}",
                index=0,
                model="orchestration/llm",
                is_terminal=True,
                finish_reason="error",
                error=str(e),
                trace_context={
                    "orchestration.dag_node_id": f"route_err_{goal_hash}",
                    "orchestration.parallel_depth": 0,
                    "orchestration.merge_ordinal": 0,
                    "orchestration.branch_taken": "none",
                    "orchestration.retry_count": 0,
                    "orchestration.resource_pool_key": "default",
                    "agent.identity": identity_value,
                },
            )
            return

        branches = route_data.get("branches", [])
        parallel_depth = context.parallel_depth  # V6.1: DAG-computed, not LLM

        # ── Step 2: asyncio.gather() parallel dispatch ─────────
        resource_pools = context.resource_pools or {}

        async def _run_branch(branch_spec: dict) -> List[dict]:
            results: List[dict] = []
            name = branch_spec.get("name", "unknown")
            pool = branch_spec.get("pool", "default")
            item_count = branch_spec.get("items", 0)
            pool_key = resource_pools.get(name, pool)

            for i in range(item_count):
                chunk_id = f"{name}_{i:03d}"
                lat = 5.0 + (hash(name + str(i)) % 100) / 10.0  # 5-15ms

                for attempt in range(1, max_retries + 2):
                    await asyncio.sleep(lat / 1000.0)

                    # Simulate occasional failures on first attempt
                    if attempt == 1 and hash(chunk_id) % 5 == 0:
                        # LLM retry decision
                        retry_prompt = RETRY_PROMPT.format(
                            branch=name,
                            chunk_id=chunk_id,
                            attempt=attempt,
                            max_retries=max_retries,
                            error="Simulated transient error",
                        )
                        try:
                            retry_result = await self._adapter.generate(
                                retry_prompt, [],
                                temperature=self._retry_temp,
                            )
                            retry_data = _parse_retry_decision(retry_result.text)
                        except Exception:
                            retry_data = {"retry": True, "reason": "parse failure, defaulting to retry"}

                        if retry_data.get("retry", True) and attempt <= max_retries:
                            await asyncio.sleep(0.01 * (2 ** (attempt - 1)))
                            continue
                        else:
                            # Exhausted retries
                            results.append({
                                "chunk_id": chunk_id,
                                "latency_ms": lat,
                                "branch": name,
                                "attempts": attempt,
                                "resource_pool_key": pool_key,
                                "error": "retry_exhausted",
                                "delta": f"[{name}] chunk {chunk_id} RETRY_EXHAUSTED",
                            })
                            break

                    results.append({
                        "chunk_id": chunk_id,
                        "latency_ms": lat,
                        "branch": name,
                        "attempts": attempt,
                        "resource_pool_key": pool_key,
                    })
                    break
            return results

        if time.perf_counter() - start > deadline:
            raise asyncio.TimeoutError(
                f"Orchestration deadline exceeded before dispatch: "
                f"{time.perf_counter() - start:.3f}s > {deadline:.3f}s"
            )

        # V6.1: DAG-aware concurrency — Semaphore limits parallel depth.
        # Per-call Semaphore: created here, destroyed after gather → no cross-session blocking.
        _semaphore = asyncio.Semaphore(context.parallel_depth)

        async def _run_branch_gated(branch_spec: dict):
            async with _semaphore:
                return await _run_branch(branch_spec)

        branch_tasks = [
            _run_branch_gated(b) for b in branches
        ] if branches else []
        branch_results = await asyncio.gather(*branch_tasks)

        # ── Step 5: LLM Merge Synthesis ────────────────────────
        results_summary = "\n".join(
            f"  [{i}] branch={r.get('branch', '?')} chunk={r.get('chunk_id', '?')}"
            for i, batch in enumerate(branch_results)
            for r in batch
        )
        merge_prompt = MERGE_PROMPT.format(
            results=results_summary or "(none)",
            strategy=context.merge_strategy,
        )

        try:
            merge_result = await self._adapter.generate(
                merge_prompt, [],
                temperature=self._merge_temp,
            )
            merge_data = _parse_merge_decision(merge_result.text)
        except Exception:
            merge_data = {"strategy": context.merge_strategy}

        # ── Step 3-4: Per-item yield ───────────────────────────
        merged: List[dict] = []
        for batch in branch_results:
            merged.extend(batch)

        total = len(merged)

        if total == 0:
            yield StreamItem(
                delta="Orchestration complete: no items to merge.",
                index=0,
                model="orchestration/llm",
                is_terminal=True,
                finish_reason="stop",
                trace_context={
                    "retrieval.chunk_id": "",
                    "retrieval.latency_ms": 0.0,
                    "orchestration.dag_node_id": f"merge_{goal_hash}",
                    "orchestration.parallel_depth": parallel_depth,
                    "orchestration.merge_ordinal": 0,
                    "orchestration.branch_taken": "none",
                    "orchestration.retry_count": 0,
                    "orchestration.resource_pool_key": "default",
                    "agent.identity": identity_value,
                },
            )
            return

        for merge_idx, item in enumerate(merged):
            is_error = item.get("error") is not None
            yield StreamItem(
                delta=item.get(
                    "delta",
                    f"[{item['branch']}] chunk {item['chunk_id']} "
                    f"(latency={item['latency_ms']}ms)",
                ),
                index=merge_idx,
                model="orchestration/llm",
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
                    "orchestration.parallel_depth": parallel_depth,
                    "orchestration.merge_ordinal": merge_idx,
                    "orchestration.branch_taken": item["branch"],
                    "orchestration.retry_count": item.get("attempts", 1) - 1,
                    "orchestration.resource_pool_key": item["resource_pool_key"],
                    "agent.identity": identity_value,
                },
            )
