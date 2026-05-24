# System Architecture Evolution White Paper

## godot-qwen-agent: A Contract-Driven, Three-Platform Agent System

**Version**: 1.0
**Date**: 2026-05-24
**Status**: Active — continuously updated as new reasoning chains are archived
**Audience**: New developers, AI agents, and future maintainers inheriting this codebase

---

## 1. Executive Summary

This is a **5-year-scale AI agent platform** rebuilt from a competition-era prototype. The core insight is **"高度分化 + 转译层连通"** (maximum specialization + translation layer connection): three completely independent platforms — Contracts, Pipeline, Adapters — connected only by a thin, strictly-typed adapter layer.

The system currently has **198 tests, 0 failures**, spanning 7 architectural phases. Every non-trivial decision is recorded in the **Reasoning Chain Library** (`.ai_reasoning/chains/`), a machine-readable knowledge base that AI agents MUST consult before writing code.

This document synthesizes all 8 reasoning chains into a coherent narrative: what we built, why we built it that way, what went wrong, and what comes next.

---

## 2. Architectural Philosophy

### 2.1 The Three-Platform Model

```
┌──────────────────────┐     ┌──────────────────────┐
│  core/contracts/     │     │  core/pipeline/      │
│                      │     │                      │
│  • Data models       │     │  • Engine            │
│  • Protocols          │     │  • Tracing           │
│  • Registry           │◄────►  • Resources          │
│  • Validation         │  ɴᴇxᴜs  │  • Config loading     │
│  • SemVer             │  only  │                      │
│                      │     │                      │
│  ZERO pipeline       │     │  ZERO contracts      │
│  imports             │     │  imports             │
└──────────┬───────────┘     └──────────┬───────────┘
           │                            │
           │    ┌──────────────────┐    │
           └───►│ core/adapters/   │◄───┘
                │                  │
                │  • Translation   │
                │  • Type enforcement│
                │  • Factory        │
                │  • Async wrappers │
                │                  │
                │  ONLY layer that │
                │  imports both    │
                └──────────────────┘
```

**Invariant #1**: `core/pipeline/` NEVER imports domain types (`Chunk`, `ContentBlock`, `RetrievalResult`). It knows only the `PipelineStep` Protocol.

**Invariant #2**: `core/contracts/` NEVER imports orchestration types (`PipelineRunner`, `StepConfig`, `ResourceContainer`). It knows only data shapes and validation rules.

**Shared infrastructure types** (`SemVer`, `HealthStatus`) are the only legitimate cross-platform wiring — they are not domain types, they are language-level utilities.

### 2.2 Why This Matters (5-Year Perspective)

Without this separation, every new component type forces engine changes, and every engine upgrade breaks existing components. With it:

- Adding a new component type (Reranker, LLM Generator) requires: (a) a new Protocol in contracts/, (b) an adapter in adapters/, (c) **zero engine changes**
- The engine can be completely rewritten (e.g., from sync to async-native) without touching a single contract
- Each platform can be versioned, tested, and released independently

This is the Dependency Inversion Principle applied at the platform level.

---

## 3. Evolution Timeline

### Phase 1: Foundation (Contracts + Data Integrity)

**Chains**: `phase_01_three_platform`, `phase_01_data_integrity`

The starting point: a competition codebase with tightly-coupled components, mutable dicts, and no separation between "what data looks like" and "how it flows through the system."

**What we built**:
- Three-platform directory structure (`core/contracts/`, `core/pipeline/`, `core/adapters/`)
- `@dataclass(frozen=True)` + `MappingProxyType` for all data models
- `__post_init__` with `deepcopy` defense: callers can pass plain dicts, but stored values are always deep-copied read-only proxies
- `ComponentRegistry`: `{component_type: {strategy_name: cls}}` with `@register_component` decorator
- Strict `SemVer(X.Y.Z)` — rejects loose parsing

**Why frozen dataclasses, not Pydantic**:
- Zero external dependencies — critical for 5-year stability
- `MappingProxyType` is C-level read-only (TypeError on mutation, not silent ignore)
- No v1/v2 migration risk like Pydantic
- `with_metadata()` creates a NEW instance — never mutates in place

**Key anti-pattern prevented**: Step B mutating data that Step A produced, causing Step C to see inconsistent state.

### Phase 2: Pipeline Orchestration (Skip Propagation)

**Chain**: `phase_02_skip_propagation`

**The problem**: What happens when a chunker produces zero chunks (empty document)? Should the pipeline crash, or should downstream steps be skipped?

