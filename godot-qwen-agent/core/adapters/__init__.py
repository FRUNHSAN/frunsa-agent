"""Translation layer: bridges component contracts and pipeline engine.

The only package that imports from both core.contracts and core.pipeline.
"""

from .chunker_adapter import AdapterTypeError, ChunkerAdapter
from .composer import AssemblyError, PipelineAssembler, PipelineComposer, SourceRouter
from .event_sink import ContractAwareEventSink
from .factory import create_step_factory
from .generator_adapter import GenerationAdapter, GenerationBackend, StreamingBackend
from .reranker_adapter import ScoringAdapter, ScoringBackend
from .stream_adapter import (
    AsyncDataStreamAdapter,
    JsonRpc20Serializer,
    PaceShapingWrapper,
)
from .vector_store import VectorStoreAdapter, VectorStoreBackend

__all__ = [
    # Core adapters
    "ChunkerAdapter",
    "GenerationAdapter",
    "ScoringAdapter",
    "VectorStoreAdapter",
    # Cloud-native adapters
    "AsyncDataStreamAdapter",
    # Backend protocols
    "GenerationBackend",
    "StreamingBackend",
    "ScoringBackend",
    "VectorStoreBackend",
    # Serialization
    "JsonRpc20Serializer",
    # Pace shaping
    "PaceShapingWrapper",
    # Common
    "AdapterTypeError",
    "create_step_factory",
    # Grammar engines (Phase 19)
    "AssemblyError",
    "ContractAwareEventSink",
    "PipelineAssembler",
    "PipelineComposer",
    "SourceRouter",
]
