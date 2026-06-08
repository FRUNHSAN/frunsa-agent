"""V5.3 Dual-Engine Observer — embedding-based pattern matching + LLM reasoning.

Embedding Engine (Fast Path): cosine similarity against anchor sentences for
emotional/state dimensions (fatigue, frustration, gratitude, curiosity).
~30ms per inference, zero API calls.

LLM Reasoning Engine (Reasoning Path): lightweight LLM call for logical
coherence assessment (clarity). Only an LLM can judge that "C language + IE6
+ WebAssembly" is self-contradictory. ~10 output tokens, ~1s.

Both engines share a unified observer interface — detect() for embedding signals,
assess_clarity() for reasoning signals. V5.2 "Observe, Don't Inject" preserved.

Model: paraphrase-multilingual-MiniLM-L12-v2 (~120MB, CPU-only)
Supports Chinese naturally via multilingual pretraining.

Design:
  - Anchors computed ONCE at startup (not per round)
  - Dual-engine: embedding (pattern match) + LLM (logical reasoning)
  - Threshold per dimension, tunable per user (6.4)
  - Graceful degradation: clarity falls back to 0.5 without LLM
"""

from __future__ import annotations

import os as _os
_os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

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


class SemanticTrustEngine:
    """Dual-Engine Observer: embedding pattern matching + LLM logical reasoning.

    Usage:
        engine = SemanticTrustEngine(llm_client=cloud_llm)

        # Fast Path: embedding-based emotional/state signals
        signal = engine.detect("今天真的好烦啊")
        # {"dimension": "fatigue", "score": 0.72, ...}

        # Reasoning Path: LLM-based logical clarity assessment
        clarity = engine.assess_clarity("C语言写IE6前端")
        # 0.15 (self-contradictory) ~ 0.95 (crystal clear)
    """

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        thresholds: dict[str, float] | None = None,
        llm_client: object = None,  # V5.3: optional LLM for assess_clarity
    ) -> None:
        if not HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers 未安装。请运行: pip install sentence-transformers"
            )
        self._model = SentenceTransformer(model_name)
        self._thresholds = thresholds or {
            "fatigue": 0.40,
            "gratitude": 0.45,
            "frustration": 0.45,
            "curiosity": 0.40,
        }
        self._llm = llm_client  # V5.3: Reasoning Path backend
        # Pre-compute anchor centers ONCE
        self._centers: dict[str, np.ndarray] = {}
        for dim, sentences in ANCHOR_SENTENCES.items():
            embs = self._model.encode(sentences, convert_to_numpy=True)  # list already
            self._centers[dim] = np.mean(embs, axis=0)

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

    def assess_clarity(self, user_input: str) -> float:
        """[V5.3] Reasoning Path: lightweight LLM → intent clarity 0.0~1.0.

        Embedding-based detect() handles pattern matching (fatigue, frustration...).
        This method handles logical reasoning — only an LLM can judge that
        "C language + IE6 + WebAssembly" is self-contradictory.

        Returns:
            0.0 — self-contradictory, missing critical detail, physically impossible
            1.0 — extremely specific, technically feasible, unambiguous
            0.5 — fallback when no LLM available or parse failure (neutral)

        Robust float extraction: LLM may output "0.15", "0.15。", or
        "The clarity is 0.15" — regex extracts the first valid float.
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
            # Robust float extraction — handles "0.15", "0.15。", "The clarity is 0.15", etc.
            match = re.search(r'\b(0?\.\d+|1\.0*|0|1)\b', response)
            if match:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
        except Exception:
            pass
        return 0.5  # Fallback: neutral — don't let parse failure affect control

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    @property
    def dimensions(self) -> list[str]:
        return list(self._centers.keys())