**What we built**:
- `_SKIP_SENTINEL`: a module-private singleton object
- Identity check via `is` — can NEVER collide with a legitimate result (unlike `None`, `0`, `""`, `[]`)
- Engine-level skip propagation: if any dependency is the sentinel, mark the step as skipped and propagate
- Three failure strategies: `on_failure="abort"`, `"skip"`, `"default"` (with `default_value`)
- Skips are recorded in TraceLog with `status="skipped"` — distinct from "failed"

**Why not use None?**
None is a valid result for some steps. The sentinel eliminates the ambiguity between "no result" and "result is None."

**Why not exceptions for control flow?**
Expensive, mixes error handling with normal operation, linters flag it.

### Phase 3: Translation Layer (Adapters + Factory)

**Chain**: `phase_03_adapter_pattern`

**The problem**: How does the engine (which knows only the `PipelineStep` Protocol) call a domain-specific strategy (which knows `Chunk` → `List[Chunk]`)?

**What we built**:
- `ChunkerAdapter`: wraps `ChunkingStrategy` into `PipelineStep`
- `AdapterTypeError`: distinct exception with expected type, actual type, truncated value (≤200 chars)
- `content_key` extraction: adapter pulls the right field from engine's input dict
- Factory caching: `(component_type, strategy_name, tuple(sorted(params)))` — NO eval/exec
- `_UncacheableError` + `cacheable=False` for stateful strategies (connection pools, counters)

**Why isinstance(), not duck typing?**
`AttributeError: 'str' object has no attribute 'chunk'` at runtime is useless for debugging. `AdapterTypeError` tells the user exactly what went wrong.

**Why not Pydantic validation at the boundary?**
Adds a dependency to the translation layer. isinstance() is instantaneous, dependency-free, and unambiguous.

### Phase 4: Observability (Tracing + Health + Snapshots)

**Chain**: `phase_04_observability`

**The problem**: After Phases 1-3, the pipeline runs — but when it fails at step 7 of 12, there's zero evidence about what steps 1-6 did.

**What we built**:
- `TraceLog` + `StepTrace` dataclasses with `pipeline_run_id` (UUID)
- `SnapshotPolicy`: `FULL` (complete serialization), `SUMMARY` (blake2b hash + structural fingerprint), `NONE` (no data retained)
- `DependencyCallTrace`: per-external-call tracing (HTTP, gRPC, DB query)
- `DependencyHealth`: per-dependency status (healthy/degraded/unavailable) with latency_ms
- `HealthStatus`: aggregates multiple DependencyHealth entries
- Pluggable `TraceWriter` Protocol — ship `LocalJSONWriter` now, swap for Kafka/S3 later
- Three-level error severity: `error` (blocks pipeline), `warning` (logged, continues), `info` (audit only)

**Why not OpenTelemetry?**
Heavy dependency designed for microservices. Our custom TraceLog fits the DAG model exactly, with SnapshotPolicy as a first-class concept.

**Phase 4.5 — Operational Contract Hardening**:
This was explicitly prioritized BEFORE adding more external I/O. The lesson: harden observability before adding complexity.

### Phase 5: External I/O (Retriever + Vector Store)

**Chain**: `phase_05_external_io`

**The problem**: The first real external dependency — a vector database. This was the first test of whether the three-platform architecture actually works against real-world complexity.

**What we built**:
- `VectorStoreBackend` Protocol + `VectorStoreAdapter` (async wrapper)
- `InMemoryVectorBackend`: deterministic cosine-similarity backend for testing
- `RetrieverStep`: `@register_component("retriever", "simple_cosine")`
- Async adapter with `run_in_executor` + `asyncio.wait_for` + timeout

**Two critical bugs discovered during negative testing**:

| Bug | Symptom | Root Cause | Fix |
|-----|---------|------------|-----|
| Event loop crash | `health_check()` crashed in sync context (pytest) | `asyncio.get_event_loop()` raises RuntimeError in Python 3.10+ when no loop is running | `get_running_loop()` + `asyncio.run()` fallback |
| Swallowed exceptions | health probe reported "degraded" when backend crashed | `search()` catches exceptions → returns `[]`, probe only checked `if results:` | Inspect `last_trace.status` before interpreting empty results |

**These bugs validated the entire approach**: negative testing (shift-left) caught them before a single real vector database was connected.

**The reusable pattern** for ALL future I/O adapters:
1. Adapter catches exceptions internally → returns graceful defaults
2. Adapter sets `self._last_trace` with error status
3. `health_probe()` inspects `last_trace.status` BEFORE interpreting empty results
4. Step's `health_check()` uses `get_running_loop()` + `asyncio.run()` fallback

