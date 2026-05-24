# test_GGUF_embedding_batch.py
import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import local
from tqdm import tqdm

# 【关键】告诉 llama-cpp-python 去哪里找 llama.dll
os.environ["LLAMA_CPP_LIB"] = r"E:\anaconda\envs\qwen-helper\Lib\site-packages\llama_cpp\lib\llama.dll"

from llama_cpp import Llama

# 配置
model_path = r"G:\GGUF\nomic-embed-text-v1.5.q4_k_m.gguf"
chunks = [f"chunk_{i}: This is a sample text for embedding benchmark." for i in range(1615)]

# 线程局部存储（每个线程只创建一次模型）
thread_local = local()

def get_embedder():
    """每个线程获取自己的 embedder（只初始化一次）"""
    if not hasattr(thread_local, "embedder"):
        thread_local.embedder = Llama(
            model_path=model_path,
            embedding=True,
            n_ctx=512,
            n_threads=1,
            verbose=False
        )
    return thread_local.embedder

def embed_single(text):
    embedder = get_embedder()
    return embedder.embed(text)

if __name__ == "__main__":
    print(f"[INFO] Starting embedding for {len(chunks)} chunks...")
    
    start_time = time.time()
    
    # 执行并行 embedding
    with ThreadPoolExecutor(max_workers=6) as executor:
        embeddings = list(tqdm(executor.map(embed_single, chunks), total=len(chunks), desc="Embedding"))
    
    total_time = time.time() - start_time
    
    print(f"\n✅ Done! Total time: {total_time:.2f}s")
    print(f"⏱️  Avg per chunk: {total_time / len(chunks) * 1000:.1f} ms")
    print(f"📊 First embedding dim: {len(embeddings[0])}")
    print(f"🔍 First 5 values: {[round(x, 6) for x in embeddings[0][:5]]}")