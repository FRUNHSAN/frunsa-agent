"""Orchestrator agent identity model — Phase 18.

Follows the 6-point agent.* namespace convention established in Phase 15.
OrchestratorIdentity describes the orchestration engine's role in the
multi-agent system.

Agent Namespace Registration Convention (Phase 15, reusable):
  1. Define a frozen dataclass for the data model.
  2. Implement to_trace_value() -> dict for trace_context serialization.
  3. Register in TRACE_KEY_REGISTRY with engines=<owning-engine-name>.
  4. Key name: "agent.<concept>" (dot-separated prefix).
  5. Value type: dict (JSON-serializable for adapter passthrough).
  6. component_candidate=False (agent identity is engine metadata).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class OrchestratorIdentity:
    """Structured orchestrator agent identity.

    Fields:
        id: Agent identifier (e.g. "orchestrator-v1").
        role: Agent role ("orchestration").
        version: SemVer string for contract compatibility checks.
        capabilities: Tuple of capability labels.
    """

    id: str
    role: str
    version: str
    capabilities: tuple[str, ...] = ()

    def to_trace_value(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "version": self.version,
            "capabilities": list(self.capabilities),
        }

    @classmethod
    def from_trace_value(cls, data: Dict[str, Any]) -> "OrchestratorIdentity":
        return cls(
            id=data["id"],
            role=data["role"],
            version=data["version"],
            capabilities=tuple(data.get("capabilities", [])),
        )
