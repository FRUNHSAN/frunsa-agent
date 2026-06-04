"""KnowledgeSearch — minimal real RAG: file read + keyword match + contract guard.

Architecture: the search technology is intentionally simple (keyword match).
The value is NOT the search — it's the contract gating around it.
Swap keyword match for embedding/vector search by replacing find().
"""

from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent / "knowledge_base"
SUPPORTED_SUFFIXES = {".txt", ".md", ".py", ".yaml", ".yml", ".json", ".log"}


def search(query: str, max_results: int = 3) -> list[dict]:
    """Search knowledge base for files matching query keywords.

    Returns [{file, content, snippet}].
    This is a placeholder — swap for embedding + vector search.
    """
    if not BASE_DIR.exists():
        return []

    keywords = set(query.lower().split())
    results: list[tuple[int, Path, str]] = []  # (score, path, content)

    for file_path in BASE_DIR.rglob("*"):
        if file_path.suffix not in SUPPORTED_SUFFIXES:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            continue

        content_lower = content.lower()
        score = sum(1 for kw in keywords if kw in content_lower)
        if score > 0:
            results.append((score, file_path, content))

    results.sort(key=lambda r: r[0], reverse=True)
    return [
        {
            "file": str(r[1].relative_to(BASE_DIR)),
            "content": r[2][:800],
            "query": query,
        }
        for r in results[:max_results]
    ]


# Extension point: replace with embedding-based search
# def search(query, max_results=3):
#     from sentence_transformers import SentenceTransformer
#     model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
#     q_emb = model.encode(query)
#     ... cosine similarity against pre-computed chunk embeddings ...
