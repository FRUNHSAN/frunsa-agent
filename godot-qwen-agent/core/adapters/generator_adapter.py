"""GenerationAdapter: async wrapper around LLM generation backends.

Isolates external LLM SDK (OpenAI, Anthropic, etc.) behind a uniform async interface.
Every generate call auto-injects a DependencyCallTrace for observability.
Credentials are obtained from ResourceContainer, never from globals or os.environ.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Protocol

from core.contracts import Chunk, GenerationResult, StreamItem
from core.pipeline.tracing import DependencyCallTrace, SpanType


class GenerationBackend(Protocol):
    """Protocol for LLM generation backends — OpenAI, Anthropic, local models, etc."""

    def generate(self, prompt: str, context: List[Chunk], **params: Any) -> GenerationResult:
        """Synchronous generation. The adapter wraps this in an executor."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate token count for budget tracking."""
        ...


class StreamingBackend(Protocol):
    """Protocol for streaming LLM backends — yields tokens as they are produced.

    Extends GenerationBackend with a sync generate_stream() that the adapter
    bridges to an AsyncIterator via Producer-Consumer + Sentinel pattern.
    """

    def generate(self, prompt: str, context: List[Chunk], **params: Any) -> GenerationResult:
        """Synchronous generation (non-streaming fallback)."""
        ...

    def generate_stream(self, prompt: str, context: List[Chunk], **params: Any) -> Iterator[StreamItem]:
        """Synchronous streaming generation. The adapter bridges this to async."""
        ...

    def count_tokens(self, text: str) -> int:
        """Estimate token count for budget tracking."""
        ...


class GenerationAdapter:
    """Async wrapper with auto-tracing, timeout, and credential isolation."""

    def __init__(
        self,
        backend: GenerationBackend,
        dependency_name: str = "llm_api",
        default_timeout: float = 120.0,
    ) -> None:
        self._backend = backend
        self._dependency_name = dependency_name
        self._default_timeout = default_timeout
        self._last_probe_latency_ms: Optional[float] = None
        self._cumulative_tokens: int = 0

    async def generate(
        self,
        prompt: str,
        context: Optional[List[Chunk]] = None,
        timeout: Optional[float] = None,
        **params: Any,
    ) -> GenerationResult:
        """Async generation with automatic DependencyCallTrace and token tracking."""
        effective_timeout = timeout or self._default_timeout
        ctx = context or []
        t0 = time.perf_counter()
        status: str = "success"
        error_msg: Optional[str] = None
        result: Optional[GenerationResult] = None

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: self._backend.generate(prompt, ctx, **params)
                ),
                timeout=effective_timeout,
            )
            self._cumulative_tokens += result.total_tokens
        except asyncio.TimeoutError:
            status = "timeout"
            error_msg = f"generation exceeded {effective_timeout}s"
        except Exception as exc:
            status = "error"
            error_msg = f"{type(exc).__name__}: {exc}"

        elapsed = (time.perf_counter() - t0) * 1000.0
        self._last_probe_latency_ms = elapsed

        metadata: Dict[str, Any] = {
            "model": result.model if result else "unknown",
            "finish_reason": result.finish_reason if result else "error",
            "prompt_tokens": result.prompt_tokens if result else 0,
            "completion_tokens": result.completion_tokens if result else 0,
            "total_tokens": result.total_tokens if result else 0,
            "cumulative_tokens": self._cumulative_tokens,
            **({"error": error_msg} if error_msg else {}),
        }

        trace = DependencyCallTrace(
            dependency_name=f"{self._dependency_name}.generate",
            span_type=SpanType.DEPENDENCY_CALL,
            started_at=t0,
            finished_at=time.perf_counter(),
            duration_ms=round(elapsed, 3),
            status=status,
            metadata=metadata,
        )
        self._last_trace = trace

        if result is None:
            result = GenerationResult(
                text="",
                model="unknown",
                finish_reason="error",
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

        return result

    async def generate_stream(
        self,
        prompt: str,
        context: Optional[List[Chunk]] = None,
        timeout: Optional[float] = None,
        **params: Any,
    ) -> AsyncIterator[StreamItem]:
        """Async streaming generation with backpressure-aware sync-to-async bridge.

        If the backend implements generate_stream(), bridges it via a
        Producer-Consumer pattern with asyncio.Queue. Otherwise falls back
        to generate() and yields a single StreamItem.
        """
        ctx = context or []

        if hasattr(self._backend, "generate_stream"):
            queue: asyncio.Queue = asyncio.Queue(maxsize=32)
            sentinel = object()
            loop = asyncio.get_running_loop()
            producer_error: Optional[Exception] = None

            def _producer() -> None:
                nonlocal producer_error
                try:
                    for item in self._backend.generate_stream(prompt, ctx, **params):
                        asyncio.run_coroutine_threadsafe(queue.put(item), loop)
                    asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)
                except Exception as exc:
                    producer_error = exc
                    asyncio.run_coroutine_threadsafe(queue.put(sentinel), loop)

            task = loop.run_in_executor(None, _producer)

            try:
                while True:
                    item = await queue.get()
                    if item is sentinel:
                        break
                    if isinstance(item, StreamItem):
                        self._cumulative_tokens += len(item.delta) // 4
                        yield item
            finally:
                await task
                if producer_error is not None:
                    raise producer_error
        else:
            result = await self.generate(
                prompt=prompt, context=ctx, timeout=timeout, **params
            )
            yield StreamItem(
                delta=result.text,
                index=0,
                finish_reason=result.finish_reason,
                is_terminal=True,
                model=result.model,
            )

    @property
    def last_trace(self) -> Optional[DependencyCallTrace]:
        return getattr(self, "_last_trace", None)

    @property
    def last_probe_latency_ms(self) -> Optional[float]:
        return self._last_probe_latency_ms

    @property
    def cumulative_tokens(self) -> int:
        return self._cumulative_tokens

    async def health_probe(self) -> Dict[str, Any]:
        """Health probe: send a minimal generation request to verify the endpoint is reachable."""
        try:
            result = await self.generate(
                prompt="__health_probe__",
                context=[],
                timeout=10.0,
                max_tokens=1,
            )
            last = self.last_trace
            if last and last.status == "error":
                return {
                    "status": "unavailable",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": last.metadata.get("error", "health probe: generation error"),
                }
            elif result.text or result.finish_reason not in ("error", ""):
                return {
                    "status": "healthy",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": f"health probe: model={result.model}, finish={result.finish_reason}",
                }
            else:
                return {
                    "status": "degraded",
                    "latency_ms": self._last_probe_latency_ms,
                    "message": "health probe: generation returned empty result",
                }
        except asyncio.TimeoutError:
            return {
                "status": "degraded",
                "latency_ms": self._last_probe_latency_ms,
                "message": "health probe timed out",
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "latency_ms": self._last_probe_latency_ms,
                "message": f"health probe failed: {exc}",
            }
