"""Agent identity data model — first agent.* namespace key.

Phase 15 defines the agent.* namespace registration convention through this module.
Future agent keys (agent.capability_manifest, agent.trust_level, agent.role_graph)
follow the same pattern.

Agent Namespace Registration Convention (Phase 15):
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
class AgentIdentity:
    """Structured agent identity carrying id, role, version, and capabilities manifest.

    The capabilities field directly pre-positions for capability negotiation
    with observability arbitration (Phase 16+): ENGINE_TO_COMPONENT_MAP evolves
    from static dict to runtime discovery where capability declarations must be
    backed by trace evidence.

    Fields:
        id: Agent identifier (e.g. "planner-v1").
        role: Agent role within the multi-agent system (e.g. "planning").
        version: SemVer string for contract compatibility checks.
        capabilities: Tuple of capability labels declared by this agent
            (e.g. ("task_decomposition", "parallel_planning")).
    """

    id: str
    role: str
    version: str
    capabilities: tuple[str, ...] = ()

    def to_trace_value(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict for trace_context injection."""
        return {
            "id": self.id,
            "role": self.role,
            "version": self.version,
            "capabilities": list(self.capabilities),
        }

    @classmethod
    def from_trace_value(cls, data: Dict[str, Any]) -> "AgentIdentity":
        """Deserialize from a trace_context dict back to AgentIdentity."""
        return cls(
            id=data["id"],
            role=data["role"],
            version=data["version"],
            capabilities=tuple(data.get("capabilities", [])),
        )
