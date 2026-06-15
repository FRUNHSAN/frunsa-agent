# prompt/query_processors.py
import re

def simple_processor(query: str) -> str:
    return query.strip()

def expanded_processor(query: str) -> str:
    # 简单同义词扩展（Godot 场景）
    expansions = {
        "jump": "jump physics gravity impulse",
        "move": "movement velocity position transform",
        "script": "GDScript code function"
    }
    result = query
    for word, expansion in expansions.items():
        if word in query.lower():
            result += f" {expansion}"
    return result.strip()

def rewritten_processor(query: str) -> str:
    # 简化版：加个前缀
    return f"How to {query} in Godot engine?"

# 工厂函数
def get_query_processor(config):
    processor_type = config["query_processor"]["type"]
    processors = {
        "simple": simple_processor,
        "expanded": expanded_processor,
        "rewritten": rewritten_processor
    }
    return processors[processor_type]