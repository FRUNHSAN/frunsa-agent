# benchmark/config.py

from pathlib import Path

# === 路径定义 ===
BENCHMARK_DIR = Path(__file__).parent              # .../benchmark/
PROJECT_ROOT = BENCHMARK_DIR.parent                # .../godot-qwen-agent/

# ✅ 原始结果文件：放在项目根目录
BENCHMARK_RESULTS_FILE = PROJECT_ROOT / "benchmark_results.json"

# ✅ 输出目录：放在项目根目录下的 benchmark_results/ 文件夹
OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"

# ==============================
# 🧪 嵌入模型评测配置
# ==============================

# 要评测的模型列表
# 格式说明：
# - 普通模型：直接写 Hugging Face ID，如 "BAAI/bge-m3"
# - GGUF 模型：使用前缀 "gguf:<hf_id>:<quant>"，例如 "gguf:BAAI/bge-m3:q4_k_m"
#   ⚠️ 必须提前在 benchmark/gguf_model_registry.json 中注册对应 .gguf 文件路径！
MODELS: list[str] = [
    # --- 原生模型（使用 sentence-transformers 加载）---
    # "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    # "BAAI/bge-m3",
    # "nomic-ai/nomic-embed-text-v1.5",
    # "Qwen/Qwen3-VL-Embedding-2B",
    # "Qwen/Qwen3-Embedding-0.6B",

    # --- GGUF 量化模型（使用 llama.cpp 加载）---
    # "gguf:nomic-ai/nomic-embed-text-v1.5:q4_k_m",
    # "gguf:Qwen/Qwen3-VL-Embedding-2B:q4_k_m",
    "gguf:Qwen/Qwen3-Embedding-0.6B:q4_k_m",
    # "gguf:BAAI/bge-m3:q5_k_m",   # 可按需启用更多量化版本
]
# 💡 所有 sentence-transformers 官方模型都在 sentence-transformers/ 组织下！
# 你可以在这里确认：
# 👉 https://huggingface.co/sentence-transformers

GGUF_MODEL_REGISTRY = Path("gguf_model_registry.json")

# ====== 知识库配置 ======
KNOWLEDGE_SOURCES = {
    "short_zh": {
        "path": "knowledge/old/short_zh.txt",
        "lang": "zh",
        "description": "Godot 中文 FAQ（短问答）",
        "loader": {                     # ← 统一入口：loader 配置
            "type": "custom",           # ← 关键！指定 loader 类型
            "format": "txt_qa",         # 自定义格式标识
        },
        "chunking": {
            "strategy": "fixed",
            "chunk_size": 256,
            "chunk_overlap": 0
        }
    },

    "medium_en": {
        "path": "knowledge/old/medium_en.md",
        "lang": "en",
        "description": "Godot 英文教程片段",
        "loader": {
            "type": "custom",
            "format": "plain_text"
        },
        "chunking": {
            "strategy": "recursive",
            "chunk_size": 512,
            "chunk_overlap": 50
        }
    },

    "long_en": {
        "path": "knowledge/old/long_en.html",
        "lang": "en",
        "description": "Godot 官方类文档（长文本）",
        "loader": {
            "type": "custom",
            "format": "html"   # 虽然是 HTML，但用简单解析（BeautifulSoup get_text）
        },
        "chunking": {
            "strategy": "recursive",
            "chunk_size": 768,
            "chunk_overlap": 100
        }
    },

    "godot_en": {
        "path": "knowledge/new/godot-docs",
        "lang": "en",
        "description": "完整 Godot 官方文档（新 loader）",
        "loader": {
            "type": "data_loader",      # ← 使用新框架
            "engine": "html_recursive", # data_loader 内部策略
            "enable_dedup": True,
            "min_length": 50,
            "max_length": 1024
        },
        "chunking": {
            "strategy": "level1",       # 注意：这个 strategy 是给 embedding mapping 用的 key
            "chunk_sizes": [256, 512],  # 实际由 data_loader 决定如何 chunk
            "overlaps": [0, 50]
        }
    }
}

# === 新增：知识库加载模式开关 ===
# 可选值：
#   "new_only"      → 仅使用 data_loader（推荐）
#   "old_only"      → 仅使用内置知识库（兼容旧版）
#   "both"          → 同时测试新旧（需确保无冲突 ID）
KNOWLEDGE_LOADING_MODE = "both"


# 🔢 Embedding 推理 benchmark 配置
EMBEDDING_BENCHMARK_ENCODE_RUNS = 20  # 默认 5 次 encode 取平均

WARMUP_ENCODE_RUNS = 3  # Warm-up 预跑次数，不计入正式测量

# 是否复用已有的 chunk 缓存（True: 复用；False: 强制重新切分）
REUSE_CHUNK_CACHE = True

# 是否复用已有的 embedding 缓存（True: 复用；False: 强制重新编码）
REUSE_EMBED_CACHE = True

# 全局路径配置
CACHE_ROOT = Path("cache")
CHUNKS_DIR = CACHE_ROOT / "chunks"
EMBEDDINGS_DIR = CACHE_ROOT / "embeddings"

