# Frunsa-Agent 可视化演示平台

Streamlit 可视化 Demo，展示 RAG 知识检索 + 三层可验证安全机制 + 多引擎 LLM 架构。

## 运行

```bash
cd demo
pip install -r requirements.txt
streamlit run app.py
```

无需 API Key — 默认使用 MockBackend 驱动，所有引擎结果可复现。

## Tab 说明

| Tab | 功能 | 展示要点 |
|-----|------|---------|
| 🧠 引擎 Pipeline | RAG → Planning → Orchestration → Critic 全链路实时运行 | 知识检索、流式渲染、并行分发、Trace Badge |
| 🛡 Guardrail 扫描 | 16 条 AST 规则 + 动态违规注入 | 注入前/后对比、多选注入、架构合规强制 |
| 📋 Trace 审计 | SQLite 审计日志查询 + 时间线 | 全链路追溯、条件格式、甘特图 |
| 📖 架构文档 | 专业架构说明 + 通俗白话解释 | Pipeline 原理、Trace 体系、安全三层 |

## Pipeline 数据流

```
📚 RAG 知识检索 (Phase 0)
    │ 向量检索 (InMemoryVectorBackend) → Rerank (MockScoringBackend)
    │ 内置 12 条 AI Agent / RAG / 安全领域知识片段
    │ Top-3 召回结果注入为 Planning 上下文
    ▼
🧠 Planning Engine
    │ 目标 + 知识上下文 → 任务拆解
    │ 产出 planning.{step_index, reasoning_depth, ...}
    ▼
🔀 Orchestration Engine
    │ 2 分支 fan-out 并行分发 → WAIT_ALL 归并
    │ 产出 orchestration.{dag_node_id, parallel_depth, ...}
    ▼
🛡 Critic Engine
    │ 对 plan_output 评估 → 打分 → 裁决
    │ 产出 critic.{score, verdict}
    ▼
📊 Stats + SQLite Trace 写入
```text

## 文件说明

| 文件 | 职责 |
| ---- | ---- |
| `app.py` | Streamlit 入口 + 4 Tab 页面 + Event Loop 冲突处理 |
| `demo_engine.py` | 引擎 Pipeline 运行器（Async → Sync 桥接） |
| `demo_rag.py` | RAG 知识检索管道（向量检索 + Rerank + 内置知识库） |
| `demo_guardrails.py` | Guardrail 扫描封装 + 7 种违规注入/清理 |
| `demo_trace.py` | Trace 查询 + 时间线数据构建 |
| `demo_trace.db` | SQLite Trace 数据库（跨 Tab 共享） |

## 技术栈

- Streamlit (Web UI)
- 主项目 `engines/` + `core/` + `guardrails/`（仅 import，不修改）
- MockBackend 驱动（无需真实 LLM API Key）
- `core/steps/retriever.py` — 向量检索步骤
- `core/steps/reranker.py` — Rerank 重排序步骤
