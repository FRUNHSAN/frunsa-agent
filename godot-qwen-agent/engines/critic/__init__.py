"""Critic engine: quality evaluation and verdict assignment.

Phase 16: Minimal stub implementation for multi-agent foundation validation.
Phase 18: CriticEngine Protocol + CriticContext for contract-locked engine swap.
"""
from engines.critic.identity import CriticAgent
from engines.critic.interface import CriticContext, CriticEngine
from engines.critic.stub import StubCriticEngine

__all__ = ["CriticAgent", "CriticContext", "CriticEngine", "StubCriticEngine"]