# 映射文件路径
MODEL_CHUNK_EMBED_MAPPING_FILE = Path(__file__).parent / "model_chunk_embed_mapping.json"

# ==============================
# 🖥️ Embedding 模型运行设备配置
# ==============================
# 可选值：
#   "cpu"          → 强制使用 CPU
#   "cuda"         → 使用默认 GPU (等价于 cuda:0)
#   "cuda:0"       → 使用第 0 块 GPU
#   "cuda:1"       → 使用第 1 块 GPU（需存在）
#   "auto"         → 自动选择：有 GPU 用 cuda:0，否则用 cpu（推荐）
EMBEDDING_DEVICE = "cuda"

# ==============================
# 📦 模型下载文件过滤规则（用于 snapshot_download）
# ==============================
SNAPSHOT_DOWNLOAD_ALLOW_PATTERNS = [
    "*.json",
    "*.bin",
    "*.txt",
    "*.py",
    "tokenizer.*",
    "vocab.*",
    "special_tokens_map.*",
    "config_sentence_transformers.json",
    "model.safetensors",
]

SNAPSHOT_DOWNLOAD_IGNORE_PATTERNS = [
    ".git/*",
    "*.DS_Store",
    "imgs/",
    "*.jpg",
    "*.png",
    "*.webp",
    "*.md",
    "LICENSE",
    
]

# ==============================
# 🦙 GGUF 模型支持配置
# ==============================

# --- [A] 评测阶段：GGUF 模型推理参数（用于 llama-cpp-python）
GGUF_INFERENCE_CONFIG = {
    "n_threads": 8,      # CPU 线程数
    "n_ctx": 8192,       # 上下文长度（BGE-M3 支持长文本）
    # "n_gpu_layers": 0, # embedding 暂不支持 GPU offload
}

# --- [B] 构建阶段：仅用于 convert/quantize 脚本（benchmark 本身不使用）
LLAMA_CPP_PATH = "H:\\agent项目\\godot-qwen-agent\\GGUF\\llama.cpp"
QUANTIZE_EXE_PATH = "H:\\agent项目\\godot-qwen-agent\\GGUF"
QUANTIZATION_TYPE = "q4_k_m"

# ⭐ 新增：是否跳过量化（用于生成中间 f16 模型）
SKIP_QUANTIZE = True  # 设为 True 时，只生成 f16 模型，不量化


# ====== 测试查询（按知识源 ID 精准匹配）======
TEST_QUERIES = {
    # === short_zh.txt 中的内容（Godot 4.5 + FastAPI 常见问题）===
    "short_zh": [
        "在 Godot 4.5 中调用 HTTPRequest.request() 时 body 参数报类型错误怎么办？",
        "使用 JSON.stringify() 时返回 null 导致后续错误如何避免？",
        "FastAPI 接口返回 422 Unprocessable Entity 错误怎么解决？"
    ],
    
    # === medium_en.md 中的内容（Godot HTTP 最佳实践）===
    "medium_en": [
        "How to properly send JSON data in Godot 4 using HTTPRequest?",
        "Why does my FastAPI backend return 422 when I send a request from Godot?",
        "What headers must be set when sending JSON from Godot to a FastAPI endpoint?"
    ],
    
    # === long_en.html 中的内容（Godot 官方文档风格）===
    "long_en": [
        "How to use the HTTPRequest node in Godot Engine to send a POST request with JSON body?",
        "What is the correct way to handle non-serializable objects when using JSON.stringify() in GDScript?",
        "How to test an /ask API endpoint using Postman according to the Godot-Qwen agent documentation?"
    ],

    # === 默认 fallback（保留，以防新增 source 未定义）===
    "default_zh": ["这个功能怎么用？"],
    "default_en": ["How to use this feature?"]
}


# ==============================
# 🔧 内部路径解析
# ==============================
BENCHMARK_DIR = Path(__file__).parent
PROJECT_ROOT = BENCHMARK_DIR.parent

# 将相对路径转为绝对 Path 对象，并补充 full_path
RESOLVED_KNOWLEDGE_SOURCES = {
    key: {
        **value,
        "full_path": (PROJECT_ROOT / value["path"]).resolve()
    }
    for key, value in KNOWLEDGE_SOURCES.items()
}

# ✅ 统一定义缓存注册表和结果文件
CACHE_REGISTRY_FILE = BENCHMARK_DIR / "cache_registry.json"
# 确保输出目录存在（可选，非必须）
OUTPUT_DIR.mkdir(exist_ok=True)

