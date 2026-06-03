# 最小可闭环 MVP：RAG 知识检索 + 本地 GGUF 推理完整链路

## 设计哲学

旧资产的价值不在代码，在**已验证的设计模式**。三个核心模式全部在新架构下重新实现：

| 旧资产 | 已验证的模式 | 新架构下的实现 |
|--------|-------------|---------------|
| `data_loader/chunking/` | 递归分隔符分块 / 固定窗口重叠 / 多粒度委托 | `core/steps/chunking/` — `ContentBlock → List[Chunk]`，`@register_component` |
| `benchmark/benchmark_embedding_models.py` | GGUF embedding 的 SentenceTransformer 兼容封装 | `core/steps/` 下自建 GGUFEmbedder，原生适配 `VectorStoreBackend` |
| `experiment/api_client.py` | 本地/云端双模推理 + 流式输出 | `core/adapters/` 下自建 `LlamaCppGenerationBackend`，适配 `GenerationAdapter` |

人不换，思路换。同一个人，更好的架构。

---

## 目标

> 用户输入 → chunking 策略分块 → GGUF Embedding 语义检索 → 检索结果注入上下文 → 本地 GGUF LLM 生成 → Critic 评估

Mock 模式保持默认（CI 零依赖），本地 GGUF 为可选增强。

---

## Step 1: Chunking 策略实现 `core/steps/chunking/`

> **优先级**: 🔴 P0

### 架构原则

`core/contracts/chunking.py` 已定义 `ChunkingStrategy` Protocol + `ContentBlock`/`Chunk` 数据模型。三种策略实现放在 `core/steps/chunking/`，通过 `@register_component("chunker", ...)` 自动注册。

借鉴旧 `data_loader/chunking/` 的三种算法思路，用新合约接口从零重写：

| 新文件 | 借鉴的旧思路 | 新架构要求 |
|--------|------------|-----------|
| `fixed_chunker.py` (~45 行) | 固定窗口 + chunk_overlap 重叠滑动 | `chunk(ContentBlock) → List[Chunk]`，span 追踪 |
| `recursive_chunker.py` (~60 行) | 分隔符层级递归下降 (`\n\n → \n → 。→ . → `) | UTF-8 字节感知，Chunk.source_strategy 标记 |
| `multi_granularity_chunker.py` (~55 行) | 委托给两个不同粒度的 chunker，合并去重 | 内部委托 FixedChunker(256) + RecursiveChunker(512) |

每个 chunker 遵循 `IdentityChunker` 模式：

```python
@register_component("chunker", "recursive")
class RecursiveChunker:
    VERSION: ClassVar[SemVer] = SemVer(0, 1, 0)
    requires_metadata: ClassVar[Set[str]] = set()
    provides_metadata: ClassVar[Set[str]] = set()

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64) -> None: ...
    def chunk(self, content: ContentBlock) -> List[Chunk]: ...
    def validate_config(self, config: dict) -> None: ...
    def health_check(self) -> HealthStatus: ...
```

分隔符序列（recursive_chunker 核心算法）：
`["\n\n", "\n", "。", ". ", " ", ""]`

### 目录结构

```
core/steps/chunking/
├── __init__.py                  ← 导出 + 触发 @register_component 注册
├── fixed_chunker.py
├── recursive_chunker.py
└── multi_granularity_chunker.py
```

---

## Step 2: `demo/demo_rag.py` — 文档加载 + GGUF 语义检索 + Embedding 缓存

> **优先级**: 🔴 P0

当前行为不变（Mock 模式默认）。新增三项增强：

### 2.1 文档加载器（~40 行）

支持 `.txt/.md` + chardet 编码检测。不支持的格式抛出 `ValueError`。

```python
def _load_document(path: str) -> ContentBlock:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in (".txt", ".md"):
        raise ValueError(f"Unsupported format '{suffix}': {path}")
    raw = p.read_bytes()
    try:
        import chardet
        encoding = chardet.detect(raw).get("encoding", "utf-8") or "utf-8"
    except ImportError:
        encoding = "utf-8"
    return ContentBlock(
        text=raw.decode(encoding, errors="replace"),
        source=str(p),
        metadata={"format": suffix, "encoding": encoding},
    )
```

