"""
RAG 子系统 — 检索增强生成引擎。

提供 API: search(query) -> list[Chunk]
不直接被 L3 Mainboard 编排。
连接点: mainboard/slots/tools/knowledge_search.py (薄 ToolSlot 包装器)

目录规划:
  chunker.py       — 分块逻辑
  vector_store.py  — 向量库接口
  retriever.py     — 检索逻辑
  reranker.py      — 重排序
  composer.py      — PipelineComposer (合约驱动的管道组合)
"""
