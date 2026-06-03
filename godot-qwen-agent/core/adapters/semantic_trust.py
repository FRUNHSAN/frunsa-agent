"""PLAN6 Semantic Trust Engine — embedding-based signal detection.

Replaces brittle keyword matching with cosine similarity against
hand-crafted anchor sentences. Each anchor set defines a trust dimension.

Model: all-MiniLM-L6-v2 (80MB, CPU-only, ~30ms per inference)
Supports Chinese naturally via multilingual pretraining.

Design:
  - Anchors computed ONCE at startup (not per round)
  - Two-tier: embedding recall -> LLM confirmation (6.2)
  - Threshold per dimension, tunable per user (6.4)
"""

from __future__ import annotations

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
    """Embedding-based trust signal detector.

    Usage:
        engine = SemanticTrustEngine()
        signal = engine.detect("今天真的好烦啊")
        # {"dimension": "fatigue", "score": 0.72}
    """

    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
        thresholds: dict[str, float] | None = None,
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
        # Pre-compute anchor centers ONCE
        self._centers: dict[str, np.ndarray] = {}
        for dim, sentences in ANCHOR_SENTENCES.items():
            embs = self._model.encode(sentences, convert_to_numpy=True)
            self._centers[dim] = np.mean(embs, axis=0)

    def detect(self, text: str) -> dict:
        """Detect the closest trust dimension for a given text.

        Returns: {"dimension": str|None, "score": float, "all_scores": dict}
        """
        user_emb = self._model.encode(text, convert_to_numpy=True)
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

    @property
    def thresholds(self) -> dict[str, float]:
        return dict(self._thresholds)

    @property
    def dimensions(self) -> list[str]:
        return list(self._centers.keys())
