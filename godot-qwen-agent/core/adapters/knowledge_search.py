"""KnowledgeSearch — pipeline-composable RAG with contract gating.

Uses PLAN1-4 infrastructure: ChunkingStrategy → keyword match → contract guard.
Swap any component via COMPONENT_REGISTRY — chunker, retriever, scorer.
"""

from __future__ import annotations

from pathlib import Path

from core.contracts.chunking import ContentBlock
from core.contracts.registry import COMPONENT_REGISTRY


BASE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_base"
SUPPORTED_SUFFIXES = {".txt", ".md", ".py", ".yaml", ".yml", ".json", ".log"}


def search(query: str, max_results: int = 3, chunker_name: str = "keyword") -> list[dict]:
    """Pipeline-composable knowledge search.

    1. Load files → ContentBlock
    2. Chunk via COMPONENT_REGISTRY (default: KeywordChunker)
    3. Keyword match scoring
    4. Return top-N results → ActionPipeline.guard_post_retrieval()

    Swap chunker: search("query", chunker_name="semantic")
    Swap to embedding: replace keyword match with vector similarity.
    """
    if not BASE_DIR.exists():
        return []

    # Get chunker from registry
    chunker = COMPONENT_REGISTRY.get("chunker", chunker_name)
    if chunker is None:
        # Fallback: instantiate keyword chunker directly
        from core.adapters.keyword_chunker import KeywordChunker
        chunker = KeywordChunker()

    keywords = set(query.lower().split())
    results: list[tuple[int, str, str]] = []  # (score, file, chunk_text)

    for file_path in BASE_DIR.rglob("*"):
        if file_path.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        # Pipeline: ContentBlock → ChunkingStrategy.chunk()
        block = ContentBlock(text=raw, metadata={"source": str(file_path)})
        chunks = chunker.chunk(block)

        for chunk in chunks:
            text_lower = chunk.text.lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                rel_path = str(file_path.relative_to(BASE_DIR))
                results.append((score, rel_path, chunk.text[:800]))

    results.sort(key=lambda r: r[0], reverse=True)
    return [
        {"file": r[1], "content": r[2], "query": query}
        for r in results[:max_results]
    ]
