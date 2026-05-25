"""Critic agent identity model — Phase 16.

Follows the 6-point agent.* namespace convention established in Phase 15.
CriticAgent evaluates results produced by other engines (planning, retrieval)
and assigns quality scores + verdicts.

Agent Namespace Registration Convention (Phase 15, reusable):
  1. Define a frozen dataclass for the data model.
  2. Implement to_trace_value() -> dict for trace_context serialization.
  3. Register in TRACE_KEY_REGISTRY with engine=<owning-engine-name>.
  4. Key name: "agent.<concept>" (dot-separated prefix).
  5. Value type: dict (JSON-serializable for adapter passthrough).
  6. component_candidate=False (agent identity is engine metadata, not a component capability).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class CriticAgent:
    """Structured critic agent identity.

    Fields:
        id: Agent identifier (e.g. "critic-v1").
        role: Agent role within the multi-agent system ("critic").
        version: SemVer string for contract compatibility checks.
        capabilities: Tuple of capability labels (e.g. "result_evaluation", "quality_scoring").
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
    def from_trace_value(cls, data: Dict[str, Any]) -> "CriticAgent":
        return cls(
            id=data["id"],
            role=data["role"],
            version=data["version"],
            capabilities=tuple(data.get("capabilities", [])),
        )