### Phase 6: Reasoning Chain Library (AI Self-Iteration)

**Chains**: (meta-chains — the library itself)

**The problem**: How does an AI agent know what NOT to do when modifying this codebase 2 years from now?

**What we built**:
- `.ai_reasoning/` directory with JSON Schema-validated YAML chains
- Each chain records: context → alternatives → decision → rationale → evidence → future_guidance → anti_patterns
- `index.yaml`: global index with tag-based lookup
- `CLAUDE.md`: AI Collaboration Protocol — mandatory Read → Code → Archive workflow
- 26 verification tests proving the library is "alive" (Pre-Coding, Anti-pattern, Post-Coding, Closed-Loop)

**The AI Collaboration Protocol**:
1. **Pre-Coding** (MANDATORY): Read index → find relevant chains → read future_guidance + anti_patterns
2. **In-Coding**: Never violate listed anti_patterns; reuse established patterns
3. **Post-Coding** (MANDATORY after complex work): Write new chain → update index → run full test suite

### Phase 7: LLM Generator + Reranker

**Chains**: `phase_07_llm_risks`, `phase_07_implementation_reality`

**Pre-Coding (Phase 7.0)**: 7 anti-patterns defined BEFORE implementation began:
1. Hardcoding API keys → use ResourceContainer
2. Synchronous HTTP → async run_in_executor
3. Unhandled JSON parse errors → validate_generation_output
4. Real APIs in tests → mock backends
5. Full prompt in TraceLog → SnapshotPolicy.SUMMARY
6. Fake health_check → probe provider endpoint
7. Reranker output > input → contract violation

**Implementation (Phase 7.1)**: GenerationAdapter, ScoringAdapter, GeneratorStep, RerankerStep, both with built-in mock backends.

**Post-Coding (Phase 7.2)**: Three discoveries the pre-analysis missed:

1. **Frozen dataclass collision**: Re-ranking creates NEW `RetrievalResult` instances — `object.__setattr__` on frozen is blocked. The immutability chain (`phase_01_data_integrity`) proved its value: what looked like an inconvenience was actually protecting data integrity.

2. **Two-layer budget enforcement**: Adapter tracks cumulative tokens (read-only), Step enforces `max_tokens_per_run`. This split is correct per the platform architecture but subtle — putting budget logic in the adapter would violate the "adapter is translation, step is business logic" separation.

3. **Type-specific safe empty values**: Each component type has its own "safe empty" format — `GenerationResult(finish_reason="error")` for generator, `[]` for reranker/retriever/chunker. The principle is uniform (return a valid instance of the expected type) even though the concrete type differs.

**Full pipeline integration (Phase 7.3)**: Chunker → Retriever → Reranker → Generator — all 4 component types in a single pipeline, 13 integration tests.

---

## 4. Key Design Decisions & Trade-offs

| Decision | Why We Chose It | The Risk We Accepted |
|----------|----------------|---------------------|
| Frozen dataclasses over Pydantic | Zero deps, 5-year stability | No built-in JSON Schema generation |
| Custom TraceLog over OpenTelemetry | Exact DAG fit, SnapshotPolicy first-class | Not interoperable without export adapter |
| `_SKIP_SENTINEL` over None/exceptions | No collision risk, no exception overhead | Engine-internal detail; steps must never return it |
| `isinstance()` over duck typing | Instant, unambiguous error messages | Must add new isinstance branches for new types |
| `asyncio.run()` per step call (not async-native engine) | Simpler mental model, sync-safe | Overhead of loop creation per step; future async-native rewrite possible |
| Protocol classes over ABC | Lightweight, structural subtyping | No runtime enforcement without additional checking |
| Mock backends over recorded HTTP (VCR) | Deterministic, zero network, latency-configurable | May miss real API quirks; need separate integration environment |
| YAML reasoning chains over code comments | Machine-readable, schema-validated, AI-queryable | Requires discipline to maintain; can rot if not updated |

---

## 5. Current System Metrics

| Metric | Value |
|--------|-------|
| Total tests | **198** |
| Test pass rate | **100%** (0 failures) |
| Reasoning chains | **8** (7 phases + 1 implementation reality) |
| Core platform files | **~25** across contracts/adapters/pipeline |
| Component types registered | **4** (chunker, retriever, reranker, generator) |
| Adapter types | **5** (ChunkerAdapter, VectorStoreAdapter, GenerationAdapter, ScoringAdapter, factory) |
| External dependencies | **0** (stdlib-only in core/) |
| Python compatibility | 3.10+ (uses `get_running_loop()`, `MappingProxyType`) |

