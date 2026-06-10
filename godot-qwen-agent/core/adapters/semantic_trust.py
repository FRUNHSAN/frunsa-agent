"""V7.7 Unified Semantic Observer — sheaf-theoretic intent classification.

Replaces the Voronoi partition of the old _classify_command() with:
  - Local sections σ_i: U_i → F defined only on open sets U_i ⊂ E (S³⁸³)
  - ⊥ = E \\ ∪ U_i as the complement of all command domains (not an 8th class)
  - Product fiber F_emotion × F_command with conditional dependence
  - Angular (geodesic) distance on the hypersphere for numerical stability

Embedding Engine: cosine/angular similarity against anchor sentences for
emotional dimensions + command classes. Single MiniLM instance.

LLM Reasoning Engine: lightweight LLM call for clarity assessment.

Model: paraphrase-multilingual-MiniLM-L12-v2 (~120MB, CPU-only)
"""

from __future__ import annotations

import os as _os
_os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from dataclasses import dataclass
import numpy as np

try:
    from sentence_transformers import SentenceTransformer, util
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


# ── Anchor sentences ──────────────────────────────────────────────
# These define the "meaning" of each trust dimension. Write them in
# the user's language with the emotional nuance you want to detect.

ANCHOR_SENTENCES: dict[str, list[str]] = {
    "fatigue": [
        "我累了",
        "好烦啊今天",
        "没劲",
        "不想说话了",
        "心好累",
        "就这样吧",
        "没什么精力了",
        "不想动脑子",
    ],
    "gratitude": [
        "谢谢你",
        "帮大忙了",
        "太感谢了",
        "有你真好",
        "很棒",
        "太好了",
        "就是这个意思",
    ],
    "frustration": [
        "听不懂你在说什么",
        "算了不问了",
        "好失望",
        "你又没听懂",
        "我说了好几遍了",
        "别说了",
    ],
    "curiosity": [
        "然后呢",
        "再讲讲",
        "这个有意思",
        "展开说说",
        "为什么",
        "我想了解更多",
        "继续",
    ],
}

# ── V7.7: Command anchors — blueprint field → target value ──
# Each label encodes a (blueprint_key, target_value) pair.
# ⊥ (null region) is NOT a class here — it is E \\ ∪ U_i, the complement of all domains.
COMMAND_ANCHORS: dict[str, list[str]] = {
    "response_verbose_level:MINIMAL": [
        "字少点", "别啰嗦", "简单点说", "话少点", "精简", "简洁", "短一点",
    ],
    "response_verbose_level:HIGH": [
        "详细点", "展开讲讲", "多说点", "再讲讲", "展开来说",
    ],
    "response_verbose_level:MEDIUM": [
        "字多点", "多一点", "多一点点", "多讲几句",
    ],
    "conversational_initiative:PROACTIVE": [
        "你问", "问问题", "反问", "问我", "你问我", "你倒是问", "继续问",
    ],
    "conversational_initiative:RESPONSIVE_ONLY": [
        "别问了", "不要问", "别反问", "别老问我",
    ],
    "tone_style:WARM": [
        "带点感情", "自然点", "像朋友", "来点人味",
    ],
}

# ── V7.7: Noise anchors — determine the ⊥ "ceiling" ──
# In 384-dim space, random text can have angular similarity baselines up to ~0.85.
# These noise anchors establish the dynamic minimum radius to prevent ⊥ from vanishing.
NOISE_ANCHORS: list[str] = [
    "你好", "嗯嗯", "今天天气不错", "随便看看", "12345",
    "吃了吗", "好的收到", "知道了", "哦哦", "哈哈",
]

# ── V7.7: Cross-coefficients — Radon-Nikodym derivative dP_joint / dP_indep ──
# Equivalent to Bayesian likelihood ratio: Coeff(c, em) = P(c | em) / P(c)
# Applied as multiplicative factor on command score, then softmax-normalized.
CROSS_COEFFICIENTS: dict[tuple, float] = {
    ("curiosity", "HIGH"): 1.2,
    ("curiosity", "MINIMAL"): 0.6,
    ("frustration", "HIGH"): 0.5,
    ("frustration", "MINIMAL"): 1.2,
    ("frustration", "RESPONSIVE_ONLY"): 1.3,
    ("fatigue", "PROACTIVE"): 0.5,
    ("gratitude", "WARM"): 1.2,
}


# ── V7.7: Angular distance utilities ──
# MiniLM output is L2-normalized → embedding manifold is the hypersphere S³⁸³.
# Angular (geodesic) distance is the correct Riemannian metric.
# cos_sim in [0.99, 1.0] has float resolution ~1e-7; arccos gives ~33× improvement.

