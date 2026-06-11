"""Container — dependency injection. The only place that knows concrete classes."""

from __future__ import annotations

from core.config import Config
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.user_profile import UserProfile
from core.contracts.blueprint_schema import blueprint_defaults
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.contract_auditor import ContractAuditor
from core.adapters.output_pipeline import OutputPipeline
from core.adapters.output_grammar import build_grammar as build_gbnf
from core.adapters.action_pipeline import ActionPipeline
from core.adapters.stream_interceptor import StreamInterceptor
from core.adapters.threshold_learner import EMALearner
from core.adapters.feedback_listener import FeedbackListener
from core.adapters.knowledge_search import warm_cache
from core.contracts.registry import COMPONENT_REGISTRY
from core.xray_bus import XRayBus


class Container:
    """Assembles the full agent pipeline from config."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

        # ── Persistence ──
        self.profile = UserProfile.load(cfg.user_id)
        self.learner = EMALearner(user_id=cfg.user_id)

        # ── V7.4: Cross-session identity manifold ──
        self._identity_store = None  # Lazy-loaded

        # ── V7.5: Entropy monitor for active concern ──
        self._entropy_monitor = None  # Lazy-loaded

        # ── Contract engine ──
        self.bp = DynamicBlueprint(blueprint_defaults())
        self.engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)

        # ── Shared event bus (decouples components from X-Ray display) ──
        self.bus = XRayBus()

        # ── Engine layer (V4.3: ToolEngine as 4th engine) ──
        from engines.tool import RegistryToolEngine
        self.tool_engine = RegistryToolEngine()

        # ── Enforcement ──
        self.output_pipeline = OutputPipeline(self.bp)
        self.action_pipeline = ActionPipeline(self.bp, trust=0.30)
        self.fsm = StreamInterceptor()
        self.listener = FeedbackListener(self.learner)

        # ── Adaptive tracking (V5: Wasserstein model reduction) ──
        from core.adapters.tracking_error import TrackingErrorEstimator
        from core.adapters.meta_adapt_trigger import MetaAdaptTrigger
        from core.adapters.selection_pressure_accumulator import SelectionPressureAccumulator
        self.tracking_error = TrackingErrorEstimator(tau=300.0)
        self.meta_adapt = MetaAdaptTrigger()
        self.selection_pressure = SelectionPressureAccumulator()

        # ── Pre-load all registered components before sealing ──
        import core.adapters.keyword_chunker  # noqa: triggers @register_component
        import core.adapters.semantic_chunker  # noqa: triggers @register_component
        import core.execution.sandbox_tool     # noqa: V7.2 — register sandbox_python
        import components.tools.run_powershell  # noqa: V8.4 — register run_powershell
        import components.tools.filesystem_tools # noqa: V8.4 — register write_file, read_file

        # ── Mock MCP tools (always available for demo) ──
        try:
            from core.adapters.mock_mcp_tools import register_mock_mcp_tools
            n = len(register_mock_mcp_tools())
            import sys
            print(f"  [🔧 工具] 注册 {n} 个 mock 工具 (mcp__*)", file=sys.stderr)
        except Exception:
            pass  # Non-critical

        # ── MCP tool discovery (graceful degradation) ──
        if cfg.mcp_servers:
            self._boot_mcp_servers(cfg.mcp_servers)

        # ── Seal the registry (invariant #23) ──
        COMPONENT_REGISTRY.freeze()

        # ── Pre-warm RAG cache (async-friendly for low-spec laptops) ──
        try:
            n = warm_cache()
            if n > 0:
                import sys
                print(f"  [RAG] 预热 {n} 个 chunks 完成", file=sys.stderr)
        except Exception:
            pass  # Startup must not fail on cache warming

        # ── LLM clients (lazy, requires API key) ──
        self._cloud_llm = None
        self._local_llm = None
        self._auditor = None

    # ── V7.4: Identity manifold (lazy) ──

    @property
    def identity_store(self):
        """Lazy-load IdentityManifoldStore — pure math, zero API calls."""
        if self._identity_store is None:
            from core.memory.identity_manifold import IdentityManifoldStore
            self._identity_store = IdentityManifoldStore()
        return self._identity_store

    @property
    def entropy_monitor(self):
        """Lazy-load EntropyMonitor — pure math, zero API calls."""
        if self._entropy_monitor is None:
            from core.watcher.entropy_monitor import EntropyMonitor
            self._entropy_monitor = EntropyMonitor()
        return self._entropy_monitor

    @property
    def cloud_llm(self):
        if self._cloud_llm is None:
            from LLM.deepseek import DeepSeekClient
            self._cloud_llm = DeepSeekClient(
                model="deepseek-chat", temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        return self._cloud_llm

    @property
    def local_llm(self):
        if self._local_llm is None:
            from LLM.native_llm import NativeLLMClient
            self._local_llm = NativeLLMClient(
                max_tokens=self.cfg.max_tokens, temperature=self.cfg.temperature,
                n_ctx=2048, n_gpu_layers=0,
            )
        return self._local_llm

    def _boot_mcp_servers(self, server_specs: list[str]) -> None:
        """Start MCP servers and register their tools into COMPONENT_REGISTRY.

        Each spec is a comma-separated command string.
        Example: --mcp "npx,@anthropic/mcp-server-filesystem,/path/to/dir"
        Graceful degradation: if a server fails to start, log and skip.
        """
        import sys, shlex
        try:
            from core.adapters.mcp_adapter import register_mcp_server
        except ImportError:
            print("  [🔌 MCP] mcp 包未安装。pip install mcp", file=sys.stderr)
            return
        except Exception:
            print("  [🔌 MCP] mcp_adapter 导入失败。跳过。", file=sys.stderr)
            return

        for spec in server_specs:
            # Split by space into command argv (like: "npx -y @anthropic/mcp-server-filesystem .")
            cmd = spec.strip().split()
            if not cmd:
                continue
            label = cmd[0]
            print(f"  [🔌 MCP] 正在连接 {label}...", file=sys.stderr)
            try:
                registered = register_mcp_server(cmd)
                print(f"  [🔌 MCP] {label} → 注册 {len(registered)} 个工具", file=sys.stderr)
            except Exception as e:
                print(f"  [🔌 MCP] {label} 启动失败: {e}", file=sys.stderr)

    # ── KernelService methods (Phase 5: engine decoupling) ──

    # ── KernelService Protocol alias methods (ContractAware wrappers call these names) ──
    def evaluate_health(self) -> dict:
        return self.kernel_evaluate_health()

    def decide_repair(self, report: dict) -> list:
        return self.kernel_decide_repair(report)

    def execute_repairs(self, actions: list) -> None:
        return self.kernel_execute_repairs(actions)

    def enforce(self, key: str):
        return self.kernel_enforce(key)

    def check_tool(self, tool_name: str) -> dict:
        return self.kernel_check_tool(tool_name)

    def _event_sink(self, event=None, **kwargs):
        """KernelService.event_sink — accepts CompositionEvent or (stage, detail) pair.

        ContractAware wrappers call kernel.event_sink(CompositionEvent(...)).
        REPL calls kernel.event_sink(stage="X", detail="Y").
        Both paths route to XRayBus.
        """
        if event is not None:
            # ContractAware path: only log significant events, skip diagnostic noise
            if event.event_type in ("document_failed", "contract_violated"):
                self.bus.emit("契约事件", event.context.get("message", str(event.context)[:80]))
        elif "stage" in kwargs:
            # REPL path: stage + detail keywords
            self.bus.emit(kwargs["stage"], kwargs.get("detail", ""))
        else:
            # Fallback: log raw
            self.bus.emit("event_sink", str(kwargs))

    @property
    def event_sink(self):
        """Property accessor for event_sink as callable."""
        return self._event_sink

    def generate(self, prompt: str, context: Any = None, **params: Any) -> Any:
        """Sync LLM generation (KernelService.generate stub for ContractAware wrappers).

        Note: engines use kernel_generate for async. This provides a sync version
        for ContractAware wrappers that need a simple generate() call.
        """
        return self.cloud_llm.generate(prompt)

    async def kernel_generate(self, prompt: str, context: Any = None, **params):
        """Async LLM generation — KernelService.generate() implementation."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.cloud_llm.generate, prompt)

    def kernel_enforce(self, key: str):
        """Hard-read contract field — KernelService.enforce() implementation."""
        return self.bp.enforce(key)

    def kernel_check_tool(self, tool_name: str) -> dict:
        """ActionPipeline gate — KernelService.check_tool() implementation."""
        return self.action_pipeline.check(tool_name)

    def kernel_evaluate_health(self) -> dict:
        """Contract health evaluation — 3 signals: backlash, guardrail squeeze, trust collapse."""
        failures = sum(self.action_pipeline._failure_counts.values())
        backlash = any(v >= 3 for v in self.action_pipeline._failure_counts.values())
        thresholds = self.learner.get_all_thresholds()
        from core.adapters.threshold_learner import GUARDRAILS
        at_guardrail = [
            dim for dim, (lo, hi) in GUARDRAILS.items()
            if thresholds.get(dim, 0) <= lo or thresholds.get(dim, 0) >= hi
        ]
        trust = self.action_pipeline.trust

        if backlash or len(at_guardrail) >= 2 or trust < 0.10:
            status = "unhealthy"
        elif failures >= 2 or trust < 0.20 or len(at_guardrail) >= 1:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "overall_status": status,
            "trust": trust,
            "tool_failures": failures,
            "backlash_detected": backlash,
            "thresholds_at_guardrail": at_guardrail,
            "compliance_rate": 1.0 - failures / max(failures + 1, 1),
        }

    def kernel_decide_repair(self, report: dict) -> list:
        """Decide repair actions from health report. Idempotent — won't repeat."""
        actions = []
        status = report.get("overall_status", "healthy")

        if status == "unhealthy":
            current = self.bp.enforce("execution_autonomy") or "ASK_FIRST"
            if report.get("backlash_detected") and current != "DISABLED":
                actions.append({"action": "lock_failed_tools", "reason": "backlash"})
            if current not in ("ASK_FIRST", "DISABLED"):
                actions.append({"action": "lower_autonomy", "target": "ASK_FIRST"})

        elif status == "degraded":
            current = self.bp.enforce("execution_autonomy") or "ASK_FIRST"
            if current in ("FULL", "HIGH"):
                actions.append({"action": "lower_autonomy", "target": "ASK_FIRST"})
            if report.get("tool_failures", 0) >= 2:
                actions.append({"action": "suggest_trust_recalibration"})

        elif status == "healthy":
            # Phase 8: recovery — raise autonomy if sustained healthy
            healthy_rounds = report.get("healthy_rounds", 0)
            if healthy_rounds >= 3:
                current = self.bp.enforce("execution_autonomy") or "ASK_FIRST"
                if current in ("ASK_FIRST", "DISABLED"):
                    actions.append({"action": "raise_autonomy", "target": "HIGH"})

        return actions

    def kernel_execute_repairs(self, actions: list) -> None:
        """Execute repair actions — modify DynamicBlueprint in-place.

        V7.6: After repair, emit contract_synced event to close the
        nominal-actual divergence gap (裂缝 3). Kernel repairs skip
        ContractEvolutionEngine.evaluate() by design (they ARE the immune
        system), but the audit trail must still reflect the state change.
        """
        modified = False
        for action in actions:
            if action["action"] == "lower_autonomy":
                self.bp.apply_proposal("execution_autonomy", action["target"])
                self.bus.emit("自修复", f"autonomy → {action['target']} ({action.get('reason','健康恶化')})")
                modified = True
            elif action["action"] == "lock_failed_tools":
                self.bus.emit("自修复", "failed tools locked by backlash")
                modified = True
            elif action["action"] == "raise_autonomy":
                self.bp.apply_proposal("execution_autonomy", action["target"], ignore_cooldown=True)
                report_info = f"连续健康 {action.get('healthy_rounds', 0)} 轮" if action.get("healthy_rounds") else "恢复"
                self.bus.emit("自修复", f"autonomy → {action['target']} ({report_info})")
                modified = True
            elif action["action"] == "suggest_trust_recalibration":
                self.bus.emit("自修复", "建议信任校准")
        # V7.6: sync nominal state for audit consistency (裂缝 3)
        if modified:
            self.bus.emit("契约同步",
                f"kernel_repair applied, autonomy={self.bp.enforce('execution_autonomy')}")

    @property
    def auditor(self) -> ContractAuditor | None:
        if self._auditor is None:
            self._auditor = ContractAuditor(self.cloud_llm, interval=self.cfg.auditor_interval)
        return self._auditor
