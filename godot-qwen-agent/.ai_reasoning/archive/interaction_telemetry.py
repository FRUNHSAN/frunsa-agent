# [ARCHIVED — DEPRECATED_BY_V5]
# 
# This module implements the old "guess user intent via LLM/embedding signals"
# paradigm (PLAN2/PLAN4). V5 replaces this with:
#   - tracking_error.py (behavior-gap measurement, not intent-guessing)
#   - meta_adapt_trigger.py (selection threshold relaxation)
#
# The V5 paradigm: agent does NOT negotiate contracts — it is SELECTED BY
# user behavior feedback. "Intentional violation" and "telemetry of internal
# emotional state" are superseded concepts.
#
# Archived: 2026-06-07
# See .ai_reasoning/BRAINSTORM_TRUE_ADAPTIVE.md for the full derivation.
# See PLAN8.md for the current engineering plan.
#
"""Interaction Telemetry — PLAN4 black box recorder.

Silently appends one JSONL line per interaction round.
Records the full relational state before and after each response,
plus implicit feedback signals from the user's next action.

No modification of system behavior — pure observation.
Data accumulated here becomes the training set for Proxy Loss
calibration and PLAN4 tensor engine.

Design:
  - JSONL append (one line per round, safe for concurrent writes)
  - Records: context (with Bayesian variance), seed, response,
    user next action, computed proxy loss
  - Zero dependencies beyond stdlib json
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any


class InteractionTelemetry:
    """Black box recorder for relational interaction data.

    Usage:
        telem = InteractionTelemetry("relational_telemetry.jsonl")
        telem.log_turn(
            turn_id=1,
            aggregated_ctx=history.get_all_states(),
            generated_seed=seed,
            agent_response_length=len(response),
            user_next_response_length=15,
            user_response_latency_sec=2.5,
            computed_proxy_loss=0.0,
        )
    """

    def __init__(self, path: str = "relational_telemetry.jsonl") -> None:
        self._path = Path(path)
        # Ensure directory exists
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log_turn(self, **fields: Any) -> None:
        """Append one interaction round as a JSONL line.

        All kwargs become top-level fields in the JSON object.
        Timestamp and turn_id are auto-populated if missing.
        """
        record = dict(fields)
        record.setdefault("timestamp", time.time())
        record.setdefault("recorded_at_iso", time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.localtime(record["timestamp"])
        ))

        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict]:
        """Read all recorded turns for analysis."""
        if not self._path.exists():
            return []
        results = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))
        return results

    def count_rounds(self) -> int:
        """Total rounds recorded so far."""
        return len(self.read_all())

    @property
    def path(self) -> str:
        return str(self._path)
