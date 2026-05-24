太棒了！🎉 恭喜你的 RAG 嵌入模型基准测试平台达到 **v1.0** 里程碑！

下面为你精心编写了一份专业、清晰、可直接使用的 `README.md` 和 `requirements.txt`，方便他人快速上手和复现你的工作。

---

## ✅ `README.md`

```markdown
# 🧪 RAG Embedding Benchmark Suite (v1.0)

> 一个轻量级、可扩展的嵌入模型（Embedding Model）在多语言、多长度知识库上的检索质量与推理延迟综合评测平台。

本工具支持：
- 多种开源嵌入模型（如 BAAI/bge-m3、sentence-transformers 系列）
- 多语言、多长度知识源（短中文、中英文段落、长英文文档等）
- 自动分块（chunking）与语义检索模拟
- **延迟（Latency） + 相似度（Similarity）双维度评估**
- 丰富的可视化报告：柱状图、折线图（含误差线）、箱线图、分块分析等
- 中文友好输出（自动适配系统中文字体）

适用于：RAG 系统选型、模型性能对比、部署前压测验证。

---

## 📦 功能亮点

- ✅ **一键运行完整 benchmark**  
- ✅ **支持按需生成特定图表**（如仅延迟折线图）
- ✅ **自动生成 CSV 摘要报告 + 性能排名**
- ✅ **详细 per-query 延迟分布分析**（多次运行取平均）
- ✅ **分块策略透明化**：展示 chunk 数量、长度分布
- ✅ **配置驱动**：通过 `config.py` 轻松定制测试集、模型列表、绘图样式

---

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置测试（可选）

编辑 `benchmark/config.py`：
- 添加/修改 `EMBEDDING_MODELS` 列表以测试你的模型
- 调整 `KNOWLEDGE_SOURCES` 中的知识库路径与类型
- 修改 `REPORT_CONFIG` 自定义图表样式或输出路径

> 默认已包含示例数据（`short_zh`, `medium_en`, `long_en`），开箱即用。

### 3. 运行基准测试

```bash
# Step 1: 执行嵌入模型评测（生成 benchmark_results.json）
python benchmark_embedding_models.py

# Step 2: 生成可视化报告
python report_generator.py
```

### 4. 查看结果

所有输出位于 `./benchmark_results/` 目录，包括：
- `performance_summary.csv`：模型平均性能摘要
- `latency_comparison.png`：各模型延迟对比
- `semantic_similarity_cosine.png`：语义相似度对比
- `latency_line_*.png` / `latency_distribution_*.png`：延迟分布细节
- `chunking_analysis_*.png`：分块统计

---

## 🔧 高级用法

### 只生成特定图表

```bash
# 仅生成延迟折线图（含误差线）
python report_generator.py --line-plots

# 仅生成延迟箱线图
python report_generator.py --box-plots

# 仅分析分块情况
python report_generator.py --chunking-only

# 仅测试某个知识源（如 short_zh）
python report_generator.py --source_filter short_zh
```

### 跳过绘图，只生成摘要

```bash
python report_generator.py --no-plots
```

---

## 📁 项目结构

```
.
├── benchmark/
│   ├── config.py                 # 测试配置（模型、知识源、报告选项）
│   ├── benchmark_embedding_models.py  # 核心评测逻辑
│   └── report_generator.py       # 报告生成器（含多种图表）
├── benchmark_results/            # 自动生成的输出目录
├── requirements.txt              # 依赖列表
└── README.md
```

---

## 📦 依赖说明 (`requirements.txt`)

见下文。

---

## 📜 许可证

MIT License — 免费用于个人及商业项目。

---

## 🙌 致谢

- [Hugging Face Transformers](https://huggingface.co/)
- [Sentence-Transformers](https://www.sbert.net/)
- [Matplotlib](https://matplotlib.org/) & [Seaborn](https://seaborn.pydata.org/)

---

> 💡 **提示**：首次运行会自动下载模型（如未缓存），请确保网络畅通。
>
> 📩 欢迎提交 Issue 或 PR！如果你觉得这个工具对你有帮助，请点个 ⭐️！
```

---

## ✅ `requirements.txt`
```
# 核心机器学习与嵌入模型
torch>=1.13.0
transformers>=4.30.0
sentence-transformers>=2.5.0

# Hugging Face 工具
huggingface-hub>=0.16.0

# 数据处理
numpy>=1.21.0
pandas>=1.3.0
scipy>=1.7.0          # seaborn/matplotlib 可能间接依赖，显式声明更安全

# 可视化
matplotlib>=3.5.0
seaborn>=0.11.0

# 文本与网页解析
beautifulsoup4>=4.10.0

# 命令行与工具
tqdm>=4.60.0          # 虽未显式 import，但 benchmark 通常会用（建议保留）
```

> ✅ 所有依赖均为常见库，兼容 CPU/GPU 环境。无需额外安装 Faiss 或向量数据库——本工具通过直接计算相似度模拟 RAG 检索过程，更轻量、更可控。

---

