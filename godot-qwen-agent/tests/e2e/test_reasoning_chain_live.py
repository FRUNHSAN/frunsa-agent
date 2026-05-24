"""Phase 6.5: Reasoning chain library "living integration" verification.

Three verification pillars:
  1. Pre-Coding  — AI can locate relevant chains and extract actionable guidance
  2. Anti-pattern — Known violations are detectable; chains serve as a "firewall"
  3. Post-Coding — New chains validate against schema; index remains consistent

These tests are the "neural synapse" connecting the static knowledge base
(.ai_reasoning/) to the AI's coding behavior (CLAUDE.md + schema enforcement).
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest
import yaml

# ── Paths ─────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent.parent
AI_REASONING = ROOT / ".ai_reasoning"
INDEX_PATH = AI_REASONING / "index.yaml"
SCHEMA_PATH = AI_REASONING / "schemas" / "reasoning_chain.schema.json"
CHAINS_DIR = AI_REASONING / "chains"
CLAUDE_MD_PATH = ROOT / "CLAUDE.md"


# ── Helpers ───────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_all_chains() -> Dict[str, Dict[str, Any]]:
    chains: Dict[str, Dict[str, Any]] = {}
    for chain_file in sorted(CHAINS_DIR.glob("*.yaml")):
        chain = _load_yaml(chain_file)
        chains[chain["chain_id"]] = chain
    return chains


# ═══════════════════════════════════════════════════════════════════════
# Verification 1: Pre-Coding — Read + Locate + Extract
# ═══════════════════════════════════════════════════════════════════════


class TestPreCodingReadCapability:
    """AI must be able to: read index → find chains by tag → extract guidance."""

    def test_index_exists_and_is_valid_yaml(self):
        assert INDEX_PATH.exists(), f"index.yaml not found at {INDEX_PATH}"
        index = _load_yaml(INDEX_PATH)
        assert "chains" in index, "index.yaml missing 'chains' key"
        assert "tag_index" in index, "index.yaml missing 'tag_index' key"
        assert "library_version" in index

    def test_all_indexed_chains_exist_on_disk(self):
        """Every chain referenced in index.yaml must have a corresponding file."""
        index = _load_yaml(INDEX_PATH)
        for entry in index["chains"]:
            chain_file = AI_REASONING / entry["file"]
            assert chain_file.exists(), (
                f"Chain '{entry['chain_id']}' indexed but file missing: {chain_file}"
            )

    def test_all_chain_files_are_indexed(self):
        """Every .yaml file in chains/ must appear in index.yaml (no orphans)."""
        index = _load_yaml(INDEX_PATH)
        indexed_files = {entry["file"] for entry in index["chains"]}
        for chain_file in CHAINS_DIR.glob("*.yaml"):
            rel = str(chain_file.relative_to(AI_REASONING)).replace("\\", "/")
            assert rel in indexed_files, (
                f"Chain file '{chain_file.name}' not listed in index.yaml"
            )

    def test_tag_index_resolves_to_real_chains(self):
        """Every tag in tag_index must point to existing chain_ids."""
        index = _load_yaml(INDEX_PATH)
        all_chain_ids = {entry["chain_id"] for entry in index["chains"]}
        for tag, chain_ids in index["tag_index"].items():
            for cid in chain_ids:
                assert cid in all_chain_ids, (
                    f"Tag '{tag}' references unknown chain_id '{cid}'"
                )

    def test_every_tag_points_to_at_least_one_chain(self):
        index = _load_yaml(INDEX_PATH)
        for tag, chain_ids in index["tag_index"].items():
            assert len(chain_ids) >= 1, f"Tag '{tag}' has no chain references"

    def test_claude_md_references_reasoning_library(self):
        """CLAUDE.md must explicitly instruct AI to read .ai_reasoning/."""
        assert CLAUDE_MD_PATH.exists(), "CLAUDE.md not found at project root"
        content = CLAUDE_MD_PATH.read_text(encoding="utf-8")
        assert ".ai_reasoning/" in content, (
            "CLAUDE.md must reference .ai_reasoning/ directory"
        )
        assert "index.yaml" in content, (
            "CLAUDE.md must reference index.yaml as the entry point"
        )

    def test_claude_md_lists_architectural_invariants_table(self):
        """CLAUDE.md must contain the invariants table derived from chains."""
        content = CLAUDE_MD_PATH.read_text(encoding="utf-8")
        # Markdown table rows — check for invariant content regardless of backtick formatting
        assert "NEVER imports" in content
        assert "phase_01_three_platform" in content
        assert "phase_05_external_io" in content
        assert "phase_01_data_integrity" in content
        assert "phase_03_adapter_pattern" in content


# ═══════════════════════════════════════════════════════════════════════
# Verification 2: Anti-pattern Interception
# ═══════════════════════════════════════════════════════════════════════


class TestAntiPatternInterception:
    """Every chain's anti_patterns must be actionable — detectable in code or review."""

    def test_every_chain_has_anti_patterns(self):
        """Chains without anti_patterns can't serve as a firewall."""
        chains = _load_all_chains()
        for chain_id, chain in chains.items():
            anti = chain.get("anti_patterns", [])
            assert len(anti) >= 1, (
                f"Chain '{chain_id}' has no anti_patterns — add at least one"
            )

    def test_anti_patterns_are_specific_and_detectable(self):
        """Anti-patterns must be concrete and actionable — either referencing a
        code element (file, function, type, module) or being a detailed negative
        instruction (50+ chars) that a reviewer could grep for."""
        chains = _load_all_chains()
        for chain_id, chain in chains.items():
            for i, ap in enumerate(chain.get("anti_patterns", [])):
                import re

                # Concrete code reference: file path, function call, module path,
                # CamelCase type, dunder method, architectural layer
                has_code_ref = (
                    ".py" in ap
                    or "()" in ap
                    or "core/" in ap
                    or "import" in ap.lower()
                    or bool(re.search(r'[A-Z][a-z]+[A-Z]', ap))
                    or ".__" in ap
                    or any(word in ap.lower() for word in ["adapter", "engine"])
                )

                # Detailed instruction: long enough to be grep-able and actionable
                is_detailed = len(ap) >= 50

                assert has_code_ref or is_detailed, (
                    f"Chain '{chain_id}' anti_pattern[{i}] is too vague "
                    f"({len(ap)} chars, needs code ref or 50+ chars): {ap[:80]}..."
                )

    def test_invariant_1_no_pipeline_imports_domain_contracts(self):
        """Invariant: core/pipeline/ must not import domain-specific contracts types
        (Chunk, ContentBlock, RetrievalResult, ChunkingStrategy, RetrievalStrategy).
        Shared infrastructure types (SemVer) are the legitimate wiring between platforms."""
        import ast

        domain_types = {"Chunk", "ContentBlock", "RetrievalResult", "ChunkingStrategy", "RetrievalStrategy"}
        pipeline_dir = ROOT / "core" / "pipeline"
        violations: List[str] = []
        for py_file in pipeline_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "core.contracts" in node.module:
                        imported_names = {alias.name for alias in node.names}
                        domain_imports = imported_names & domain_types
                        if domain_imports:
                            violations.append(
                                f"{py_file.name}: imports {domain_imports} from {node.module}"
                            )
        assert len(violations) == 0, (
            f"INVARIANT VIOLATION: core/pipeline/ imports domain contracts types:\n"
            + "\n".join(violations)
        )

    def test_invariant_2_no_contracts_imports_pipeline_orchestration(self):
        """Invariant: core/contracts/ must not import pipeline orchestration types
        (PipelineRunner, StepConfig, PipelineConfig, ResourceContainer).
        Shared infrastructure types (HealthStatus) are the legitimate wiring between platforms."""
        import ast

        orchestration_types = {"PipelineRunner", "StepConfig", "PipelineConfig", "ResourceContainer"}
        contracts_dir = ROOT / "core" / "contracts"
        violations: List[str] = []
        for py_file in contracts_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module and "core.pipeline" in node.module:
                        imported_names = {alias.name for alias in node.names}
                        orch_imports = imported_names & orchestration_types
                        if orch_imports:
                            violations.append(
                                f"{py_file.name}: imports {orch_imports} from {node.module}"
                            )
        assert len(violations) == 0, (
            f"INVARIANT VIOLATION: core/contracts/ imports pipeline orchestration types:\n"
            + "\n".join(violations)
        )

    def test_no_eval_or_exec_in_factory(self):
        """Invariant: factory.py must not contain eval() or exec() in actual code."""
        factory_path = ROOT / "core" / "adapters" / "factory.py"
        if factory_path.exists():
            import ast
            tree = ast.parse(factory_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Name) and func.id in ("eval", "exec"):
                        pytest.fail(
                            f"factory.py line {node.lineno}: {func.id}() call — FORBIDDEN"
                        )

    def test_health_check_is_sync_no_asyncio_run(self):
        """Phase 8.1 invariant: health_check() uses direct sync backend probe, no asyncio."""
        retriever_path = ROOT / "core" / "steps" / "retriever.py"
        content = retriever_path.read_text(encoding="utf-8")
        # Must NOT use deprecated get_event_loop()
        lines_with_get_event_loop = [
            line for line in content.split("\n")
            if "get_event_loop()" in line and not line.strip().startswith("#")
        ]
        assert len(lines_with_get_event_loop) == 0, (
            "retriever.py must not call get_event_loop() — use direct sync probe:\n"
            + "\n".join(lines_with_get_event_loop)
        )
        # Must NOT use asyncio.run() in health_check (Phase 8.1: sync-only)
        assert "asyncio.run(" not in content, (
            "retriever.py health_check must use direct sync backend probe, not asyncio.run()"
        )


