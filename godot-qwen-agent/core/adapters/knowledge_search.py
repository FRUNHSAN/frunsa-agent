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

# ── Cache: chunks + query results ──
_chunk_cache: dict[str, list[dict]] = {}  # file_path → [{content, file}]
_file_mtimes: dict[str, float] = {}       # file_path → last modified time
_query_cache: dict[str, list[dict]] = {}  # query → results
_CACHE_MAX = 50        # Max cached queries
_CHUNK_CACHE_MB = 128  # Max chunk cache size in MB


def _evict_if_needed() -> None:
    """LRU eviction: remove oldest files if cache exceeds size limit."""
    total_bytes = sum(
        sum(len(c.get("content", "")) for c in chunks)
        for chunks in _chunk_cache.values()
    )
    limit_bytes = _CHUNK_CACHE_MB * 1024 * 1024
    while total_bytes > limit_bytes and len(_chunk_cache) > 1:
        oldest = next(iter(_chunk_cache))
        for c in _chunk_cache[oldest]:
            total_bytes -= len(c.get("content", ""))
        del _chunk_cache[oldest]
        _file_mtimes.pop(oldest, None)


def clear_cache() -> None:
    """Clear all caches (for testing)."""
    _chunk_cache.clear()
    _file_mtimes.clear()
    _query_cache.clear()


def cache_stats() -> dict:
    """Return cache statistics: {files, queries, size_mb}."""
    total_bytes = sum(
        sum(len(c.get("content", "")) for c in chunks)
        for chunks in _chunk_cache.values()
    )
    return {
        "files_cached": len(_chunk_cache),
        "queries_cached": len(_query_cache),
        "size_mb": round(total_bytes / (1024 * 1024), 2),
    }


def warm_cache(chunker_name: str = "keyword") -> int:
    """Pre-compute chunks for all files. Call once at startup.
    Returns number of chunks cached. Blocks for ~1s on cold start.
    """
    import core.adapters.keyword_chunker  # noqa
    import core.adapters.semantic_chunker  # noqa
    chunker_cls = COMPONENT_REGISTRY.get("chunker", chunker_name)
    if chunker_cls is None:
        from core.adapters.keyword_chunker import KeywordChunker
        chunker_cls = KeywordChunker
    chunker = chunker_cls()

    count = 0
    for file_path in BASE_DIR.rglob("*"):
        if file_path.suffix not in SUPPORTED_SUFFIXES:
            continue
        rel = str(file_path.relative_to(BASE_DIR))
        if rel in _chunk_cache:
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        block = ContentBlock(text=raw, source=str(file_path))
        file_chunks = []
        for chunk in chunker.chunk(block):
            file_chunks.append({"file": rel, "content": chunk.text[:800], "query": ""})
            count += 1
        _chunk_cache[rel] = file_chunks
    return count


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

    # ── Cache: check query cache first ──
    cache_key = f"{query}|{mode}|{chunker_name}"
    if cache_key in _query_cache:
        return _query_cache[cache_key]

    # Phase 1: Load + Chunk (from file cache if available)
    all_chunks: list[dict] = []
    for file_path in BASE_DIR.rglob("*"):
        if file_path.suffix not in SUPPORTED_SUFFIXES:
            continue
        rel = str(file_path.relative_to(BASE_DIR))
        mtime = file_path.stat().st_mtime
        # Use cache only if file hasn't changed
        if rel in _chunk_cache and _file_mtimes.get(rel) == mtime:
            all_chunks.extend(_chunk_cache[rel])
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
        except Exception:
            continue
        block = ContentBlock(text=raw, source=str(file_path))
        file_chunks = []
        for chunk in chunker.chunk(block):
            cd = {"file": rel, "content": chunk.text[:800], "query": query}
            file_chunks.append(cd)
            all_chunks.append(cd)
        _chunk_cache[rel] = file_chunks
        _file_mtimes[rel] = mtime

        # LRU eviction if cache exceeds limit
        _evict_if_needed()

    # Phase 2: Score + Rank
    if mode == "semantic":
        try:
            from core.adapters.semantic_retriever import SemanticRetriever
            retriever = SemanticRetriever()
            return retriever.rank(query, all_chunks, top_k=max_results)
        except (ImportError, OSError):
            pass  # Fall through to keyword mode

    # Keyword mode (default + fallback)
    # Chinese: split into 2-gram and 3-gram tokens (no spaces between words)
    keywords = set(query.lower().split())
    if not keywords or len(keywords) == 1:  # Chinese — no spaces
        bigrams = [query[i:i+2] for i in range(len(query)-1)]
        trigrams = [query[i:i+3] for i in range(len(query)-2)]
        keywords = set(bigrams + trigrams)
    scored = []
    for c in all_chunks:
        score = sum(1 for kw in keywords if kw in c["content"].lower())
        if score > 0:
            c["score"] = float(score)
            scored.append(c)
    scored.sort(key=lambda c: c.get("score", 0), reverse=True)
    result = scored[:max_results]

    # Cache result
    if len(_query_cache) >= _CACHE_MAX:
        _query_cache.pop(next(iter(_query_cache)))
    _query_cache[cache_key] = result
    return result
