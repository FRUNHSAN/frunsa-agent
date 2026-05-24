# components/retrievers/godot_vector.py

import os
import json
import numpy as np
from typing import List, Dict, Any
import faiss
from sentence_transformers import SentenceTransformer

class GodotVectorRetriever:
    """
    从本地 Godot 文档向量库中检索相关段落（完全离线）。
    
    配置参数 (params):
        kb_key: str                 # e.g., "godot_en"
        chunking_strategy: str      # e.g., "level1"
        embedding_model: str        # e.g., "BAAI/bge-m3"
        top_k: int                  # 默认 3
        mapping_file: str           # 默认 "benchmark/model_chunk_embed_mapping.json"
        cache_registry: str         # 默认 "benchmark/cache_registry.json"
    """

    def __init__(self, params: Dict[str, Any]):
        self.kb_key = params["kb_key"]
        self.chunking_strategy = params["chunking_strategy"]
        self.embedding_model = params["embedding_model"]
        self.top_k = params.get("top_k", 3)
        self.mapping_file = params.get("mapping_file", "benchmark/model_chunk_embed_mapping.json")
        self.cache_registry = params.get("cache_registry", "benchmark/cache_registry.json")
        
        self.params_hash = "a5770051"
        
        # 解析数据路径
        self.chunk_dir = None
        self.embed_dir = None
        self._resolve_paths()
        
        # 查找本地模型路径
        self.local_model_path = self._find_local_model()
        
        # 延迟加载
        self._chunks = None
        self._texts = None
        self._embeddings = None
        self._index = None
        self._encoder = None
        self._loaded = False

    def _resolve_paths(self):
        if not os.path.exists(self.mapping_file):
            raise FileNotFoundError(f"Mapping file not found: {self.mapping_file}")
        with open(self.mapping_file, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        
        chunk_key = f"{self.kb_key}__{self.chunking_strategy}__{self.params_hash}"
        if chunk_key not in mapping["chunks"]:
            available = list(mapping["chunks"].keys())
            raise ValueError(f"Chunk key '{chunk_key}' not found. Available: {available}")
        self.chunk_dir = mapping["chunks"][chunk_key]["chunk_dir"]

        target_embed_key = None
        for embed_key, meta in mapping["embeddings"].items():
            if meta["chunk_key"] == chunk_key and meta["model_name"] == self.embedding_model:
                target_embed_key = embed_key
                break
        if not target_embed_key:
            available_models = [meta["model_name"] for meta in mapping["embeddings"].values() if meta["chunk_key"] == chunk_key]
            raise ValueError(f"No embedding for {chunk_key} + {self.embedding_model}. Available: {available_models}")
        self.embed_dir = mapping["embeddings"][target_embed_key]["embed_dir"]

    def _find_local_model(self) -> str:
        """在 cache_registry 中查找匹配 embedding_model 的本地路径"""
        if not os.path.exists(self.cache_registry):
            raise FileNotFoundError(f"Cache registry not found: {self.cache_registry}")
        
        with open(self.cache_registry, 'r', encoding='utf-8') as f:
            cache_dirs = json.load(f)  # List[str]
        
        for cache_dir in cache_dirs:
            model_id_file = os.path.join(cache_dir, "model_id.txt")
            if os.path.exists(model_id_file):
                with open(model_id_file, 'r', encoding='utf-8') as f:
                    model_id = f.read().strip()
                if model_id == self.embedding_model:
                    return cache_dir
        
        raise ValueError(
            f"Local model cache for '{self.embedding_model}' not found in {self.cache_registry}. "
            f"Checked directories: {cache_dirs}"
        )

    def _load_data(self):
        if self._loaded:
            return

        # 加载 chunks.json
        chunk_file = os.path.join(self.chunk_dir, "chunks.json")
        if not os.path.exists(chunk_file):
            raise FileNotFoundError(f"chunks.json not found in {self.chunk_dir}")
        with open(chunk_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            if isinstance(data[0], str):
                self._texts = data
                self._chunks = [{"text": t} for t in data]
            elif isinstance(data[0], dict) and "text" in data[0]:
                self._chunks = data
                self._texts = [item["text"] for item in data]
            else:
                raise ValueError("chunks.json format not recognized")
        else:
            raise ValueError("chunks.json must be a list")

        # 加载 embeddings.npy
        embed_file = os.path.join(self.embed_dir, "embeddings.npy")
        if not os.path.exists(embed_file):
            raise FileNotFoundError(f"embeddings.npy not found in {self.embed_dir}")
        self._embeddings = np.load(embed_file)
        if self._embeddings.shape[0] != len(self._texts):
            raise ValueError(f"Chunk count ({len(self._texts)}) != embedding count ({self._embeddings.shape[0]})")

        # 构建 FAISS 索引
        dim = self._embeddings.shape[1]
        self._index = faiss.IndexFlatIP(dim)
        embeddings_f32 = self._embeddings.astype('float32')
        faiss.normalize_L2(embeddings_f32)
        self._index.add(embeddings_f32)

        self._loaded = True

    def _encode_query(self, query: str) -> np.ndarray:
        if self._encoder is None:
            # ✅ 关键修改：使用本地路径加载模型，避免联网
            print(f"[GodotVectorRetriever] Loading local model from: {self.local_model_path}")
            self._encoder = SentenceTransformer(self.local_model_path)
        
        vec = self._encoder.encode([query], convert_to_numpy=True).astype('float32')
        faiss.normalize_L2(vec)
        return vec

    def run(self, inputs: Dict[str, Any], global_resources: Dict[str, Any]) -> Dict[str, Any]:
        query = inputs["processed_query"]
        self._load_data()
        query_vec = self._encode_query(query)
        distances, indices = self._index.search(query_vec, self.top_k)
        
        results = []
        for idx in indices[0]:
            if idx < len(self._chunks):
                results.append(self._chunks[idx])
        
        return {
            "result": results,
            "trace_log": {
                "retriever": "godot_vector",
                "kb_key": self.kb_key,
                "embedding_model": self.embedding_model,
                "local_model_path": self.local_model_path,
                "top_k": self.top_k,
                "distances": distances[0].tolist(),
                "num_results": len(results),
                "chunk_dir": self.chunk_dir,
                "embed_dir": self.embed_dir
            }
        }

def create_godot_vector_retriever(params: Dict[str, Any]):
    return GodotVectorRetriever(params)