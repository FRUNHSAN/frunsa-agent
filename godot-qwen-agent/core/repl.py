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

# ── Semantic command classifier (embedding-based, no hardcoded keywords) ──
_EMBED_MODEL: object | None = None


def _get_command_model():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
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
    m, st_util, centers = _get_command_model()
    emb = m.encode(text)
    best_label, best_score = None, 0.0
    for label, center in centers.items():
        s = float(st_util.cos_sim(emb, center))
        if s > best_score:
            best_label, best_score = label, s
    if best_label and best_score > 0.45:
        key, val = best_label.split(":", 1)
        return (key, val)
    return None


class Repl:
    """Interactive chat loop. Assembled by Container, run by main()."""

    def __init__(self, ctr: Container) -> None:
        self.c = ctr
        self.trust = 0.30
        self.round_count = 0
        self.pending: list[dict] = []
        self.history: list[str] = []
        self.contract_events: list[str] = []
        self._amendments_shown: set[str] = set()
        self.prev_response_len = 0
        self.prev_signal: dict = {"dimension": None, "score": 0.0}

    # ── Prompt construction (delegates to adapters) ──

    def _build_prompt(self, uid: str = "default") -> str:
        from core.adapters.output_grammar import build_grammar as build_gbnf

        def _build_contract_directive(bp_fields: dict) -> str:
            v = bp_fields.get("response_verbose_level", "HIGH")
            initiative = bp_fields.get("conversational_initiative", "BALANCED")
            tone = bp_fields.get("tone_style", "WARM")
            anchoring = bp_fields.get("contextual_anchoring", "HIGH")
            parts = ["[CURRENT MODE]"]
            v_map = {"HIGH": "详细解释, 最多 3 段", "MEDIUM": "均衡, ~2 段",
                     "LOW": "简洁, 2-3 句", "MINIMAL": "一句话"}
            parts.append(f"字数: {v_map.get(v, v)}")
            init_map = {"PROACTIVE": "主动引导对话", "BALANCED": "自然有来有回",
                        "RESPONSIVE_ONLY": "绝对不反问"}
            parts.append(f"主动性: {init_map.get(initiative, initiative)}")
            tone_map = {"ENTHUSIASTIC": "热情", "WARM": "温和", "CALM": "克制", "PRAGMATIC": "务实直白"}
            parts.append(f"语气: {tone_map.get(tone, tone)}")
            if anchoring == "LOW":
                parts.append("禁止提及时间/天气/环境")
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
            print(f"  [relation] {hint[:100]}")
            xray.log("模式记录", hint[:80])
        # ── V3.1: Narrative emergence (first round only) ──
        if self.round_count == 1:
            narrative = self.c.narrative.inject(uid)
            if narrative:
                system = f"{narrative}\n\n{system}"
                print(f"  [narrative] injected user profile ({len(narrative)} chars)")
                xray.log("叙事注入", f"注入用户画像 ({len(narrative)} chars)")
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
            if cmd.startswith("/rag"):
                # Demo: simulate knowledge search with contract gating
                query = user[5:].strip() or "test"
                check = self.c.action_pipeline.check("knowledge_search")
                if not check["allowed"]:
                    print(f"  [RAG] BLOCKED: {check['reason']}")
                    xray.log("知识网关", f"拦截: {check['reason']}")
                else:
                    # Real file search from knowledge_base/
                    from core.adapters.knowledge_search import search as kb_search
                    results = kb_search(query, max_results=5)
                    if not results:
                        print(f"  [RAG] 未找到匹配结果: {query}")
                        continue
                    filtered = self.c.action_pipeline.guard_post_retrieval("knowledge_search", results)
                    for r in filtered:
                        blocked = "不可访问" in r.get("content", "")
                        status = "🔴 拦截" if blocked else "🟢 放行"
                        print(f"  [RAG] {status} {r['file']}: {r['content'][:80]}...")
                        xray.log("知识网关" if blocked else "RAG检索", f"{status} {r['file']}")
                continue
            if not user.strip():
                continue

            xray = XRay()  # Fresh dashboard each round
            self.round_count += 1
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
                print(f"  [sense] {dim}={score:.3f}")
                xray.log("语义感知", f"{dim}={score:.3f}")

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
                    xray.log("用户指令", f"{cmd_prop['target_blueprint_key']} → {cmd_prop['new_value']}")

            # ── Signal interpreter ──
            if USE_SEMANTIC and dim:
                from core.adapters.signal_interpreter import interpret as signal_interpret
                learned = self.c.learner.get_all_thresholds()
                for sp in signal_interpret(dim, score, trust, bp.snapshot, user, thresholds=learned):
                    if self._apply_proposal(sp, label="SIGNAL→CONTRACT"):
                        self.contract_events.append(f"[R{self.round_count}] {sp['target_blueprint_key']} -> {sp['new_value']}")
                        xray.log("契约演化", f"{sp['target_blueprint_key']} → {sp['new_value']} ({sp.get('human_reason','')[:40]})")

            # ── Build prompt + generate ──
            system = self._build_prompt(uid)
            full_prompt = f"{system}\n\nUser: {user}"

            backend = route_decide(bp.snapshot, user, trust)
            if backend == "local":
                full_response = self.c.local_llm.generate(full_prompt, grammar=build_gbnf(bp.snapshot))
                xray.log("路由决策", "本地 + GBNF 物理约束")
            else:
                full_response = self.c.cloud_llm.generate(full_prompt)
            xray.log("内容生成", f"生成 {len(full_response)} 字符")

            # ── Output pipeline ──
            orig_len = len(full_response)
            full_response, penalty = self.c.output_pipeline.process(full_response.strip())
            if penalty:
                trust = max(0.0, trust - penalty)
            if len(full_response) < orig_len * 0.7:
                print(f"  [pipeline] {orig_len}→{len(full_response)} chars")
            xray.log("输出管道", f"截断/清洗: {orig_len}→{len(full_response)} 字符 | tone={bp.fields.get('tone_style','?')}")

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

            print(f"\n[agent] {full_response}")
            session_log.append(f"User: {user}\nAgent: {full_response}\n")

            # ── Feedback ──
            if self.prev_signal.get("dimension"):
                result = self.c.listener.on_user_input(user, self.prev_signal, self.prev_response_len)
                if result:
                    print(f"  [learn] {result['dimension']}: {result['old_threshold']:.3f}→{result['new_threshold']:.3f}")

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
                print(f"  [ROLLBACK] {reason}")
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
                    print(f"  [AMENDMENT] {amendment['human_reason'][:120]}")

            self.c.profile.save()
            self.history.append(f"User: {user}")
            self.history.append(f"Agent: {full_response[:200]}")
            if len(self.history) > 40:
                self.history = self.history[-40:]

            self.trust = trust
            print(f"  [trust={trust:.2f} | verbose={bp.fields.get('response_verbose_level', '?')} | round={self.round_count}]")
            xray.render()  # Show X-Ray dashboard after each round

        print(f"\n{'='*50}")
        print(f"结束。{self.round_count} 轮。")
        # Save session log
        if session_log:
            log_file = f"session_{uid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"=== Session: {uid} | {datetime.now().isoformat()} | {self.round_count} rounds ===\n\n")
                f.write("\n".join(session_log))
            print(f"日志已保存: {log_file}")
