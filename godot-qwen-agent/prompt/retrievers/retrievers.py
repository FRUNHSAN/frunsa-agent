# prompt/retrievers/retrievers.py
import os
import json
from pathlib import Path
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

def find_local_embedder(model_name: str, cache_registry_path: str):
    """
    在 cache_registry.json 列出的每个路径中查找模型：
      - 先检查路径本身是否有 mod_id.txt
      - 再检查其子目录
    """
    with open(cache_registry_path, "r", encoding="utf-8") as f:
        cache_dirs = json.load(f)

    for base_dir in cache_dirs:
        base_path = Path(base_dir)
        if not base_path.exists():
            continue

        # 🔹 第一步：检查 base_dir 本身（你的场景！）
        mod_id_file = base_path / "model_id.txt"
        if mod_id_file.exists():
            with open(mod_id_file, "r", encoding="utf-8") as f2:
                name_in_file = f2.read().strip()
            if name_in_file == model_name:
                print(f"✅ Found local embedder: {model_name} at {base_path}")
                return str(base_path)

        # 🔹 第二步：再检查子目录（兼容其他结构）
        if base_path.is_dir():
            for candidate in base_path.iterdir():
                if candidate.is_dir():
                    mod_id_file = candidate / "model_id.txt"
                    if mod_id_file.exists():
                        with open(mod_id_file, "r", encoding="utf-8") as f2:
                            name_in_file = f2.read().strip()
                        if name_in_file == model_name:
                            print(f"✅ Found local embedder: {model_name} at {candidate}")
                            return str(candidate)

    raise FileNotFoundError(
        f"Embedding model '{model_name}' not found in any directory listed in {cache_registry_path}. "
        f"Please check mod_id.txt content and paths."
    )

class SimpleVectorRetriever:
    def __init__(self, texts, embeddings, embed_model_name, cache_registry_path):
        self.texts = texts
        self.embeddings = np.array(embeddings)

        # 🔍 从本地缓存找模型
        local_model_path = find_local_embedder(embed_model_name, cache_registry_path)
        
        # 🚫 确保不联网
        self.embedder = SentenceTransformer(local_model_path, local_files_only=True)

    def retrieve(self, query: str, top_k: int = 3):
        # 对 query 实时 embedding
        query_vec = self.embedder.encode([query], convert_to_numpy=True)
        sims = cosine_similarity(query_vec, self.embeddings)[0]
        top_indices = np.argsort(sims)[-top_k:][::-1]
        return [{"text": self.texts[i], "score": float(sims[i])} for i in top_indices]

# 工厂函数
def get_retriever(config, texts, embeddings, cache_registry_path=None):
    retriever_type = config["retriever"]["type"]
    params = config["retriever"].get("params", {})
    
    if retriever_type == "vector":
        embed_model_name = params["embed_model"]  # 现在 config 里一定有
        return SimpleVectorRetriever(
            texts=texts,
            embeddings=embeddings,
            embed_model_name=embed_model_name,
            cache_registry_path=cache_registry_path
        )
    else:
        raise ValueError(f"Unknown retriever type: {retriever_type}")