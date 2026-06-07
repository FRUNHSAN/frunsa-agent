"""Config — CLI + env, zero business logic."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Config:
    user_id: str = "default"
    use_local: bool = False
    model_path: str = ""
    temperature: float = 0.7
    max_tokens: int = 512
    auditor_interval: int = 10
    mcp_servers: list[str] | None = None  # MCP server names or config paths

    @classmethod
    def from_args(cls, argv: list[str]) -> "Config":
        uid = argv[1] if len(argv) > 1 else "default"
        local = "--local" in argv
        # --mcp server1,server2 → list of server names
        mcp = None
        for i, a in enumerate(argv):
            if a == "--mcp" and i + 1 < len(argv):
                mcp = argv[i + 1].split(",")
        return cls(user_id=uid, use_local=local, mcp_servers=mcp)
