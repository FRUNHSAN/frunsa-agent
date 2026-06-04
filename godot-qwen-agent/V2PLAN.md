# V2 Plan — Stream Interception + Foundation Hardening

> **代码钳制，不是 Prompt 建议。**
> V1 proved the contract engine works. V2 makes it intercept LLM output in real-time.

## V2 Priorities

| # | Priority | Scope | Rationale |
|---|----------|-------|-----------|
| 1 | 200+ tests | PLAN5-8 edge cases | Refactoring safety net |
| 2 | SQLite persistence | Replace UserProfile JSON | Concurrent-safe, WAL mode |
| 3 | llama-server HTTP | Replace subprocess IPC | Persistent model, no cold start |
| 4 | Stream Interceptor | Token-level contract enforcement | **The crown jewel** |

---

## Stream Interception State Machine

The core V2 innovation. When LLM streams output, the contract must intercept
BEFORE dangerous tokens reach the user or trigger frontend auto-execution.

```
TEXT_MODE ──[detects <tool>]──→ BUFFERING ──[JSON complete]──→ VALIDATING
    ↑                              │                                │
    │                        [timeout/overflow]               ┌────┴────┐
    │                              │                          │         │
    └──────────────────────────────┘                    [PASS] ✓     [FAIL] ✋
                                                           │           │
                                                      EXECUTING   FALLBACK
                                                           │           │
                                                      [result→LLM]  [inject alert→LLM]
                                                           │           │
                                                           └─────┬─────┘
                                                                 ↓
                                                            TEXT_MODE
```

### State Definitions

| State | Condition | Action |
|-------|-----------|--------|
| **TEXT_MODE** | Default. LLM outputs natural language. | Tokens stream directly to frontend. |
| **BUFFERING** | `<tool>` or `{` detected at stream start. | Hold stream. Accumulate tokens in memory. Max 4KB buffer. 10s timeout. |
| **VALIDATING** | Buffer contains complete JSON. | Parse tool_name + params. Call `ContractGateway.authorize_action()`. |
| **EXECUTING** | Contract ALLOWED. | Execute tool. Feed result back to LLM. Resume streaming. |
| **FALLBACK** | Contract BLOCKED. | Discard buffer. Inject `[ContractViolation]` into LLM context. Never expose blocked JSON to user. |

### Edge Cases (The Hard Parts)

1. **Half JSON**: LLM outputs `{"tool": "de` then network dies. → Timeout (10s) → discard buffer → FALLBACK.
2. **Buffer overflow**: LLM outputs 8KB JSON (attack/malfunction). → 4KB limit → truncate → FALLBACK.
3. **Nested tool calls**: LLM outputs `<tool>...</tool><tool>...</tool>`. → Process first, buffer second.
4. **False positive**: User says "use `<tool>` in your response". → Heuristic: only trigger BUFFERING if tool marker appears at line start or after `\n\n`.
5. **Stream resume**: After FALLBACK, LLM must generate a new natural-language response. The injected alert is: `[System] Your tool call was blocked by the contract engine. Reason: {reason}. Explain this to the user and ask for authorization.`

---

## Architecture Decisions (ADR-002 through ADR-004)

### ADR-002: Stream Interceptor is a separate component

The interceptor sits between `llm.generate_stream()` and the frontend.
It is NOT part of ActionPipeline — ActionPipeline validates complete tool calls.
The interceptor decides WHEN to invoke ActionPipeline.

```
LLM stream → [Interceptor FSM] → validated JSON → ActionPipeline.check()
                  │
                  ├── TEXT_MODE tokens → frontend (direct)
                  └── FALLBACK injection → LLM context (never frontend)
```

### ADR-003: SQLite WAL mode is mandatory

`PRAGMA journal_mode=WAL;` enables concurrent reads during writes.
Without WAL, every `profile.save()` locks the database.
`busy_timeout=5000` gives 5 seconds for lock contention before throwing.

### ADR-004: llama-server HTTP replaces subprocess

Persistent process. Model loads ONCE. All requests share the loaded model.
Removes 2-3s cold start. Enables streaming (server-sent events).
Backward compatible: `NativeLLMClient` becomes `HttpLLMClient`, same `generate()` signature.

---

## Timeline

```
Week 1-2:  200+ tests (DynamicBlueprint, EvolutionEngine, ActionPipeline, Backlash)
Week 3:    SQLite persistence (drop-in replacement for JSON UserProfile)
Week 4:    llama-server HTTP (replace subprocess, test streaming)
Week 5-6:  Stream Interceptor FSM (implement 5 states, edge case testing)
Week 7:    Integration testing + ADR documentation
```