---

## 6. Known Pain Points & Risks

### 6.1 Architectural Risks

**1. Async engine is "sync wrapping async"**
Each step's `run()` calls `asyncio.run(self.async_run(...))`. This creates and destroys an event loop per step. For a 4-step pipeline, that's 4 loop creations. Currently acceptable (~0.3s total pipeline time), but will become a bottleneck at scale. The engine should eventually become async-native: `async def run_pipeline()` with a single event loop.

**2. No streaming support**
All adapters are request-response. For LLM generation, streaming is essential for UX (user sees tokens as they arrive). The current `GenerationBackend.generate()` returns a complete `GenerationResult` — no `AsyncIterator[str]` in the protocol. Adding streaming requires: (a) a new `StreamingGenerationBackend` Protocol, (b) SSE/WebSocket transport in the adapter, (c) streaming-aware StepOutput that can carry an async generator.

**3. Cross-step type incompatibility**
Retriever returns `List[RetrievalResult]` but Reranker expects `List[Chunk]`. In the full pipeline test, both use the original `chunks` from the chunker — they don't actually chain retriever→reranker. A real RAG pipeline needs the reranker to accept `List[RetrievalResult]` and extract `.chunk` from each. This is a contract gap, not a bug.

**4. No pipeline-level retry/backoff for idempotent steps**
RetryPolicy exists per-step but there's no pipeline-level "retry from step N" mechanism. If the generator fails due to a transient API error, you must re-run the entire pipeline.

**5. Factory caching key is fragile**
`(component_type, strategy_name, tuple(sorted(params)))` — params order matters for the tuple but not semantically. `sorted()` handles key ordering, but two dicts with same keys in different order produce different cache keys. The `tuple(sorted(params.items()))` pattern mitigates this but doesn't handle nested dicts.

### 6.2 Test Coverage Gaps

**6. No async-native pipeline test**
All tests run synchronously via `asyncio.run()`. There's no test that verifies behavior when steps run concurrently in a shared event loop (which is what a future async-native engine would do).

**7. No memory/resource leak tests**
`ResourceContainer.register_managed()` supports cleanup callbacks, but there's no test that verifies resources are actually released after pipeline completion. A long-running agent process could accumulate connection pool leaks.

**8. No large-scale stress tests**
All tests use ≤10 chunks. The system has never been tested with 10,000 chunks in the vector store or 1,000-step pipelines. The `SnapshotPolicy.FULL` could OOM on a large pipeline state.

### 6.3 Codebase Health

**9. Legacy code still present**
The `components/`, `data_loader/`, `backend/`, and `benchmark/` directories are competition-era code that coexists with the new core platform. They use different patterns (mutable dataclasses, direct imports). This is a migration-in-progress, not a clean split.

**10. No CI/CD pipeline**
All tests run locally. There's no GitHub Actions, no pre-commit hooks, no automated reasoning chain validation on push. The CLAUDE.md protocol is human-enforced, not machine-enforced.

**11. No versioned releases**
While SemVer exists for components, there's no overall system version, no CHANGELOG, no deprecation policy. The reasoning chains are the closest thing to a changelog.

---

## 7. Future Evolution Roadmap

### Short-term (Phase 8-9)

| Priority | Task | Rationale |
|----------|------|-----------|
| **P0** | Async-native engine | Eliminates per-step event loop overhead; enables concurrent step execution |
| **P0** | Streaming generator support | Blocking gap for real LLM UX |
| **P1** | Cross-step type bridge (RetrievalResult → Chunk extraction in reranker) | Fixes the retriever→reranker chain gap |
| **P1** | CI/CD with automated reasoning chain validation | Prevents architectural drift |
| **P2** | Real LLM backend (OpenAI/Anthropic adapter) | First real external API integration |
| **P2** | Real reranker backend (Cohere/Cross-encoder adapter) | First real scoring API integration |

### Medium-term (Phase 10-12)

| Priority | Task | Rationale |
|----------|------|-----------|
| **P1** | Pipeline-level retry with checkpoint/resume | Handles transient API failures without full re-run |
| **P1** | Memory/resource leak tests | Prevent production accumulation issues |
| **P2** | Large-scale stress tests (10K+ chunks) | Verify scalability assumptions |
| **P2** | Structured output mode for generator (JSON mode) | Required for tool-calling agents |
| **P3** | OpenTelemetry export adapter for TraceLog | Interop with existing observability platforms |

