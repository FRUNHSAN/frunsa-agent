# test_local_llm.py

# 在 test_local_llm.py 开头加（调试用）
from LLM.template_registry import _TEMPLATE_CACHE
_TEMPLATE_CACHE.clear()

import os
import sys
import time
from typing import Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from experiment.api_client import LLMClient


def count_tokens(text: str) -> int:
    """
    简单估算 token 数（中文按字，英文按空格）
    注意：这只是近似值！真实 token 数需用 tokenizer
    """
    # 更准确的做法是用 transformers 的 tokenizer，但这里避免额外依赖
    if not text:
        return 0
    # 中文字符基本 1 字 = 1 token，英文单词 ≈ 1 token
    return len(text)


def timed_generate(llm, prompt: str) -> Tuple[str, float, int]:
    """执行推理并返回 (响应, 总耗时, 输出token数)"""
    start_time = time.time()
    response = llm.generate(prompt)
    total_time = time.time() - start_time
    output_tokens = count_tokens(response)
    return response, total_time, output_tokens


if __name__ == "__main__":
    MODEL_PATH = r"D:/tuili/qwen3-4b-instruct-2507-q4_k_m.gguf"

    print("🚀 测试本地 LLM 推理（带性能统计）...\n")
    # === 打印配置信息 ===
    print(f"📁 模型路径: {MODEL_PATH}")



    # 初始化（加载模型本身也会耗时）
    load_start = time.time()
    llm = LLMClient(
        local_model_path=MODEL_PATH,
        temperature=0.3,
        n_ctx=4096,  
        n_threads=12
    )
    load_time = time.time() - load_start
        # 兼容 llama_cpp 新旧版本
    if hasattr(llm, 'local_llm') and llm.local_llm is not None:
        n_ctx_val = llm.local_llm.n_ctx() if callable(llm.local_llm.n_ctx) else llm.local_llm.n_ctx
        n_threads_val = llm.local_llm.n_threads() if callable(llm.local_llm.n_threads) else llm.local_llm.n_threads
        print(f"🧵 线程数: {n_threads_val} | 上下文长度: {n_ctx_val}\n")
    else:
        print("（API 模式）\n")

    # === 测试 1：简单问候 ===
    test_prompt = "你好，请用一句话介绍你自己。"
    print(f"👤 用户: {test_prompt}")
    
    response, total_time, out_tokens = timed_generate(llm, test_prompt)
    
    print(f"🤖 模型: {response}\n")
    if out_tokens > 0 and total_time > 0:
        speed = out_tokens / total_time
        print(f"📊 [测试1] 耗时: {total_time:.2f}s | 输出: ~{out_tokens} tokens | 速度: {speed:.1f} token/s")
        print(f"      ≈ {speed * 60:.0f} token/分钟\n")
    else:
        print(f"⚠️  无法计算速度（输出为空或时间异常）\n")

    # === 测试 2：RAG 场景 ===
    rag_prompt = (
        "根据以下文档回答问题：\n"
        "Godot 引擎中，Node 是场景树的基本构建块，所有游戏对象都继承自 Node。\n"
        "它负责管理子节点、处理输入事件、以及生命周期回调。\n\n"
        "问题：Godot 中什么是 Node？请简要说明其作用。"
    )
    print(f"📄 RAG Prompt:\n{rag_prompt}\n")
    
    response2, total_time2, out_tokens2 = timed_generate(llm, rag_prompt)
    
    print(f"🤖 模型: {response2}\n")
    if out_tokens2 > 0 and total_time2 > 0:
        speed2 = out_tokens2 / total_time2
        print(f"📊 [测试2] 耫时: {total_time2:.2f}s | 输出: ~{out_tokens2} tokens | 速度: {speed2:.1f} token/s")
        print(f"      ≈ {speed2 * 60:.0f} token/分钟\n")

    print("✅ 测试完成！")
    print("\n💡 建议：")
    print("   • 若速度 < 5 token/s，考虑换 Q4_K_M 量化模型")
    print("   • 有 NVIDIA 显卡？安装 CUDA 版 llama-cpp-python 可提速 5~10 倍！")