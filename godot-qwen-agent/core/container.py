"""Container — dependency injection. The only place that knows concrete classes."""

from __future__ import annotations

from core.config import Config
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.user_profile import UserProfile
from core.contracts.blueprint_schema import blueprint_defaults
from core.adapters.contract_evolution_engine import ContractEvolutionEngine
from core.adapters.contract_auditor import ContractAuditor
from core.adapters.signal_interpreter import interpret as signal_interpret
from core.adapters.output_pipeline import OutputPipeline
from core.adapters.output_grammar import build_grammar as build_gbnf
from core.adapters.action_pipeline import ActionPipeline
from core.adapters.stream_interceptor import StreamInterceptor
from core.adapters.threshold_learner import EMALearner
from core.adapters.feedback_listener import FeedbackListener
from core.adapters.relational_patterns import RelationalPatterns
from core.adapters.narrative_emergence import NarrativeEmergence
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
        self.patterns = RelationalPatterns()
        self._narrative: NarrativeEmergence | None = None

        # ── Contract engine ──
        self.bp = DynamicBlueprint(blueprint_defaults())
        self.engine = ContractEvolutionEngine(trust_threshold=0.10, rollback_window=3)

        # ── Shared event bus (decouples components from X-Ray display) ──
        self.bus = XRayBus()

        # ── Enforcement ──
        self.output_pipeline = OutputPipeline(self.bp)
        self.action_pipeline = ActionPipeline(self.bp, trust=0.30)
        self.fsm = StreamInterceptor()
        self.listener = FeedbackListener(self.learner)

        # ── Pre-load all registered components before sealing ──
        import core.adapters.keyword_chunker  # noqa: triggers @register_component
        import core.adapters.semantic_chunker  # noqa: triggers @register_component

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

    @property
    def narrative(self) -> NarrativeEmergence:
        if self._narrative is None:
            self._narrative = NarrativeEmergence(self.patterns, self.cloud_llm)
        return self._narrative

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

    @property
    def auditor(self) -> ContractAuditor | None:
        if self._auditor is None:
            self._auditor = ContractAuditor(self.cloud_llm, interval=self.cfg.auditor_interval)
        return self._auditor