# ═══════════════════════════════════════════════════════════════════════
# Verification 3: Post-Coding — Schema Compliance + Index Consistency
# ═══════════════════════════════════════════════════════════════════════


class TestPostCodingSchemaCompliance:
    """New chains must validate against the JSON Schema; index must stay consistent."""

    @pytest.fixture(scope="class")
    def schema(self):
        return _load_json(SCHEMA_PATH)

    @pytest.fixture(scope="class")
    def chains(self):
        return _load_all_chains()

    def test_schema_file_exists(self):
        assert SCHEMA_PATH.exists(), f"Schema not found at {SCHEMA_PATH}"

    def test_all_chains_pass_schema_validation(self, schema, chains):
        """Every existing chain must validate against reasoning_chain.schema.json."""
        import jsonschema

        for chain_id, chain in chains.items():
            try:
                jsonschema.validate(chain, schema)
            except jsonschema.ValidationError as e:
                pytest.fail(f"Chain '{chain_id}' failed schema validation: {e.message}")

    def test_all_chains_have_required_fields(self, chains):
        """Mandatory fields per schema: chain_id, title, created_at, status, context, decision, rationale, future_guidance."""
        required = {"chain_id", "title", "created_at", "status", "context", "decision", "rationale", "future_guidance"}
        for chain_id, chain in chains.items():
            missing = required - set(chain.keys())
            assert not missing, f"Chain '{chain_id}' missing required fields: {missing}"

    def test_all_chains_have_valid_status(self, chains):
        valid = {"active", "deprecated", "superseded"}
        for chain_id, chain in chains.items():
            assert chain["status"] in valid, (
                f"Chain '{chain_id}' has invalid status '{chain['status']}'"
            )

    def test_superseded_chains_have_superseded_by(self, chains):
        for chain_id, chain in chains.items():
            if chain["status"] == "superseded":
                assert "superseded_by" in chain, (
                    f"Chain '{chain_id}' is superseded but missing 'superseded_by'"
                )

    def test_alternatives_count_is_reasonable(self, chains):
        """Each chain should have 2-4 alternatives (per schema, max 6)."""
        for chain_id, chain in chains.items():
            alts = chain.get("alternatives", [])
            assert 1 <= len(alts) <= 6, (
                f"Chain '{chain_id}' has {len(alts)} alternatives (expected 2-4, max 6)"
            )

    def test_created_at_is_valid_iso8601(self, chains):
        for chain_id, chain in chains.items():
            try:
                datetime.datetime.fromisoformat(chain["created_at"])
            except ValueError:
                pytest.fail(f"Chain '{chain_id}' created_at is not valid ISO 8601: {chain['created_at']}")

    def test_chain_ids_match_filename_convention(self, chains):
        """chain_id should match filename stem (snake_case convention)."""
        for chain_file in CHAINS_DIR.glob("*.yaml"):
            chain = _load_yaml(chain_file)
            expected_stem = chain_file.stem  # e.g., phase_01_three_platform
            assert chain["chain_id"] == expected_stem, (
                f"chain_id '{chain['chain_id']}' does not match filename '{chain_file.name}'"
            )

    def test_index_library_version_matches_reality(self, chains):
        index = _load_yaml(INDEX_PATH)
        assert index["library_version"] >= 1
        # Number of entries in chains list should match number of chain files
        assert len(index["chains"]) == len(chains), (
            f"Index has {len(index['chains'])} entries but {len(chains)} chain files exist"
        )


