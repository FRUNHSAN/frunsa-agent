"""Business-agnostic pipeline orchestration engine.

The engine knows nothing about specific component types (chunker, retriever, tool).
It only recognises the uniform PipelineStep protocol.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    Protocol,
    Set,
    Tuple,
)

from .resources import ResourceContainer
from .tracing import StepTrace, TraceLog, TraceWriter, SnapshotPolicy, snapshot


# ── Protocol ─────────────────────────────────────────────────────


class PipelineStep(Protocol):
    """Uniform step interface. The engine calls either run() or async_run()."""

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        """Synchronous execution. All v1 components implement this."""
        ...

    async def async_run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        """Async execution (optional). Engine prefers this when available."""
        ...

    def health_check(self) -> HealthStatus:
        """Optional health probe. Engine calls at init; defaults to healthy."""
        ...


# ── Data classes ─────────────────────────────────────────────────


@dataclass
class StepOutput:
    """Standard return from any step."""
    result: Any
    stream: Optional[AsyncIterator[Any]] = None  # v2: UserFacingStream (SSE/Generator)
    internal_stream: Optional[AsyncIterator[Any]] = None  # v2: InternalStream (DAG nodes)
    trace_log: Dict[str, Any] = field(default_factory=dict)
    contract_validation: Any = None


@dataclass
class RetryPolicy:
    """Step-level retry configuration. max_retries=0 disables retry."""
    max_retries: int = 0
    backoff: Literal["none", "exponential"] = "exponential"
    retry_on: List[str] = field(
        default_factory=lambda: ["TimeoutError", "ConnectionError"]
    )


@dataclass
class DependencyHealth:
    """Health status of a single external dependency (vector DB, LLM API, etc.)."""
    name: str
    status: Literal["healthy", "degraded", "unavailable"]
    latency_ms: Optional[float] = None
    message: Optional[str] = None


@dataclass
class HealthStatus:
    status: Literal["healthy", "degraded", "unavailable"]
    message: str = ""
    details: Optional[Dict[str, Any]] = None
    dependencies: List[DependencyHealth] = field(default_factory=list)
    version: Optional[str] = None  # SemVer string of the component


@dataclass
class StepConfig:
    name: str
    component_type: str
    strategy: str
    version: Optional[Any] = None  # SemVer from contracts, kept as Any to avoid coupling
    params: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    provides: str = ""
    on_failure: Literal["abort", "skip", "default"] = "abort"
    default_value: Any = None
    timeout_seconds: Optional[float] = None
    output_type: Optional[str] = None
    retry_policy: Optional[RetryPolicy] = None
    sub_pipeline: Optional[str] = None
    input_mapping: Optional[Dict[str, str]] = None


@dataclass
class PipelineConfig:
    steps: List[StepConfig]
    pipeline_version: int = 1
    default_timeout_seconds: float = 300.0


# ── Sentinel for skip propagation ────────────────────────────────

_SKIP_SENTINEL = object()

# ── Engine ───────────────────────────────────────────────────────


class PipelineRunner:
    """Business-agnostic pipeline engine. Knows nothing about chunker/retriever/tool."""

    def __init__(
        self,
        config: PipelineConfig,
        step_factories: Dict[str, Callable[[StepConfig], PipelineStep]],
        snapshot_policy: SnapshotPolicy = SnapshotPolicy.SUMMARY,
        type_compatibility_checker: Optional[
            Callable[[StepConfig, StepConfig], List[str]]
        ] = None,
        initial_keys: Optional[Set[str]] = None,
        trace_writer: Optional[TraceWriter] = None,
        sync_workers: int = 4,
    ) -> None:
        self.config = config
        self._factories = step_factories
        self._snapshot_policy = snapshot_policy
        self._type_checker = type_compatibility_checker
        self._trace_writer = trace_writer
        self._initial_keys: Set[str] = set(initial_keys or []) | {"original_query"}
        self._sync_executor = ThreadPoolExecutor(max_workers=sync_workers)
        self._validate_structure()

    # ── Static validation ────────────────────────────────────

    def _validate_structure(self) -> None:
        errors: List[str] = []
        provided_keys: Dict[str, int] = {}

        for i, step in enumerate(self.config.steps):
            if not step.provides:
                continue
            if step.provides in provided_keys:
                errors.append(
                    f"Step '{step.name}' provides key '{step.provides}' "
                    f"already provided by step {provided_keys[step.provides]}"
                )
            provided_keys[step.provides] = i

        for i, step in enumerate(self.config.steps):
            for dep in step.depends_on:
                if dep in self._initial_keys:
                    continue
                if dep not in provided_keys:
                    errors.append(
                        f"Step '{step.name}' depends on '{dep}', "
                        f"but no previous step provides it and it is not "
                        f"in initial_keys ({list(self._initial_keys)})."
                    )
                    continue
                provider_idx = provided_keys[dep]
                if provider_idx >= i:
                    errors.append(
                        f"Step '{step.name}' depends on '{dep}' from "
                        f"step {provider_idx}, but it runs at index {i} (must be earlier)."
                    )

        if errors:
            raise PipelineStartupError(
                "Pipeline structure validation failed:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    # ── Lifecycle ────────────────────────────────────────────

    def close(self) -> None:
        """Shut down the sync-executor thread pool. Safe to call multiple times."""
        self._sync_executor.shutdown(wait=True)

    def __enter__(self) -> PipelineRunner:
        return self

    def __exit__(self, *args: Any) -> bool:
        self.close()
        return False

    # ── Public API ───────────────────────────────────────────

    def run(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
        on_step: Optional[Callable[[StepTrace], Optional[bool]]] = None,
    ) -> Tuple[Dict[str, Any], TraceLog]:
        """Synchronous entry point. Delegates to async core via asyncio.run()."""
        return asyncio.run(
            self.arun(initial_state=initial_state, resources=resources, on_step=on_step)
        )

    async def arun(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
        on_step: Optional[Callable[[StepTrace], Optional[bool]]] = None,
    ) -> Tuple[Dict[str, Any], TraceLog]:
        """Async core with DAG-based concurrent execution (Phase 8.1).

        Independent branches execute concurrently within a single event loop.
        Skip propagation is maintained: if a dependency is skipped, dependents skip.
        """
        pipeline_run_id = str(uuid.uuid4())
        state = dict(initial_state or {})
        stream_state: Dict[str, AsyncIterator[Any]] = {}  # provided_key → internal_stream
        res = resources or ResourceContainer()
        traces: Dict[int, StepTrace] = {}  # step_index → StepTrace
        started_at_iso = datetime.now(timezone.utc).isoformat()
        pipeline_start = time.perf_counter()
        executor = self._sync_executor

        n_steps = len(self.config.steps)

        # Pre-compute dependency indices: provided key → step index
        provided_to_idx: Dict[str, int] = {}
        for idx, step in enumerate(self.config.steps):
            if step.provides:
                provided_to_idx[step.provides] = idx

        # For each step, compute which step indices it directly depends on
        dep_indices: Dict[int, List[int]] = {}  # step_idx → [dep_step_idx, ...]
        for idx, step in enumerate(self.config.steps):
            deps: List[int] = []
            for dep_name in step.depends_on:
                if dep_name in self._initial_keys:
                    continue
                if dep_name in provided_to_idx:
                    deps.append(provided_to_idx[dep_name])
            dep_indices[idx] = deps

        # Lock for thread-safe state/traces access (not needed in asyncio but belt-and-suspenders)
        state_lock = asyncio.Lock()

        async def execute_step(idx: int) -> None:
            step = self.config.steps[idx]

            t = StepTrace(
                step_index=idx,
                step_name=step.name,
                pipeline_run_id=pipeline_run_id,
                snapshot_policy=self._snapshot_policy,
                component_type=step.component_type,
                strategy=step.strategy,
                status="running",
                started_at=time.perf_counter(),
                input_keys=list(step.depends_on),
                input_snapshot=None,
                output_key=step.provides,
                params=dict(step.params),
            )

            # Wait for all dependencies to be satisfied before reading state
            # (this is handled by the scheduler — when this coroutine is spawned,
            #  all deps already have their results in state)

            # Skip propagation check
            if any(
                state.get(dep) is _SKIP_SENTINEL for dep in step.depends_on
            ):
                t.status = "skipped"
                if step.provides:
                    async with state_lock:
                        state[step.provides] = _SKIP_SENTINEL
                t.finished_at = time.perf_counter()
                t.duration_seconds = 0.0
                traces[idx] = t
                if on_step:
                    on_step(t)
                return

            # Build input_dict with input_mapping if configured
            raw_inputs = {key: state.get(key) for key in step.depends_on}
            input_dict = _apply_input_mapping(raw_inputs, step.input_mapping)

            # Auto-merge upstream internal_streams (Phase 8.2b)
            upstream_streams = [
                stream_state[dep] for dep in step.depends_on if dep in stream_state
            ]
            if len(upstream_streams) > 1:
                try:
                    from core.pipeline.streaming import merge_streams as _merge
                except ImportError:
                    _merge = None
                if _merge is not None:
                    input_dict["_merged_stream"] = _merge(list(upstream_streams))
                else:
                    input_dict["_internal_stream"] = upstream_streams[0]
            elif len(upstream_streams) == 1:
                input_dict["_internal_stream"] = upstream_streams[0]

            t.input_snapshot = snapshot(input_dict, self._snapshot_policy)

            timeout = step.timeout_seconds or self.config.default_timeout_seconds
            retry = step.retry_policy

            try:
                component = self._factories[step.name](step)
                output = await _execute_with_retry(
                    component, input_dict, res, timeout, retry, executor
                )
                if step.provides:
                    async with state_lock:
                        state[step.provides] = output.result
                    if output.internal_stream is not None:
                        stream_state[step.provides] = output.internal_stream
                t.status = "success"
                t.output_snapshot = snapshot(output.result, self._snapshot_policy)
                t.contract_validation = output.contract_validation

            except asyncio.TimeoutError:
                t.status = "failed"
                t.error_type = "TimeoutError"
                t.error_message = f"Step exceeded {timeout}s"
                self._apply_failure(step, state, t)

            except Exception as exc:
                t.status = "failed"
                t.error_type = type(exc).__name__
                t.error_message = str(exc)
                t.error_traceback = traceback.format_exc()
                self._apply_failure(step, state, t)

            t.finished_at = time.perf_counter()
            t.duration_seconds = t.finished_at - t.started_at
            traces[idx] = t

            if on_step:
                on_step(t)

        # ── DAG scheduler ──────────────────────────────────────────

        # Track which steps have completed (0 = pending, 1 = executing/complete)
        completed = asyncio.Event()
        pending_count = n_steps

        # Build reverse dependency map: step_idx → steps that depend on it
        dependents: Dict[int, List[int]] = {i: [] for i in range(n_steps)}
        for idx, deps in dep_indices.items():
            for dep_idx in deps:
                dependents[dep_idx].append(idx)

        # Count unsatisfied deps per step
        unsatisfied: Dict[int, int] = {
            idx: len(deps) for idx, deps in dep_indices.items()
        }

        # Ready queue: steps with no unsatisfied deps
        ready: List[int] = [idx for idx, count in unsatisfied.items() if count == 0]

        try:
            # Execute DAG in waves: run all ready steps concurrently,
            # then check for newly ready steps
            while ready:
                wave_tasks = [
                    asyncio.create_task(execute_step(idx)) for idx in ready
                ]
                await asyncio.gather(*wave_tasks)

                # Find newly ready steps
                new_ready: List[int] = []
                for completed_idx in ready:
                    for dep_idx in dependents[completed_idx]:
                        unsatisfied[dep_idx] -= 1
                        if unsatisfied[dep_idx] == 0:
                            new_ready.append(dep_idx)
                ready = new_ready

            # Build ordered trace list (by step index for determinism)
            ordered_traces = [traces[i] for i in range(n_steps) if i in traces]

            if self._trace_writer and ordered_traces:
                tl = _build_tracelog(
                    pipeline_run_id, ordered_traces, started_at_iso, pipeline_start, self.config.pipeline_version
                )
                self._trace_writer.write([tl])

            tracelog = _build_tracelog(
                pipeline_run_id, ordered_traces, started_at_iso, pipeline_start, self.config.pipeline_version
            )

            return state, tracelog
        finally:
            # Resource lifecycle: close managed resources at pipeline end (Phase 8.2 readiness)
            res.close()

    # ── Streaming (Phase 8.2a) ──────────────────────────────

    async def _arun_streaming_impl(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
    ) -> AsyncIterator[Any]:
        """Shared streaming implementation. Finds the generator step, runs
        preceding steps through the normal DAG, then streams from the generator.

        8.2a scope: single-link streaming (Generator→User). Multi-node DAG
        streaming propagation is deferred to 8.2b.
        """
        state = dict(initial_state or {})
        res = resources or ResourceContainer()

        gen_idx: Optional[int] = None
        gen_step: Optional[StepConfig] = None
        for i, step in enumerate(self.config.steps):
            if step.component_type == "generator":
                gen_idx = i
                gen_step = step
                break

        if gen_step is None:
            raise PipelineStartupError(
                "No generator step found in pipeline. "
                "run_streaming() requires exactly one step with component_type='generator'."
            )

        try:
            if gen_idx > 0:
                pre_config = PipelineConfig(
                    steps=self.config.steps[:gen_idx],
                    pipeline_version=self.config.pipeline_version,
                    default_timeout_seconds=self.config.default_timeout_seconds,
                )
                pre_runner = PipelineRunner(
                    config=pre_config,
                    step_factories=self._factories,
                    snapshot_policy=self._snapshot_policy,
                    type_compatibility_checker=self._type_checker,
                    initial_keys=self._initial_keys,
                    trace_writer=self._trace_writer,
                    sync_workers=1,
                )
                try:
                    state, _ = await pre_runner.arun(initial_state=state, resources=res)
                finally:
                    pre_runner.close()

            raw_inputs = {key: state.get(key) for key in gen_step.depends_on}
            input_dict = _apply_input_mapping(raw_inputs, gen_step.input_mapping)

            component = self._factories[gen_step.name](gen_step)
            if not hasattr(component, "run_streaming"):
                raise PipelineStartupError(
                    f"Generator step '{gen_step.name}' does not implement "
                    "run_streaming(). Streaming requires the step to have an "
                    "async run_streaming() method."
                )

            async for item in component.run_streaming(input_dict, res):
                yield item
        finally:
            res.close()

    def run_streaming(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
    ) -> Iterator[Any]:
        """Sync entry point for streaming. Collects all stream items via
        asyncio.run(), then yields them as a sync iterator for CLI/Flask callers."""

        async def _collect() -> List[Any]:
            items: List[Any] = []
            async for item in self._arun_streaming_impl(
                initial_state=initial_state, resources=resources
            ):
                items.append(item)
            return items

        items = asyncio.run(_collect())
        yield from items

    async def arun_streaming(
        self,
        initial_state: Optional[Dict[str, Any]] = None,
        resources: Optional[ResourceContainer] = None,
    ) -> AsyncIterator[Any]:
        """Async entry point for streaming. Yields tokens as they arrive,
        suitable for FastAPI/WebSocket streaming endpoints."""
        async for item in self._arun_streaming_impl(
            initial_state=initial_state, resources=resources
        ):
            yield item

    # ── Failure handling ────────────────────────────────────

    def _apply_failure(
        self, step: StepConfig, state: Dict[str, Any], t: StepTrace
    ) -> None:
        if step.on_failure == "abort":
            return  # don't update state
        elif step.on_failure == "skip":
            if step.provides:
                state[step.provides] = _SKIP_SENTINEL
        elif step.on_failure == "default":
            if step.provides:
                state[step.provides] = step.default_value


# ── Internal helpers ─────────────────────────────────────────────


def _apply_input_mapping(
    raw_inputs: Dict[str, Any],
    mapping: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    """Engine-level input routing: remap upstream keys to param names."""
    if not mapping:
        return raw_inputs
    result: Dict[str, Any] = {}
    for from_key, to_key in mapping.items():
        result[to_key] = raw_inputs.get(from_key)
    return result


async def _execute_with_retry(
    component: PipelineStep,
    inputs: Dict[str, Any],
    resources: ResourceContainer,
    timeout: float,
    retry: Optional[RetryPolicy],
    executor: ThreadPoolExecutor,
) -> StepOutput:
    """Execute a step with retry logic and timeout."""
    max_retries = retry.max_retries if retry else 0
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await _dispatch(component, inputs, resources, timeout, executor)
        except Exception as exc:
            last_exc = exc
            if attempt == max_retries:
                raise
            retry_on = retry.retry_on if retry else []
            if not any(
                exc.__class__.__name__ == name for name in retry_on
            ):
                raise
            if retry and retry.backoff == "exponential":
                await asyncio.sleep(0.5 * (2**attempt))
    raise RuntimeError("Unreachable") from last_exc


async def _dispatch(
    component: PipelineStep,
    inputs: Dict[str, Any],
    resources: ResourceContainer,
    timeout: float,
    executor: ThreadPoolExecutor,
) -> StepOutput:
    """Adaptive dispatch (Phase 8.1).

    Calls step.run() — if it's async (returns awaitable), await it directly.
    Falls back to async_run() for backward compat.
    Falls back to a dedicated thread pool for sync run() implementations.
    """
    # Try run() first
    try:
        result_or_coro = component.run(inputs, resources)
    except Exception:
        # If run() doesn't exist or crashes, fall back to async_run()
        if hasattr(component, "async_run") and callable(component.async_run):
            result_or_coro = component.async_run(inputs, resources)
        else:
            raise

    if inspect.isasyncgen(result_or_coro):
        raise TypeError(
            f"Step '{type(component).__name__}.run()' returned an async generator. "
            "Streaming steps must implement 'run_streaming() -> AsyncIterator[StreamItem]'. "
            "Use runner.run_streaming() or runner.arun_streaming() for streaming pipelines."
        )
    if asyncio.iscoroutine(result_or_coro):
        return await asyncio.wait_for(result_or_coro, timeout=timeout)
    # Sync run() — offload to dedicated thread pool (Phase 8.2 readiness)
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(executor, lambda: result_or_coro),
        timeout=timeout,
    )


def _build_tracelog(
    pipeline_run_id: str,
    traces: List[StepTrace],
    started_at_iso: str,
    pipeline_start: float,
    pipeline_version: int,
) -> TraceLog:
    success = sum(1 for t in traces if t.status == "success")
    failed = sum(1 for t in traces if t.status == "failed")
    skipped = sum(1 for t in traces if t.status == "skipped")
    cancelled = sum(1 for t in traces if t.status == "cancelled")
    return TraceLog(
        pipeline_run_id=pipeline_run_id,
        pipeline_version=pipeline_version,
        started_at_iso=started_at_iso,
        finished_at_iso=datetime.now(timezone.utc).isoformat(),
        total_duration_seconds=time.perf_counter() - pipeline_start,
        steps=traces,
        total_steps=len(traces),
        success_count=success,
        failure_count=failed,
        skipped_count=skipped,
        cancelled_count=cancelled,
    )


class PipelineStartupError(Exception):
    """Raised during __init__ when pipeline configuration is structurally invalid."""
