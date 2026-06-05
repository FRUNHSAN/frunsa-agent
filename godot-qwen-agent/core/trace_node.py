"""TraceNode — engine-level execution trace data structure.

Future-proof: this is the standard format for agent execution traces.
  - Terminal X-Ray → renders events
  - Web UI dashboard → renders the trace tree
  - LangSmith export → serializes the tree as JSON
  - File logger → writes the tree after each session

Design: frozen dataclass. Immutable. Serializable via asdict().
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class TraceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    SKIPPED = "skipped"  # Contract blocked, etc.


@dataclass(frozen=True)
class TraceNode:
    """One node in the agent's execution trace tree.

    Example tree:
      Root: "帮我准备腾讯面试"
        ├── Planning: "拆解为 3 个子任务"
        │   ├── Step 1: "分析岗位要求"
        │   ├── Step 2: "准备项目介绍" (knowledge_search ✅)
        │   └── Step 3: "模拟面试问答"
        └── Critic: "评估: 满意"
    """

    node_id: str
    name: str = ""              # Display name, e.g. "TrackB_Planning"
    node_type: str = ""         # "agent" | "tool" | "rag" | "llm" | "pipeline"
    status: TraceStatus = TraceStatus.PENDING
    parent_id: str = ""         # Empty = root node

    # ── I/O ──
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    # ── Metadata ──
    elapsed_ms: float = 0.0
    tokens: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