### 2.2 GGUF 语义检索（~50 行）

借鉴旧 `benchmark/benchmark_embedding_models.py` 的 GGUF embedding 封装思路，在新架构下自建 `GGUFEmbedder`。将 hash 伪向量替换为真实语义向量。

```python
class GGUFEmbedder:
    """借鉴旧 GGUFEmbedder 的 SentenceTransformer 兼容封装思路。"""
    def __init__(self, model_path: str, dim: int = 768) -> None: ...
    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

### 2.3 Embedding 缓存（~30 行）

MD5 → JSON 持久化（`.cache/embeddings.json`），知识库不变时重启零推理开销。

### 降级链

无 GGUF 模型 → hash 伪向量 → 无文档文件 → 12 条硬编码知识 → 缓存损坏 → 静默重建

---

## Step 3: `demo/demo_engine.py` — 本地 GGUF LLM 推理 + CPU 优化锚点

> **优先级**: 🔴 P0

### 自建 LlamaCppGenerationBackend

借鉴旧 `experiment/api_client.py` 的双模（本地/云端）抽象思路，在新架构下自建 backend，原生适配 `GenerationAdapter` 协议：

```python
class LlamaCppGenerationBackend:
    """借鉴旧 LLMClient 的双模推理抽象思路，为 GenerationAdapter 协议原生设计。

    CPU 推理优化锚点（当前预留，面试时展示接口设计）：
      - routing_hints: 未来 Router 根据 {"intent": "simple_extraction"} 选择快模型
      - grammar:       未来传入 GBNF 语法约束，减少 30-50% 无效 token
      - cache_prompt:  未来开启 KV Cache 复用，多轮对话 Prefill 加速 5-10x
    """

    def __init__(
        self, client: LLMClient,
        routing_hints: dict | None = None,  # ← 大小模型路由锚点
        grammar: str | None = None,         # ← GBNF 约束解码锚点
        cache_prompt: bool = False,         # ← KV Cache 复用锚点
    ): ...

    def generate(self, prompt: str, **kwargs) -> str: ...
    def generate_stream(self, prompt: str, **kwargs) -> Iterator[str]: ...
