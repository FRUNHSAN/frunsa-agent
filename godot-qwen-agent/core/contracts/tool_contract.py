"""ToolContract — PLAN8: contract metadata for tool execution.

Every tool carries a contract: risk level, minimum trust required,
and whether it can auto-execute or requires human confirmation.

This is the "skeleton key" for contract-bound agents.
The contract doesn't just control what the LLM SAYS —
it controls what the Agent CAN DO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    READ = "read"              # Query only, no side effects
    WRITE = "write"            # Creates/modifies data
    DESTRUCTIVE = "destructive"  # Deletes, restarts, sends — permanent


@dataclass(frozen=True)
class ToolContract:
    """Metadata contract for a tool.

    Before any tool executes, the ActionPipeline checks:
      - Is this tool's risk level permitted under current trust?
      - Does the Constitution forbid this tool category?
      - Does recent tool failure history (Backlash) suggest caution?
    """

    name: str
    description: str = ""
    risk_level: RiskLevel = RiskLevel.READ
    min_trust: float = 0.0          # Minimum trust to auto-execute
    require_hitl: bool = False       # Always require human confirmation
    category: str = "general"        # For Constitution checks
    tags: frozenset[str] = field(default_factory=frozenset)

    def check_trust(self, current_trust: float) -> tuple[bool, str]:
        """Can this tool execute at the current trust level?"""
        if self.require_hitl:
            return False, f"Tool '{self.name}' requires human confirmation."
        if current_trust < self.min_trust:
            return False, (
                f"Trust {current_trust:.2f} below minimum "
                f"{self.min_trust} for '{self.name}' ({self.risk_level.value})."
            )
        return True, "OK"

    def check_constitution(self, forbidden_categories: frozenset[str]) -> tuple[bool, str]:
        """Does the Constitution allow this tool?"""
        if self.category in forbidden_categories:
            return False, (
                f"Constitution forbids category '{self.category}'. "
                f"Tool '{self.name}' blocked."
            )
        return True, "OK"


# ── Toy tool registry for demo ──

TOOLS: dict[str, dict[str, Any]] = {
    "search_web": {
        "name": "search_web",
        "description": "Search the internet for information",
        "risk_level": RiskLevel.READ,
        "min_trust": 0.0,
        "category": "search",
    },
    "read_file": {
        "name": "read_file",
        "description": "Read a file from disk",
        "risk_level": RiskLevel.READ,
        "min_trust": 0.1,
        "category": "filesystem",
    },
    "write_file": {
        "name": "write_file",
        "description": "Write data to a file",
        "risk_level": RiskLevel.WRITE,
        "min_trust": 0.35,
        "category": "filesystem",
    },
    "send_email": {
        "name": "send_email",
        "description": "Send an email to a recipient",
        "risk_level": RiskLevel.WRITE,
        "min_trust": 0.50,
        "require_hitl": True,
        "category": "communication",
    },
    "delete_logs": {
        "name": "delete_logs",
        "description": "Delete system log files",
        "risk_level": RiskLevel.DESTRUCTIVE,
        "min_trust": 0.85,
        "require_hitl": True,
        "category": "system_admin",
    },
    "restart_server": {
        "name": "restart_server",
        "description": "Restart the production server",
        "risk_level": RiskLevel.DESTRUCTIVE,
        "min_trust": 0.90,
        "require_hitl": True,
        "category": "system_admin",
    },
    "knowledge_search": {
        "name": "knowledge_search",
        "description": "Search the internal knowledge base with trust-gated access",
        "risk_level": RiskLevel.READ,
        "min_trust": 0.20,
        "category": "knowledge",
        "whitelist": ["knowledge_base/public_docs/", "knowledge_base/company_wiki/"],
        "blocked_keywords": ["机密", "confidential", "裁员", "layoff", "高管", "executive"],
        "max_results": 3,
    },
}

# Permanent constitutional ban: these categories are NEVER allowed
CONSTITUTIONAL_BAN: frozenset[str] = frozenset()
# Example: CONSTITUTIONAL_BAN = frozenset({"system_admin"})
# would permanently disable delete_logs and restart_server.
