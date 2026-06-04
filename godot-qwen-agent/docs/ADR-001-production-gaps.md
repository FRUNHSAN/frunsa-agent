# ADR-001: Production Readiness Gaps

**Date**: 2026-06-04
**Status**: Accepted
**Author**: Frunsa

## Context

PLAN1-8 (99 commits, 890+ tests) have validated the core primitives:
DynamicBlueprint, ContractEvolutionEngine, ActionPipeline, OutputPipeline,
GBNF grammar enforcement, and SemanticTrust. The architecture is stable.
But the system is at Proof-of-Concept maturity, not production maturity.

This ADR documents what is deliberately deferred and why.

## Decision: Known Compromises

### 1. Single-file JSON persistence (UserProfile)

**Status**: Active. `user_profiles/{user_id}.json` — one file per user.
**Risk**: Concurrent writes from multiple sessions to the same user file will corrupt data.
**Why not fixed now**: V1 is single-user, single-session. No concurrency exists.
**Plan**: SQLite in V2 (single-file, reader-writer lock, zero-dependency).
**Migration path**: `UserProfile.save()` and `UserProfile.load()` are the only I/O touch points. Swap the implementation, zero API change.

### 2. No authentication or authorization

**Status**: None. Anyone who can run `python run_live.py` can interact with any profile.
**Why not fixed now**: V1 runs on localhost. No network exposure.
**Plan**: Environment-variable API key in `run_live.py` for V2. Proper OAuth2/JWT in V3.

### 3. Subprocess-based local inference (NativeLLMClient)

**Status**: Functional but fragile. File IPC with `llama-completion.exe`.
**Risk**: Subprocess hangs on Windows, timeout-based recovery, 2-3s cold start per request.
**Why not fixed now**: llama.cpp HTTP server requires build migration. Current approach validates GBNF architecture.
**Plan**: Replace with `llama-server` HTTP API (persistent process) in V2.
**Migration path**: `NativeLLMClient.generate()` is the only call site. Swap the implementation.

### 4. No audit log or monitoring

**Status**: `print()` statements for visibility. No structured logging.
**Risk**: No way to debug production issues or detect anomalies retroactively.
**Why not fixed now**: V1 is interactive. The user IS the observer.
**Plan**: Structured JSONL logging (`interaction_telemetry.py` exists, not wired). Prometheus metrics in V3.

### 5. Prompt-based Layer 1 enforcement (50% reliability)

**Status**: `build_contract_directive()` translates Blueprint to System Prompt text. LLM compliance is probabilistic.
**Risk**: LLM can ignore contract directives (observed: "格式越狱" — compound sentences in LOW mode).
**Why not fixed now**: Layer 2 (OutputPipeline) and Layer 3 (GBNF) provide deterministic fallback. Layer 1 is advisory.
**Plan**: No change. Three-layer model is the architecture. Layer 1 is intentionally probabilistic.

### 6. No CI/CD pipeline

**Status**: Manual `pytest tests/` before commits.
**Risk**: Regression bugs can be committed. No automated enforcement.
**Why not fixed now**: Single developer. Manual discipline is sufficient.
**Plan**: GitHub Actions workflow (`pytest + guardrails`) before V2 public release.

### 7. Only 38 tests for PLAN5-8 (vs 855 for PLAN1-4)

**Status**: Core logic validated but edge cases not exhaustively covered.
**Risk**: Refactoring PLAN5-8 code may introduce undetected regressions.
**Why not fixed now**: PLAN5-8 evolved rapidly (70+ commits in one session). Tests lagged.
**Plan**: 200+ tests for PLAN5-8 before V2. Priority: DynamicBlueprint edge cases, ActionPipeline Backlash, EvolutionEngine rollback timing.

### 8. Tight coupling in run_live.py

**Status**: 400-line main loop with 14 concerns in one file.
**Risk**: Adding features requires editing a monolithic script. Hard to test in isolation.
**Why not fixed now**: run_live.py is the demo harness, not the SDK. Production integration goes through ContractEngine.
**Plan**: ContractEngine SDK is the public API. run_live.py stays as interactive demo. No architectural refactor needed.

## Consequences

- **Positive**: Honest documentation attracts contributors who understand trade-offs.
- **Positive**: Each known gap has a concrete fix plan and migration path.
- **Negative**: Some gaps (audit log, authentication) are blockers for real production use.
- **Negative**: Subprocess instability may frustrate users testing local mode.
