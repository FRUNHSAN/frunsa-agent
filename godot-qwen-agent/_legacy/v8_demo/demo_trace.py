"""Trace query and timeline builder — reads SQLiteTraceSink for Tab 3.

Zero-intrusion: imports core from parent project only.
Timeline data built from demo-layer timestamps (not engine internals).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def query_traces(
    db_path: str,
    engine_filter: str | None = None,
) -> List[Dict[str, Any]]:
    """Query trace records from SQLite, optionally filtered by engine."""
    if not Path(db_path).exists():
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if engine_filter and engine_filter != "all":
            rows = conn.execute(
                "SELECT * FROM trace_records WHERE engine = ? ORDER BY ts, item_index",
                (engine_filter,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trace_records ORDER BY ts, item_index"
            ).fetchall()

        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_trace_stats(db_path: str) -> Dict[str, Any]:
    """Get per-engine record counts and key completeness."""
    if not Path(db_path).exists():
        return {
            "exists": False,
            "total_records": 0,
            "by_engine": {},
            "key_completeness": {},
        }

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM trace_records"
        ).fetchone()["cnt"]

        engine_counts = {}
        engines = conn.execute(
            "SELECT engine, COUNT(*) as cnt FROM trace_records GROUP BY engine"
        ).fetchall()
        for row in engines:
            if row["engine"]:
                engine_counts[row["engine"]] = row["cnt"]

        # Check key completeness: for each engine, verify all required keys
        required_keys = {
            "planning": [
                "planning.step_index", "planning.reasoning_depth",
                "planning.parent_step_id", "planning.cumulative_tokens",
                "agent.identity",
            ],
            "orchestration": [
                "orchestration.dag_node_id", "orchestration.parallel_depth",
                "orchestration.merge_ordinal", "orchestration.branch_taken",
                "orchestration.retry_count", "orchestration.resource_pool_key",
                "agent.identity",
            ],
            "critic": [
                "critic.score", "critic.verdict", "agent.identity",
            ],
        }

        key_completeness = {}
        for eng, keys in required_keys.items():
            rows = conn.execute(
                "SELECT trace_context_json FROM trace_records WHERE engine = ? LIMIT 50",
                (eng,),
            ).fetchall()
            if not rows:
                key_completeness[eng] = {"total_keys": len(keys), "found": 0}
                continue
            found = set()
            for row in rows:
                try:
                    ctx = json.loads(row["trace_context_json"] or "{}")
                    found.update(ctx.keys())
                except json.JSONDecodeError:
                    pass
            present = sum(1 for k in keys if k in found)
            key_completeness[eng] = {"total_keys": len(keys), "found": present}

        return {
            "exists": True,
            "total_records": total,
            "by_engine": engine_counts,
            "key_completeness": key_completeness,
        }
    finally:
        conn.close()


def build_timeline_data(records: List[Dict[str, Any]]) -> "pd.DataFrame | None":
    """Build a timeline DataFrame for engine-level bar chart visualization.

    Uses item_index as sequential time proxy since all trace records share
    the same ISO ts (pipeline completes in < 200ms). Each engine's total
    duration is derived from its item count, creating a stacked timeline
    showing the Planning/Orchestration/Critic execution phases.
    """
    if not HAS_PANDAS or not records:
        return None

    # Count items per engine in order of first appearance
    engine_items: Dict[str, int] = {}
    engine_order: list[str] = []
    for rec in sorted(records, key=lambda r: (r.get("item_index", 0), r.get("engine", ""))):
        eng = rec.get("engine", "unknown")
        if eng not in engine_items:
            engine_items[eng] = 0
            engine_order.append(eng)
        engine_items[eng] += 1

    if not engine_items:
        return None

    rows = []
    for eng in engine_order:
        count = engine_items[eng]
        rows.append({
            "engine": eng,
            "duration": float(count),
            "item_count": count,
        })

    return pd.DataFrame(rows)


def clear_traces(db_path: str) -> None:
    """Delete trace database for fresh demo runs."""
    p = Path(db_path)
    if p.exists():
        p.unlink()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    # Parse trace_context_json if present
    if "trace_context_json" in d and d["trace_context_json"]:
        try:
            d["trace_context_parsed"] = json.loads(d["trace_context_json"])
        except json.JSONDecodeError:
            d["trace_context_parsed"] = {}
    return d