def angular_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Geodesic distance on S³⁸³ in [0, π]. Numerically stable near cos≈1."""
    cos = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    cos = max(-1.0, min(1.0, cos))
    return float(np.arccos(cos))


def angular_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Angular similarity in [0, 1]: 1 - θ/π."""
    return 1.0 - angular_distance(a, b) / np.pi


@dataclass
class ObservationResult:
    """Unified sheaf-theoretic observation — input to contract evolution.

    Fields:
        emotion: emotion detection result (backward-compat with detect())
        command: best command or None, with raw_joint_score and normalized_prob
        command_candidates: all commands that passed the domain gate
        ambiguity: True if gap-type ⊥ (boundary between domains — germ extension possible)
        null_region: True if exterior-type ⊥ (far from all domains — section undefined)
        confidence: [0,1] margin-based from normalized joint distribution
        gap_region: True if gap-type ⊥ specifically
    """
    emotion: dict
    command: dict | None
    command_candidates: list
    ambiguity: bool = False
    null_region: bool = False
    confidence: float = 0.0
    gap_region: bool = False


class SemanticTrustEngine:
    """V7.7 Unified Semantic Observer — sheaf-theoretic intent classification.

    Combines emotion detection (fatigue, frustration, gratitude, curiosity),
    command classification (6 blueprint field targets), and LLM clarity assessment
    into a single observer with a shared MiniLM instance.

    Usage:
        engine = SemanticTrustEngine(llm_client=cloud_llm)

        # Unified observation (emotion + command jointly)
        obs = engine.observe("展开讲讲")
        # ObservationResult(emotion={...}, command={...}, confidence=0.85, ...)

        # Backward-compatible: emotion-only detection
        signal = engine.detect("今天真的好烦啊")
        # {"dimension": "fatigue", "score": 0.72, ...}

        # Backward-compatible: command-only classification
        cmd = engine.classify_command("字少点")
        # {"key": "response_verbose_level", "value": "MINIMAL", "score": 0.82, ...}
    """

    # ── Sheaf parameters (injectivity radius estimation) ──
    K_SIGMA: float = 1.0          # std-dev coefficient (k=1 covers ~68% of anchors)
    MAX_MIN_RADIUS: float = 0.90  # cap for dynamic minimum radius

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        thresholds: dict[str, float] | None = None,
        llm_client: object = None,
    ) -> None:
        if not HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers 未安装。请运行: pip install sentence-transformers"
            )
        self._model = SentenceTransformer(model_name)

        # ── Emotion thresholds ──
        self._thresholds = thresholds or {
            "fatigue": 0.40,
            "gratitude": 0.45,
            "frustration": 0.45,
            "curiosity": 0.40,
        }
        self._llm = llm_client

        # ── Emotion centers ──
        self._centers: dict[str, np.ndarray] = {}
        for dim, sentences in ANCHOR_SENTENCES.items():
            embs = self._model.encode(sentences, convert_to_numpy=True)
            self._centers[dim] = np.mean(embs, axis=0)

        # ── V7.7: Command centers + sheaf radii ──
        self._command_centers: dict[str, np.ndarray] = {}
        self._command_radii: dict[str, float] = {}
        self._dynamic_min_radius: float = 0.85  # fallback; computed below

        # Compute noise ceiling first (need command centers for comparison)
        noise_embs = self._model.encode(NOISE_ANCHORS, convert_to_numpy=True)
        # Pre-compute command centers
        raw_command_centers: dict[str, np.ndarray] = {}
        for label, sentences in COMMAND_ANCHORS.items():
            embs = self._model.encode(sentences, convert_to_numpy=True)
            raw_command_centers[label] = np.mean(embs, axis=0)

        # Dynamic minimum radius from noise ceiling
        noise_max_sims = [
            max(angular_similarity(n, c) for c in raw_command_centers.values())
            for n in noise_embs
        ]
        noise_ceiling = float(np.max(noise_max_sims))
        self._dynamic_min_radius = min(noise_ceiling + 0.05, self.MAX_MIN_RADIUS)

        # Compute command centers and radii
        for label, sentences in COMMAND_ANCHORS.items():
            embs = self._model.encode(sentences, convert_to_numpy=True)
            center = np.mean(embs, axis=0)
            self._command_centers[label] = center

            if len(embs) > 1:
                ang_sims = np.array([angular_similarity(e, center) for e in embs])
                mu = float(np.mean(ang_sims))
                sigma = float(np.std(ang_sims))
                # radius = mean - k·sigma (tighter anchors → bigger radius)
                self._command_radii[label] = max(mu - self.K_SIGMA * sigma, self._dynamic_min_radius)
            else:
                self._command_radii[label] = self._dynamic_min_radius

    # ═══════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════

    @property
    def model(self):
        """Shared MiniLM instance — for Wasserstein calibration and drift computation."""
        return self._model

    def encode(self, texts: list[str], convert_to_numpy: bool = True) -> np.ndarray:
        """Encode texts using the shared MiniLM model."""
        return self._model.encode(texts, convert_to_numpy=convert_to_numpy)

    def detect(self, text: str) -> dict:
        """Detect the closest trust dimension for a given text.

        Returns: {"dimension": str|None, "score": float, "all_scores": dict}
        """
        user_emb = self._model.encode([text], convert_to_numpy=True)
        all_scores: dict[str, float] = {}
        best_dim, best_score = None, 0.0

        for dim, center in self._centers.items():
            score = float(util.cos_sim(user_emb, center).item())
            all_scores[dim] = round(score, 4)
            if score > best_score:
                best_dim, best_score = dim, score

        threshold = self._thresholds.get(best_dim or "", 0.45)
        if best_score < threshold:
            best_dim = None

        return {
            "dimension": best_dim,
            "score": round(best_score, 4),
            "all_scores": all_scores,
        }

    def classify_command(self, text: str) -> dict | None:
        """Classify text as a blueprint command. Returns None if in ⊥ region.

        Returns: {"key": str, "value": str, "score": float, ...} or None
        """
        t = text.strip()
        if len(t) < 2:
            return None
        try:
            user_emb = self._model.encode([t], convert_to_numpy=True)
        except Exception:
            return None

        # Compute angular similarity to all command centers
        all_sims: dict[str, float] = {}
        in_domain: list[dict] = []
        for label, center in self._command_centers.items():
            sim = angular_similarity(user_emb[0], center)
            all_sims[label] = sim
            if sim > self._command_radii[label]:
                key, val = label.split(":", 1)
                in_domain.append({"key": key, "value": val, "score": round(sim, 4)})

        if not in_domain:
            return None

        # Domain membership → best candidate is the command
        best = max(in_domain, key=lambda c: c["score"])
        return best

    def observe(self, text: str) -> ObservationResult:
        """Unified sheaf-theoretic observation: emotion + command jointly.

        This is the primary V7.7 entry point for the REPL main loop.
        It replaces two separate calls (detect + classify_command) with a
        single observation that carries the conditional structure of the
        product fiber F_emotion × F_command.

        Returns:
            ObservationResult with emotion, command, candidates, null/gap
            classification, and margin-based confidence.
        """
        # ── Emotion detection (existing path, unchanged) ──
        emotion_sig = self.detect(text)

        # ── Command detection (sheaf-theoretic) ──
        t = text.strip()
        cmd_candidates: list[dict] = []
        all_sims: dict[str, float] = {}
        if len(t) >= 2:
            try:
                user_emb = self._model.encode([t], convert_to_numpy=True)
                for label, center in self._command_centers.items():
                    sim = angular_similarity(user_emb[0], center)
                    all_sims[label] = sim
                    if sim > self._command_radii[label]:
                        key, val = label.split(":", 1)
                        cmd_candidates.append({"key": key, "value": val, "score": round(sim, 4)})
            except Exception:
                pass

        # ── ⊥ classification: gap-type vs exterior-type ──
        ambiguity, null_region, null_conf = self._classify_null_region(all_sims)

        # ── Joint distribution: emotion × command → normalized + margin ──
        emotion_dim = emotion_sig["dimension"]
        emotion_score = emotion_sig["score"]
        best_cmd, margin = self._compute_joint_distribution(
            cmd_candidates, emotion_dim, emotion_score,
        )

        # Build result
        if null_region and ambiguity:
            # Gap-type ⊥: boundary region, low confidence
            return ObservationResult(
                emotion=emotion_sig,
                command=best_cmd,
                command_candidates=cmd_candidates,
                ambiguity=True,
                null_region=False,
                confidence=margin if margin > 0 else null_conf,
                gap_region=True,
            )
        elif null_region:
            # Exterior-type ⊥: far from all domains
            return ObservationResult(
                emotion=emotion_sig,
                command=None,
                command_candidates=cmd_candidates,
                ambiguity=False,
                null_region=True,
                confidence=0.0,
                gap_region=False,
            )
        elif ambiguity:
            # Intersection region (U_i ∩ U_j): multiple sections defined
            return ObservationResult(
                emotion=emotion_sig,
                command=best_cmd,
                command_candidates=cmd_candidates,
                ambiguity=True,
                null_region=False,
                confidence=margin,
                gap_region=False,
            )
        else:
            # Clean single-domain command
            return ObservationResult(
                emotion=emotion_sig,
                command=best_cmd,
                command_candidates=cmd_candidates,
                ambiguity=False,
                null_region=False,
                confidence=margin,
                gap_region=False,
            )

    # ═══════════════════════════════════════════════════════════════════
    # Internal: sheaf structure
    # ═══════════════════════════════════════════════════════════════════

    def _classify_null_region(
        self, all_sims: dict[str, float],
    ) -> tuple[bool, bool, float]:
        """Decompose ⊥ into gap-type (boundary) vs exterior-type (exterior).

        Gap-type ⊥: e is near the boundary of one or more command domains.
            Sections may have germ extensions here — mark as ambiguity.
        Exterior-type ⊥: e is far from ALL command domains.
            Sections are completely undefined — mark as null_region.

        Returns: (ambiguity: bool, null_region: bool, confidence: float)
        """
        if not all_sims:
            return (False, True, 0.0)

        max_label = max(all_sims, key=all_sims.get)
        max_sim = all_sims[max_label]
        sorted_sims = sorted(all_sims.values(), reverse=True)
        second_sim = sorted_sims[1] if len(sorted_sims) > 1 else 0.0

        # ── Absolute height gate: low-similarity → force Exterior ──
        exterior_abs_threshold = self._dynamic_min_radius + 0.02
        if max_sim < exterior_abs_threshold:
            return (False, True, 0.0)

        # ── Relative position: gap vs exterior ──
        best_gap = max_sim - self._command_radii.get(max_label, self._dynamic_min_radius)
        null_gap_threshold = 0.03   # angular sim within 0.03 of boundary
        gap_margin = 0.02           # best-second difference < 0.02

        if best_gap > -null_gap_threshold and (max_sim - second_sim) < gap_margin:
            # Gap-type ⊥: near boundary, multiple domains similarly close
            return (True, False, max_sim * 0.5)
        elif best_gap <= -null_gap_threshold:
            # Exterior-type ⊥: far from all domains
            return (False, True, 0.0)
        else:
            # Near single domain but not inside → null with trace confidence
            return (False, True, max_sim * 0.3)

    def _compute_joint_distribution(
        self,
        cmd_candidates: list[dict],
        emotion_dim: str | None,
        emotion_score: float,
    ) -> tuple[dict | None, float]:
        """Normalized joint distribution over product fiber F_emotion × F_command.

        Cross-coefficients act as Radon-Nikodym derivative dP_joint/dP_indep,
        equivalent to Bayesian likelihood ratio P(c|em)/P(c).

        Returns two parallel channels on best_cmd:
          - raw_joint_score: unnormalized activation (for threshold gating, tests)
          - normalized_prob: softmax-normalized probability (for margin confidence)
        """
        if not cmd_candidates:
            return None, 0.0

        raw_joints: dict[str, float] = {}
        for c in cmd_candidates:
            coeff = CROSS_COEFFICIENTS.get((emotion_dim, c["value"]), 1.0)
            raw_joints[c["key"]] = c["score"] * coeff

        # Softmax normalization
        total = sum(raw_joints.values()) + 1e-12
        normalized = {k: v / total for k, v in raw_joints.items()}

        # Margin-based confidence from normalized distribution
        sorted_scores = sorted(normalized.values(), reverse=True)
        best_key = max(normalized, key=normalized.get)
        margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]

        best_cmd = next(c for c in cmd_candidates if c["key"] == best_key)
        best_cmd["raw_joint_score"] = raw_joints[best_key]
        best_cmd["normalized_prob"] = normalized[best_key]
        return best_cmd, margin

    def assess_clarity(self, user_input: str) -> float:
        """[V5.3] Reasoning Path: lightweight LLM → intent clarity 0.0~1.0.

        Embedding-based detect() handles pattern matching (fatigue, frustration...).
        This method handles logical reasoning — only an LLM can judge that
        "C language + IE6 + WebAssembly" is self-contradictory.

        Returns:
            0.0 — self-contradictory, missing critical detail, physically impossible
            1.0 — extremely specific, technically feasible, unambiguous
            0.5 — fallback when no LLM available or parse failure (neutral)
        """
        if self._llm is None:
            return 0.5

        import re
        prompt = (
            "评估以下用户需求的意图清晰度 (0.0 到 1.0)。\n"
            "- 0.0: 需求自相矛盾、缺乏必要技术细节、或包含物理/逻辑上不可能的要求。\n"
            "- 1.0: 需求极其明确、具体、技术可行且无歧义。\n"
            "只输出一个浮点数，不要任何解释。\n\n"
            f'用户需求: "{user_input}"\n'
            "清晰度分数:"
        )
        try:
            response = self._llm.generate(prompt)
            match = re.search(r'\b(0?\.\d+|1\.0*|0|1)\b', response)
            if match:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
        except Exception:
            pass
        return 0.5

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    @property
    def dimensions(self) -> list[str]:
        return list(self._centers.keys())
