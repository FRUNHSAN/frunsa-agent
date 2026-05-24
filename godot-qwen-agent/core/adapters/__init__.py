"""Translation layer: bridges component contracts and pipeline engine.

The only package that imports from both core.contracts and core.pipeline.
"""

from .chunker_adapter import AdapterTypeError, ChunkerAdapter
from .factory import create_step_factory

__all__ = [
    "ChunkerAdapter",
    "AdapterTypeError",
    "create_step_factory",
]
