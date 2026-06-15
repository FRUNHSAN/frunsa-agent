"""Component candidate empirical analysis — Phase 12 Step 4.

Runs N=2 engine stubs (planning + simulated RAG), collects trace_context
data from every StreamItem, and computes per-key statistics for the 3
component_candidate=True keys in TRACE_KEY_REGISTRY.

Classification uses hardcoded, documented thresholds:
  - confirmed_component: >=95% occurrence AND 100% type match AND bounded cardinality
  - type_mismatch: <100% type match (even one deviation is unambiguous)
  - needs_more_data: everything else

Output: human-readable to STDOUT, structured JSON to --output file.

Usage:
  python scripts/analyze_component_candidates.py
  python scripts/analyze_component_candidates.py --output analysis.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is on sys.path (parent of scripts/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.contracts.generation import StreamItem
from core.contracts.streaming_protocol import PaceConfig
from core.observability.trace_registry import TRACE_KEY_REGISTRY, TraceKeyDef

# ── Classification thresholds ─────────────────────────────────────────

# Rationale (from reasoning chain phase_12_observability_closed_loop):
#   ≥95% occurrence: tolerates engine stub edge cases that may not produce
#     every key in every call, while still requiring near-universal presence
#   100% type match: TraceKeyDef.type is a contract — runtime deviation is
#     unambiguous; no tolerance band needed
#   Bounded cardinality: free-text values (e.g., user-generated content) are
#     not component-level signals; component keys carry structured values
#     (int counters, float latencies, string IDs)
CLASSIFICATION_RULES = {
    "confirmed_component": {
        "min_occurrence_rate": 0.95,
        "type_match_rate": 1.0,
        "value_cardinality_set": {"bounded", "unique_identifiers"},
    },
    "type_mismatch": {
        "type_match_rate_max": 0.99,  # <100% → type mismatch
    },
    # Default: "needs_more_data"
}


@dataclass
class KeyStats:
    """Per-key statistics collected across all StreamItems."""
    key_name: str
    declared_type: str
    engine: str
    occurrences: int = 0
    total_items: int = 0
    values: List[Any] = field(default_factory=list)
    type_mismatches: int = 0
    type_mismatch_examples: List[Tuple[type, Any]] = field(default_factory=list)

    @property
    def occurrence_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return self.occurrences / self.total_items

    @property
    def type_match_rate(self) -> float:
        if self.occurrences == 0:
            return 1.0
        return 1.0 - (self.type_mismatches / self.occurrences)

    @property
    def value_cardinality(self) -> str:
        if not self.values:
            return "empty"
        if all(isinstance(v, (int, float)) for v in self.values):
            unique = len(set(self.values))
            if unique <= 1:
                return "constant"
            return "bounded"
        if all(isinstance(v, str) for v in self.values):
            unique = len(set(self.values))
            total = len(self.values)
            if unique == total:
                # Distinguish unique identifiers (IDs) from free text
                # Heuristic: IDs are short, alphanumeric, no spaces
                sample = self.values[: min(10, len(self.values))]
                if all(
                    isinstance(v, str) and len(v) < 200 and " " not in v
                    for v in sample
                ):
                    return "unique_identifiers"
                return "free_text"  # every value unique → not a component signal
            if unique / total < 0.5:
                return "bounded"
            return "free_text"
        return "mixed"

    def classify(self) -> str:
        """Classify this key based on hardcoded thresholds."""
        # Check type_mismatch first (most severe non-confirmed state)
        if self.type_match_rate <= CLASSIFICATION_RULES["type_mismatch"]["type_match_rate_max"]:
            return "type_mismatch"

        # Check confirmed_component thresholds
        rules = CLASSIFICATION_RULES["confirmed_component"]
        if (
            self.occurrence_rate >= rules["min_occurrence_rate"]
            and self.type_match_rate >= rules["type_match_rate"]
            and self.value_cardinality in rules["value_cardinality_set"]
        ):
            return "confirmed_component"

        return "needs_more_data"

    def numeric_summary(self) -> Dict[str, float]:
        """Compute min/max/mean/median for numeric values."""
        numeric_vals = [v for v in self.values if isinstance(v, (int, float))]
        if not numeric_vals:
            return {}
        return {
            "min": min(numeric_vals),
            "max": max(numeric_vals),
            "mean": statistics.mean(numeric_vals),
            "median": statistics.median(numeric_vals),
        }


def _collect_trace_contexts(items: List[StreamItem]) -> List[Dict[str, Any]]:
    """Extract non-None trace_context dicts from StreamItems."""
    return [item.trace_context for item in items if item.trace_context is not None]


def _compute_stats(
    key_name: str,
    key_def: TraceKeyDef,
    all_contexts: List[Dict[str, Any]],
) -> KeyStats:
    """Compute per-key statistics from collected trace_context dicts."""
    stats = KeyStats(
        key_name=key_name,
        declared_type=key_def.type.__name__,
        engine=key_def.engine,
        total_items=len(all_contexts),
    )

    declared_type = key_def.type

    for ctx in all_contexts:
        if key_name in ctx:
            stats.occurrences += 1
            value = ctx[key_name]
            stats.values.append(value)

            # Type check: use isinstance, not type() ==
            if not isinstance(value, declared_type):
                stats.type_mismatches += 1
                if len(stats.type_mismatch_examples) < 3:
                    stats.type_mismatch_examples.append((type(value), value))

    return stats


async def _run_planning_engine() -> List[Dict[str, Any]]:
    """Run the StubPlanningEngine and collect trace_context from all items."""
    from engines.planning.stub import StubPlanningEngine

    engine = StubPlanningEngine()
    items: List[StreamItem] = []

    async for item in engine.plan(
        goal="Analyze component candidate trace keys for Phase 13 interface design",
        deadline=30.0,
        pace_config=PaceConfig(item_throughput=None, burst_size=3, adaptive=False),
    ):
        items.append(item)

    return _collect_trace_contexts(items)


def _simulate_rag_engine() -> List[Dict[str, Any]]:
    """Simulate a RAG engine producing 5 chunks with trace_context.

    No RAG engine stub exists yet (Phase 12 scope is observability, not
    engine building). This simulation covers the 2 component_candidate
    RAG keys with controlled data.
    """
    items: List[StreamItem] = []

    chunk_ids = ["c001", "c002", "c003", "c004", "c005"]
    latencies_ms = [12.3, 8.7, 15.1, 9.4, 11.8]

    for i, (chunk_id, latency) in enumerate(zip(chunk_ids, latencies_ms)):
        items.append(StreamItem(
            delta=f"Retrieved chunk {chunk_id}: content excerpt...",
            index=i,
            model="rag/stub",
            is_terminal=(i == len(chunk_ids) - 1),
            finish_reason="stop" if i == len(chunk_ids) - 1 else None,
            trace_context={
                "rag.chunk_id": chunk_id,
                "rag.retrieval_latency_ms": latency,
            },
        ))

    return _collect_trace_contexts(items)


def _analyze_cross_engine(component_keys: List[KeyStats]) -> Dict[str, Any]:
    """Cross-engine structural analysis: key clustering by engine."""
    by_engine: Dict[str, List[str]] = defaultdict(list)
    for ks in component_keys:
        by_engine[ks.engine].append(ks.key_name)

    return {
        "engines_represented": sorted(by_engine.keys()),
        "keys_per_engine": {eng: len(keys) for eng, keys in by_engine.items()},
        "key_clusters": dict(by_engine),
    }


def _migration_recommendations(component_keys: List[KeyStats]) -> List[str]:
    """Generate Phase 13 migration recommendations with stable justification."""
    recommendations: List[str] = []

    from core.observability.trace_registry import ENGINE_TO_COMPONENT_MAP

    for ks in component_keys:
        classification = ks.classify()
        if classification == "confirmed_component":
            component_key = ENGINE_TO_COMPONENT_MAP.get(ks.key_name, ks.key_name)
            recommendations.append(
                f"PROMOTE '{ks.key_name}' → component key '{component_key}': "
                f"{ks.occurrence_rate:.0%} occurrence, {ks.type_match_rate:.0%} type match, "
                f"cardinality={ks.value_cardinality}. "
                f"Justification: meets all confirmed_component thresholds "
                f"(≥{CLASSIFICATION_RULES['confirmed_component']['min_occurrence_rate']:.0%} "
                f"occurrence, {CLASSIFICATION_RULES['confirmed_component']['type_match_rate']:.0%} type match, "
                f"cardinality in {CLASSIFICATION_RULES['confirmed_component']['value_cardinality_set']})."
            )
        elif classification == "type_mismatch":
            examples = ", ".join(
                f"{t.__name__}({repr(v)[:50]})"
                for t, v in ks.type_mismatch_examples
            )
            recommendations.append(
                f"FIX '{ks.key_name}': type mismatch ({ks.type_mismatches}/{ks.occurrences} "
                f"deviations). Declared type={ks.declared_type}, "
                f"runtime types: {examples}. "
                f"Justification: type_match_rate={ks.type_match_rate:.0%} < "
                f"{CLASSIFICATION_RULES['type_mismatch']['type_match_rate_max']:.0%} threshold."
            )
        else:  # needs_more_data
            shortfall = []
            rules = CLASSIFICATION_RULES["confirmed_component"]
            if ks.occurrence_rate < rules["min_occurrence_rate"]:
                shortfall.append(
                    f"occurrence_rate={ks.occurrence_rate:.0%} "
                    f"< {rules['min_occurrence_rate']:.0%}"
                )
            if ks.type_match_rate < rules["type_match_rate"]:
                shortfall.append(
                    f"type_match_rate={ks.type_match_rate:.0%} "
                    f"< {rules['type_match_rate']:.0%}"
                )
            if ks.value_cardinality not in rules["value_cardinality_set"]:
                shortfall.append(
                    f"cardinality={ks.value_cardinality} "
                    f"∉ {rules['value_cardinality_set']}"
                )
            reasons = "; ".join(shortfall) if shortfall else "insufficient data"
            recommendations.append(
                f"INVESTIGATE '{ks.key_name}': {reasons}. "
                f"Collect more data from additional engine runs or real LLM calls."
            )

    return recommendations


def _format_report(
    component_keys: List[KeyStats],
    cross_engine: Dict[str, Any],
    recommendations: List[str],
) -> str:
    """Format human-readable analysis report."""
    lines = [
        "=" * 72,
        "  Component Candidate Empirical Analysis — Phase 12",
        "=" * 72,
        "",
        f"Engines sampled: {', '.join(cross_engine['engines_represented'])}",
        f"Component candidate keys analyzed: {len(component_keys)}",
        "",
        "─" * 72,
        "  Per-Key Statistics",
        "─" * 72,
    ]

    for ks in component_keys:
        classification = ks.classify()
        status_marker = {
            "confirmed_component": "[READY]",
            "type_mismatch": "[FIX]",
            "needs_more_data": "[MORE DATA]",
        }.get(classification, "[?]")

        lines.append("")
        lines.append(f"  {status_marker} {ks.key_name}")
        lines.append(f"      Declared type : {ks.declared_type}")
        lines.append(f"      Engine        : {ks.engine}")
        lines.append(f"      Occurrences   : {ks.occurrences}/{ks.total_items} ({ks.occurrence_rate:.0%})")
        lines.append(f"      Type match    : {ks.type_match_rate:.0%} ({ks.type_mismatches} mismatches)")
        lines.append(f"      Cardinality   : {ks.value_cardinality}")

        num_summary = ks.numeric_summary()
        if num_summary:
            lines.append(
                f"      Value range   : min={num_summary['min']}, max={num_summary['max']}, "
                f"mean={num_summary['mean']:.2f}, median={num_summary['median']}"
            )

        if ks.type_mismatch_examples:
            lines.append("      Type mismatch examples:")
            for t, v in ks.type_mismatch_examples:
                lines.append(f"        - {t.__name__}: {repr(v)[:80]}")

        lines.append(f"      Classification: {classification}")

    lines.append("")
    lines.append("─" * 72)
    lines.append("  Cross-Engine Structural Analysis")
    lines.append("─" * 72)
    lines.append(f"  Keys per engine: {cross_engine['keys_per_engine']}")
    lines.append("  Key clusters:")
    for engine, keys in cross_engine["key_clusters"].items():
        lines.append(f"    {engine}: {keys}")

    lines.append("")
    lines.append("─" * 72)
    lines.append("  Phase 13 Migration Recommendations")
    lines.append("─" * 72)
    for i, rec in enumerate(recommendations, 1):
        lines.append(f"  {i}. {rec}")

    lines.append("")
    lines.append("─" * 72)
    lines.append("  Classification Thresholds (hardcoded)")
    lines.append("─" * 72)
    lines.append(f"  confirmed_component.min_occurrence_rate = {CLASSIFICATION_RULES['confirmed_component']['min_occurrence_rate']}")
    lines.append(f"  confirmed_component.type_match_rate      = {CLASSIFICATION_RULES['confirmed_component']['type_match_rate']}")
    lines.append(f"  confirmed_component.value_cardinality_set = {CLASSIFICATION_RULES['confirmed_component']['value_cardinality_set']}")
    lines.append(f"  type_mismatch.type_match_rate_max        = {CLASSIFICATION_RULES['type_mismatch']['type_match_rate_max']}")
    lines.append("")

    return "\n".join(lines)


def _build_json_output(
    component_keys: List[KeyStats],
    cross_engine: Dict[str, Any],
    recommendations: List[str],
) -> Dict[str, Any]:
    """Build structured JSON output."""
    return {
        "analysis_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "phase": "12",
        "engines_sampled": cross_engine["engines_represented"],
        "component_candidate_keys": [
            {
                "key_name": ks.key_name,
                "declared_type": ks.declared_type,
                "engine": ks.engine,
                "occurrences": ks.occurrences,
                "total_items": ks.total_items,
                "occurrence_rate": ks.occurrence_rate,
                "type_match_rate": ks.type_match_rate,
                "type_mismatches": ks.type_mismatches,
                "value_cardinality": ks.value_cardinality,
                "numeric_summary": ks.numeric_summary(),
                "classification": ks.classify(),
            }
            for ks in component_keys
        ],
        "cross_engine_analysis": cross_engine,
        "migration_recommendations": recommendations,
        "classification_thresholds": {
            "confirmed_component": CLASSIFICATION_RULES["confirmed_component"],
            "type_mismatch": CLASSIFICATION_RULES["type_mismatch"],
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Component candidate empirical analysis — Phase 12"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Write structured JSON output to this file",
    )
    parser.add_argument(
        "--per-engine", "-e",
        action="store_true",
        default=False,
        help="Analyze each engine's keys within its own item scope (not cross-engine pooled)",
    )
    args = parser.parse_args()

    print("Collecting trace_context data from engines...")

    # Collect trace_context from both engines
    planning_contexts = await _run_planning_engine()
    rag_contexts = _simulate_rag_engine()

    print(f"  Planning engine: {len(planning_contexts)} StreamItems collected")
    print(f"  RAG engine (simulated): {len(rag_contexts)} StreamItems collected")

    all_contexts = planning_contexts + rag_contexts

    # Identify component_candidate keys
    component_keys_defs = {
        name: defn
        for name, defn in TRACE_KEY_REGISTRY.items()
        if defn.component_candidate
    }

    # Compute per-key statistics
    component_keys: List[KeyStats] = []
    if args.per_engine:
        # Per-engine scope: analyze each engine's keys within its own items only
        for engine_contexts, engine_name in [
            (planning_contexts, "planning"),
            (rag_contexts, "rag"),
        ]:
            for key_name, key_def in sorted(component_keys_defs.items()):
                if key_def.engine != engine_name:
                    continue
                stats = _compute_stats(key_name, key_def, engine_contexts)
                component_keys.append(stats)
    else:
        for key_name, key_def in sorted(component_keys_defs.items()):
            stats = _compute_stats(key_name, key_def, all_contexts)
            component_keys.append(stats)

    # Cross-engine analysis
    cross_engine = _analyze_cross_engine(component_keys)

    # Migration recommendations
    recommendations = _migration_recommendations(component_keys)

    # Output
    report = _format_report(component_keys, cross_engine, recommendations)
    print(report)

    if args.output:
        json_output = _build_json_output(component_keys, cross_engine, recommendations)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(json_output, f, indent=2, ensure_ascii=False)
        print(f"Structured JSON written to: {args.output}")

    # Exit code: non-zero if any type_mismatch (CI-friendly)
    mismatches = sum(1 for ks in component_keys if ks.classify() == "type_mismatch")
    if mismatches > 0:
        print(f"\n{mismatches} key(s) with type mismatch. Investigate before Phase 13 migration.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
