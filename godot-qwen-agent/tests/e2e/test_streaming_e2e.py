"""Phase 8.2a: Streaming E2E tests — StreamItem, MockStreamingBackend,
GenerationAdapter.generate_stream(), GeneratorStep.run_streaming(),
PipelineRunner.run_streaming()/arun_streaming(), and validate_stream_output().
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType
from typing import Any, Dict, List

import pytest

from core.adapters.generator_adapter import GenerationAdapter
from core.contracts import (
    Chunk,
    GenerationResult,
    StreamItem,
    validate_stream_output,
)
from core.contracts.validation import ContractValidationResult
from core.pipeline.engine import (
    PipelineConfig,
    PipelineRunner,
    PipelineStartupError,
    StepConfig,
    _dispatch,
)
from core.pipeline.resources import ResourceContainer
from core.steps.generator import GeneratorStep, MockGenerationBackend, MockStreamingBackend


# ── Helpers ──────────────────────────────────────────────────────────


def _make_pipeline_config(
    steps: List[StepConfig],
    pipeline_version: int = 1,
    timeout: float = 60.0,
) -> PipelineConfig:
    return PipelineConfig(
        steps=steps,
        pipeline_version=pipeline_version,
        default_timeout_seconds=timeout,
    )


def _step_factories() -> Dict[str, Any]:
    """Return a factory dict that knows how to build GeneratorStep."""

    def _build_generator(config: StepConfig) -> GeneratorStep:
        backend = MockStreamingBackend(model="mock/stream")
        return GeneratorStep(backend=backend)

    def _build_mock_echo(config: StepConfig) -> GeneratorStep:
        return GeneratorStep(backend=MockGenerationBackend(model="mock/echo"))

    return {
        "generate": _build_generator,
        "generate_echo": _build_mock_echo,
    }


# ── TestStreamItemContract ────────────────────────────────────────────


class TestStreamItemContract:
    """StreamItem dataclass: frozen, defaults, MappingProxyType."""

    def test_frozen_prevents_mutation(self):
        item = StreamItem(delta="hello", index=0)
        with pytest.raises(Exception):
            item.delta = "world"  # type: ignore[misc]

    def test_defaults(self):
        item = StreamItem(delta="", index=0)
        assert item.finish_reason is None
        assert item.model == ""

    def test_metadata_is_mappingproxy(self):
        item = StreamItem(delta="x", index=1, metadata={"key": "val"})
        assert isinstance(item.metadata, MappingProxyType)

    def test_finish_reason_set_on_terminal(self):
        item = StreamItem(delta="end", index=5, finish_reason="stop")
        assert item.finish_reason == "stop"

    def test_index_sequential_across_items(self):
        items = [
            StreamItem(delta="a", index=0),
            StreamItem(delta="b", index=1, finish_reason="stop"),
        ]
        assert items[0].index == 0
        assert items[1].index == 1
        assert items[1].finish_reason == "stop"


# ── TestMockStreamingBackend ──────────────────────────────────────────


class TestMockStreamingBackend:
    """MockStreamingBackend: word-by-word yield, empty prompt, sequential indexes."""

    def test_yields_one_stream_item_per_word(self):
        backend = MockStreamingBackend(model="mock/stream")
        items = list(backend.generate_stream("hello world foo", context=[]))
        assert len(items) == 3
        assert items[0].delta == "hello"
        assert items[1].delta == " world"
        assert items[2].delta == " foo"

    def test_empty_prompt_yields_single_item(self):
        backend = MockStreamingBackend()
        items = list(backend.generate_stream("", context=[]))
        assert len(items) == 1
        assert items[0].delta == ""
        assert items[0].finish_reason == "stop"

    def test_whitespace_only_prompt(self):
        backend = MockStreamingBackend()
        items = list(backend.generate_stream("   ", context=[]))
        assert len(items) == 1
        assert items[0].finish_reason == "stop"

    def test_last_item_has_finish_reason(self):
        backend = MockStreamingBackend(model="mock/stream")
        items = list(backend.generate_stream("one two", context=[]))
        assert items[-1].finish_reason == "stop"
        assert all(i.finish_reason is None for i in items[:-1])

    def test_indexes_are_sequential(self):
        backend = MockStreamingBackend()
        items = list(backend.generate_stream("a b c d", context=[]))
        for i, item in enumerate(items):
            assert item.index == i

    def test_generate_method_still_works(self):
        backend = MockStreamingBackend(model="mock/stream")
        result = backend.generate("test prompt", context=[])
        assert isinstance(result, GenerationResult)
        assert result.model == "mock/stream"

    def test_count_tokens(self):
        backend = MockStreamingBackend()
        assert backend.count_tokens("hello world") == 2


# ── TestGenerationAdapterStreaming ────────────────────────────────────


class TestGenerationAdapterStreaming:
    """GenerationAdapter.generate_stream(): bridge path, fallback path, token tracking."""

    def test_streaming_backend_path_yields_stream_items(self):
        async def _test():
            backend = MockStreamingBackend(model="mock/stream")
            adapter = GenerationAdapter(backend, dependency_name="test_llm")
            items = [item async for item in adapter.generate_stream(prompt="hello world")]
            assert len(items) >= 1
            for item in items:
                assert isinstance(item, StreamItem)

        asyncio.run(_test())

    def test_fallback_to_generate_when_no_stream_method(self):
        """Backend without generate_stream() falls back to single StreamItem."""
        async def _test():
            backend = MockGenerationBackend(model="mock/echo")
            adapter = GenerationAdapter(backend, dependency_name="test_llm")
            items = [item async for item in adapter.generate_stream(prompt="hello")]
            assert len(items) == 1
            assert isinstance(items[0], StreamItem)
            assert items[0].index == 0
            assert items[0].finish_reason == "stop"

        asyncio.run(_test())

    def test_cumulative_tokens_tracked(self):
        async def _test():
            backend = MockStreamingBackend(model="mock/stream")
            adapter = GenerationAdapter(backend, dependency_name="test_llm")
            before = adapter.cumulative_tokens
            async for _ in adapter.generate_stream(prompt="hello world foo bar baz"):
                pass
            assert adapter.cumulative_tokens > before

        asyncio.run(_test())

    def test_stream_items_have_model(self):
        async def _test():
            backend = MockStreamingBackend(model="mock/stream")
            adapter = GenerationAdapter(backend, dependency_name="test_llm")
            items = [item async for item in adapter.generate_stream(prompt="test")]
            for item in items:
                assert item.model == "mock/stream"

        asyncio.run(_test())

    def test_sequential_indexes_from_stream_backend(self):
        async def _test():
            backend = MockStreamingBackend(model="mock/stream")
            adapter = GenerationAdapter(backend, dependency_name="test_llm")
            items = [item async for item in adapter.generate_stream(prompt="a b c d e")]
            for i, item in enumerate(items):
                assert item.index == i

        asyncio.run(_test())


# ── TestGeneratorStepStreaming ────────────────────────────────────────


class TestGeneratorStepStreaming:
    """GeneratorStep.run_streaming(): yields tokens, budget exceeded, adapter delegation."""

    def test_run_streaming_yields_items(self):
        async def _test():
            step = GeneratorStep(backend=MockStreamingBackend(model="mock/stream"))
            items = [
                item
                async for item in step.run_streaming(
                    inputs={"prompt": "hello world"}, resources=ResourceContainer()
                )
            ]
            assert len(items) >= 1
            for item in items:
                assert isinstance(item, StreamItem)

        asyncio.run(_test())

    def test_budget_exceeded_yields_error_item(self):
        async def _test():
            step = GeneratorStep(
                backend=MockStreamingBackend(model="mock/stream"),
                max_tokens_per_run=0,
            )
            items = [
                item
                async for item in step.run_streaming(
                    inputs={"prompt": "hello"}, resources=ResourceContainer()
                )
            ]
            assert len(items) == 1
            assert items[0].finish_reason == "error"
            assert items[0].model == "budget_exceeded"

        asyncio.run(_test())

    def test_run_streaming_with_context_chunks(self):
        async def _test():
            step = GeneratorStep(backend=MockStreamingBackend(model="mock/stream"))
            chunk = Chunk(text="ctx", span=(0, 3), source_strategy="identity")
            items = [
                item
                async for item in step.run_streaming(
                    inputs={"prompt": "test", "context": [chunk]},
                    resources=ResourceContainer(),
                )
            ]
            assert len(items) >= 1

        asyncio.run(_test())

    def test_run_streaming_with_non_list_context(self):
        async def _test():
            step = GeneratorStep(backend=MockStreamingBackend(model="mock/stream"))
            items = [
                item
                async for item in step.run_streaming(
                    inputs={"prompt": "test", "context": "not_a_list"},
                    resources=ResourceContainer(),
                )
            ]
            assert len(items) >= 1

        asyncio.run(_test())

    def test_last_item_has_finish_reason_in_normal_flow(self):
        async def _test():
            step = GeneratorStep(backend=MockStreamingBackend(model="mock/stream"))
            items = [
                item
                async for item in step.run_streaming(
                    inputs={"prompt": "hello world"}, resources=ResourceContainer()
                )
            ]
            assert items[-1].finish_reason is not None

        asyncio.run(_test())


# ── TestPipelineRunnerStreaming ───────────────────────────────────────


class TestPipelineRunnerStreaming:
    """PipelineRunner.run_streaming() / arun_streaming(): full pipeline, detection, errors."""

    def test_run_streaming_full_pipeline(self):
        """Sync entry: run_streaming() yields StreamItems from a complete pipeline."""
        config = _make_pipeline_config(
            steps=[
                StepConfig(
                    name="generate",
                    component_type="generator",
                    strategy="mock_echo",
                    provides="generation",
                    depends_on=["original_query"],
                ),
            ]
        )
        factories = _step_factories()
        with PipelineRunner(config, factories) as runner:
            items = list(
                runner.run_streaming(
                    initial_state={"original_query": "hello world"}
                )
            )
        assert len(items) >= 1
        for item in items:
            assert isinstance(item, StreamItem)

    def test_arun_streaming_full_pipeline(self):
        """Async entry: arun_streaming() yields StreamItems as they arrive."""
        async def _test():
            config = _make_pipeline_config(
                steps=[
                    StepConfig(
                        name="generate",
                        component_type="generator",
                        strategy="mock_echo",
                        provides="generation",
                        depends_on=["original_query"],
                    ),
                ]
            )
            factories = _step_factories()
            with PipelineRunner(config, factories) as runner:
                items = [
                    item
                    async for item in runner.arun_streaming(
                        initial_state={"original_query": "hello async"}
                    )
                ]
            assert len(items) >= 1
            for item in items:
                assert isinstance(item, StreamItem)

        asyncio.run(_test())

    def test_no_generator_step_raises_error(self):
        """Pipeline without a generator step raises PipelineStartupError."""
        config = _make_pipeline_config(steps=[])
        factories: Dict[str, Any] = {}
        with PipelineRunner(config, factories) as runner:
            with pytest.raises(PipelineStartupError, match="No generator step"):
                list(runner.run_streaming())

    def test_arun_streaming_no_generator_raises_error(self):
        async def _test():
            config = _make_pipeline_config(steps=[])
            factories: Dict[str, Any] = {}
            with PipelineRunner(config, factories) as runner:
                with pytest.raises(PipelineStartupError, match="No generator step"):
                    async for _ in runner.arun_streaming():
                        pass

        asyncio.run(_test())

    def test_run_streaming_with_pre_steps(self):
        """Streaming pipeline with steps before the generator."""
        config = _make_pipeline_config(
            steps=[
                StepConfig(
                    name="generate",
                    component_type="generator",
                    strategy="mock_echo",
                    provides="generation",
                    depends_on=["original_query"],
                ),
            ]
        )
        factories = _step_factories()
        with PipelineRunner(config, factories) as runner:
            items = list(
                runner.run_streaming(
                    initial_state={"original_query": "pipeline test"}
                )
            )
        assert len(items) >= 1
        assert all(isinstance(item, StreamItem) for item in items)

    def test_run_streaming_without_context_manager(self):
        """run_streaming() works without using the context manager (manual close)."""
        config = _make_pipeline_config(
            steps=[
                StepConfig(
                    name="generate",
                    component_type="generator",
                    strategy="mock_echo",
                    provides="generation",
                    depends_on=["original_query"],
                ),
            ]
        )
        factories = _step_factories()
        runner = PipelineRunner(config, factories)
        try:
            items = list(
                runner.run_streaming(initial_state={"original_query": "test"})
            )
            assert len(items) >= 1
        finally:
            runner.close()


# ── TestValidateStreamOutput ──────────────────────────────────────────


class TestValidateStreamOutput:
    """validate_stream_output(): valid stream, empty stream, multiple finish, bad indexes."""

    def test_valid_stream_passes(self):
        items = [
            StreamItem(delta="hello", index=0, model="m"),
            StreamItem(delta=" world", index=1, finish_reason="stop", model="m"),
        ]
        result = validate_stream_output(items)
        assert result.passed is True
        assert len(result.errors) == 0

    def test_empty_list_is_error(self):
        result = validate_stream_output([])
        assert result.passed is False
        assert any(e.code == "EMPTY_STREAM" for e in result.errors)

    def test_not_a_list_is_error(self):
        result = validate_stream_output("not_a_list")
        assert result.passed is False
        assert any(e.code == "NOT_A_LIST" for e in result.errors)

    def test_multiple_finish_reasons_is_error(self):
        items = [
            StreamItem(delta="a", index=0, finish_reason="stop", model="m"),
            StreamItem(delta="b", index=1, finish_reason="stop", model="m"),
        ]
        result = validate_stream_output(items)
        assert result.passed is False
        assert any(e.code == "MULTIPLE_FINISH" for e in result.errors)

    def test_non_streamitem_warns_or_errors(self):
        items = [
            StreamItem(delta="a", index=0, model="m"),
            "not_a_stream_item",
            StreamItem(delta="b", index=2, finish_reason="stop", model="m"),
        ]
        result = validate_stream_output(items)
        assert not result.passed  # TYPE_MISMATCH errors

    def test_non_sequential_index_warns(self):
        items = [
            StreamItem(delta="a", index=0, model="m"),
            StreamItem(delta="b", index=5, finish_reason="stop", model="m"),
        ]
        result = validate_stream_output(items)
        assert any(w.code == "NON_SEQUENTIAL_INDEX" for w in result.warnings)

    def test_empty_text_warns(self):
        items = [
            StreamItem(delta="", index=0, finish_reason="stop", model="m"),
        ]
        result = validate_stream_output(items)
        assert any(w.code == "EMPTY_STREAM_TEXT" for w in result.warnings)

    def test_item_after_finish_is_error(self):
        items = [
            StreamItem(delta="a", index=0, model="m"),
            StreamItem(delta="b", index=1, finish_reason="stop", model="m"),
            StreamItem(delta="c", index=2, model="m"),
        ]
        result = validate_stream_output(items)
        assert any(e.code == "ITEM_AFTER_FINISH" for e in result.errors)

    def test_no_finish_reason_warns(self):
        items = [
            StreamItem(delta="a", index=0, model="m"),
            StreamItem(delta="b", index=1, model="m"),
        ]
        result = validate_stream_output(items)
        assert any(w.code == "NO_FINISH_REASON" for w in result.warnings)

    def test_returns_contract_validation_result(self):
        items = [StreamItem(delta="ok", index=0, finish_reason="stop", model="m")]
        result = validate_stream_output(items)
        assert isinstance(result, ContractValidationResult)
        assert result.passed is True


# ── TestStreamingAsyncGeneratorGuard ──────────────────────────────────


class TestStreamingAsyncGeneratorGuard:
    """Engine._dispatch() raises TypeError if run() returns an async generator."""

    def test_async_generator_in_run_raises_typeerror(self):
        """If a step's run() returns an async generator, _dispatch raises TypeError."""

        class BadStep:
            async def run(self, inputs, resources):
                yield StreamItem(delta="oops", index=0)

        async def _test():
            executor = ThreadPoolExecutor(max_workers=1)
            try:
                with pytest.raises(TypeError, match="async generator"):
                    await _dispatch(
                        BadStep(), {}, ResourceContainer(), 10.0, executor
                    )
            finally:
                executor.shutdown(wait=True)

        asyncio.run(_test())
