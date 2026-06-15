# prompt/prompt_builders.py
def simple_builder(query: str, context_list: list) -> str:
    context = "\n\n".join([doc["text"] for doc in context_list])
    return f"""You are a Godot expert. Answer based ONLY on the context.

Context:
{context}

Question:
{query}

Answer:"""

def routed_builder(query: str, context_list: list, config) -> str:
    # 简化版路由：根据关键词判断
    if any(word in query.lower() for word in ["code", "script", "function"]):
        template = """Generate GDScript code for:
{query}

Reference context:
{context}"""
    else:
        template = """Explain based on the following context:

Context:
{context}

Question:
{query}

Answer:"""
    
    context = "\n\n".join([doc["text"] for doc in context_list])
    return template.format(query=query, context=context)

# 工厂函数
def get_prompt_builder(config):
    builder_type = config["prompt_builder"]["type"]
    if builder_type == "simple":
        return lambda q, c: simple_builder(q, c)
    elif builder_type == "routed":
        return lambda q, c: routed_builder(q, c, config)
    else:
        raise ValueError(f"Unknown prompt builder: {builder_type}")