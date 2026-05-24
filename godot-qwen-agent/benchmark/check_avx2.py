# check_avx2.py
try:
    from llama_cpp import Llama
except ImportError:
    try:
        from llama_cpp import Llama
    except ImportError:
        print("错误: 无法导入 llama_cpp 模块")
        print("请先安装 llama-cpp-python: pip install llama-cpp-python")
        exit(1)

import logging

# 启用 llama.cpp 的内部日志
logging.basicConfig(level=logging.INFO)

print("正在初始化 llama.cpp...")

try:
    # 使用一个不存在的模型路径，但开启 verbose=True 以输出底层日志
    model = Llama(
        model_path=r"G:\GGUF\nomic-embed-text-v1.5.q4_k_m.gguf",   # 不存在也没关系
        embedding=True,
        n_threads=4,
        verbose=True               # 👈 关键：启用详细日志
    )
except Exception as e:
    # 预期会报 "model not found"，但我们只关心初始化日志
    if "dummy.gguf" in str(e):
        print("✅ 初始化日志已输出（模型未找到是正常的）")
    else:
        print("❌ 意外错误:", e)