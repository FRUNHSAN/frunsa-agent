"""Engine registry — one package per engine type.

Each engine is a consumer of the core platform (core.contracts, core.adapters).
Engines do NOT extend or modify core internals — they use the public API
(AsyncDataStreamAdapter, StreamItem, PaceConfig) to plug into the pipeline.

N=3 engines: planning, rag, orchestration (Phase 14).
"""