### Long-term (Year 2-5)

| Priority | Task | Rationale |
|----------|------|-----------|
| **P2** | Clean removal of legacy components/ directory | Complete the migration |
| **P2** | Multi-agent pipeline (parallel branches in DAG) | Enable ensemble strategies |
| **P3** | Pipeline versioning + migration tooling | Safe evolution of pipeline configs |
| **P3** | Real-time pipeline visualization dashboard | Debugging complex DAG executions |

---

## 8. Onboarding Guide

### For a New Human Developer

**Read order**:
1. This whitepaper (you're reading it)
2. `CLAUDE.md` — the AI Collaboration Protocol
3. `.ai_reasoning/index.yaml` — find chains relevant to your task
4. At minimum, read these 3 chains before writing any code:
   - `phase_01_three_platform` (the architecture)
   - `phase_01_data_integrity` (how data models work)
   - `phase_03_adapter_pattern` (how to add new components)

**Key files to understand first**:
- `core/contracts/chunking.py` — the simplest data model; understand how frozen + MappingProxyType works
- `core/pipeline/engine.py` — the PipelineStep Protocol and PipelineRunner
- `core/adapters/chunker_adapter.py` — the simplest adapter; template for all new adapters
- `core/steps/retriever.py` — a complete step with health_check, async adapter, and mock backend

**Before your first PR**:
- Run `pytest tests/ -q` — all 198 tests must pass
- Check if your change warrants a new reasoning chain (did you choose between ≥2 approaches?)
- Verify no cross-platform import violations (see CLAUDE.md invariants table)

### For a New AI Agent

**Mandatory protocol** (from `CLAUDE.md`):

1. **Read `.ai_reasoning/index.yaml`** — find chains matching your task's domain by tag
2. **Load matching chain files** — read `future_guidance` and `anti_patterns`
3. **Reference specific chain_ids** in your design explanation
4. **Never violate listed anti_patterns**
5. **After completing complex work**: write a new chain, update index.yaml, run full test suite

**Architectural invariants — never violate these**:

| # | Rule | Source Chain |
|---|------|-------------|
| 1 | `core/pipeline/` NEVER imports domain types | phase_01_three_platform |
| 2 | `core/contracts/` NEVER imports orchestration types | phase_01_three_platform |
| 3 | All data models use `@dataclass(frozen=True)` + `MappingProxyType` | phase_01_data_integrity |
| 4 | Adapters raise `AdapterTypeError` on type mismatch — NEVER coerce | phase_03_adapter_pattern |
| 5 | Factory cache keys use `(type, strategy, tuple(sorted(params)))` — NO eval/exec | phase_03_adapter_pattern |
| 6 | Empty results = `StepOutput(result=[])` (success), NOT sentinel | phase_02_skip_propagation |
| 7 | Every I/O adapter's `health_probe()` checks `last_trace.status` | phase_05_external_io |
| 8 | `health_check()` uses `get_running_loop()` + `asyncio.run()` fallback | phase_05_external_io |
| 9 | `DependencyHealth` declared for every external dependency | phase_04_observability |
| 10 | `DependencyCallTrace` injected for every external call | phase_04_observability |

---

## 9. Appendix: All Reasoning Chains

| Chain ID | Title | Layer | Status |
|----------|-------|-------|--------|
| `phase_01_three_platform` | Three-platform architecture | foundation | active |
| `phase_01_data_integrity` | Immutable data models | contracts | active |
| `phase_02_skip_propagation` | Empty-result skip semantics | pipeline | active |
| `phase_03_adapter_pattern` | Strict adapter pattern | adapters | active |
| `phase_04_observability` | Observability contracts | pipeline | active |
| `phase_05_external_io` | External I/O pattern | adapters | active |
| `phase_07_llm_risks` | LLM/Reranker risk pre-analysis | adapters | active |
| `phase_07_implementation_reality` | LLM/Reranker implementation reality | adapters | active |

**Tag index**: `architecture`, `data_model`, `immutability`, `pipeline`, `skip`, `adapter`, `protocol`, `observability`, `health_check`, `external_io`, `async`, `exception_handling`, `llm`, `reranker`, `generation`, `anti_patterns`, `frozen_dataclass`, `budget`, `graceful_degradation`, `mock_backend`

---

*This whitepaper is a living document. After each major phase, update Section 3 (Evolution Timeline) and Section 5 (Current Metrics). After discovering new pain points, update Section 6. The reasoning chain library is the source of truth — this document is a synthesis.*
