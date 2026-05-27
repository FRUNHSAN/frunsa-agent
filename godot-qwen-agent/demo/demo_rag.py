"""Lightweight RAG pipeline — built-in knowledge base + retrieval + rerank.

Zero-intrusion: imports RetrieverStep, RerankerStep, and Chunk from parent project.
Provides a sync `retrieve()` function usable from Streamlit.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, List

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from core.contracts.chunking import Chunk
from core.contracts.retrieval import RetrievalResult
from core.steps.retriever import InMemoryVectorBackend, RetrieverStep
from core.steps.reranker import MockScoringBackend, RerankerStep

# ── Built-in knowledge base: AI Agent security & architecture ──────────

KNOWLEDGE_CHUNKS: List[Chunk] = [
    Chunk(
        "AI Agent 安全架构的核心是三层防护：编译时 AST 扫描、运行时安全隔离、事后全链路审计。"
        "编译时通过静态分析检测架构违规，运行时通过引擎隔离防止故障传播，事后通过 Trace 数据库实现操作溯源。",
        source_strategy="kb/agent_security",
        span=(0, 0),
    ),
    Chunk(
        "RAG（检索增强生成）系统通过向量检索从知识库中召回相关文档片段，注入 LLM 上下文窗口，"
        "提升回答的事实准确性。典型的 RAG 流程包含：文档切片 → Embedding 向量化 → FAISS 索引 → 相似度检索 → Rerank 重排序。",
        source_strategy="kb/rag_basics",
        span=(0, 0),
    ),
    Chunk(
        "Prompt 注入攻击是当前大模型应用面临的首要安全威胁。攻击者通过在用户输入中嵌入恶意指令，"
        "试图覆盖系统 Prompt 的行为约束。防御手段包括：输入净化、指令分隔符、权限分级、输出审计。",
        source_strategy="kb/prompt_injection",
        span=(0, 0),
    ),
    Chunk(
        "多引擎 Agent 架构将 AI Agent 拆分为规划引擎（Planning）、编排引擎（Orchestration）和评估引擎（Critic），"
        "各引擎职责单一、可独立替换。规划引擎负责任务拆解，编排引擎负责并行执行与资源调度，评估引擎负责质量打分与裁决。",
        source_strategy="kb/multi_engine",
        span=(0, 0),
    ),
    Chunk(
        "向量数据库（Vector Database）是 RAG 系统的核心组件，用于存储和检索高维 Embedding 向量。"
        "常见的向量数据库包括 FAISS（Meta）、Milvus（Zilliz）、Chroma、Qdrant 等。"
        "选择向量数据库时需考虑：索引算法（HNSW/IVF）、分布式扩展能力、过滤查询支持。",
        source_strategy="kb/vector_db",
        span=(0, 0),
    ),
    Chunk(
        "混合检索（Hybrid Search）结合了关键词检索（BM25）和语义检索（向量相似度）两种策略，"
        "通过加权融合或 Rerank 模型对两路召回结果进行重排序，兼顾精确匹配和语义理解，提升召回覆盖率。",
        source_strategy="kb/hybrid_search",
        span=(0, 0),
    ),
    Chunk(
        "DAG（有向无环图）编排是 Agent 并行执行的基础。将任务拆解为 DAG 节点后，"
        "无依赖关系的节点可以并行执行（fan-out），结果在汇聚节点合并（merge）。"
        "常见的合并策略包括 WAIT_ALL（等待全部完成）、WAIT_ANY（任一完成即返回）、PRIORITY（按优先级选择）。",
        source_strategy="kb/dag_orchestration",
        span=(0, 0),
    ),
    Chunk(
        "可观测性（Observability）是生产级 AI Agent 的必备能力。每次 LLM 调用都应记录："
        "输入 Prompt、输出 Token、模型名称、耗时、状态码。这些 Trace 数据用于："
        "性能优化、成本核算、异常排查、安全审计。",
        source_strategy="kb/observability",
        span=(0, 0),
    ),
    Chunk(
        "Embedding 模型将文本转换为固定维度的向量表示，语义相近的文本在向量空间中距离更近。"
        "主流 Embedding 模型包括：text-embedding-3（OpenAI）、bge-large（BAAI）、"
        "m3e（Moka AI）。选择 Embedding 模型需权衡：维度大小、语言支持、推理速度、 Embedding 质量（MTEB 基准）。",
        source_strategy="kb/embedding",
        span=(0, 0),
    ),
    Chunk(
        "LLM Agent 的幻觉（Hallucination）问题可通过 RAG + 事实核查链路缓解："
        "检索结果作为 grounding 锚点，Critic 引擎对输出逐条验证，"
        "对于无法验证的声明标注不确定性。关键原则：宁可承认不知道，不可编造事实。",
        source_strategy="kb/hallucination",
        span=(0, 0),
    ),
    Chunk(
        "安全左移（Shift Left Security）理念强调在开发生命周期早期嵌入安全实践，"
        "而非事后补救。具体手段包括：pre-commit 安全扫描、CI 管道集成 SAST 工具、"
        "基础设施即代码（IaC）安全审计、依赖项漏洞自动检测。",
        source_strategy="kb/shift_left",
        span=(0, 0),
    ),
    Chunk(
        "Rerank（重排序）模型在 RAG 系统中用于对初检结果进行精细排序。"
        "与向量检索的粗排不同，Rerank 模型将查询和文档拼接后送入 Cross-Encoder，"
        "逐对计算相关性分数。常见 Rerank 模型：bge-reranker、Cohere Rerank API。"
        "代价是延迟增加，通常只对 Top-K（如 top 20）候选做 Rerank。",
        source_strategy="kb/rerank",
        span=(0, 0),
    ),
]

# ── Singleton RAG pipeline (lazy init) ─────────────────────────────────

_retriever: RetrieverStep | None = None
_reranker: RerankerStep | None = None


def _ensure_pipeline() -> tuple[RetrieverStep, RerankerStep]:
    global _retriever, _reranker
    if _retriever is None:
        backend = InMemoryVectorBackend(KNOWLEDGE_CHUNKS)
        _retriever = RetrieverStep(top_k=5, backend=backend)
    if _reranker is None:
        _reranker = RerankerStep(backend=MockScoringBackend())
    return _retriever, _reranker


# ── Public API ─────────────────────────────────────────────────────────


def retrieve(query: str, top_k: int = 3) -> Dict[str, Any]:
    """Run retrieval + rerank for a query, returning structured results.

    Returns a dict with:
      - query: the original query string
      - retrieved: list of {text, score, rank, source} from vector search
      - reranked: list of {text, score, rank, source} after rerank
      - elapsed_ms: total time
    """
    import time

    t0 = time.perf_counter()
    retriever, reranker = _ensure_pipeline()

    # Phase 1: Vector retrieval
    async def _retrieve():
        result = await retriever.run(
            inputs={"query": query, "chunks": KNOWLEDGE_CHUNKS},
            resources=None,
        )
        return result

    ret_output = asyncio.run(_retrieve())
    ret_results: List[RetrievalResult] = ret_output.result if hasattr(ret_output, 'result') else []

    retrieved = [
        {
            "text": r.chunk.text[:200],
            "score": r.score,
            "rank": r.rank,
            "source": r.chunk.source_strategy,
        }
        for r in ret_results[:top_k]
    ]

    # Phase 2: Rerank
    chunks_to_rerank = [r.chunk for r in ret_results[:top_k]]

    async def _rerank():
        result = await reranker.run(
            inputs={"query": query, "chunks": chunks_to_rerank},
            resources=None,
        )
        return result

    rerank_output = asyncio.run(_rerank())
    rerank_results: List[RetrievalResult] = rerank_output.result if hasattr(rerank_output, 'result') else []

    reranked = [
        {
            "text": r.chunk.text[:200],
            "score": r.score,
            "rank": r.rank,
            "source": r.chunk.source_strategy,
        }
        for r in rerank_results
    ]

    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "query": query,
        "retrieved": retrieved,
        "reranked": reranked,
        "elapsed_ms": round(elapsed_ms, 2),
        "knowledge_base_size": len(KNOWLEDGE_CHUNKS),
    }
