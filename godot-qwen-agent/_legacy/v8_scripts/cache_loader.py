# cache_loader.py
import os
import json
import numpy as np
from pathlib import Path

def normalize_model_name(model_name: str) -> str:
    """将模型名标准化为文件夹中使用的格式（替换 / 为 _）"""
    return model_name.replace("/", "_")

def load_chunks_and_embeddings(mapping_file, chunk_key, embed_model_name):
    """
    从映射文件加载指定源的 chunks 和 embeddings
    
    Args:
        mapping_file (str): 映射文件路径
        chunk_key (str): 分块缓存键（如 "godot_en__level1__a5770051"）
        embed_model_name (str): 嵌入模型名称
    
    Returns:
        tuple: (texts, embeddings) 文本列表和嵌入数组
    """
    mapping_file = Path(mapping_file)
    if not mapping_file.exists():
        raise FileNotFoundError(f"映射文件不存在: {mapping_file}")
    
    with open(mapping_file, 'r', encoding='utf-8') as f:
        mapping = json.load(f)
    
    # 查找 chunk 信息
    chunk_info = mapping.get("chunks", {}).get(chunk_key)
    if not chunk_info:
        raise ValueError(f"在映射文件中找不到分块: {chunk_key}")
    
    chunk_dir = Path(chunk_info["chunk_dir"])
    if not chunk_dir.exists():
        raise FileNotFoundError(f"Chunk 目录不存在: {chunk_dir}")
    
    # 加载 chunks
    chunks_file = chunk_dir / "chunks.json"
    if not chunks_file.exists():
        raise FileNotFoundError(f"Chunks 文件不存在: {chunks_file}")
    
    with open(chunks_file, 'r', encoding='utf-8') as f:
        texts = json.load(f)
    
    # 构建 embedding 键
    embed_model_safe = embed_model_name.replace("/", "_")
    embed_key = f"{chunk_key}__{embed_model_safe}"
    
    # 查找 embedding 信息
    embed_info = mapping.get("embeddings", {}).get(embed_key)
    
    if not embed_info or not Path(embed_info["embed_dir"]).exists():
        print(f"⚠️  警告: 未找到 {embed_model_name} 的嵌入缓存，将返回 None")
        return texts, None
    
    # 加载 embeddings
    embed_dir = Path(embed_info["embed_dir"])
    embed_file = embed_dir / "embeddings.npy"
    
    if not embed_file.exists():
        raise FileNotFoundError(f"Embedding 文件不存在: {embed_file}")
    
    embeddings = np.load(embed_file)
    
    return texts, embeddings

def list_available_configs(mapping_file: str):
    """
    打印所有可用的 (chunk_key, embedding_model) 组合，方便配置实验。
    
    Args:
        mapping_file (str): model_chunk_embed_mapping.json 路径
    """
    with open(mapping_file, 'r', encoding='utf-8') as f:
        mapping = json.load(f)
    
    print("🔍 Available RAG configurations:")
    print("=" * 80)
    
    # 按 chunk_key 分组展示
    for chunk_key, chunk_info in mapping["chunks"].items():
        print(f"\n📦 Chunk Key: {chunk_key}")
        print(f"   Source: {chunk_info['source_id']}")
        print(f"   Strategy: {chunk_info['chunking_strategy']}")
        print(f"   Params Hash: {chunk_info['chunking_params_hash']}")
        print(f"   Created: {chunk_info['created_at']}")
        
        # 找出所有基于这个 chunk_key 的 embeddings
        available_models = []
        for embed_key, embed_info in mapping["embeddings"].items():
            if embed_info["chunk_key"] == chunk_key:
                available_models.append(embed_info["model_name"])
        
        if available_models:
            print("   ✅ Available embedding models:")
            for model in sorted(available_models):
                print(f"      - {model}")
        else:
            print("   ⚠️  No embeddings found for this chunk key!")
    
    print("\n" + "=" * 80)
    print("💡 Tip: Use these chunk_key and model_name in your prompt/config.yaml")