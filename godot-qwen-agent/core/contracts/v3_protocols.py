"""V3 Protocols — frozen interfaces for components with multiple future backends.

Only components that WILL fork into ≥2 implementations get a Protocol.
Stable single-implementation components stay as-is.

Protocols defined:
  - SemanticTrustDetector : embedding | zero-shot classifier | tinyLLM+GBNF
  - PatternRepository     : SQLite | Redis | Postgres
  - ToolRegistry          : static dict | MCP dynamic discovery
  - ThresholdLearner      : (already exists in threshold_learner.py, referenced here)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


# ═══════════════════════════════════════════════════════════════════
# SemanticTrustDetector — 三个后端: embedding / zero-shot / 小模型
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class SemanticTrustDetector(Protocol):
    """Detect trust-relevant signals from user text.

    Current: SemanticTrustEngine (embedding similarity)
    Future:  ZeroShotTrustDetector (bart-large-mnli)
             GBNFConstrainedDetector (0.5B local model with grammar)
    """

    def detect(self, text: str) -> dict:
        """Return {"dimension": str|None, "score": float, "all_scores": dict}."""
        ...

    @property
    def dimensions(self) -> list[str]:
        """List of detectable trust dimensions."""
        ...


# ═══════════════════════════════════════════════════════════════════
# PatternRepository — 三个后端: SQLite / Redis / Postgres
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class PatternRepository(Protocol):
    """Store and query cross-session behavioral patterns.

    Current: RelationalPatterns (SQLite)
    Future:  RedisPatternRepository (in-memory, clustered)
             PostgresPatternRepository (multi-tenant, HA)
    """

    def record(
        self, user_id: str, behavior: str, action: str,
        success: bool = True, tags: str = "",
    ) -> bool:
        """Record a pattern occurrence. Returns True if newly created."""
        ...

    def query_active(
        self, user_id: str, min_occurrence: int = 3,
        min_confidence: float = 0.8,
    ) -> list[dict]:
        """Return patterns ready for proactive anticipation."""
        ...

    def generate_hint(self, user_id: str) -> str | None:
        """Return a natural-language proactive hint, or None."""
        ...

    def decay_all(self, user_id: str, days: int = 28) -> int:
        """Apply time decay to old patterns. Returns count of rows decayed."""
        ...


# ═══════════════════════════════════════════════════════════════════
# ToolRegistry — 两个后端: 静态 / MCP 动态发现
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class ToolRegistry(Protocol):
    """Registry of contract-bound tools with metadata.

    Current: TOOLS dict in tool_contract.py (static)
    Future:  MCPToolRegistry (dynamic discovery via MCP servers)
    """

    def get_contract(self, tool_name: str) -> dict | None:
        """Return tool contract metadata, or None if not found."""
        ...

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        ...

    def register(self, name: str, contract: dict) -> None:
        """Register a new tool with contract metadata."""
        ...
