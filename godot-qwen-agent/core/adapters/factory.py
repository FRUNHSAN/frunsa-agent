"""Translation-layer factory: the only code that knows about both platforms.

Routes component_type → PipelineStep via ComponentRegistry.
Thin, mechanical, no business logic. Safe tuple-based caching — zero eval() risk.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, Tuple

from core.contracts import COMPONENT_REGISTRY
from core.pipeline.engine import PipelineStep, StepConfig

from .chunker_adapter import ChunkerAdapter


def _make_cache_key(
    component_type: str, strategy_name: str, params: Dict[str, Any]
) -> Tuple[str, str, Tuple[Tuple[str, Any], ...]]:
    """Safe cache key: tuple of sorted items. No eval(), no code execution."""
    return (component_type, strategy_name, tuple(sorted(params.items())))


@lru_cache(maxsize=128)
def _cached_create(cache_key: Tuple[str, str, Tuple[Tuple[str, Any], ...]]) -> PipelineStep:
    """Cached instance creation for stateless strategies.

    cache_key = (component_type, strategy_name, ((k1,v1), (k2,v2), ...))
    Params reconstructed via dict() — no exec/eval.
    """
    component_type, strategy_name, params_tuple = cache_key
    params = dict(params_tuple)

    cls = COMPONENT_REGISTRY.get(component_type, strategy_name)
    if not getattr(cls, "cacheable", True):
        raise _UncacheableError(component_type, strategy_name)

    instance = cls(**params)
    return ChunkerAdapter(instance)


class _UncacheableError(Exception):
    """Internal signal: strategy declares cacheable=False, needs fresh instance."""

    def __init__(self, component_type: str, strategy_name: str) -> None:
        self.component_type = component_type
        self.strategy_name = strategy_name
        super().__init__(
            f"Strategy '{strategy_name}' ({component_type}) is not cacheable"
        )


def create_step_factory(step: StepConfig) -> PipelineStep:
    """Single entry point connecting both platforms. Pure routing — no business logic."""
    cache_key = _make_cache_key(step.component_type, step.strategy, step.params)
    try:
        return _cached_create(cache_key)
    except _UncacheableError as e:
        cls = COMPONENT_REGISTRY.get(e.component_type, e.strategy_name)
        instance = cls(**step.params)
        return ChunkerAdapter(instance)
