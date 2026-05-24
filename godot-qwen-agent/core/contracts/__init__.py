"""Component contracts: data models, protocols, validation, and unified registry."""

from .chunking import Chunk, ChunkingStrategy, ContentBlock, SemVer
from .identity_chunker import IdentityChunker
from .registry import (
    COMPONENT_REGISTRY,
    ComponentRegistry,
    auto_discover,
    register_component,
    validate_pipeline_steps,
)
from .retrieval import RetrievalResult, RetrievalStrategy
from .validation import ContractValidationResult, ValidationError, validate_chunk_output

__all__ = [
    # Data models
    "Chunk",
    "ContentBlock",
    "SemVer",
    "RetrievalResult",
    # Strategy protocols
    "ChunkingStrategy",
    "RetrievalStrategy",
    # Validation
    "ContractValidationResult",
    "ValidationError",
    "validate_chunk_output",
    # Registry
    "COMPONENT_REGISTRY",
    "ComponentRegistry",
    "register_component",
    "auto_discover",
    "validate_pipeline_steps",
    # Built-in strategies
    "IdentityChunker",
]
