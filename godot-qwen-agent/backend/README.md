# 🧠 Godot-Qwen 智能助手

> 基于 **RAG（检索增强生成）** 的 Godot 游戏开发 AI 助手，专为解决实际开发问题而生。

## 🌟 核心功能

- ✅ **精准问答**：基于 Godot 官方文档与项目知识库回答问题
- ✅ **上下文感知**：支持多轮对话，理解前后文
- ✅ **代码修复建议**：可分析用户提供的 GDScript 片段
- ✅ **本地部署**：无需联网（除调用 Qwen API 外），保护隐私

## 🏗️ 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | FastAPI + Uvicorn |
| AI 模型 | Qwen-Max（通过 DashScope API） |
| RAG 引擎 | sentence-transformers + FAISS |
| 前端 | Godot 4.5 HTTPRequest |

## 🚀 快速开始

### 1. 准备环境
- 安装 [Anaconda](https://www.anaconda.com/)
- 创建 Conda 环境：
  ```bash
  conda create -n qwen-helper python=3.10
  ```

### 2. 安装依赖
双击运行：
```
H:\agent项目\install_deps.bat
```
或手动执行：
```bash
cd godot-qwen-agent/backend
pip install -r requirements.txt
```

### 3. 构建知识库（RAG）
```bash
python build_rag_index.py
```

### 4. 启动后端服务
```bash
python app.py
```
服务地址：`http://localhost:8000`

### 5. 在 Godot 中测试
使用 `HTTPRequest` 向 `/ask` 发送 JSON 请求：
```gdscript
var body = JSON.stringify({"prompt": "如何检测空格键？"})
```

## 📂 项目结构

```
godot-qwen-agent/
├── backend/
│   ├── app.py              # FastAPI 后端
│   ├── build_rag_index.py  # 构建 RAG 索引
│   └── requirements.txt     # 依赖列表
├── addons/                 # Godot 插件（如有）
└── README.md               # 本文件
```

## 🏆 比赛亮点

- **创新性（20%）**：RAG 知识库让 AI 回答基于真实 Godot 文档
- **实用价值（20%）**：解决开发者真实痛点（如节点报错、输入检测）
- **鲁棒性（15%）**：错误处理 + 重试机制
- **人机交互（15%）**：流畅对话 + 代码高亮（前端实现）

---
Made with ❤️ for 深理工 Agent 比赛

---

## ⚙️ RAG 模块参数配置说明

下面是一份 **项目定制的参数说明表**，采用 **Markdown 格式**
以下参数定义在 `backend/build_rag_index.py` 顶部，用于控制知识库构建与检索行为：

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `KNOWLEDGE_FILE` | `"godot_qwen_knowledge.txt"` | 知识库源文件路径（UTF-8 编码），每行一条独立知识 |
| `COMMENT_PREFIX` | `"#"` | 注释标识符；以该字符开头的行将被自动忽略（便于写说明） |
| `EMBEDDING_MODEL` | `"paraphrase-multilingual-MiniLM-L12-v2"` | 用于生成文本向量的预训练模型（支持中文，约 400MB） |
| `INDEX_FILE` | `"rag_index.faiss"` | 构建后的向量索引文件（FAISS 格式，二进制） |
| `CHUNKS_FILE` | `"rag_chunks.pkl"` | 原始文本块缓存文件（Python pickle 格式） |
| `DEFAULT_TOP_K` | `3` | 检索时默认返回最相关的前 N 条知识（可在调用时覆盖） |

---

### 📝 使用示例

#### 1. 在 `godot_qwen_knowledge.txt` 中写知识（支持注释）：
```txt
# Godot 输入系统常见问题
如何检测空格键按下？
在 Godot 4 中，使用 Input.is_action_pressed("ui_accept")。

# 节点相关
节点报错“Node not found”怎么办？
使用 get_node_or_null() 避免崩溃。
```

> ✅ 所有以 `#` 开头的行会被自动跳过，不会进入向量库！

#### 2. 调整检索数量（在 `app.py` 中）：
```python
# 获取最相关的 5 条知识（而非默认 3 条）
relevant = retrieve_relevant_chunks(user_prompt, top_k=5)
```

#### 3. 更换嵌入模型（如需更强性能）：
```python
EMBEDDING_MODEL = "BAAI/bge-m3"  # 更强的多语言模型（需更多内存）
```

> ⚠️ 注意：更换模型后需**重新运行 `build_rag_index.py`** 重建索引！

---

### 💡 小贴士
- 首次运行会自动从 [HF 镜像站](https://hf-mirror.com) 下载模型，请保持网络畅通 🌐
- 所有输出文件（`.faiss`, `.pkl`）会保存在 `backend/` 目录下，**不要手动修改**
- 若更新了 `godot_qwen_knowledge.txt`，**务必重新构建索引**，否则 RAG 不会生效！

---
