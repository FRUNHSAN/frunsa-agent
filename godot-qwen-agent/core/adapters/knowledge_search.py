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


def search(
    query: str, max_results: int = 3,
    chunker_name: str = "keyword",
    mode: str = "keyword",  # "keyword" | "semantic"
) -> list[dict]:
    """Pipeline-composable knowledge search.

    1. Load files → ContentBlock
    2. Chunk via COMPONENT_REGISTRY (default: KeywordChunker)
    3. Score: keyword match (mode="keyword") or embedding cosine (mode="semantic")
    4. Return top-N results → ActionPipeline.guard_post_retrieval()

    Swap chunker: search("query", chunker_name="semantic")
    Swap retriever: search("query", mode="semantic")
    """
    if not BASE_DIR.exists():
        return []

    # Get chunker from registry (import ensures registration)
    # Ensure chunker modules are loaded (idempotent after freeze)
    try:
        import core.adapters.keyword_chunker  # noqa
        import core.adapters.semantic_chunker  # noqa
    except RuntimeError:
        pass  # Already registered from Container pre-load

    chunker_cls = COMPONENT_REGISTRY.get("chunker", chunker_name)
    if chunker_cls is None:
        from core.adapters.keyword_chunker import KeywordChunker
        chunker_cls = KeywordChunker
    chunker = chunker_cls()  # Instantiate the chunker class

    # Phase 1: Load + Chunk all files
    all_chunks: list[dict] = []
    for file_path in BASE_DIR.rglob("*"):
        if file_path.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        block = ContentBlock(text=raw, source=str(file_path))
        for chunk in chunker.chunk(block):
            all_chunks.append({
                "file": str(file_path.relative_to(BASE_DIR)),
                "content": chunk.text[:800],
                "query": query,
            })

    # Phase 2: Score + Rank
    if mode == "semantic":
        try:
            from core.adapters.semantic_retriever import SemanticRetriever
            retriever = SemanticRetriever()
            return retriever.rank(query, all_chunks, top_k=max_results)
        except (ImportError, OSError):
            pass  # Fall through to keyword mode

    # Keyword mode (default + fallback)
    keywords = set(query.lower().split())
    scored = []
    for c in all_chunks:
        score = sum(1 for kw in keywords if kw in c["content"].lower())
        if score > 0:
            c["score"] = float(score)
            scored.append(c)
    scored.sort(key=lambda c: c.get("score", 0), reverse=True)
    return scored[:max_results]
