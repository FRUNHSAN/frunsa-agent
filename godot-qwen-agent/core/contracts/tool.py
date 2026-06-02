"""Tool contracts — Phase 22a.

ToolProtocol, ToolCall, and ToolResult define the contract for tool/function
calling. This is NOT an RPC layer — it's a "relationship extension" where
every tool invocation flows through the contract compliance system.

Design invariants:
  - ToolCall is a frozen, deterministic record of an LLM's decision
  - ToolResult carries contract_violation for EventSink integration
  - ToolProtocol is the USB interface — all tools implement this
  - call_id is a deterministic hash for audit trail (same pattern as rule_id)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol

from .composition import ContractViolation


# ── Tool Protocol (USB interface) ────────────────────────────────────

class ToolProtocol(Protocol):
    """Every tool registered in the system must satisfy this Protocol.

    This is the "USB interface" for tools — ToolAdapter only knows about
    this Protocol, never about concrete tool implementations.

    Attributes:
        name:             Registry key (e.g. "web_search", "calculator")
        description:      Human-readable, used by LLM for tool selection
        parameters_schema: JSON Schema dict describing expected parameters
    """

    name: str
    description: str
    parameters_schema: dict

    def execute(self, **params: Any) -> ToolResult:
        """Execute the tool with the given parameters.

        MUST return ToolResult (never raise). Errors are wrapped in
        ToolResult(success=False, error=...).
        """
        ...


# ── Tool Call ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolCall:
    """Immutable record of an LLM's decision to invoke a tool.

    Analogous to SourceRule — a deterministic, auditable artifact.
    call_id is a sha256 hash of (tool_name, sorted_params) for
    offline verification, same pattern as rule_id.

    Attributes:
        tool_name:  Registry key of the requested tool
        parameters: kwargs passed to the tool
        call_id:    Deterministic hash for audit trail
        timestamp:  epoch seconds when this call was created
    """

    tool_name: str
    parameters: MappingProxyType[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    call_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "parameters",
            MappingProxyType(dict(self.parameters))
        )
        if not self.call_id:
            raw = json.dumps({
                "tool_name": self.tool_name,
                "parameters": dict(sorted(self.parameters.items())),
            }, sort_keys=True, separators=(",", ":"))
            rid = hashlib.sha256(raw.encode()).hexdigest()[:12]
            object.__setattr__(self, "call_id", rid)


# ── Tool Result ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class ToolResult:
    """Immutable record of a tool execution outcome.

    Every result flows into ContractAwareEventSink for health evaluation.
    contract_violation is None for successful executions; non-None when
    the tool call breaches a contract (tool not found, params mismatch,
    output schema violation).

    Attributes:
        call_id:            Matches ToolCall.call_id for correlation
        tool_name:          Which tool was executed
        success:            True if the tool produced usable output
        data:               The tool's output (Any type — validated by adapter)
        error:              Error message if success=False
        contract_violation: ContractViolation enum if a contract was breached
        timestamp:          epoch seconds when execution completed
    """

    call_id: str
    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None
    contract_violation: ContractViolation | None = None
    timestamp: float = field(default_factory=time.time)
