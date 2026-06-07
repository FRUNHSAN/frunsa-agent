"""Tool Adapter — Phase 22a.

Translates LLM function_call → ToolCall → ToolResult, with contract-aware
validation. This is NOT an RPC layer — every tool invocation is validated
against the current Blueprint and flows into the contract compliance system.

Design:
  - ToolAdapter is a component adapter (1:1 translation, stateless) —
    same design paradigm as ChunkerAdapter.
  - _validate_against_blueprint() is the "semantic/intent alignment" check —
    it verifies that the LLM's tool choice makes contractual sense.
  - All violations flow into event_sink → HealthEvaluator → SelfRepairEngine
    (Phase 22b).
  - Tool discovery via COMPONENT_REGISTRY.get("tool", name) — USB model.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

import core.adapters.tool_format_defaults  # noqa: triggers ToolFormatRegistry registration
from core.contracts import COMPONENT_REGISTRY
from core.contracts.composition import (
    CompositionBlueprint,
    ContractLifecycle,
    ContractViolation,
)
from core.contracts.tool import ToolCall, ToolProtocol, ToolResult


class ToolAdapter:
    """Translates LLM function_call → validated ToolCall → executed ToolResult.

    Usage:
        adapter = ToolAdapter(blueprint, event_sink=sink)
        tool_call = adapter.parse_function_call(llm_response)
        result = adapter.execute(tool_call)

    The adapter does NOT call the LLM — it only translates and executes.
    The LLM interaction is handled upstream (in the generation/planning layer).
    """

    def __init__(
        self,
        blueprint: CompositionBlueprint | None = None,
        event_sink: Callable | None = None,
    ) -> None:
        """Initialize with an optional blueprint for contract validation.

        Args:
            blueprint:   If provided, _validate_against_blueprint() checks
                         tool calls against this contract. If None, validation
                         is skipped (backward compatible / testing).
            event_sink:  Injected event sink for violation recording.
        """
        self._blueprint = blueprint
        self._emit = event_sink if event_sink is not None else (lambda _e: None)

    # ── Translation (LLM function_call → ToolCall) ─────────────────

    def parse_function_call(self, raw: dict) -> ToolCall:
        """Parse an LLM's raw function_call response into a ToolCall.

        Args:
            raw: Dict with keys 'name' (tool name) and 'arguments' (dict).

        Returns:
            ToolCall with deterministic call_id for audit.

        Raises:
            ValueError: if 'name' or 'arguments' are missing/invalid.
        """
        tool_name = raw.get("name", "")
        if not tool_name:
            raise ValueError("function_call missing 'name' field")

        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            # Some LLMs return arguments as a JSON string
            if isinstance(arguments, str):
                import json
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    raise ValueError(
                        f"function_call 'arguments' is not a valid dict or "
                        f"JSON string: {arguments!r}"
                    )
            else:
                raise ValueError(
                    f"function_call 'arguments' must be a dict, "
                    f"got {type(arguments).__name__}"
                )

        return ToolCall(
            tool_name=tool_name,
            parameters=arguments,
            timestamp=time.time(),
        )

    def from_llm_response(self, response: Any) -> ToolCall:
        """Convert an LLMResponse into a ToolCall — the type-safe bridge.

        Phase 22 P0: eliminates the fragile dict intermediate step.
        Accepts LLMResponse (from LLM/base.py) directly, extracting
        tool_name and tool_input with type safety instead of bare dict keys.

        Args:
            response: LLMResponse with type="tool_call"

        Returns:
            ToolCall ready for execute()

        Raises:
            ValueError: if response is not a tool_call type
        """
        if not hasattr(response, "is_tool_call") or not response.is_tool_call():
            raise ValueError(
                f"Expected LLMResponse with type='tool_call', "
                f"got type='{getattr(response, 'type', 'unknown')}'"
            )
        return ToolCall(
            tool_name=response.tool_name,
            parameters=dict(response.tool_input),
            timestamp=time.time(),
        )

    # ── Execution (ToolCall → ToolResult) ───────────────────────────

    def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a ToolCall via COMPONENT_REGISTRY with contract validation.

        1. Validate against blueprint (tool exists? params match?)
        2. Look up tool via Registry (USB model)
        3. Execute with params
        4. Check output contract
        5. Return ToolResult with violation info

        Tool execution failures (exceptions during execute()) are wrapped
        as ToolResult(success=False) — they are TECHNICAL failures, not
        contract violations (same pattern as PipelineAssembler).
        """
        # Step 1: Validate against blueprint contract
        violation = self._validate_against_blueprint(tool_call)
        if violation is not None:
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=False,
                error=f"Contract violation: {violation.value}",
                contract_violation=violation,
                timestamp=time.time(),
            )
            self._emit(self._make_event(tool_call, result, violation))
            return result

        # Step 2: Look up tool via USB Registry
        try:
            tool_cls = COMPONENT_REGISTRY.get("tool", tool_call.tool_name)
        except KeyError:
            violation = ContractViolation.TOOL_NOT_FOUND
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=False,
                error=f"Tool '{tool_call.tool_name}' not found in Registry",
                contract_violation=violation,
                timestamp=time.time(),
            )
            self._emit(self._make_event(tool_call, result, violation))
            return result

        # Step 3: Instantiate and execute
        tool: ToolProtocol = tool_cls()
        try:
            result = tool.execute(**dict(tool_call.parameters))
        except Exception as exc:
            # Execution failure = technical, not contractual
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                success=False,
                error=f"Tool execution failed: {type(exc).__name__}: {exc}",
                contract_violation=None,  # technical, not contractual
                timestamp=time.time(),
            )
            self._emit(self._make_event(tool_call, result, None))
            return result

        # Step 4: Check output contract
        output_violation = self._check_output_contract(result)
        if output_violation is not None:
            result = ToolResult(
                call_id=result.call_id,
                tool_name=result.tool_name,
                success=False,
                data=result.data,
                error=result.error,
                contract_violation=output_violation,
                timestamp=result.timestamp,
            )

        # Step 5: Emit event
        self._emit(self._make_event(
            tool_call, result, result.contract_violation
        ))
        return result

    # ── Tool Schema Conversion (Phase 22 LLM wiring) ──────────────

    @staticmethod
    def to_llm_tool_format(
        registry_tools: list[dict] | None = None,
        provider: str = "anthropic",
    ) -> list[dict]:
        """Convert USB-registered tools to LLM-native tool format.

        Scans COMPONENT_REGISTRY for all registered tools and converts
        their parameters_schema into the format expected by each LLM provider.

        Args:
            registry_tools: Optional pre-filtered tool list. If None,
                           auto-discovers all registered tools via Registry.
            provider:       "anthropic" or "openai"

        Returns:
            List of tool definitions in the provider's native format.

        Anthropic format:
            {"name": "...", "description": "...",
             "input_schema": {"type": "object", "required": [...], "properties": {...}}}

        OpenAI format:
            {"type": "function", "function": {
                "name": "...", "description": "...",
                "parameters": {"type": "object", "required": [...], "properties": {...}}}}
        """
        from core.contracts import COMPONENT_REGISTRY

        if registry_tools is None:
            tool_names = COMPONENT_REGISTRY.list_strategies("tool")
            registry_tools = []
            for name in tool_names:
                try:
                    cls = COMPONENT_REGISTRY.get("tool", name)
                    registry_tools.append({
                        "name": getattr(cls, "name", name),
                        "description": getattr(cls, "description", ""),
                        "parameters_schema": getattr(
                            cls, "parameters_schema", {},
                        ),
                    })
                except KeyError:
                    continue

        from core.adapters.tool_format_registry import ToolFormatRegistry
        return ToolFormatRegistry.format(provider, registry_tools)

    @staticmethod
    def _sanitize_schema(schema: dict) -> dict:
        """Strip advanced JSON Schema features that LLMs don't support.

        Keeps: type, required, properties, description
        Strips: default, enum, oneOf, anyOf, allOf, $ref, const,
                pattern, minLength, maxLength, minimum, maximum,
                additionalProperties (for now)

        Phase 22 minimal: only required + properties + type + description.
        """
        clean: dict = {"type": schema.get("type", "object")}

        if "description" in schema:
            clean["description"] = schema["description"]

        if "required" in schema:
            clean["required"] = schema["required"]

        if "properties" in schema:
            clean["properties"] = {}
            for prop_name, prop_schema in schema["properties"].items():
                clean_prop = {"type": prop_schema.get("type", "string")}
                if "description" in prop_schema:
                    clean_prop["description"] = prop_schema["description"]
                clean["properties"][prop_name] = clean_prop

        return clean

    # ── Validation ──────────────────────────────────────────────────

    def _validate_against_blueprint(
        self, tool_call: ToolCall
    ) -> ContractViolation | None:
        """Validate a ToolCall against the current Blueprint contract.

        Phase 22a minimal checks:
          1. Tool name is non-empty
          2. Tool exists in COMPONENT_REGISTRY
          3. Parameters match the tool's declared schema (basic)

        Phase 22+ extensions (not yet implemented):
          - Tool allowlists per blueprint (contract-aware routing)
          - Parameter range validation (budget, rate limits)
          - Lifecycle-aware routing (draft tools, deprecated tools)

        Returns None if the call is contractually valid.
        """
        if not tool_call.tool_name:
            return ContractViolation.TOOL_NOT_FOUND

        # Check Registry existence
        try:
            tool_cls = COMPONENT_REGISTRY.get("tool", tool_call.tool_name)
        except KeyError:
            return ContractViolation.TOOL_NOT_FOUND

        # Check parameter compatibility
        if hasattr(tool_cls, "parameters_schema"):
            schema = tool_cls.parameters_schema
            # MCPToolWrapper uses @property — instantiate to get value
            if isinstance(schema, property):
                try:
                    schema = schema.fget(tool_cls())
                except Exception:
                    schema = {}
            required = schema.get("required", [])
            properties = schema.get("properties", {})
            provided = set(dict(tool_call.parameters).keys())

            # Check required params are present
            missing = set(required) - provided
            if missing:
                return ContractViolation.TOOL_PARAM_MISMATCH

            # Check provided params exist in schema
            unknown = provided - set(properties.keys())
            if unknown:
                return ContractViolation.TOOL_PARAM_MISMATCH

        return None

    @staticmethod
    def _check_output_contract(
        result: ToolResult,
    ) -> ContractViolation | None:
        """Check if the tool result violates output expectations.

        Phase 22a minimal: if success=False and no contract_violation set,
        it might still be an output contract issue. For now, only flag
        explicit output schema mismatches.

        Phase 22+ extensions:
          - Output JSON Schema validation
          - Response time budget enforcement
          - Data freshness/staleness checks
        """
        if not result.success and result.contract_violation is None:
            # Tool failed but the failure isn't classified yet.
            # If there's error text suggesting malformed output → violation
            if result.error and "schema" in result.error.lower():
                return ContractViolation.OUTPUT_CONTRACT_VIOLATION
        return None

    # ── Event emission ──────────────────────────────────────────────

    @staticmethod
    def _make_event(
        tool_call: ToolCall,
        result: ToolResult,
        violation: ContractViolation | None,
    ) -> Any:
        """Build a CompositionEvent-compatible dict for the event sink.

        Uses the CompositionEvent shape: event_type, correlation_id,
        timestamp, context. Built as a dict to avoid circular import
        (tool_adapter shouldn't import composition.py for event types).
        """
        from core.contracts.composition import CompositionEvent

        return CompositionEvent(
            event_type="tool_executed",
            correlation_id=tool_call.call_id,
            timestamp=time.time(),
            context={
                "tool_name": tool_call.tool_name,
                "call_id": tool_call.call_id,
                "success": result.success,
                "error": result.error,
                "contract_violation": violation,
            },
        )

    # ── Properties ──────────────────────────────────────────────────

    @property
    def blueprint(self) -> CompositionBlueprint | None:
        return self._blueprint
