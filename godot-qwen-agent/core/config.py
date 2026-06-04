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

    @classmethod
    def from_args(cls, argv: list[str]) -> "Config":
        uid = argv[1] if len(argv) > 1 else "default"
        local = "--local" in argv
        return cls(user_id=uid, use_local=local)
