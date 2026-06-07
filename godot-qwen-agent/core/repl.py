"""REPL — interactive loop. Depends only on Container, no knowledge of backends."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from core.container import Container
from core.contracts.blueprint_schema import BLUEPRINT_SCHEMA
from core.adapters.agent_router import decide as route_decide
from core.adapters.stream_interceptor import FSMState
from core.xray import XRay
from core.trace_node import TraceNode, TraceStatus


async def _collect_stream(agen):
    """Drain an AsyncIterator into a list."""
    items = []
    async for item in agen:
        items.append(item)
    return items


def _get_registered_tools() -> list[dict]:
    """Return list of {name, description, required_params} for all registered tools."""
    from core.contracts.registry import COMPONENT_REGISTRY
    result = []
    for name in COMPONENT_REGISTRY.list_strategies("tool"):
        try:
            cls = COMPONENT_REGISTRY.get("tool", name)
            schema = getattr(cls, "parameters_schema", {})
            if isinstance(schema, property):
                try:
                    schema = schema.fget(cls())
                except Exception:
                    schema = {}
            desc = getattr(cls, "description", "")
            if isinstance(desc, property):
                try:
                    desc = desc.fget(cls())
                except Exception:
                    desc = name
            if not desc and hasattr(cls, "_mcp_description"):
                desc = cls._mcp_description
            result.append({
                "name": name,
                "description": str(desc)[:100],
                "required_params": schema.get("required", []) if isinstance(schema, dict) else [],
            })
        except Exception:
            pass
    return result

# ── Semantic command classifier (embedding-based, no hardcoded keywords) ──
_EMBED_MODEL: object | None = None


def _get_command_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        import os
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        import numpy as np
        from sentence_transformers import SentenceTransformer, util as st_util
        m = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        anchors = {
            "response_verbose_level:MINIMAL": ["字少点", "别啰嗦", "简单点说", "话少点", "精简", "简洁", "短一点"],
            "response_verbose_level:HIGH": ["详细点", "展开讲讲", "多说点", "再讲讲", "展开来说"],
            "response_verbose_level:MEDIUM": ["字多点", "多一点", "多一点点", "多讲几句"],
            "conversational_initiative:PROACTIVE": ["你问", "问问题", "反问", "问我", "你问我", "问我几个", "你倒是问", "继续问", "多问点"],
            "conversational_initiative:RESPONSIVE_ONLY": ["别问了", "不要问", "别反问", "别老问我"],
            "tone_style:WARM": ["带点感情", "自然点", "像朋友", "来点人味"],
        }
        centers = {}
        for label, sentences in anchors.items():
            centers[label] = np.mean(m.encode(sentences), axis=0)
        _EMBED_MODEL = (m, st_util, centers)
    return _EMBED_MODEL


def _classify_command(text: str) -> tuple[str, str] | None:
    # Short greetings/closers + very short text should never trigger commands
    t = text.strip()
    if len(t) < 3 or t in ("拜拜", "再见", "bye", "晚安", "谢谢", "好的", "你好", "可以", "嗯", "哦"):
        return None
    if t.startswith("好的"):
        return None
    m, st_util, centers = _get_command_model()
    # Guard: garbled/surrogate text → skip classification
    if not text or any(0xD800 <= ord(c) <= 0xDFFF for c in text):
        return None
    try:
        emb = m.encode([text])[0]
    except Exception:
        # Older sentence-transformers accept bare string; fallback gracefully
        try:
            emb = m.encode(text)
        except Exception:
            return None
    best_label, best_score = None, 0.0
    for label, center in centers.items():
        s = float(st_util.cos_sim(emb, center))
        if s > best_score:
            best_label, best_score = label, s
    if best_label and best_score > 0.70:
        key, val = best_label.split(":", 1)
        return (key, val)
    return None


class Repl:
    """Interactive chat loop. Assembled by Container, run by main()."""

    def __init__(self, ctr: Container) -> None:
        self.c = ctr
        self.trust = 0.30
        self.round_count = 0
        self.healthy_rounds = 0  # Phase 8: consecutive healthy rounds counter
        self.pending: list[dict] = []
        self._restore_contract_state()  # Phase 8b: cross-session persistence
        self.history: list[str] = []
        self.contract_events: list[str] = []
        self._amendments_shown: set[str] = set()
        self.prev_response_len = 0
        self.prev_signal: dict = {"dimension": None, "score": 0.0}
        # Embedding model loads lazily on first _route_task() or _classify_command() call

    # ── Prompt construction (delegates to adapters) ──

    def _build_prompt(self, uid: str = "default", xray: "XRay | None" = None) -> str:
        from core.adapters.output_grammar import build_grammar as build_gbnf

        def _build_contract_directive(bp_fields: dict) -> str:
            v = bp_fields.get("response_verbose_level", "HIGH")
            initiative = bp_fields.get("conversational_initiative", "BALANCED")
            tone = bp_fields.get("tone_style", "WARM")
            anchoring = bp_fields.get("contextual_anchoring", "HIGH")
            parts = ["[CURRENT MODE]"]
            v_map = {"HIGH": "详细解释, 600-800 字, 多用列表",
                     "MEDIUM": "均衡, 300-400 字",
                     "LOW": "简洁, 100-150 字, 单段落",
                     "MINIMAL": "一句话, 不超过 50 字"}
            parts.append(f"输出规范: {v_map.get(v, v)}")
            init_map = {"PROACTIVE": "主动引导对话", "BALANCED": "自然有来有回",
                        "RESPONSIVE_ONLY": "绝对不反问"}
            parts.append(f"主动性: {init_map.get(initiative, initiative)}")
            tone_map = {"ENTHUSIASTIC": "热情", "WARM": "温和", "CALM": "克制", "PRAGMATIC": "务实直白"}
            parts.append(f"语气: {tone_map.get(tone, tone)}")
            if anchoring == "LOW":
                parts.append("禁止: 晨光/阳光/月光/夜色/微风等时间天气隐喻。直接说事。")
            # Self-evolving values: render custom instruction from Blueprint
            for key in ("tone_style", "response_verbose_level", "explanation_style"):
                inst = self.c.bp.get_instruction(key)
                if inst:
                    parts.append(f"自定义特质({key}): {inst}")
            parts.append("禁止以'你说得对'/'你的判断正确'开头。分歧是尊重。")
            if v in ("LOW", "MINIMAL"):
                parts.append("格式锁: 单段落, 禁止列表/标题/引用。禁止复合句。")
            return "\n".join(parts)

        def _build_context(hist, events) -> str:
            parts = []
            if events:
                parts.append("[契约历史: " + " → ".join(events[-3:]) + "]")
            if hist:
                parts.append("[最近上下文]\n" + "\n".join(hist[-6:]))
            return "\n".join(parts) if parts else ""

        contract = _build_contract_directive(self.c.bp.snapshot)
        context = _build_context(self.history, self.contract_events)
        now = datetime.now().strftime("%H:%M")
        system = f"{contract}\n当前时间: {now}\n{context}".strip()

        # ── V2.2: Relational hint ──
        hint = self.c.patterns.generate_hint(self.c.cfg.user_id) if self.round_count <= 2 else None
        if hint:
            system = f"{hint}\n\n{system}"
            if xray: self.c.bus.emit("模式记录", hint[:80])
        # ── V3.1: Narrative emergence (first round only) ──
        if self.round_count == 1:
            narrative = self.c.narrative.inject(uid)
            if narrative:
                system = f"{narrative}\n\n{system}"
                if xray: self.c.bus.emit("叙事注入", f"注入用户画像 ({len(narrative)} chars)")
        return system

    def _detect_explicit_command(self, text: str) -> tuple[str, str] | None:
        """Semantic command detection via embedding — no hardcoded keywords."""
        try:
            return _classify_command(text)
        except Exception:
            return self._keyword_fallback(text)

    @staticmethod
    def _keyword_fallback(text: str) -> tuple[str, str] | None:
        t = text.strip()
        if any(w in t for w in ("字少点", "别啰嗦", "简洁", "简单点说", "短一点")):
            return ("response_verbose_level", "MINIMAL")
        if any(w in t for w in ("详细点", "展开", "多说点", "展开讲讲")):
            return ("response_verbose_level", "HIGH")
        if any(w in t for w in ("字多点", "多一点", "多一点点", "多讲几句")):
            return ("response_verbose_level", "MEDIUM")
        if any(w in t for w in ("带点感情", "来点人味", "像朋友")):
            return ("tone_style", "WARM")
        if any(w in t for w in ("别问了", "不要问", "别反问", "别老问")):
            return ("conversational_initiative", "RESPONSIVE_ONLY")
        if any(w in t for w in ("你问", "问问题", "反问", "问我", "问几个", "继续问", "多问")):
            return ("conversational_initiative", "PROACTIVE")
        return None

    # ── V4.1 Phase 3: Track A/B/C Router ──

    # Cached route anchors — computed once at init
    _route_anchors: dict[str, list[str]] = {}
    _route_centers: dict | None = None  # {track_label: numpy vector}

    @classmethod
    def _init_route_classifier(cls) -> None:
        """Pre-load embedding model and cache route anchors (暗礁 3: cold start).

        Reuses the same SentenceTransformer instance from _get_command_model()
        to avoid loading a second copy into memory.
        """
        if cls._route_centers is not None:
            return
        import numpy as np
        m, _, _ = _get_command_model()  # Reuse existing model
        anchors = {
            # "C" anchors: complex, multi-step, engine-worthy tasks
            "C": [
                "帮我准备面试", "写一份方案", "深度调研", "全面分析并给出策略",
                "帮我设计架构", "对比多个方案并推荐", "模拟答辩",
            ],
            # "B" anchors: moderate complexity, static 3-step sufficient
            "B": [
                "分析优缺点", "做个对比", "解释原理", "总结要点",
            ],
        }
        centers = {}
        for label, sentences in anchors.items():
            centers[label] = np.mean(m.encode(sentences), axis=0)
        cls._route_centers = centers

    @staticmethod
    def _route_task(text: str) -> str:
        """Embedding-based router: returns 'A', 'B', or 'C'.

        Thresholds calibrated from natural gaps in anchor similarity distribution.
        Tier 1 ambiguity → B (safer than falling to A).
        """
        try:
            return Repl._route_task_embedding(text)
        except Exception:
            return Repl._route_task_fallback(text)

    @staticmethod
    def _route_task_embedding(text: str) -> str:
        import os, numpy as np
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        # Ensure route centers are computed
        if Repl._route_centers is None:
            Repl._init_route_classifier()
        m, _, _ = _get_command_model()
        centers = Repl._route_centers
        emb = m.encode([text])[0]  # encode expects list, return first vector
        scores = {}
        for label, center in centers.items():
            scores[label] = float(np.dot(emb, center) / (
                np.linalg.norm(emb) * np.linalg.norm(center) + 1e-8
            ))
        # Tier decision: highest score wins, with minimum threshold
        best = max(scores, key=scores.get)
        best_score = scores[best]

        if best == "C" and best_score > 0.45:
            return "C"
        if best == "B" and best_score > 0.40:
            return "B"
        # Fuzzy: close to B/C boundary → B (safer than A)
        if best_score > 0.30:
            return "B"
        return "A"

    @staticmethod
    def _route_task_fallback(text: str) -> str:
        """Keyword fallback when embedding model is unavailable."""
        markers_c = ["面试", "答辩", "方案", "策略", "架构", "深度", "全面"]
        markers_b = ["分析", "比较", "对比", "原理", "优缺点", "为什么"]
        if any(m in text for m in markers_c):
            return "C"
        if any(m in text for m in markers_b):
            return "B"
        return "A"

    def _execute_tool(self, tool_name: str, params: dict, xray: XRay) -> str:
        """Execute a tool through ToolEngine (4th engine) with ActionPipeline gate."""
        # Contract gate (backlash, trust, autonomy)
        check = self.c.action_pipeline.check(tool_name)
        if not check["allowed"]:
            return f"[契约拦截: {check['reason']}]"

        try:
            from engines.tool import ToolContext
            from core.contracts.streaming_protocol import PaceConfig
            from core.track_c import safe_async_run

            ctx = ToolContext(tool_name=tool_name, parameters=params)
            items = safe_async_run(_collect_stream(
                self.c.tool_engine.execute(ctx, deadline=30.0, pace_config=PaceConfig())
            ))
            # Extract delta from StreamItems
            full = "".join(item.delta for item in items)
            if full:
                return full
            # Check for error in trace_context
            for item in items:
                if not item.trace_context:
                    continue
                if not item.trace_context.get("tool.success", True):
                    err = item.trace_context.get("tool.error", "unknown")
                    return f"[工具执行失败: {err}]"
            return "[工具返回空结果]"
        except Exception as e:
            return f"[工具异常: {e}]"

    def _restore_contract_state(self) -> None:
        """Phase 8b: restore contract state from previous session on startup."""
        snapshot = self.c.profile.load_blueprint_snapshot()
        if not snapshot:
            return
        # Schema guard: only restore fields that exist in current schema
        valid_keys = set(self.c.bp.fields.keys())
        restored = 0
        for key, val in snapshot.items():
            if key in valid_keys and val is not None:
                try:
                    self.c.bp.apply_proposal(key, val, ignore_cooldown=True)
                    restored += 1
                except Exception:
                    pass  # Skip invalid field values gracefully
        if restored > 0:
            print(f"  [系统] 已从上次会话恢复 {restored} 个合同字段", flush=True)

        # Restore trust baseline if available
        trust_snap = snapshot.get("_trust_baseline")
        if trust_snap is not None and 0.0 <= float(trust_snap) <= 1.0:
            self.trust = float(trust_snap)
            self.c.action_pipeline.trust = self.trust

        # Restore learner thresholds if available
        thresholds = snapshot.get("_thresholds")
        if isinstance(thresholds, dict):
            try:
                self.c.learner.restore_thresholds(thresholds)
            except Exception:
                pass

    def _run_track_c(self, user: str, system: str, xray: XRay, live=None) -> str:
        """Track C: full engine pipeline with retry."""
        from core.track_c import TrackCEngine
        engine = self._get_track_c_engine()
        return engine.run(user, system, self.round_count)

    def _get_track_c_engine(self):
        """Lazy-init Track C engine with real CloudLLM backend."""
        if not hasattr(self, '_track_c_engine'):
            from core.adapters.cloudllm_backend import CloudLLMBackend
            from core.adapters.generator_adapter import GenerationAdapter
            from engines.planning.llm import LLMPlanningEngine
            from engines.orchestration.llm import LLMOrchestrationEngine
            from engines.critic.llm import LLMCriticEngine
            from core.track_c import TrackCEngine

            backend = CloudLLMBackend(self.c.cloud_llm, model="deepseek-chat")
            adapter = GenerationAdapter(backend)

            from engines.planning.contract_aware import ContractAwarePlanningEngine
            from engines.orchestration.contract_aware import ContractAwareOrchestrationEngine
            from engines.critic.contract_aware import ContractAwareCriticEngine

            planning = ContractAwarePlanningEngine(
                LLMPlanningEngine(adapter, kernel=self.c), kernel=self.c,
            )
            orch = ContractAwareOrchestrationEngine(
                LLMOrchestrationEngine(adapter, kernel=self.c), kernel=self.c,
            )
            critic = ContractAwareCriticEngine(
                LLMCriticEngine(adapter, kernel=self.c), kernel=self.c,
            )

            self._track_c_engine = TrackCEngine(
                planning_engine=planning,
                orch_engine=orch,
                critic_engine=critic,
                adapter=adapter,
                bus=self.c.bus,
            )
        return self._track_c_engine

    def _track_b_agentic(self, user: str, system: str, trust: float,
                         bp, xray: XRay, live=None) -> str:
        """Track B: Planning → Orch → Critic. Live X-Ray updates."""
        import time, sys

        try:
            t0 = time.time()
            plan_steps = self._plan_task(user, system)
            self.c.bus.emit("🔀 Track B Planning", f"拆解为 {len(plan_steps)} 步 ({time.time()-t0:.2f}s)")
            self.c.bus.trace(TraceNode(
                node_id=f"planning_{self.round_count}", name="Planning",
                node_type="agent", status=TraceStatus.SUCCESS,
                metadata={"steps": len(plan_steps), "elapsed_ms": (time.time()-t0)*1000},
            ))
            self._update_live(xray, live)

            results = []
            total = len(plan_steps)
            for i, step in enumerate(plan_steps):
                t_step = time.time()
                if step.get("tool"):
                    check = self.c.action_pipeline.check(step["tool"])
                    if not check["allowed"]:
                        results.append(
                            f"[系统提示：由于契约限制({check['reason']})，无法执行 {step['tool']}。"
                            f"请在回复中委婉地向用户解释此限制。]"
                        )
                        self.c.bus.emit(f"🔀 Track B Step {i+1}", f"🚫 拦截: {step['tool']}")
                        continue
                    # Execute tool via ToolAdapter (MCP or local)
                    self.c.bus.emit_pending(f"🔀 Track B Step {i+1}", f"⏳ {step['tool']}...")
                    self._update_live(xray, live)
                    tool_result = self._execute_tool(step["tool"], {"query": step["prompt"]}, xray)
                    results.append(f"[工具结果: {step['tool']}]\n{tool_result}")
                    self.c.bus.emit(f"🔀 Track B Step {i+1}", f"{step['tool']} 完成 ({time.time()-t_step:.1f}s)")
                else:
                    self.c.bus.emit_pending(f"🔀 Track B Step {i+1}", "⏳ 执行中...")
                    self._update_live(xray, live)
                    step_prompt = f"{system}\n\n[当前任务]: {step['prompt']}\n[已有结果]: {results}"
                    step_resp = self.c.cloud_llm.generate(step_prompt)

                    # Auto-parse [TOOL:xxx] {...} from LLM response
                    import re as _re
                    tool_match = _re.search(r'\[TOOL:(\w+)\]\s*(\{[^}]+\})', step_resp)
                    if tool_match:
                        tool_name = tool_match.group(1)
                        try:
                            params = __import__('json').loads(tool_match.group(2))
                            tool_result = self._execute_tool(tool_name, params, xray)
                            step_resp += f"\n\n[工具结果: {tool_name}]\n{tool_result[:1500]}"
                            self.c.bus.emit(f"🔀 Track B Step {i+1}", f"{tool_name} 完成")
                        except Exception:
                            pass  # Parse failed — use LLM response as-is

                    results.append(step_resp)
                    self.c.bus.emit(f"🔀 Track B Step {i+1}", f"完成 ({time.time()-t_step:.1f}s)")
                self._update_live(xray, live)

            t_critic = time.time()
            critique = self._critique_results(user, results)
            self.c.bus.emit("🔀 Track B Critic", f"评估: {critique} ({time.time()-t_critic:.1f}s)")
            self._update_live(xray, live)

            final_prompt = (
                f"{system}\n\n用户问: {user}\n"
                f"分析结果: {results}\n"
                f"Critic建议: {critique}\n"
                f"请基于以上内容生成最终回复。"
            )
            self.c.bus.emit_pending("🔀 Track B 合成", "⏳ 合成最终回复...")
            self._update_live(xray, live)
            return self.c.cloud_llm.generate(final_prompt)

        except Exception as e:
            self.c.bus.emit("⚠️ Track B", f"引擎异常降级: {e}")
            self._update_live(xray, live)
            return self.c.cloud_llm.generate(f"{system}\n\nUser: {user}")

    def _build_tools_section(self) -> str:
        """Build an [可用工具] section listing all registered tools."""
        try:
            tools = _get_registered_tools()
        except Exception:
            return ""
        if not tools:
            return ""
        lines = ["[可用工具 — 你可以自主选择调用以下工具来完成任务]"]
        for t in tools:
            desc = t.get("description", "")[:80]
            params = ", ".join(t.get("required_params", []))
            lines.append(f"  - {t['name']}: {desc} (参数: {params})")
        lines.append("调用格式: 在回复中写 [TOOL:工具名] {\"参数\":\"值\"}")
        return "\n".join(lines)

    @staticmethod
    def _plan_task(user: str, system: str) -> list[dict]:
        """Decompose user request into ordered steps."""
        return [
            {"prompt": f"分析用户问题的核心要点: {user}", "tool": ""},
            {"prompt": f"基于分析结果，提供详细回答: {user}", "tool": "knowledge_search"},
            {"prompt": f"总结并给出最终建议", "tool": ""},
        ]

    @staticmethod
    def _critique_results(user: str, results: list[str]) -> str:
        """Evaluate results completeness. Returns '满意' or suggestion."""
        total_chars = sum(len(r) for r in results)
        if total_chars < 50:
            return "结果过短，建议补充细节"
        return "满意"

    def _update_live(self, xray: XRay, live=None) -> None:
        if live and xray._stages:
            xray.render_live(live)

    def _do_rag(self, query: str, xray: XRay) -> str:
        """Execute RAG pipeline: search → guard → return context or blocked message."""
        from core.adapters.knowledge_search import search as kb_search
        check = self.c.action_pipeline.check("knowledge_search")
        if not check["allowed"]:
            reason = check["reason"]
            print(f"  [RAG] 🔴 拦截: {reason}")
            self.c.bus.emit("知识网关", f"拦截: {reason}")
            return f"[RAG拦截: {reason}]"

        # Semantic mode for Chinese (no word boundaries in keyword mode)
        results = kb_search(query, max_results=5, mode="semantic")
        if not results:
            # Fallback to keyword
            results = kb_search(query, max_results=5, mode="keyword")
        if not results:
            print(f"  [RAG] 未找到匹配: {query}")
            return ""

        filtered = self.c.action_pipeline.guard_post_retrieval("knowledge_search", results)
        context_parts = []
        blocked_count = 0
        for r in filtered:
            blocked = "不可访问" in r.get("content", "")
            if blocked:
                blocked_count += 1
            else:
                self.c.bus.emit("RAG检索", f"命中 {r['file']}")
                context_parts.append(f"[来源: {r['file']}]\n{r['content']}")

        if blocked_count > 0:
            print(f"  [RAG] {blocked_count} 个拦截, {len(filtered)-blocked_count} 个命中")

        rag_context = "\n\n".join(context_parts)
        if not rag_context.strip():
            return "[RAG: 未找到可访问的匹配内容]"
        return rag_context

    def _apply_proposal(self, prop: dict, label: str = "") -> bool:
        accepted, reason = self.c.engine.evaluate(prop, self.c.bp, self.trust)
        if accepted:
            ok, msg = self.c.bp.apply_proposal(prop["target_blueprint_key"], prop["new_value"])
            if ok:
                self.c.engine.record_evolution(self.trust)
                self.c.profile.record_modification(prop["target_blueprint_key"], prop["new_value"])
                if label:
                    print(f"  [{label}] {prop['target_blueprint_key']} -> {prop['new_value']}")
                return True
        return False

    # ── Main loop ──

    def run(self) -> None:
        bp, trust = self.c.bp, self.trust
        uid = self.c.cfg.user_id
        session_log: list[str] = []
        rag_mode = False  # Toggle: /rag on | /rag off

        print(f"\n{'='*50}")
        print(f"PLAN5 Live — {uid}")
        print(f"  blueprint: {bp.snapshot}")
        print(f"  trust: {trust:.2f} | sessions: {self.c.profile.session_count}")
        print(f"  /quit 退出 | /new 新对话")
        print(f"{'='*50}")

        # Semantic trust (lazy load)
        USE_SEMANTIC = False
        sem = None
        try:
            from core.adapters.semantic_trust import SemanticTrustEngine
            sem = SemanticTrustEngine()
            USE_SEMANTIC = True
        except (ImportError, OSError):
            pass

        while True:
            bp.tick(half_life_rounds=20)
            try:
                user = input(f"\n[{uid}]> ")
            except (EOFError, KeyboardInterrupt):
                break
            cmd = user.strip().lower()
            if cmd in ("/quit", "/exit"):
                break
            if cmd == "/new":
                self.round_count = 0
                self.history.clear()
                self.contract_events.clear()
                self.c.bp.apply_proposal("tone_style", "WARM", ignore_cooldown=True)
                self.c.bp.apply_proposal("conversational_initiative", "BALANCED", ignore_cooldown=True)
                self.trust = 0.30  # 热数据重置
                self.c.profile.start_session()
                print(f"  [新对话] Session {self.c.profile.session_count}. 情绪状态已重置。")
                continue
            if cmd == "/mood":
                print(f"  当前: tone={bp.fields.get('tone_style','?')} "
                      f"trust={trust:.2f} initiative={bp.fields.get('conversational_initiative','?')}")
                continue
            if cmd == "/rag on":
                rag_mode = True
                print(f"  [RAG] 本地知识库模式已开启。")
                continue
            if cmd == "/rag off":
                rag_mode = False
                print(f"  [RAG] 本地知识库模式已关闭。")
                continue
            if cmd == "/mcp" or cmd.startswith("/mcp "):
                # /mcp <tool_name> <json_params>
                parts = user.strip().split(None, 2)
                if len(parts) < 3:
                    print("  用法: /mcp <工具名> <JSON参数>")
                    print("  例如: /mcp read_text_file {\"path\":\"CLAUDE.md\"}")
                    continue
                import json as _json
                try:
                    params = _json.loads(parts[2])
                except _json.JSONDecodeError as e:
                    print(f"  JSON 解析失败: {e}")
                    continue
                xray = XRay()
                result = self._execute_tool(parts[1], params, xray)
                # Truncate long results
                if len(result) > 800:
                    result = result[:800] + f"\n... (截断, 共 {len(result)} 字符)"
                print(f"  [MCP] {parts[1]} →")
                print(result)
                continue
            if cmd == "/tools":
                from core.contracts.registry import COMPONENT_REGISTRY
                tools = COMPONENT_REGISTRY.list_strategies("tool")
                if tools:
                    print(f"  [🔧 工具] 已注册 {len(tools)} 个:")
                    for t in tools:
                        print(f"    - {t}")
                else:
                    print("  [🔧 工具] 无已注册工具。用 --mcp <server> 启动 MCP 服务器。")
                continue
            if cmd == "/trace":
                nodes = self.c.bus.export_trace()
                if nodes:
                    import json as _json
                    print(_json.dumps(nodes, ensure_ascii=False, indent=2))
                else:
                    print("  [trace] 无 Trace 数据。尝试 Track B 任务。")
                continue
            if cmd == "/rag stats":
                from core.adapters.knowledge_search import cache_stats
                s = cache_stats()
                print(f"  [RAG] 缓存: {s['files_cached']} 文件, "
                      f"{s['queries_cached']} 查询, {s['size_mb']}MB")
                continue
            if cmd.startswith("/rag"):
                # Direct RAG query: /rag 微服务
                xray = XRay()
                query = user[5:].strip() or "test"
                self._do_rag(query, xray)
                continue
            if not user.strip():
                continue

            xray = XRay()
            self.c.bus.subscribe(xray)  # X-Ray = observer on the bus
            self.round_count += 1
            try:
                from rich.live import Live
                live = Live(auto_refresh=False, vertical_overflow="visible")
                live.start()
            except ImportError:
                live = None
            if self.round_count == 1:
                self.c.profile.start_session()
                print(f"  [新对话] Session {self.c.profile.session_count}.")

            # ── Evaluate (dual-track: Embedding + LLM fallback) ──
            trust_before = trust
            dim, score = None, 0.0
            if USE_SEMANTIC and sem:
                try:
                    sig = sem.detect(user)
                except Exception:
                    sig = {"dimension": None, "score": 0.0, "all_scores": {}}
                dim, score = sig["dimension"], sig["score"]
            # Track B: LLM fallback when embedding is uncertain or unavailable
            if dim is None or (0.3 < score < 0.6 and USE_SEMANTIC):
                try:
                    llm_judge = self.c.cloud_llm.generate(
                        f"判断用户这句话的情绪倾向,只输出一个词(fatigue/gratitude/frustration/neutral):\n"
                        f"用户: {user}\n情绪:"
                    ).strip().lower()
                    if "fatigue" in llm_judge: dim, score = "fatigue", 0.55
                    elif "frustrat" in llm_judge: dim, score = "frustration", 0.55
                    elif "gratitude" in llm_judge or "grateful" in llm_judge: dim, score = "gratitude", 0.55
                except Exception:
                    pass  # Both tracks failed — skip this round

            if dim == "fatigue":
                trust = max(0.0, trust - 0.01 * (1 + score))
            elif dim == "gratitude":
                trust = min(0.85, trust + 0.02 * (1 + score))
            elif dim == "frustration":
                trust = max(0.0, trust - 0.03 * (1 + score))
            if dim:
                self.c.bus.emit("语义感知", f"{dim}={score:.3f}")
                self._update_live(xray, live)

            # ── Pending proposals ──
            for prop in list(self.pending):
                if self._apply_proposal(prop, label="SYSTEM2"):
                    self.contract_events.append(f"[R{self.round_count}] {prop['target_blueprint_key']} -> {prop['new_value']}")
                self.pending.remove(prop)

            # ── Explicit commands ──
            explicit = self._detect_explicit_command(user)
            if explicit:
                cmd_prop = {
                    "target_blueprint_key": explicit[0], "new_value": explicit[1],
                    "source": "explicit_user_command",
                    "trigger_condition": "user_said_so",
                    "human_reason": f"User said: '{user[:40]}'",
                }
                if self._apply_proposal(cmd_prop, label="USER COMMAND"):
                    self.contract_events.append(f"[R{self.round_count}] {cmd_prop['target_blueprint_key']} -> {cmd_prop['new_value']}")
                    self.c.bus.emit("用户指令", f"{cmd_prop['target_blueprint_key']} → {cmd_prop['new_value']}")

            # ── Signal interpreter ──
            if USE_SEMANTIC and dim:
                from core.adapters.signal_interpreter import interpret as signal_interpret
                learned = self.c.learner.get_all_thresholds()
                for sp in signal_interpret(dim, score, trust, bp.snapshot, user, thresholds=learned):
                    if self._apply_proposal(sp, label="SIGNAL→CONTRACT"):
                        self.contract_events.append(f"[R{self.round_count}] {sp['target_blueprint_key']} -> {sp['new_value']}")
                        self.c.bus.emit("契约演化", f"{sp['target_blueprint_key']} → {sp['new_value']} ({sp.get('human_reason','')[:40]})")

            # ── Auto-RAG: inject knowledge context when mode is on ──
            rag_context = ""
            if rag_mode and not cmd.startswith("/"):
                rag_context = self._do_rag(user, xray)
                if rag_context:
                    rag_context = f"\n\n[本地知识库检索结果]\n{rag_context}\n[/知识库]"

            # ── Build prompt + generate ──
            system = self._build_prompt(uid, xray)
            # Inject available tools so LLM can autonomously choose
            tools_section = self._build_tools_section()
            system = f"{system}\n\n{tools_section}" if tools_section else system
            self._update_live(xray, live)  # Flush events from _build_prompt
            full_prompt = f"{system}{rag_context}\n\nUser: {user}"

            # ── V4.1 Phase 3: Track A/B/C Router ──
            route = self._route_task(user)
            # Conversation openers/closers → always Track A (no planning needed)
            t = user.strip()
            if len(t) <= 3 and any(w in t for w in ("拜拜","再见","bye","你好","晚安","谢谢","好的","嗯","哦","行","ok","hi")):
                route = "A"
            if route == "C":
                self.c.bus.emit("路由决策", f"Track C (embedding)")
                full_response = self._run_track_c(user, system, xray, live)
            elif route == "B":
                self.c.bus.emit("路由决策", "Track B")
                full_response = self._track_b_agentic(user, system, trust, bp, xray, live)
            else:
                self.c.bus.emit_pending("内容生成", "⏳ 生成中...")
                self._update_live(xray, live)
                backend = route_decide(bp.snapshot, user, trust)
                if backend == "local":
                    full_response = self.c.local_llm.generate(full_prompt, grammar=build_gbnf(bp.snapshot))
                    self.c.bus.emit("路由决策", "本地 + GBNF 物理约束")
                else:
                    full_response = self.c.cloud_llm.generate(full_prompt)
                self.c.bus.emit("内容生成", f"生成 {len(full_response)} 字符")
                self._update_live(xray, live)

            # ── Output pipeline ──
            orig_len = len(full_response)
            full_response, penalty = self.c.output_pipeline.process(full_response.strip())
            if penalty:
                trust = max(0.0, trust - penalty)
            self.c.bus.emit("输出管道", f"截断/清洗: {orig_len}→{len(full_response)} 字符 | tone={bp.fields.get('tone_style','?')}")
            self._update_live(xray, live)

            # ── FSM intercept ──
            self.c.action_pipeline.trust = trust
            for token in full_response:
                self.c.fsm.feed(token)
            if self.c.fsm.state == FSMState.BUFFERING:
                self.c.fsm.force_complete()
            if self.c.fsm.state == FSMState.VALIDATING:
                tool_name = self.c.fsm._last_buffer and self.c.fsm._extract_tool_name(self.c.fsm._last_buffer) or "unknown"
                check = self.c.action_pipeline.check(tool_name)
                if check["allowed"]:
                    self.c.fsm.accept()
                else:
                    self.c.fsm.reject(check["reason"])
                    full_response = f"[契约拦截 {tool_name}: {check['reason']}]"

            # Final Live update with all events, then stop
            if live:
                xray.render_live(live)
                live.stop()

            print(f"\n[agent] {full_response}")
            session_log.append(f"User: {user}\nAgent: {full_response}\n")

            # ── Feedback ──
            if self.prev_signal.get("dimension"):
                result = self.c.listener.on_user_input(user, self.prev_signal, self.prev_response_len)
                if result:
                    pass

            # ── Record patterns ──
            if dim == "fatigue" and score > 0.5:
                self.c.patterns.record(uid, behavior="fatigue_brevity", action="verbose_reduce")
            if any(w in user for w in ("字少点", "别啰嗦", "简洁")):
                self.c.patterns.record(uid, behavior="fatigue_explicit", action="brevity_command")

            self.prev_response_len = len(full_response)
            self.prev_signal = {"dimension": dim, "score": score} if dim else {"dimension": None, "score": 0.0}

            # ── Post-check + audit ──
            rolled, reason = self.c.engine.post_check(bp, trust)
            if rolled:
                pass
            if self.c.auditor.should_audit(self.round_count):
                self.c.auditor.audit_async(
                    self.history[-20:], bp.snapshot, datetime.now().strftime("%H:%M"),
                    callback=lambda p: self.pending.append(p) if p else None,
                    schema=BLUEPRINT_SCHEMA, rejection_log=bp.rejection_log,
                )

            # ── Amendment ──
            current_v = bp.fields.get("response_verbose_level", "HIGH")
            if current_v != BLUEPRINT_SCHEMA["response_verbose_level"]["default"]:
                amendment = self.c.profile.propose_amendment("response_verbose_level", current_v)
                if amendment and amendment["target_blueprint_key"] not in self._amendments_shown:
                    self._amendments_shown.add(amendment["target_blueprint_key"])

            self.c.profile.save()
            self.history.append(f"User: {user}")
            self.history.append(f"Agent: {full_response[:200]}")
            if len(self.history) > 40:
                self.history = self.history[-40:]

            # Track trust delta across rounds
            old_trust = self.trust
            self.trust = trust
            delta = trust - old_trust
            if abs(delta) > 0.001:
                self.c.profile.record_trust_delta(delta, self.c.profile.session_count)

            # Phase 7-8: self-repair + recovery — health check every 5 rounds or acute crisis
            failures_this_round = sum(self.c.action_pipeline._failure_counts.values())
            if self.round_count % 5 == 0 or failures_this_round >= 2:
                report = self.c.kernel_evaluate_health()

                # Track consecutive healthy rounds (Phase 8)
                if report["overall_status"] == "healthy" and failures_this_round == 0:
                    self.healthy_rounds += 1
                    if self.healthy_rounds == 3:
                        self.c.bus.emit("合同恢复", "提议恢复自主权限 → HIGH")
                else:
                    self.healthy_rounds = 0
                report["healthy_rounds"] = self.healthy_rounds

                if report["overall_status"] != "healthy":
                    actions = self.c.kernel_decide_repair(report)
                    if actions:
                        self.c.kernel_execute_repairs(actions)
                elif report["healthy_rounds"] >= 3:
                    # Phase 8: recovery — try to raise autonomy
                    actions = self.c.kernel_decide_repair(report)
                    if actions:
                        for a in actions:
                            a["healthy_rounds"] = self.healthy_rounds
                        self.c.kernel_execute_repairs(actions)

            print(f"  [trust={trust:.2f} | verbose={bp.fields.get('response_verbose_level', '?')} | round={self.round_count}]")

        print(f"\n{'='*50}")
        print(f"结束。{self.round_count} 轮。")
        # Save session log
        if session_log:
            log_file = f"session_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== Session: {uid} | {datetime.now().isoformat()} | {self.round_count} rounds ===\n\n")
                cleaned = "\n".join(session_log).encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
                f.write(cleaned)
            print(f"日志已保存: {log_file}")

        # Phase 7-8b: save full contract state for cross-session persistence
        try:
            snap = dict(self.c.bp.snapshot)
            snap["_trust_baseline"] = self.trust
            snap["_thresholds"] = self.c.learner.get_all_thresholds()
            self.c.profile.save_blueprint_snapshot(snap)
        except Exception:
            pass

        # Cleanup: close SQLite connections
        try:
            self.c.learner.close()
        except Exception:
            pass
        try:
            self.c.patterns.close()
        except Exception:
            pass
