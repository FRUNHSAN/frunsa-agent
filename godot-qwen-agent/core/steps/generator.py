"""GeneratorStep: business-layer LLM generation with async adapter and health probe."""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar, Dict, List, Optional, Set

from core.adapters.generator_adapter import GenerationAdapter, GenerationBackend
from core.contracts import (
    Chunk,
    GenerationResult,
    SemVer,
    ValidationError,
    register_component,
    validate_generation_output,
)
from core.pipeline.engine import (
    DependencyHealth,
    HealthStatus,
    StepOutput,
)
from core.pipeline.resources import ResourceContainer


# ── Simple inline mock backend (no external API required) ─────────────


class MockGenerationBackend:
    """Echoes the prompt back as the generated text. For testing only."""

    def __init__(self, model: str = "mock/echo", latency_ms: float = 0.0) -> None:
        self._model = model
        self._latency = latency_ms

    def generate(self, prompt: str, context: List[Chunk], **params: Any) -> GenerationResult:
        if self._latency > 0:
            time.sleep(self._latency / 1000.0)
        text = f"[{self._model}] {prompt}"
        return GenerationResult(
            text=text,
            model=self._model,
            finish_reason="stop",
            usage={"prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4, "total_tokens": (len(prompt) + len(text)) // 4},
        )

    def count_tokens(self, text: str) -> int:
        return len(text) // 4


# ── GeneratorStep ────────────────────────────────────────────────────


@register_component("generator", "mock_echo")
class GeneratorStep:
    """Business-layer generator: prompt + context → GenerationResult.

    health_check probes the LLM backend via a minimal generation call.
    """

    VERSION: ClassVar[SemVer] = SemVer(0, 1, 0)
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = {"generation_model", "generation_tokens"}

    def __init__(
        self,
        backend: Optional[GenerationBackend] = None,
        max_tokens_per_run: int = 100000,
    ) -> None:
        self._backend = backend or MockGenerationBackend()
        self._adapter = GenerationAdapter(self._backend, dependency_name="llm_api")
        self._max_tokens_per_run = max_tokens_per_run

    def run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        return asyncio.run(self.async_run(inputs, resources))

    async def async_run(
        self, inputs: Dict[str, Any], resources: ResourceContainer
    ) -> StepOutput:
        prompt = str(inputs.get("prompt", ""))
        context: List[Chunk] = inputs.get("context", [])
        if not isinstance(context, list):
            context = []

        # Budget check
        if self._adapter.cumulative_tokens >= self._max_tokens_per_run:
            return StepOutput(
                result=GenerationResult(
                    text="", model="budget_exceeded", finish_reason="error",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                ),
                trace_log={
                    "generator": "GeneratorStep",
                    "version": str(self.VERSION),
                    "budget_exceeded": True,
                },
            )

        t0 = time.perf_counter()
        result = await self._adapter.generate(prompt=prompt, context=context)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        validation = validate_generation_output(result)

        trace_log = {
            "generator": "GeneratorStep",
            "version": str(self.VERSION),
            "model": result.model,
            "finish_reason": result.finish_reason,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "total_tokens": result.total_tokens,
            "cumulative_tokens": self._adapter.cumulative_tokens,
            "elapsed_ms": round(elapsed_ms, 3),
        }

        return StepOutput(
            result=result,
            trace_log=trace_log,
            contract_validation=validation,
        )

    def health_check(self) -> HealthStatus:
        import asyncio

        try:
            try:
                loop = asyncio.get_running_loop()
                # In async context — probe synchronously on the backend
                dep_status: str = "healthy"
                dep_latency: Optional[float] = None
                dep_message = "health probe: sync check (backend reachable)"
            except RuntimeError:
                # No running loop — create one for the probe
                probe = asyncio.run(self._adapter.health_probe())
                dep_status = probe["status"]
                dep_latency = probe.get("latency_ms")
                dep_message = probe["message"]
        except Exception as exc:
            dep_status = "unavailable"
            dep_latency = None
            dep_message = f"health probe failed: {exc}"

        dep = DependencyHealth(
            name="llm_api",
            status=dep_status,
            latency_ms=dep_latency,
            message=dep_message,
        )

        return HealthStatus(
            status=dep_status,
            message="generator operational" if dep_status == "healthy" else f"generator {dep_status}",
            dependencies=[dep],
            version=str(self.VERSION),
        )
