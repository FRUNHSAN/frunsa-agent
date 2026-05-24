# prompt/generators.py
import sys
sys.path.append("..")  # 访问 llm/

from LLM import create_llm_client

def single_generator(prompt: str, config):
    llm_config = config["generator"]["params"]
    llm = create_llm_client(**llm_config)
    return llm.generate(prompt)

def dual_generator(prompt: str, config):
    # 简化版：先用 turbo 快速生成，再用 max 优化
    llm_turbo = create_llm_client(provider="qwen", model="qwen-turbo")
    draft = llm_turbo.generate(prompt)
    
    refine_prompt = f"Improve this answer:\n{draft}\n\nOriginal question: {prompt}"
    llm_max = create_llm_client(provider="qwen", model="qwen-max")
    return llm_max.generate(refine_prompt)

# 工厂函数
def get_generator(config):
    gen_type = config["generator"]["type"]
    if gen_type == "single":
        return lambda p: single_generator(p, config)
    elif gen_type == "dual":
        return lambda p: dual_generator(p, config)
    else:
        raise ValueError(f"Unknown generator: {gen_type}")