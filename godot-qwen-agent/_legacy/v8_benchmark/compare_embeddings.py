# compare_embeddings.py
"""
Embedding 对比工具：验证 GGUF 量化模型 vs 原生 Hugging Face 模型
- 支持 HF 模型指定设备（cpu / cuda）
- 输出余弦相似度 + 推理耗时
- 自动 L2 归一化（符合 BGE 规范）
"""
import os
import sys
import time
import argparse
import numpy as np

# 添加当前目录到路径（确保 utils 可导入）
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from utils import l2_normalize

# === 默认配置（可通过命令行覆盖）===
DEFAULT_GGUF_PATH = r"G:\GGUF\BAAI-bge-m3.q4_k_m.gguf"
DEFAULT_HF_PATH = r"G:\rag666"
DEFAULT_TEXT = "Hello, world!"
DEFAULT_DEVICE = "auto"  # 可选: cpu, cuda, auto
DEFAULT_THREADS = 6

# Windows 下指定 llama.dll 路径（如需要）
os.environ["LLAMA_CPP_LIB"] = r"E:\anaconda\envs\qwen-helper\Lib\site-packages\llama_cpp\lib\llama.dll"

def parse_args():
    parser = argparse.ArgumentParser(description="Compare HF and GGUF embedding models.")
    parser.add_argument("--gguf", type=str, default=DEFAULT_GGUF_PATH, help="Path to GGUF model file")
    parser.add_argument("--hf", type=str, default=DEFAULT_HF_PATH, help="Path to local HF model directory")
    parser.add_argument("--text", type=str, default=DEFAULT_TEXT, help="Base input text for embedding")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat the text N times to simulate long input (e.g., --repeat 100)")
    parser.add_argument("--device", type=str, default=DEFAULT_DEVICE, choices=["cpu", "cuda", "auto"],
                        help="Device for HF model (GGUF always runs on CPU)")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS, help="Number of threads for GGUF (CPU only)")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs for timing average")
    return parser.parse_args()

def get_device(device_option: str) -> str:
    if device_option == "auto":
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device_option

def main():
    args = parse_args()
    test_text = args.text * args.repeat  # ✅ 生成长文本

    # 打印时截断显示，但实际用完整文本
    display_text = test_text[:100] + "..." if len(test_text) > 100 else test_text
    print(f"\nTest text: '{display_text}' (length: {len(test_text)} chars)")

    # === 确定 HF 设备 ===
    hf_device = get_device(args.device)
    print(f"[INFO] Using HF model on device: {hf_device}")
    print(f"[INFO] GGUF model will run on CPU (threads={args.threads})")

    # === 加载 GGUF 模型 ===
    print("\nLoading GGUF model...")
    from llama_cpp import Llama
    gguf_model = Llama(
        model_path=args.gguf,
        embedding=True,
        n_ctx=8192,          # 支持更长上下文
        n_threads=args.threads,
        verbose=False
    )

    # === 加载 HF 模型 ===
    print("Loading HF model...")
    from sentence_transformers import SentenceTransformer
    hf_model = SentenceTransformer(args.hf, device=hf_device)
    hf_model.prompts = {}  # 禁用默认 prompt

    # === 性能测试函数 ===
    def time_embedding(model, text, is_gguf=False, runs=3):
        # 预热 1 次
        if is_gguf:
            model.embed(text)
        else:
            model.encode(text, convert_to_numpy=True)

        times = []
        for _ in range(runs):
            start = time.perf_counter()
            if is_gguf:
                emb = model.embed(text)
            else:
                emb = model.encode(text, convert_to_numpy=True)
            end = time.perf_counter()
            times.append((end - start) * 1000)  # ms
        return np.array(emb), np.mean(times)

    # === 执行对比（使用 test_text！）===
    print("-" * 60)

    emb_hf, time_hf = time_embedding(hf_model, test_text, is_gguf=False, runs=args.runs)   # ✅ 用 test_text
    emb_gguf, time_gguf = time_embedding(gguf_model, test_text, is_gguf=True, runs=args.runs)  # ✅ 用 test_text

    # ✅ 使用新函数归一化
    emb_hf = l2_normalize(emb_hf)
    emb_gguf = l2_normalize(emb_gguf)

    similarity = np.dot(emb_hf, emb_gguf)

    # === 输出结果 ===
    print("\n=== Embedding Comparison ===")
    print(f"HF   first 5: {emb_hf[:5]}")
    print(f"GGUF first 5: {emb_gguf[:5]}")
    print(f"Cosine similarity: {similarity:.4f}")
    print(f"HF   L2 norm: {np.linalg.norm(emb_hf):.6f}")
    print(f"GGUF L2 norm: {np.linalg.norm(emb_gguf):.6f}")

    print("\n=== ⏱️  Inference Time (avg over {} runs) ===".format(args.runs))
    print(f"HF   ({hf_device}): {time_hf:.2f} ms")
    print(f"GGUF (CPU)     : {time_gguf:.2f} ms")
    
    if time_gguf > 0:
        speedup = time_hf / time_gguf
        print(f"Speedup: {speedup:.2f}x {'faster' if speedup > 1 else 'slower'} with GGUF")
        if speedup > 1.5:
            print("\n💡 GGUF 显著加速！非常适合无 CUDA 的低配电脑。")
        elif speedup < 0.8:
            print("\n⚠️ GGUF slower — try longer text (e.g., --repeat 300+) or increase --threads.")
        else:
            print("\nℹ️ Similar speed — GGUF shines on longer texts.")
    else:
        print("\n⚠️ GGUF time is zero (unlikely).")


if __name__ == "__main__":
    main()