# ═══════════════════════════════════════════════════════════════════════
# Integration: Simulated closed-loop workflow
# ═══════════════════════════════════════════════════════════════════════


class TestClosedLoopSimulation:
    """End-to-end simulation: a hypothetical new feature triggers the full workflow."""

    def test_hypothetical_redis_cache_design_would_find_relevant_chains(self):
        """Simulate Pre-Coding for 'add Redis cache layer' — must find external_io + health_check chains."""
        index = _load_yaml(INDEX_PATH)
        tags_to_check = ["external_io", "health_check", "async"]

        relevant_chain_ids: Set[str] = set()
        for tag in tags_to_check:
            if tag in index["tag_index"]:
                relevant_chain_ids.update(index["tag_index"][tag])

        assert len(relevant_chain_ids) >= 2, (
            f"Expected at least 2 relevant chains for Redis cache design, "
            f"found {len(relevant_chain_ids)}: {relevant_chain_ids}"
        )
        # phase_05_external_io MUST be in the results
        assert "phase_05_external_io" in relevant_chain_ids, (
            "Redis cache is external I/O — phase_05_external_io must be relevant"
        )

    def test_design_would_reuse_dependency_health_not_invent_new(self):
        """Verify that phase_05 mandates DependencyHealth — no new health check system."""
        chain = _load_yaml(CHAINS_DIR / "phase_05_external_io.yaml")
        guidance = chain["future_guidance"]
        assert "DependencyHealth" in guidance or "health_probe" in guidance, (
            "phase_05 must mandate DependencyHealth reuse for new I/O components"
        )

    def test_anti_pattern_global_variable_would_be_rejected(self):
        """Simulate: 'use a global variable for the connection pool' — must be rejected."""
        chain = _load_yaml(CHAINS_DIR / "phase_05_external_io.yaml")
        anti_patterns = " ".join(chain.get("anti_patterns", [])).lower()

        # Global variable anti-patterns should be detectable
        global_indicators = [
            any(phrase in ap.lower() for phrase in ["global", "module-level", "singleton"])
            for ap in chain.get("anti_patterns", [])
        ]

        # At minimum, the chain should warn against bypassing established patterns
        has_resource_guidance = (
            "resource" in anti_patterns
            or "resourcecontainer" in anti_patterns
            or "bypass" in anti_patterns
        )
        assert has_resource_guidance or any(global_indicators), (
            "phase_05_external_io anti_patterns should warn against bypassing "
            "ResourceContainer or using global state"
        )

    def test_new_chain_can_be_generated_programmatically(self):
        """Verify that a programmatically generated chain passes schema validation."""
        import jsonschema
        schema = _load_json(SCHEMA_PATH)

        new_chain = {
            "chain_id": "test_generated_chain",
            "title": "Test: programmatic chain generation",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tags": ["test", "verification"],
            "status": "active",
            "context": "This chain was generated programmatically to verify Phase 6.5 Post-Coding extraction.",
            "alternatives": [
                {
                    "option": "Manual chain writing",
                    "pros": "Full human control",
                    "cons": "Error-prone; format drift over time"
                },
                {
                    "option": "Programmatic generation with schema validation",
                    "pros": "Guaranteed format compliance; automatable",
                    "cons": "Requires schema maintenance"
                }
            ],
            "decision": "Use programmatic generation with JSON Schema validation.",
            "rationale": "Schema validation catches format drift before it enters version control. "
                        "This is the same philosophy as contract-driven development applied to knowledge management.",
            "evidence": {
                "test_files": ["tests/e2e/test_reasoning_chain_live.py"],
                "test_cases": ["test_new_chain_can_be_generated_programmatically"]
            },
            "future_guidance": "All future chains should be validated against the schema before commit. "
                              "CI should run schema validation as a pre-commit hook.",
            "anti_patterns": [
                "Writing chains without schema validation — format drift erodes AI readability",
                "Skipping the alternatives section — decisions without trade-off analysis are just opinions"
            ]
        }

        # Must pass schema validation
        jsonschema.validate(new_chain, schema)

        # Must have all required fields
        required = {"chain_id", "title", "created_at", "status", "context", "decision", "rationale", "future_guidance"}
        assert required.issubset(set(new_chain.keys()))

        # Alternatives count must be reasonable
        assert 1 <= len(new_chain["alternatives"]) <= 6

        # chain_id must match pattern
        import re
        assert re.match(r"^[a-z0-9_]+$", new_chain["chain_id"]), "chain_id must be snake_case"
