"""Pytest configuration for the agent platform test suite."""

from __future__ import annotations

import pytest


@pytest.fixture
def common_initial_keys() -> set[str]:
    return {"document"}
