"""Guardrail rule modules — each rule is a function returning List[Violation]."""

from guardrails.rules.cross_platform import cross_platform_imports
from guardrails.rules.frozen_dataclass import frozen_dataclass_integrity
from guardrails.rules.component_registry import component_registration_coverage
from guardrails.rules.chain_coverage import reasoning_chain_coverage
from guardrails.rules.stream_isolation import user_facing_stream_isolation
from guardrails.rules.internal_stream_only import internal_stream_only
from guardrails.rules.transport_adapter_boundary import transport_adapter_boundary
from guardrails.rules.engine_interface_purity import engine_interface_purity
from guardrails.rules.trace_context_namespace import trace_context_namespace

__all__ = [
    "cross_platform_imports",
    "frozen_dataclass_integrity",
    "component_registration_coverage",
    "reasoning_chain_coverage",
    "user_facing_stream_isolation",
    "internal_stream_only",
    "transport_adapter_boundary",
    "engine_interface_purity",
    "trace_context_namespace",
]
