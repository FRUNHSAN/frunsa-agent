# PLAN6 Audit Report — 2026-06-04

## Summary

| Dimension | Grade | Key Finding |
|-----------|-------|-------------|
| contracts/ layer purity | A- | 1 cross-layer violation (identity_chunker → pipeline) |
| adapters/ layer integrity | B | composer.py imports concrete adapters; steps/ imports adapters/ |
| Contract CRUD | C | Blueprint is a flat dict, not a clause repository |
| run_live.py cohesion | D | 14 concerns in one loop; proposal logic duplicated 3x |
| System 2 (Auditor) | C+ | Generates proposals but schema-blind; no feedback loop |
| SignalInterpreter | B | Good negative signal mapping; no positive signal handling |
| SemanticTrust | B | 80% accuracy; zero error handling in detect() |
| Safety valves | A | Cooldown, constitution, rollback, schema validation all solid |

## Critical Issues

### 1. run_live.py is a monolith (D grade)
14 concerns in a single sequential block. Proposal application logic duplicated 3 times (lines 220-260). `trust` is a god variable modified by 7 subsystems. `pending` list has no ownership protocol. ~30 hardcoded mappings duplicate blueprint_schema constants.

### 2. Contract is a dict, not a system-readable entity (C grade)
Blueprint is `Dict[str, str]`. Other components read it via `bp.enforce()` and `bp.snapshot`. This works but has no clause-level lifecycle (TTL, conditions, priority). PRODUCTION_GAPS.md item #9 remains open.

### 3. System 2 is schema-blind (C+ grade)
ContractAuditor prompt has no `BLUEPRINT_SCHEMA` injection. Proposes invalid values (e.g. "VERY_LOW"). No feedback loop — never learns which proposals were accepted. Fixed via schema validation in apply_proposal() but auditor still wastes tokens.

### 4. SemanticTrust has no error handling (B grade)
`detect()` propagates all exceptions. If model fails at runtime, loop crashes — no fallback to keywords per-round. `run_live.py` only checks availability at startup.

### 5. SignalInterpreter is negative-only (B grade)
Gratitude and curiosity signals never generate proposals. Missing: positive reinforcement proposals (e.g. "user consistently grateful → upgrade tone to WARM").

## Non-Critical Issues

- Stale `__init__.py` — PLAN4/5/6 modules not exported
- UserProfile `storage_path` inconsistency (`.` prefix)
- 7 unused typing imports across contracts/
- `ContractEvolutionEngine` only monitors last evolution for rollback
- `Detect_explicit_command()` uses hardcoded Chinese keyword lists
- `_amendments_shown` set never persisted across sessions

## Import Direction Violations

| Violation | File | Severity |
|-----------|------|----------|
| contracts → pipeline (HealthStatus) | identity_chunker.py:39 | Low (documented exception) |
| adapters → concrete adapter (ChunkerAdapter) | composer.py:33 | Medium |
| adapters → steps (RetrieverStep) | composer.py:36 | Medium |
| steps → adapters (VectorStoreAdapter) | retriever.py:11 | Medium |
| steps → adapters (GenerationAdapter) | generator.py:9 | Medium |
| steps → adapters (ScoringAdapter) | reranker.py:10 | Medium |

## What Works Well

- Constitution guard: 4 immutable genes, zero bypass found
- Cooldown: prevents oscillation (verified in stress test)
- Schema validation: invalid values rejected at apply_proposal()
- Layer 3 enforcement: token abort + format sanitizer + sycophancy penalty
- Decay engine: temporary adaptations naturally erode
- UserProfile cross-session memory with outlier rejection
- Semantic trust: 80% accuracy at ~30ms inference
- 855 core tests passing (1 known flaky: test_neutral_input_preserves_state)
