# backend/build_rag_index.py
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

from sentence_transformers import SentenceTransformer
import faiss
import pickle
import numpy as np
from typing import List

# ======================
# ⚙️ 参数配置区（方便调试 & 调整）
# ======================

# 知识库文件
KNOWLEDGE_FILE = "godot_qwen_knowledge.txt"      # ← 你的知识库文本文件
COMMENT_PREFIX = "#"                             # ← 注释行前缀（这些行会被忽略）

# 模型设置
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # ← 支持中文的轻量模型

# 输出文件
INDEX_FILE = "rag_index.faiss"    # ← 向量索引（FAISS 格式）
CHUNKS_FILE = "rag_chunks.pkl"    # ← 原始文本块（pickle 格式）

# 检索设置
DEFAULT_TOP_K = 3                 # ← 默认返回最相关的 3 条知识


# ======================
# 📚 知识库加载函数（支持【问题】【答案】格式）
# ======================

def load_knowledge() -> List[str]:
    """从 knowledge.txt 读取并按【问题】【答案】格式分割"""
    if not os.path.exists(KNOWLEDGE_FILE):
        raise FileNotFoundError(f"❌ 请创建 {KNOWLEDGE_FILE} 文件！")
    
    with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    chunks = []
    current_question = ""
    current_answer = ""

    for line in lines:
        line = line.strip()
        if not line or line.startswith(COMMENT_PREFIX):  # 跳过空行和注释
            continue
        
        if line.startswith("【问题】"):
            # 结束上一条
            if current_question and current_answer:
                chunks.append(f"{current_question}\n{current_answer}")
            # 开始新条目
            current_question = line[4:]  # 去掉【问题】
            current_answer = ""
        elif line.startswith("【答案】"):
            current_answer = line[4:]  # 去掉【答案】
        else:
            # 未识别格式，跳过（可选：也可追加到当前 answer）
            continue
    
    # 添加最后一条
    if current_question and current_answer:
        chunks.append(f"{current_question}\n{current_answer}")
    
    return chunks


# ======================
# 🧠 RAG 构建与检索模块
# ======================

def build_rag_index():
    """构建 RAG 向量索引（保留你原有的输出风格）"""
    print("📂 正在加载知识库...")
    chunks = load_knowledge()

    print(f"✅ 成功解析 {len(chunks)} 条问答对")
    for i, c in enumerate(chunks[:2], 1):
        q = c.split('\n')[0]
        print(f"  💬 {i}. {q[:50]}...")

    # 加载 Embedding 模型
    print("⏳ 正在加载 Embedding 模型（首次需联网）...")
    model = SentenceTransformer(EMBEDDING_MODEL)

    # 向量化
    print("🧠 正在生成向量...")
    embeddings = model.encode(chunks, show_progress_bar=True)

    # 构建 FAISS 索引
    print("🔍 正在构建向量索引...")
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(np.array(embeddings).astype('float32'))

    # 保存
    faiss.write_index(index, INDEX_FILE)
    with open(CHUNKS_FILE, "wb") as f:
        pickle.dump(chunks, f)

    print(f"✅ RAG 索引构建完成！已保存 {INDEX_FILE} 和 {CHUNKS_FILE}")


def retrieve_relevant_chunks(query: str, top_k: int = DEFAULT_TOP_K) -> List[str]:
    """根据查询检索相关知识片段"""
    if not os.path.exists(INDEX_FILE) or not os.path.exists(CHUNKS_FILE):
        raise RuntimeError(f"❌ 未找到 RAG 索引！请先运行 build_rag_index()")

    # 加载
    index = faiss.read_index(INDEX_FILE)
    with open(CHUNKS_FILE, "rb") as f:
        chunks = pickle.load(f)

    # 编码查询
    model = SentenceTransformer(EMBEDDING_MODEL)
    query_vec = model.encode([query])

    # 检索
    D, I = index.search(np.array(query_vec).astype('float32'), top_k)

    # 去重 & 防越界
    results = []
    seen = set()
    for idx in I[0]:
        if idx < len(chunks) and chunks[idx] not in seen:
            results.append(chunks[idx])
            seen.add(chunks[idx])
        if len(results) >= top_k:
            break
            
    return results


# ======================
# 🚀 主程序入口
# ======================

if __name__ == "__main__":
    build_rag_index()