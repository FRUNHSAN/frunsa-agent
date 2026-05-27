# Frunsa-Agent 安全演示平台

Streamlit 可视化 Demo，展示三层可验证安全机制 + 多引擎 LLM 架构。

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
| 🧠 引擎 Pipeline | Planning → Orchestration → Critic 全链路实时运行 | 流式渲染、并行分发、Trace Badge |
| 🛡 Guardrail 扫描 | 16 条 AST 规则 + 动态违规注入 | 架构合规强制、违规拦截 |
| 📋 Trace 审计 | SQLite 审计日志查询 + 时间线 | 全链路追溯、条件格式、甘特图 |

## 技术栈

- Streamlit (Web UI)
- 主项目 engines/ + core/ + guardrails/ (仅 import，不修改)
- MockBackend 驱动 (无需真实 LLM API Key)
