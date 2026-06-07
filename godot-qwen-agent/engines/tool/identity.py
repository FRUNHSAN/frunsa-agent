"""Tool agent identity model — V4.3.

Follows the 6-point agent.* namespace convention (Phase 15).
ToolIdentity marks tool execution as an agentic action — the tool
selector is an agent making an irreversible decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ToolIdentity:
    """Structured tool executor agent identity.

    Fields:
        id: Agent identifier (e.g. "tool-executor-v1").
        role: Agent role ("tool_executor").
        version: SemVer string.
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
    def from_trace_value(cls, data: Dict[str, Any]) -> "ToolIdentity":
        return cls(
            id=data["id"],
            role=data["role"],
            version=data["version"],
            capabilities=tuple(data.get("capabilities", [])),
        )
