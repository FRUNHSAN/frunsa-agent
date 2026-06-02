"""Streaming merge engine: WAIT_ALL, N-sentinel convergence, error propagation.

Phase 8.2b: Multi-branch DAG streaming semantics. The merge_streams() function
is the engine's stream orchestration primitive — it knows nothing about
specific step types (chunker, retriever, generator), only about StreamItem
contracts (is_terminal, finish_reason, error).

Imports note: StreamItem is used as streaming infrastructure (like PaceConfig),
not as a domain type. The invariants (#1) allow infrastructure-type imports
across platform boundaries.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, Optional

from core.contracts import StreamItem  # infrastructure type — streaming transport token


async def merge_streams(
    streams: List[AsyncIterator[StreamItem]],
    queue_size: int = 32,
) -> AsyncIterator[StreamItem]:
    """Merge N producer streams with WAIT_ALL semantics.

    Each producer yields data StreamItems followed by exactly one terminal
    StreamItem (is_terminal=True). The merge consumer:

    1. Passes through data items in arrival order
    2. Suppresses individual producer terminals (counts them internally)
    3. When N terminals received, yields a single merged terminal and exits
    4. On error terminal: yields it immediately, cancels remaining producers

    Backpressure: asyncio.Queue(maxsize=queue_size) blocks producers when
    the consumer is slower, naturally throttling upstream throughput.

    Args:
        streams: N async iterators of StreamItems. Each must end with a
                 terminal item (is_terminal=True).
        queue_size: Capacity of the shared merge queue for backpressure.

    Yields:
        StreamItems in arrival order. Data items are passed through;
        producer terminals are suppressed; a single merged terminal
        signals all producers have completed.
    """
    if not streams:
        return

    n_producers = len(streams)
    queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
    terminal_count = 0
    producer_tasks: List[asyncio.Task] = []

    async def _produce(stream: AsyncIterator[StreamItem]) -> None:
        """Run one producer: forward items to shared queue, stop at terminal."""
        try:
            async for item in stream:
                await queue.put(item)
                if item.is_terminal:
                    return  # producer done — terminal enqueued
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            await queue.put(
                StreamItem(
                    delta="",
                    index=-1,
                    finish_reason="error",
                    is_terminal=True,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    # Launch all producers concurrently
    producer_tasks = [asyncio.create_task(_produce(s)) for s in streams]

    async def _cancel_all() -> None:
        """Cancel all remaining producer tasks and wait for cleanup."""
        for task in producer_tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*producer_tasks, return_exceptions=True)

    try:
        while terminal_count < n_producers:
            item = await queue.get()

            if item.is_terminal:
                if item.finish_reason == "error":
                    yield item  # propagate error terminal immediately
                    await _cancel_all()
                    return

                terminal_count += 1
                # Suppress individual producer terminal — accumulate
                if terminal_count >= n_producers:
                    # All producers done → emit merged success terminal
                    yield StreamItem(
                        delta="",
                        index=-1,
                        finish_reason="stop",
                        is_terminal=True,
                        model="merged",
                    )
                    return
            else:
                yield item  # data item — pass through
    finally:
        await _cancel_all()
