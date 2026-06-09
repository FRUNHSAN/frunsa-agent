"""V7 execution layer — physical feedback via sandboxed code execution.

Hybrid automaton S × Q:
  S: semantic manifold (LLM embeddings)
  Q: physical state = {PASS, COMPILE_ERR, TYPE_MISMATCH, RUNTIME_ERR, TIMEOUT, SANDBOX_VIOLATION}

Layered execution (Defensive Axiom D):
  Layer 1: AST (~1ms, free) — catches 80% of LLM syntax errors
  Layer 2: Mypy (~500ms, costs 1 unit) — static type checking
  Layer 3: Sandbox (~100ms+, costs 1 unit) — RestrictedPython runtime

PhysicalBudget: max 5 executions per Track C cycle. Layer 1 always free.
"""

from core.execution.sandbox import SandboxExecutor, PhysicalState
from core.execution.error_mapper import ErrorMapper

__all__ = ["SandboxExecutor", "PhysicalState", "ErrorMapper"]
