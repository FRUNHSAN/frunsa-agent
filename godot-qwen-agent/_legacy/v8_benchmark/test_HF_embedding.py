# test_HF_embedding.py（修正版）
from sentence_transformers import SentenceTransformer
import os

LOCAL_MODEL_PATH = r"G:\rag666"

if os.path.exists(LOCAL_MODEL_PATH):
    print(f"Loading model from local path: {LOCAL_MODEL_PATH}")
    model = SentenceTransformer(LOCAL_MODEL_PATH)
else:
    model = SentenceTransformer("BAAI/bge-m3")

# === 关键：关闭默认的 query prompt ===
model.prompts = {}  # 清空所有 prompts
# 或者显式设置为空字符串
# model.default_prompt_name = None

text = "Hello, world!"
embedding = model.encode(text, convert_to_numpy=True)

print(f"Embedding dim: {embedding.shape[0]}")
print(f"First 5 values: {embedding[:5].tolist()}")