# ====== 📊 报告生成配置 ======
# ====== 📊 报告生成配置 ======
REPORT_CONFIG = {
    "normalize_scores_to_01": True,

    # 🖼️ 通用绘图参数
    "plot_options": {
        "dpi": 300,
        "figsize": (10, 5),
        "font_family": "Microsoft YaHei",
        "title_fontsize": 14,
        "label_fontsize": 12,
        "tick_fontsize": 10,
        "legend_fontsize": 10,
        "rotate_xticks": 15,
        "grid_alpha": 0.3,
    },

    # 📊 对比图 (Bar Chart)
    "comparison_plot": {
        "default": {
            "figsize": (10, 5),
            "rotate_xticks": 15,
            "bar_alpha": 0.8,
            "annotation": {
                "offset": (0, 3),
                "fontsize": 9,
            },
            "grid_alpha": 0.3,
            "dpi": 300,
        },
        "overrides": {}
    },

    # 📄 分块分析图 (Chunking Analysis - Dual Bar Charts)
    "chunking_analysis_plot": {
        "default": {
            "figsize": (12, 6),  # 宽度增加以容纳双子图
            "rotate_xticks": 15,
            "bar_alpha": 0.7,
            "bar_colors": ["skyblue", "lightcoral"],
            "annotation": {
                "offset": (0, 3),
                "fontsize": 9,
            },
            "grid_alpha": 0.3,
            "dpi": 300,
        },
        "overrides": {}
    },

    # 📏 分块长度详细对比图 (Detailed Chunk Length Comparison - Grouped Bar Chart)
    "chunking_detailed_comparison_plot": {
        "default": {
            "figsize": (10, 5),
            "rotate_xticks": 15,
            "bar_width": 0.35,
            "bar_alpha": 0.7,
            "bar_colors": ["lightgreen", "tomato"],
            "annotation": {
                "offset": (0, 3),
                "fontsize": 8,
            },
            "grid_alpha": 0.3,
            "dpi": 300,
        },
        "overrides": {}
    },

    # 📈 延迟分布箱线图 (Latency Distribution Boxplot)
    "latency_distribution_plot": {
        "default": {
            "figsize": (10, 6),
            "rotate_xticks": 30,
            "scatter": {
                "color": "lightgray",
                "alpha": 0.5,
                "s": 10,
                "edgecolors": "none",
                "jitter_sigma": 0.04,
            },
            "boxplot": {
                "facecolor": "steelblue",
                "alpha": 0.7,
                "median_color": "gold",
                "whisker_color": "navy",
                "cap_color": "red",
                "flier_marker": "o",
                "flier_size": 4,
                "flier_color": "black",
            },
            "annotate": {
                "offset_x": 0.10,
                "offset_y": 6,
                "fontsize": 9,
                "ha": "left",
                "va": "bottom",
                "bbox": {
                    "boxstyle": "round,pad=0.2",
                    "facecolor": "white",
                    "edgecolor": "gray",
                    "alpha": 0.85
                }
            },
            "dpi": 300,
        },
        "overrides": {}
    },

    # 📉 延迟折线图 (Latency Line Plot with Error Bars)
    "latency_line_plot": {
        "default": {
            "figsize": (10, 5),
            "rotate_xticks": 15,
            "scatter": {
                "color": "lightgray",
                "alpha": 0.6,
                "s": 15,
                "jitter_sigma": 0.04,
            },
            "line": {
                "color": "steelblue",
                "marker": "o",
                "markersize": 6,
                "capsize": 5,
                "capthick": 1.5,
                "elinewidth": 1.5,
                "ecolor": "gray",
            },
            "annotate": {
                "offset": (0, 10),  # Y方向偏移
                "fontsize": 9,
                "bbox": {
                    "boxstyle": "round,pad=0.3",
                    "facecolor": "white",
                    "edgecolor": "gray",
                    "alpha": 0.8
                }
            },
            "grid_alpha": 0.3,
            "dpi": 300,
        },
        "overrides": {}
    },

    # 📁 输出文件名模板
    "output_files": {
        "summary_csv": "performance_summary.csv",
        "latency_plot": "latency_comparison.png",
        "semantic_similarity_plot": "semantic_similarity.png",
        "chunking_analysis_plot": "chunking_analysis_{model}.png",
        "chunking_length_comparison_plot": "chunking_length_comparison.png",
        "latency_distribution_plot": "latency_distribution_{model}.png",
        "latency_line_plot": "latency_line_{model}.png"
    },

    # 🔢 相似度算法配置
    "similarity_algorithms": {
        "default": "cosine",
        "options": ["cosine", "euclidean", "manhattan", "jaccard"],
        "cosine": {
            "name": "余弦相似度",
            "description": "计算向量夹角的余弦值",
            "formula": "cos(θ) = A·B / (||A|| ||B||)"
        },
        "euclidean": {
            "name": "欧氏距离",
            "description": "计算两点间的直线距离",
            "formula": "d(A,B) = √Σ(xi - yi)²"
        },
        "manhattan": {
            "name": "曼哈顿距离",
            "description": "计算两点间沿坐标轴的距离",
            "formula": "d(A,B) = Σ|xi - yi|"
        },
        "jaccard": {
            "name": "杰卡德相似系数",
            "description": "计算两个集合的交集与并集的比例",
            "formula": "J(A,B) = |A∩B| / |A∪B|"
        }
    },

    # 📊 其他显示选项
    "show_grid": True,
    "save_plots": True,
    "display_plots": False,
}