"""Component contracts: data models, protocols, validation, and unified registry."""

from .chunking import Chunk, ChunkingStrategy, ContentBlock, SemVer
from .composition import (
    AssemblyDiagnostic,
    CompositionBlueprint,
    CompositionEvent,
    SourceRule,
)
from .generation import GenerationResult, GenerationStrategy, StreamItem
from .identity_chunker import IdentityChunker
from .registry import (
    COMPONENT_REGISTRY,
    ComponentRegistry,
    auto_discover,
    register_component,
    validate_pipeline_steps,
)
from .retrieval import RetrievalResult, RetrievalStrategy
from .scoring import ScoringStrategy
from .trace_keys import (
    COMPONENT_TRACE_KEYS,
    ComponentTraceKeyDef,
    validate_component_trace,
)
from .streaming_protocol import (
    PaceConfig,
    SerializationFormat,
    TransportBackend,
)
from .validation import (
    ContractValidationResult,
    ValidationError,
    validate_chunk_output,
    validate_generation_output,
    validate_reranker_output,
    validate_stream_output,
)

__all__ = [
    # Data models
    "Chunk",
    "ContentBlock",
    "SemVer",
    "RetrievalResult",
    "GenerationResult",
    "StreamItem",
    # Composition contracts (Phase 19)
    "AssemblyDiagnostic",
    "CompositionBlueprint",
    "CompositionEvent",
    "SourceRule",
    # Strategy protocols
    "ChunkingStrategy",
    "RetrievalStrategy",
    "GenerationStrategy",
    "ScoringStrategy",
    # Validation
    "ContractValidationResult",
    "ValidationError",
    "validate_chunk_output",
    "validate_generation_output",
    "validate_reranker_output",
    "validate_stream_output",
    # Registry
    "COMPONENT_REGISTRY",
    "ComponentRegistry",
    "register_component",
    "auto_discover",
    "validate_pipeline_steps",
    # Built-in strategies
    "IdentityChunker",
    # Cloud-native streaming protocol
    "PaceConfig",
    "SerializationFormat",
    "TransportBackend",
    # Component trace contracts
    "ComponentTraceKeyDef",
    "COMPONENT_TRACE_KEYS",
    "validate_component_trace",
]
