"""Pipeline Composition Engine — the platform's grammar layer.

Three concerns, one file:
  SourceRouter      — routing engine: Blueprint + path → SourceRule (+ events)
  PipelineAssembler — assembly engine: SourceRules → RetrieverStep (+ diagnostics)
  PipelineComposer  — Facade: Blueprint → Router → Assembler (+ audit manifest)

All three live in core/adapters/ — the only layer legally allowed to import
from both core/contracts/ and core/pipeline/.
"""

from __future__ import annotations

import hashlib
import inspect
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

from core.contracts import (
    COMPONENT_REGISTRY,
    ContentBlock,
    SemVer,
)
from core.contracts.composition import (
    AssemblyDiagnostic,
    CompositionBlueprint,
    CompositionEvent,
    ContractLifecycle,
    ContractViolation,
    SourceRule,
)
from core.adapters.chunker_adapter import ChunkerAdapter
from core.pipeline.engine import HealthStatus
from core.pipeline.resources import ResourceContainer
from core.steps.retriever import InMemoryVectorBackend, RetrieverStep


# ── Routing Engine ─────────────────────────────────────────────────

class SourceRouter:
    """Pure routing engine: Blueprint + path → SourceRule.

    Zero adapter dependency. Zero side effects. Independently testable.
    The ONLY place where glob matching and priority sort live.
    """

    def __init__(
        self,
        blueprint: CompositionBlueprint,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> None:
        self._blueprint = blueprint
        self._emit = event_sink if event_sink is not None else (lambda _e: None)

    def resolve(self, path: str) -> SourceRule:
        """Return the highest-priority matching rule for a source path.

        Algorithm: iterate rules_by_priority (ascending), first fnmatch hit wins.
        Falls back to a synthetic SourceRule using default_chunker.

        Raises:
            AssemblyError: if the blueprint lifecycle is DEPRECATED.
                Already-executing pipelines are unaffected; this only blocks
                new routing requests.
        """
        if self._blueprint.lifecycle == ContractLifecycle.DEPRECATED:
            raise AssemblyError(
                f"Cannot route to deprecated blueprint "
                f"(version {self._blueprint.version}). "
                f"Use an active or draft alternative."
            )

        correlation_id = hashlib.sha256(path.encode()).hexdigest()[:12]

        for rule in self._blueprint.rules_by_priority:
            if rule.matches(path):
                self._emit(CompositionEvent(
                    event_type="rule_matched",
                    correlation_id=correlation_id,
                    timestamp=time.time(),
                    context={
                        "path": path,
                        "rule_id": rule.rule_id,
                        "pattern": rule.pattern,
                        "priority": rule.priority,
                    },
                ))
                return rule
            self._emit(CompositionEvent(
                event_type="rule_skipped",
                correlation_id=correlation_id,
                timestamp=time.time(),
                context={"path": path, "pattern": rule.pattern, "reason": "no_match"},
            ))

        self._emit(CompositionEvent(
            event_type="fallback_used",
            correlation_id=correlation_id,
            timestamp=time.time(),
            context={"path": path, "default_chunker": self._blueprint.default_chunker},
        ))
        return SourceRule(
            pattern="*",
            chunker=self._blueprint.default_chunker,
            chunk_params=self._blueprint.default_params,
            priority=999,
            description=f"Default fallback: {self._blueprint.default_chunker}",
        )

    def resolve_all(self, paths: List[str]) -> Dict[str, SourceRule]:
        """Batch resolve: path → SourceRule."""
        return {p: self.resolve(p) for p in paths}

    @property
    def blueprint(self) -> CompositionBlueprint:
        return self._blueprint

    def health_check(self) -> HealthStatus:
        """Verify all referenced chunker strategies exist AND accept their declared params.

        Two-tier validation:
          1. Preferred: Chunker's own validate_params(params) -> list[str] classmethod
          2. Fallback: COMPONENT_REGISTRY's cached signature (captured at @register time)
        """
        issues: List[str] = []
        all_entries = [
            (self._blueprint.default_chunker, self._blueprint.default_params, "default")
        ]
        for rule in self._blueprint.source_rules:
            all_entries.append((rule.chunker, rule.chunk_params, rule.rule_id))

        for chunker_name, params, identifier in all_entries:
            try:
                cls = COMPONENT_REGISTRY.get("chunker", chunker_name)
            except KeyError:
                issues.append(
                    f"[{identifier}] Unknown chunker strategy: '{chunker_name}'"
                )
                continue

            if hasattr(cls, "validate_params"):
                semantic_errors = cls.validate_params(params)
                for err in semantic_errors:
                    issues.append(f"[{identifier}] {chunker_name}: {err}")
                if semantic_errors:
                    continue

            sig_errors = COMPONENT_REGISTRY.validate_params(
                "chunker", chunker_name, params
            )
            if sig_errors:
                issues.append(
                    f"[{identifier}] Invalid params for '{chunker_name}': {sig_errors}"
                )

        if issues:
            return HealthStatus(
                status="degraded",
                message=f"Configuration errors: {'; '.join(issues)}",
                dependencies=[],
                version=str(self._blueprint.version),
            )
        return HealthStatus(
            status="healthy",
            message=f"All {len(all_entries)} chunker references valid",
            dependencies=[],
            version=str(self._blueprint.version),
        )


# ── Assembly Engine ─────────────────────────────────────────────────

class PipelineAssembler:
    """Pure assembly engine: List[SourceRule] → RetrieverStep.

    Consumes Router output. Creates chunker instances via COMPONENT_REGISTRY,
    wraps in ChunkerAdapter, executes chunking, aggregates all Chunks into
    an InMemoryVectorBackend-backed RetrieverStep.
    """

    def __init__(
        self,
        event_sink: Callable[[CompositionEvent], None] | None = None,
        blueprint_lifecycle: ContractLifecycle = ContractLifecycle.ACTIVE,
    ) -> None:
        self._diagnostics: List[AssemblyDiagnostic] = []
        self._emit = event_sink if event_sink is not None else (lambda _e: None)
        self._blueprint_lifecycle = blueprint_lifecycle

    def assemble(
        self,
        resolved_rules: Dict[str, SourceRule],
        documents: Dict[str, ContentBlock],
        blueprint_version: str = "",
    ) -> RetrieverStep:
        """Compose a RetrieverStep from source documents and their resolved rules.

        Args:
            resolved_rules:   {path: SourceRule} from SourceRouter.resolve_all()
            documents:        {path: ContentBlock} from document loader
            blueprint_version: For chunk-level lineage tagging

        Returns:
            RetrieverStep backed by InMemoryVectorBackend with all chunks indexed.

        Raises:
            AssemblyError: if ALL documents failed (no chunks produced).
        """
        self._diagnostics.clear()
        all_chunks = []
        composed_at = time.time()

        for path, doc in documents.items():
            correlation_id = hashlib.sha256(path.encode()).hexdigest()[:12]
            rule = resolved_rules.get(path)
            if rule is None:
                self._record_failure(
                    path, "unknown", "routing",
                    "No matching rule", correlation_id,
                )
                continue

            try:
                chunker_cls = COMPONENT_REGISTRY.get("chunker", rule.chunker)
            except KeyError:
                self._record_failure(
                    path, rule.chunker, "instantiation",
                    f"Unknown strategy: '{rule.chunker}'", correlation_id,
                )
                continue

            try:
                chunker = chunker_cls(**rule.chunk_params)
                params_hash = hashlib.sha256(
                    str(sorted(rule.chunk_params.items())).encode()
                ).hexdigest()[:8]
                self._emit(CompositionEvent(
                    event_type="chunker_instantiated",
                    correlation_id=correlation_id,
                    timestamp=time.time(),
                    context={
                        "rule_id": rule.rule_id,
                        "chunker": rule.chunker,
                        "params_hash": params_hash,
                        "version": str(chunker.VERSION),
                    },
                ))
            except TypeError as e:
                self._record_failure(
                    path, rule.chunker, "instantiation",
                    f"Invalid params for '{rule.chunker}': {e}", correlation_id,
                )
                continue

            try:
                adapter = ChunkerAdapter(chunker)
                resources = ResourceContainer()
                resources.set_config("source", path)
                output = adapter.run({"content": doc}, resources)
            except Exception as e:
                self._record_failure(
                    path, rule.chunker, "execution",
                    f"ChunkerAdapter failed: {e}", correlation_id,
                )
                continue

            if output.contract_validation and output.contract_validation.errors:
                self._record_failure(
                    path, rule.chunker, "validation",
                    f"Contract validation: {output.contract_validation.errors}",
                    correlation_id,
                )
                continue

            chunks = output.result
            for ch in chunks:
                all_chunks.append(
                    ch.with_metadata(
                        source_path=path,
                        chunker_strategy=rule.chunker,
                        chunker_version=str(chunker.VERSION),
                        rule_id=rule.rule_id,
                        blueprint_version=blueprint_version,
                        composed_at=composed_at,
                    )
                )

        success_paths = {
            d.path for d in self._diagnostics
        }
        success_count = len([p for p in documents if p not in success_paths])
        self._emit(CompositionEvent(
            event_type="assembly_complete",
            correlation_id="batch",
            timestamp=time.time(),
            context={
                "total_docs": len(documents),
                "success_count": success_count,
                "fail_count": len(self._diagnostics),
                "total_chunks": len(all_chunks),
            },
        ))

        if not all_chunks:
            raise AssemblyError(
                f"All {len(documents)} document(s) failed chunking. "
                f"Diagnostics: {self._diagnostics}"
            )

        backend = InMemoryVectorBackend(all_chunks)
        return RetrieverStep(backend=backend, index_chunks=all_chunks)

    @property
    def diagnostics(self) -> List[AssemblyDiagnostic]:
        return list(self._diagnostics)

    @staticmethod
    def _classify_violation(
        error_type: str, chunker: str, message: str
    ) -> ContractViolation | None:
        """Map a technical failure to a contract violation category.

        Not all failures are contract violations. Execution failures may be
        bugs or transient I/O errors — these return None. But instantiation
        failures (unknown strategy, invalid params) and validation failures
        are always violations of the Blueprint ↔ Component contract.

        Returns ContractViolation enum (str subclass — backward compatible).
        """
        if error_type == "routing":
            return ContractViolation.ROUTING_CONTRACT_BREACH
        if error_type == "instantiation":
            if "Unknown strategy" in message:
                return ContractViolation.UNKNOWN_CHUNKER_STRATEGY
            if "Invalid params" in message:
                return ContractViolation.INVALID_CHUNK_PARAMS
            return None
        if error_type == "execution":
            return None  # Technical failure, may be transient
        if error_type == "validation":
            return ContractViolation.OUTPUT_CONTRACT_VIOLATION
        return None

    def _record_failure(
        self, path: str, chunker: str,
        error_type: str,
        message: str,
        correlation_id: str,
    ) -> None:
        contract_violation = self._classify_violation(
            error_type, chunker, message
        )
        diag = AssemblyDiagnostic(
            path=path, chunker=chunker,
            error_type=error_type,  # type: ignore[arg-type]
            message=message,
            contract_violation=contract_violation,
        )
        self._diagnostics.append(diag)
        self._emit(CompositionEvent(
            event_type="document_failed",
            correlation_id=correlation_id,
            timestamp=diag.timestamp,
            context={
                "path": path,
                "chunker": chunker,
                "error_type": error_type,
                "message": message,
                "contract_violation": contract_violation,
                "blueprint_lifecycle": self._blueprint_lifecycle,
            },
        ))


# ── Facade ──────────────────────────────────────────────────────────

class PipelineComposer:
    """Public entry point: Blueprint → configured RetrieverStep + audit manifest.

    Thin facade. Contains no logic — delegates to:
      - CompositionBlueprint.from_*() for config parsing
      - SourceRouter for rule resolution
      - PipelineAssembler for step assembly
    """

    def __init__(
        self,
        blueprint: CompositionBlueprint,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> None:
        self._blueprint = blueprint
        self._init_timestamp = time.time()
        self._router = SourceRouter(blueprint, event_sink=event_sink)
        self._assembler = PipelineAssembler(
            event_sink=event_sink,
            blueprint_lifecycle=blueprint.lifecycle,
        )

    @classmethod
    def from_yaml(
        cls, path: str | Path,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> PipelineComposer:
        return cls(CompositionBlueprint.from_yaml(str(path)), event_sink=event_sink)

    @classmethod
    def from_dict(
        cls, raw: dict,
        event_sink: Callable[[CompositionEvent], None] | None = None,
    ) -> PipelineComposer:
        return cls(CompositionBlueprint.from_dict(raw), event_sink=event_sink)

    def compose_for_sources(
        self, source_paths: List[str], documents: Dict[str, ContentBlock]
    ) -> RetrieverStep:
        """Full pipeline: resolve rules → assemble → RetrieverStep."""
        resolved = self._router.resolve_all(source_paths)
        return self._assembler.assemble(
            resolved, documents, blueprint_version=str(self._blueprint.version)
        )

    @property
    def audit_manifest(self) -> Dict[str, Any]:
        return {
            "blueprint_fingerprint": self._blueprint.fingerprint,
            "blueprint_version": str(self._blueprint.version),
            "blueprint_lifecycle": self._blueprint.lifecycle,
            "router_type": type(self._router).__name__,
            "initialized_at": self._init_timestamp,
        }

    @property
    def blueprint(self) -> CompositionBlueprint:
        return self._blueprint

    @property
    def diagnostics(self) -> List[AssemblyDiagnostic]:
        return self._assembler.diagnostics

    def health_check(self) -> HealthStatus:
        return self._router.health_check()


class AssemblyError(Exception):
    """Raised when ALL documents fail chunking. Partial failures are non-fatal."""
