# RAG Test Data Contract (RAG 测试数据契约)

> 替代原始 2.1GB Godot 文档镜像的轻量级数据契约包。

---

## 背景

本项目在 Phase 1-6 阶段进行了 RAG 检索质量评估实验，使用 Godot 引擎官方文档作为知识库，通过多种嵌入模型（BAAI/bge-m3、paraphrase-multilingual-MiniLM-L12-v2 等）在不同分块策略下进行检索质量 + 推理延迟双维度评测。

完整测试数据集（2.1GB 原始 HTML + 分块 + FAISS 索引 + embedding 向量）因体积和安全考量未纳入版本控制。本目录提供数据契约——样本 + Schema + 文档，证明实验设计的工程规范性。

---

## 数据管线架构

```
Godot 官方文档 (HTML)
       │
       ▼
  godot_qwen_knowledge.txt    ← 文本提取 + 清洗
       │
       ▼
  chunks.json                 ← 分块（按层级/长度策略）
       │
       ▼
  SentenceTransformer.encode() ← 嵌入向量生成
       │
       ▼
  embeddings.npy + FAISS      ← 向量索引
       │
       ▼
  retrieve_relevant_chunks()  ← 检索接口
```

---

## 文件说明

| 文件 | 格式 | 说明 |
|------|------|------|
| `sample.json` | JSON | 5 条脱敏样本（chunk 文本 + 元数据） |
| `schema.json` | JSON Schema | chunks.json 和 mapping.json 的完整结构定义 |

---

## 完整数据集获取

完整数据集（含 2.1GB 原始文档、嵌入向量、FAISS 索引）因以下原因未公开：

- **体积限制**：远超 Git 仓库建议上限
- **版权考量**：原始文档来自 Godot 官方（MIT 协议），已标注来源
- **安全边界**：嵌入向量可能通过模型反演泄露部分文档内容

如需复现实验，可通过以下方式获取：

1. 从 [Godot 官方文档](https://docs.godotengine.org/) 下载文档源
2. 使用 `backend/build_rag_index.py` 构建 FAISS 索引
3. 使用 `cache_loader.py` 加载 chunks + embeddings
4. 参考 `experiment/config.yaml` 配置评测参数

---

## 技术栈

- **嵌入模型**: BAAI/bge-m3, paraphrase-multilingual-MiniLM-L12-v2
- **向量索引**: FAISS (Flat IP)
- **分块策略**: 按文档层级 (level1) + 固定长度滑动窗口
- **评测指标**: Accuracy, Latency, Relevance
- **实验管理**: experiment/pipeline.py + config.yaml
