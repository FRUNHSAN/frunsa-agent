"""Business-agnostic pipeline orchestration engine.

The engine knows nothing about specific component types (chunker, retriever, tool).
It only recognises the uniform PipelineStep protocol.
"""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
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
    stream: Optional[Iterator[Any]] = None  # v2 reserved for streaming
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
class HealthStatus:
    status: Literal["healthy", "degraded", "unavailable"]
    message: str = ""
    details: Optional[Dict[str, Any]] = None


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
    ) -> None:
        self.config = config
        self._factories = step_factories
        self._snapshot_policy = snapshot_policy
        self._type_checker = type_compatibility_checker
        self._trace_writer = trace_writer
        self._initial_keys: Set[str] = set(initial_keys or []) | {"original_query"}
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
        """Async core. Future service endpoints (FastAPI/gRPC) use this directly."""
        pipeline_run_id = str(uuid.uuid4())
        state = dict(initial_state or {})
        res = resources or ResourceContainer()
        traces: List[StepTrace] = []
        started_at_iso = datetime.now(timezone.utc).isoformat()
        pipeline_start = time.perf_counter()
        cancel_requested = False

        with res:
            for idx, step in enumerate(self.config.steps):
                if cancel_requested:
                    break

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

                # Skip propagation check
                if any(
                    state.get(dep) is _SKIP_SENTINEL for dep in step.depends_on
                ):
                    t.status = "skipped"
                    if step.provides:
                        state[step.provides] = _SKIP_SENTINEL
                    t.finished_at = time.perf_counter()
                    t.duration_seconds = 0.0
                    traces.append(t)
                    if on_step:
                        cancel_req = on_step(t)
                        if cancel_req:
                            cancel_requested = True
                            break
                    continue

                # Build input_dict with input_mapping if configured
                raw_inputs = {key: state.get(key) for key in step.depends_on}
                input_dict = _apply_input_mapping(raw_inputs, step.input_mapping)
                t.input_snapshot = snapshot(input_dict, self._snapshot_policy)

                timeout = step.timeout_seconds or self.config.default_timeout_seconds
                retry = step.retry_policy

                try:
                    component = self._factories[step.name](step)
                    output = await _execute_with_retry(
                        component, input_dict, res, timeout, retry
                    )
                    state[step.provides] = output.result
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
                traces.append(t)

                if on_step:
                    cancel_req = on_step(t)
                    if cancel_req:
                        cancel_requested = True
                        break

            # Mark remaining steps as cancelled
            if cancel_requested and traces:
                for remain_idx in range(traces[-1].step_index + 1, len(self.config.steps)):
                    remaining = StepTrace(
                        step_index=remain_idx,
                        step_name=self.config.steps[remain_idx].name,
                        pipeline_run_id=pipeline_run_id,
                        status="cancelled",
                        started_at=time.perf_counter(),
                        finished_at=time.perf_counter(),
                        duration_seconds=0.0,
                    )
                    traces.append(remaining)

        if self._trace_writer and traces:
            tl = _build_tracelog(
                pipeline_run_id, traces, started_at_iso, pipeline_start, self.config.pipeline_version
            )
            self._trace_writer.write([tl])

        return state, _build_tracelog(
            pipeline_run_id, traces, started_at_iso, pipeline_start, self.config.pipeline_version
        )

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
) -> StepOutput:
    """Execute a step with retry logic and timeout."""
    max_retries = retry.max_retries if retry else 0
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await _dispatch(component, inputs, resources, timeout)
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
) -> StepOutput:
    """Adaptive dispatch: prefer async_run, fall back to run() in a thread."""
    if hasattr(component, "async_run") and callable(component.async_run):
        coro: Awaitable[StepOutput] = component.async_run(inputs, resources)
    else:
        coro = asyncio.to_thread(component.run, inputs, resources)
    return await asyncio.wait_for(coro, timeout=timeout)


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
