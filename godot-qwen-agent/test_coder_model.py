# test_coder_model.py

from LLM.template_registry import _TEMPLATE_CACHE
_TEMPLATE_CACHE.clear()  # 清除模板缓存（调试用）

import os
import sys
import time
from typing import Tuple

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from experiment.api_client import LLMClient


def count_tokens(text: str) -> int:
    """简单估算 token 数（中文按字，英文按空格）"""
    if not text:
        return 0
    return len(text)


def timed_generate(llm, prompt: str) -> Tuple[str, float, int]:
    """执行推理并返回 (响应, 总耗时, 输出token数)"""
    start_time = time.time()
    response = llm.generate(prompt)
    total_time = time.time() - start_time
    output_tokens = count_tokens(response)
    return response, total_time, output_tokens


def evaluate_gdscript_quality(code: str) -> str:
    """
    简单评估 GDScript 代码质量（非完整解析，仅启发式检查）
    """
    code_lower = code.lower()
    issues = []

    # 检查是否包含关键 Godot 4 元素
    if "characterbody2d" not in code_lower and "kinematicbody2d" not in code_lower:
        issues.append("未使用 CharacterBody2D（Godot 4 推荐）")
    if "move_and_slide" not in code_lower and "move_and_collide" not in code_lower:
        issues.append("未检测到移动方法（move_and_slide）")
    if "func _process" not in code_lower and "func _physics_process" not in code_lower:
        issues.append("缺少 _process 或 _physics_process")

    # 检查是否有明显错误
    if "extends node2d" in code_lower or "extends node" in code_lower:
        pass  # OK
    elif "extends" not in code_lower:
        issues.append("未指定 extends（可能无法运行）")

    if issues:
        return "⚠️ 可疑：" + "；".join(issues)
    else:
        return "✅ 结构合理"


if __name__ == "__main__":
    # === 配置你的 Coder 模型路径 ===
    MODEL_PATH = r"D:/tuili/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"

    print("🚀 测试本地 Coder 模型（专注 GDScript 能力）...\n")
    print(f"📁 模型路径: {MODEL_PATH}")

    # 初始化模型
    load_start = time.time()
    llm = LLMClient(
        local_model_path=MODEL_PATH,
        temperature=0.2,  # 降低温度，提高代码确定性
        n_ctx=4096,
        n_threads=12
    )
    load_time = time.time() - load_start

    # 兼容 llama_cpp 新旧版本
    if hasattr(llm, 'local_llm') and llm.local_llm is not None:
        try:
            n_ctx_val = llm.local_llm.n_ctx()
        except TypeError:
            n_ctx_val = llm.local_llm.n_ctx  # 旧版是属性
        try:
            n_threads_val = llm.local_llm.n_threads()
        except TypeError:
            n_threads_val = llm.local_llm.n_threads
        print(f"🧵 线程数: {n_threads_val} | 上下文长度: {n_ctx_val}\n")
    else:
        print("（API 模式）\n")

    # === 测试 1：基础角色控制器 ===
    test1_prompt = (
        "用 Godot 4 写一个 2D 角色控制器脚本，要求：\n"
        "- 使用 CharacterBody2D\n"
        "- 支持 WASD 移动\n"
        "- 支持空格键跳跃\n"
        "- 使用 _physics_process(delta)\n"
        "- 速度变量清晰"
    )
    print(f"💻 测试 1: 基础角色控制器\n{test1_prompt}\n")

    response1, t1, tok1 = timed_generate(llm, test1_prompt)
    print(f"📜 生成代码:\n{response1}\n")
    print(f"🔍 质量评估: {evaluate_gdscript_quality(response1)}\n")

    if tok1 > 0 and t1 > 0:
        speed1 = tok1 / t1
        print(f"📊 [测试1] 耗时: {t1:.2f}s | ~{tok1} tokens | 速度: {speed1:.1f} token/s\n")

    # === 测试 2：信号与交互 ===
    test2_prompt = (
        "在 Godot 4 中，写一个 GDScript 脚本：\n"
        "- 继承自 Area2D\n"
        "- 当玩家进入时，发出 'player_entered' 信号\n"
        "- 当玩家离开时，发出 'player_exited' 信号\n"
        "- 使用 connect() 示例（注释形式）"
    )
    print(f"💻 测试 2: 信号系统\n{test2_prompt}\n")

    response2, t2, tok2 = timed_generate(llm, test2_prompt)
    print(f"📜 生成代码:\n{response2}\n")

    if tok2 > 0 and t2 > 0:
        speed2 = tok2 / t2
        print(f"📊 [测试2] 耗时: {t2:.2f}s | ~{tok2} tokens | 速度: {speed2:.1f} token/s\n")

    # === 测试 3：简短函数（压力测试）===
    test3_prompt = "写一个 GDScript 函数，计算两点之间的欧几里得距离。"
    print(f"💻 测试 3: 工具函数\n{test3_prompt}\n")

    response3, t3, tok3 = timed_generate(llm, test3_prompt)
    print(f"📜 生成代码:\n{response3}\n")

    if tok3 > 0 and t3 > 0:
        speed3 = tok3 / t3
        print(f"📊 [测试3] 耗时: {t3:.2f}s | ~{tok3} tokens | 速度: {speed3:.1f} token/s\n")

    print("✅ Coder 模型测试完成！")
    print("\n💡 建议：")
    print("   • 若代码缺少 Godot 4 特性，可加强 prompt 中的版本说明")
    print("   • temperature=0.2~0.3 最适合代码生成")
    print("   • 可将输出粘贴到 Godot 编辑器中直接测试！")