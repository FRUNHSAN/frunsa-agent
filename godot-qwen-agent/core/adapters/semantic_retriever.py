"""SemanticRetriever — embedding-based chunk retrieval via cosine similarity.

Swap-in for keyword matching in knowledge_search.py.
Uses the same paraphrase-multilingual-MiniLM-L12-v2 as SemanticTrust.
"""

from __future__ import annotations

import numpy as np

try:
    from sentence_transformers import SentenceTransformer, util
    HAS_EMBEDDING = True
except ImportError:
    HAS_EMBEDDING = False


class SemanticRetriever:
    """Embed chunks + query → cosine similarity ranking."""

    def __init__(self) -> None:
        if not HAS_EMBEDDING:
            raise ImportError("sentence-transformers required")
        self._model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    def rank(self, query: str, chunks: list[dict], top_k: int = 3) -> list[dict]:
        """Rank chunks by semantic similarity to query.

        Args:
            query: User's search query
            chunks: [{content, file, ...}] from chunker
            top_k: Max results

        Returns:
            Same chunks with 'score' field added, sorted by similarity.
        """
        if not chunks:
            return []

        query_emb = self._model.encode(query, convert_to_numpy=True)
        chunk_texts = [c["content"] for c in chunks]
        chunk_embs = self._model.encode(chunk_texts, convert_to_numpy=True)

        scores = util.cos_sim(query_emb, chunk_embs)[0].numpy()

        for i, c in enumerate(chunks):
            c["score"] = float(scores[i])

        ranked = sorted(chunks, key=lambda c: c.get("score", 0), reverse=True)
        return ranked[:top_k]
