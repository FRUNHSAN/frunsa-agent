# godot-qwen-agent — AI Collaboration Protocol

## Core Directive

This project is a **contract-driven, three-platform agent system**. Every architectural decision is recorded in `.ai_reasoning/`. Before writing any code, you MUST consult the reasoning chain library. After completing complex work, you MUST archive new decisions.

## Mandatory Workflow: Read → Code → Archive

### Phase 1 — Pre-Coding (MANDATORY, block on skip)

Before implementing any feature or fix that touches `core/`:

1. **Read the index**: `.ai_reasoning/index.yaml`
2. **Find relevant chains**: Match your task's domain to the `tag_index`. For example:
   - Adding a new component type → `architecture`, `adapter`
   - Working on pipeline behavior → `pipeline`, `skip`
   - Adding external I/O → `external_io`, `health_check`, `async`
3. **Load matching chain files** from `.ai_reasoning/chains/`
4. **Read `future_guidance` and `anti_patterns`** in each relevant chain
5. **Reference specific chain_ids** in your design explanation (e.g., "per `phase_05_external_io`, the adapter must inspect `last_trace.status`")

If you skip this phase, you WILL violate contracts established through 107 tests and 5 phases of hardening.

### Phase 2 — In-Coding (MANDATORY)

While implementing:

1. **Do NOT violate any `anti_patterns`** listed in relevant chains. If you find yourself tempted by an anti-pattern, stop and re-read the chain that documents why it's forbidden.
2. **Reuse established patterns**, not reinvent:
   - New I/O adapter → Follow `VectorStoreAdapter` pattern (async wrapper, DependencyCallTrace, health_probe with last_trace.status check)
   - New data model → `@dataclass(frozen=True)` + `MappingProxyType` + `__post_init__` deepcopy
   - New pipeline step → `PipelineStep` Protocol, `StepOutput`, `health_check()` returning `HealthStatus`
   - New strategy → `Protocol` class in `core/contracts/`, registered via `@register_component`
3. **Never import across platform boundaries**:
   - `core/pipeline/` MUST NOT import from `core/contracts/`
   - `core/contracts/` MUST NOT import from `core/pipeline/`
   - Only `core/adapters/` may import from both

### Phase 3 — Post-Coding (MANDATORY after complex work)

After completing a non-trivial feature, bug fix with architectural implications, or any work involving trade-offs:

1. **Check if a new reasoning chain is warranted**. Threshold: did you make a choice between ≥2 valid approaches? Did you discover a constraint that wasn't obvious? Did you fix a bug that revealed a design flaw?
2. **Write a new chain** following `schemas/reasoning_chain.schema.json`:
   - Required fields: `chain_id`, `title`, `created_at`, `status`, `context`, `decision`, `rationale`, `future_guidance`
   - Include at least 2 `alternatives`
   - List concrete `evidence` (test file + test case names)
   - Add explicit `anti_patterns`
3. **Update `index.yaml`**: Add entry to `chains` list and `tag_index`
4. **Run the full test suite** (`pytest tests/ -q`) before committing

## Architectural Invariants (derived from .ai_reasoning/)

These are non-negotiable. Violating any of them will break the platform contract.

| # | Rule | Source Chain |
|---|------|-------------|
| 1 | `core/pipeline/` NEVER imports domain types (`Chunk`, `ContentBlock`, `RetrievalResult`); infrastructure types (`SemVer`) are the legitimate wiring | phase_01_three_platform |
| 2 | `core/contracts/` NEVER imports orchestration types (`PipelineRunner`, `StepConfig`, `ResourceContainer`); infrastructure types (`HealthStatus`) are the legitimate wiring | phase_01_three_platform |
| 3 | All data models use `@dataclass(frozen=True)` + `MappingProxyType` | phase_01_data_integrity |
| 4 | Adapters raise `AdapterTypeError` on type mismatch — NEVER coerce | phase_03_adapter_pattern |
| 5 | Factory cache keys use `(type, strategy, tuple(sorted(params)))` — NO eval/exec | phase_03_adapter_pattern |
| 6 | Empty results = `StepOutput(result=[])` (success), NOT sentinel (engine-internal) | phase_02_skip_propagation |
| 7 | Every I/O adapter has `health_probe()` that checks `last_trace.status` before interpreting empty results | phase_05_external_io |
| 8 | `health_check()` uses `get_running_loop()` + `asyncio.run()` fallback, never bare `get_event_loop()` | phase_05_external_io |
| 9 | `DependencyHealth` declared for every external dependency | phase_04_observability |
| 10 | `DependencyCallTrace` injected for every external call | phase_04_observability |
| 11 | 观测先行: every new capability layer must first be covered by the observability layer above it (engine trace → sink → component platform) | phase_12_observability_closed_loop |

## Machine Enforcement (Phase 8.0)

Architectural invariants are **machine-enforced**, not just documented. Before every commit, `python -m guardrails check` runs AST-based rules. Violations of severity ERROR block the commit.

To run guardrails manually:
- `python -m guardrails check` — error-level only
- `python -m guardrails check --all` — include warnings
- `python -m guardrails list-rules` — see all enforced rules

Pre-commit hook: `.pre-commit-config.yaml` — install with `pre-commit install`.
Pytest integration: `pytest tests/ --guardrails` — runs before test suite.

If you add a new file to `core/contracts/` or `core/adapters/`, the chain coverage rule will flag it unless a reasoning chain references the module name. This is BY DESIGN — new core modules require architectural documentation.

## Quick Reference: Key Files

```
.ai_reasoning/index.yaml              ← START HERE: find relevant chains by tag
.ai_reasoning/schemas/reasoning_chain.schema.json  ← Schema for new chains
.ai_reasoning/chains/                  ← Individual reasoning chain YAML files
core/contracts/                        ← Data models, Protocols, Registry (ZERO pipeline imports)
core/pipeline/                         ← Engine, tracing, resources (ZERO contracts imports)
core/adapters/                         ← ONLY layer that imports both platforms
core/steps/                            ← Built-in step implementations
tests/conformance/                     ← Contract conformance tests
tests/integration/                     ← Pipeline integration tests
tests/e2e/                            ← End-to-end + negative scenario tests
```

## Test Requirements

- All new code must pass `pytest tests/ -q`
- New component types need: conformance tests + integration tests + ≥4 negative scenarios
- If you fix a bug, add a test that would have caught it
- Current baseline: **107 tests, 0 failures** — do not regress
