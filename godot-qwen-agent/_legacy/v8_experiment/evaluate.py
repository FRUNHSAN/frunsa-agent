import os
import yaml
import pandas as pd
import json
from pathlib import Path
from datetime import datetime

# 加载 .env（必须在最前）
from dotenv import load_dotenv
load_dotenv()

# 添加项目根路径
import sys
sys.path.append(str(Path(__file__).parent.parent))

from cache_loader import load_chunks_and_embeddings
from prompt.query_processors.query_processors import get_query_processor
from prompt.retrievers.retrievers import get_retriever
from prompt.prompt_builders.prompt_builders import get_prompt_builder
from prompt.generators.generators import get_generator
from prompt.post_processors.post_processors import get_post_processor


def load_yaml_config(path: str):
    """安全加载 YAML 配置"""
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_env_in_config(value):
    """将字符串 ' $ {KEY}' 替换为 os.getenv('KEY') 的值"""
    if isinstance(value, str) and value.startswith(" $  {") and value.endswith("}"):
        key = value[2:-1]
        resolved = os.getenv(key)
        if resolved is None:
            raise ValueError(f"Environment variable '{key}' not found (required by config).")
        return resolved
    return value


def main():

    
    print("🔍 QWEN_API_KEY from .env:", os.getenv("QWEN_API_KEY")[:10] + "..." if os.getenv("QWEN_API_KEY") else "NOT SET")
    
    # ========================
    # 1. 加载实验配置（experiment/config.yaml）
    # ========================
    exp_config_path = Path(__file__).parent / "config.yaml"
    if not exp_config_path.exists():
        raise FileNotFoundError(f"Experiment config not found: {exp_config_path}")
    exp_config = load_yaml_config(exp_config_path)
    
    # ========================
    # 2. 加载 RAG 策略配置（prompt/config.yaml）
    # ========================
    current_script_dir = Path(__file__).parent
    prompt_config_relative_path = exp_config.get("prompt_config", "../prompt/config.yaml")
    prompt_config_path = (current_script_dir / prompt_config_relative_path).resolve()
    if not prompt_config_path.exists():
        raise FileNotFoundError(f"Prompt config not found: {prompt_config_path}")
    prompt_config = load_yaml_config(prompt_config_path)
    
    # ========================
    # 3. 加载查询集
    # ========================
    queries_file = (Path(__file__).parent / exp_config["queries"]["file"]).resolve()
    query_column = exp_config["queries"].get("column", "query")
    sample_size = exp_config["queries"].get("sample_size", None)
    
    df = pd.read_csv(queries_file)
    all_queries = df[query_column].dropna().tolist()
    
    if sample_size is not None and sample_size < len(all_queries):
        queries = all_queries[:sample_size]
        print(f"📝 Using {sample_size} out of {len(all_queries)} queries")
    else:
        queries = all_queries
        print(f"📝 Loaded {len(queries)} queries from {queries_file}")
    
    # ========================
    # 4. 加载缓存（chunks + embeddings）
    # ========================
    mapping_file = (Path(__file__).parent.parent / exp_config["data"]["mapping_file"]).resolve()
    texts, embeddings = load_chunks_and_embeddings(
        mapping_file=mapping_file,
        chunk_key=exp_config["data"]["chunk_key"],
        embed_model_name=exp_config["data"]["embed_model"]
    )
    
    # ========================
    # 5. 解析 LLM 配置并注入到 generator
    # ========================
    resolved_llm = {
        k: resolve_env_in_config(v)
        for k, v in exp_config["llm"].items()
    }

    if "generator" in prompt_config:
        prompt_config["generator"].setdefault("params", {})
        prompt_config["generator"]["params"].update(resolved_llm)  # ✅ 关键：用 resolved_llm
    else:
        prompt_config["generator"] = {"type": "single", "params": resolved_llm}
    
    # ========================
    # 6. 注入嵌入模型到 retriever
    # ========================
    if "retriever" in prompt_config:
        prompt_config["retriever"].setdefault("params", {})
        prompt_config["retriever"]["params"]["embed_model"] = exp_config["data"]["embed_model"]
    else:
        prompt_config["retriever"] = {
            "type": "vector", 
            "params": {"embed_model": exp_config["data"]["embed_model"]}
        }

    # ========================
    # 7. 初始化 RAG 组件
    # ========================
    cache_registry_path = (Path(__file__).parent.parent / "benchmark" / "cache_registry.json").resolve()
    if not cache_registry_path.exists():
        raise FileNotFoundError(f"cache_registry.json not found at {cache_registry_path}")
    
    query_processor = get_query_processor(prompt_config)
    retriever = get_retriever(prompt_config, texts, embeddings, cache_registry_path=str(cache_registry_path))
    prompt_builder = get_prompt_builder(prompt_config)
    generator = get_generator(prompt_config)
    post_processor = get_post_processor(prompt_config)
    
    # ========================
    # 8. 运行评估
    # ========================
    results = []
    print(f"\n🚀 Starting evaluation with:")
    print(f"   Chunk key: {exp_config['data']['chunk_key']}")
    print(f"   Embed model: {exp_config['data']['embed_model']}")
    print(f"   LLM: {exp_config['llm']['model']}")
    print("-" * 50)
    
    for i, query in enumerate(queries, 1):
        print(f"[{i}/{len(queries)}] Processing: {query[:60]}...")
        
        try:
            processed_query = query_processor(query)
            docs = retriever.retrieve(processed_query)
            prompt = prompt_builder(processed_query, docs)
            raw_response = generator(prompt)
            final_result = post_processor(raw_response, docs)
            
            results.append({
                "original_query": query,
                "processed_query": processed_query,
                "retrieved_count": len(docs),
                "retrieved_scores": [doc.get("score", 0.0) for doc in docs],
                "answer": final_result["answer"],
                "timestamp": datetime.now().isoformat()
            })
            
        except Exception as e:
            print(f"  ❌ Error on query '{query[:30]}...': {str(e)}")
            results.append({
                "original_query": query,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
    
    # ========================
    # 9. 保存结果
    # ========================
    output_dir = (Path(__file__).parent / exp_config["evaluation"].get("output_dir", "results")).resolve()
    raw_output_dir = output_dir / "raw_outputs"
    raw_output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_file = raw_output_dir / f"run_{timestamp}.json"

    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Evaluation complete!")
    print(f"   Total queries: {len(queries)}")
    print(f"   Raw results saved to: {result_file}")


if __name__ == "__main__":
    main()