```

---

## Step 4: 模型注册表 `GGUF/model_registry.json`

> **优先级**: 🟡 P1

```json
{
  "embedding": {
    "nomic-embed-text-v1.5": {
      "file": "embedding/nomic-embed-text-v1.5.Q4_K_M.gguf",
      "quant": "Q4_K_M", "dim": 768, "max_seq_len": 512
    }
  },
  "generation": {
    "qwen2.5-coder-1.5b": {
      "file": "generation/qwen2.5-coder-1.5b.Q4_K_M.gguf",
      "quant": "Q4_K_M", "template": "qwen2.5-coder-1.5b",
      "max_seq_len": 32768, "speed_tier": "fast",
      "suitable_for": ["intent_routing", "simple_extraction", "classification"]
    },
    "qwen3-4b": {
      "file": "generation/qwen3-4b.Q4_K_M.gguf",
      "quant": "Q4_K_M", "template": "qwen3",
      "max_seq_len": 32768, "speed_tier": "slow",
      "suitable_for": ["complex_reasoning", "long_generation", "planning", "evaluation"]
    }
  }
}
```

`GGUF/` 加入 `.gitignore`。

---

## Step 5: 基线对比测试 `tests/integration/test_rag_baseline.py`

> **优先级**: 🟡 P1

- `test_gguf_retrieval_hit_rate`: GGUF 语义命中率 >= 4/5
- `test_mock_retrieval_is_random`: 伪向量命中率 <= 2/5
- `test_gguf_vs_pseudo_embedding_divergence`: Jaccard < 0.5（自对比，无需外部 ground truth）
- 无 GGUF 模型时自动 skip，不阻塞 CI

---

## Step 6: `demo/app.py` — UI 控制

> **优先级**: 🔴 P0

侧边栏新增：

```
模型模式:  ○ Mock（默认）    ○ Local GGUF（CPU）
分块策略:  [recursive ▼]    (fixed / recursive / multi-granularity)
```

选 Local GGUF 时自动读 `GGUF/model_registry.json`，无模型显示提示不崩溃。

---

## 可观测性 — 结构化日志

> **优先级**: 🟢 P2 — `print` 级别够用

RAG + Pipeline 关键节点注入结构化日志。Streamlit 用 `st.expander("📋 运行日志")` 展示。

---

## 向量数据库可插拔（FAISS Backend）

> **优先级**: 🟢 P2

`core/adapters/faiss_backend.py`（~60 行）：实现 `VectorStoreBackend` 协议。延迟导入 `faiss`（`HAS_FAISS = False` 顶层标志位）。Demo 侧边栏 `InMemory | FAISS` 切换。

---

## CPU 推理优化扩展预留

- **预留 1**: 大小模型路由 — `model_registry.json` 已有 `speed_tier`，`routing_hints` 参数已预留
- **预留 2**: Semantic Cache — `demo_rag.py` 可插入 `md5(query) → cache`
- **预留 3**: Grammar Sampling — `grammar` 参数已预留，llama.cpp 原生支持 GBNF
- **预留 4**: KV Cache 复用 — `cache_prompt` 参数已预留
- **已实现**: 全链路 Streaming — `StreamItem` → Thread+Queue bridge → Streamlit 逐条渲染

---

## 改动清单

| 文件 | 操作 | 优先级 |
|------|------|--------|
| `core/steps/chunking/__init__.py` | 新增 | 🔴 P0 |
| `core/steps/chunking/fixed_chunker.py` | 新增 | 🔴 P0 |
| `core/steps/chunking/recursive_chunker.py` | 新增 | 🔴 P0 |
| `core/steps/chunking/multi_granularity_chunker.py` | 新增 | 🔴 P0 |
| `demo/demo_rag.py` | 改动 (~100 行) | 🔴 P0 |
| `demo/demo_engine.py` | 改动 (~90 行) | 🔴 P0 |
| `demo/app.py` | 改动 (~30 行) | 🔴 P0 |
| `.gitignore` | 改动 | 🔴 P0 |
| `GGUF/model_registry.json` | 新增 | 🟡 P1 |
| `tests/integration/test_rag_baseline.py` | 新增 | 🟡 P1 |
| `core/adapters/faiss_backend.py` | 新增 | 🟢 P2 |
| `.cache/` 目录 | embedding 缓存存储 | 🔴 P0 |

**总计**: 8 个 P0 文件（~400 行新代码 + ~220 行改动），2 个 P1，1 个 P2

---

## 执行风险点

| 风险 | 对策 |
|------|------|
| Chunker 注册时序：`@register_component` 依赖 import 触发 | `demo/demo_rag.py` 顶部显式 `import core.steps.chunking` |
| FAISS 依赖污染 CI | `HAS_FAISS = False` 顶层标志 + 延迟导入 |
| GGUF 浮点差异：不同 CPU 指令集结果微差 | 断言用 Top-3 命中而非 Top-1 精确匹配 |

---

## 验证

- [ ] Mock 模式 Tab 1 行为不变，所有降级路径生效
- [ ] `pytest tests/ -q` — 全量零回归
- [ ] `python -m guardrails check --all` — 16/16 通过
- [ ] chunking 三种策略对同一样本分块，chunk 数量合理不同
- [ ] `.txt/.md` 正确加载为 `ContentBlock`，不支持的格式抛 `ValueError`
- [ ] Embedding 缓存首次生成 `.cache/`，二次启动跳过推理
- [ ] `test_gguf_retrieval_hit_rate`：GGUF 命中率 >= 4/5（需 GGUF 模型，无则 skip）
- [ ] `test_gguf_vs_pseudo_embedding_divergence`：Jaccard < 0.5（需 GGUF 模型，无则 skip）
- [ ] 有 GGUF 生成模型时：本地 LLM 输出有实际语义
- [ ] 无 GGUF 模型时：降级到 Mock 模式，不崩溃，侧边栏提示
- [ ] Streamlit 侧边栏切换配置，Tab 1 行为正确
