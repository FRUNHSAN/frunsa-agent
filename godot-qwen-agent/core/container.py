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

        # ── Enforcement ──
        self.output_pipeline = OutputPipeline(self.bp)
        self.action_pipeline = ActionPipeline(self.bp, trust=0.30)
        self.fsm = StreamInterceptor()
        self.listener = FeedbackListener(self.learner)

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

    @property
    def auditor(self) -> ContractAuditor | None:
        if self._auditor is None:
            self._auditor = ContractAuditor(self.cloud_llm, interval=self.cfg.auditor_interval)
        return self._auditor
