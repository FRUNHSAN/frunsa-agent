# rag_core.py
import os
from typing import List, Dict
from LLM import create_llm_client

class RAGClient:
    def __init__(self, vector_store, llm_config: Dict):
        self.vector_store = vector_store
        self.llm = create_llm_client(**llm_config)

    def retrieve(self, query: str) -> List[Dict]:
        """从向量库中检索相关文档"""
        return self.vector_store.search(query, k=3)

    def generate_answer(self, query: str, context: str) -> str:
        """根据上下文生成回答"""
        prompt = f"""
        你是 Godot 引擎专家。
        根据以下上下文回答问题，不要编造信息。

        上下文：
        {context}

        问题：
        {query}

        回答：
        """
        return self.llm.generate(prompt)

    def run(self, query: str) -> Dict[str, str]:
        """完整 RAG 流程：检索 + 生成"""
        context = "\n\n".join([doc["text"] for doc in self.retrieve(query)])
        answer = self.generate_answer(query, context)
        return {
            "query": query,
            "answer": answer,
            "context": context
        }