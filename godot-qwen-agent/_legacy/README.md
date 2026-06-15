# _legacy/ — V8 旧世界封存

**封存日期:** 2026-06-15
**封存原因:** V9 五层微内核架构重构完成。V8 单体 REPL 的所有子系统在此隔离，等待按需迁移。

## 迁移原则

- **不删除**：所有旧代码原样保留。`git log` 随时可追溯。
- **不引用**：V9 活跃代码 (`mpc_kernel/`, `harness/`, `observer/`, `protocol/`) 不 import 此目录。
- **桥接例外**：`core/`, `components/`, `engines/`, `LLM/` 因 V9.2 `HarnessToolRegistry` 桥接需要，暂留根目录。桥接完成后移入此处。

## 目录导航

| 目录 | 内容 | 迁移状态 |
|------|------|---------|
| `v8_backend/` | Flask Web 后端 + RAG 索引 | 孤立 — V9 无 Web 后端 |
| `v8_demo/` | 演示脚本 | 孤立 |
| `v8_experiment/` | 实验配置 + 基准测试 | 孤立 |
| `v8_benchmark/` | Embedding 模型基准测试 + GGUF 转换 | 孤立 |
| `v8_build/` | C++ CMake 构建产物 | 孤立 |
| `v8_data_loader/` | 数据加载器 + 分块器 | 孤立 |
| `v8_prompt/` | 旧 RAG 提示配置 | 孤立 — V9 提示词在 `harness/plugins/prompts/` |
| `v8_guardrails/` | AST 架构不变量检查器 | 孤立 — V9 守卫待重新实现 |
| `v8_knowledge_base/` | 知识库 (company_wiki, hr_docs, public_docs) | 孤立 |
| `v8_llama/` | llama.cpp 本地推理 | 孤立 |
| `v8_results/` | 实验结果输出 | 孤立 |
| `v8_cache/` | 分块缓存 + cache_loader | 孤立 |
| `v8_data/` | 原始数据 | 孤立 |
| `v8_models/` | 模型缓存 | 孤立 |
| `v8_config/` | 旧配置文件 | 孤立 |
| `v8_scripts/` | 临时脚本 (check_chunks, evaluate, test_*) | 孤立 |
| `v8_databases/` | relational_patterns.db, thresholds.db | 孤立 |
| `v8_user_profiles/` | 用户配置持久化 | 孤立 |
| `_archive/sessions/` | 92 个开发会话转录 | 归档 — 永不删除 |
| `_archive/designs/` | 20 个旧计划书 + 审计报告 | 归档 — 永不删除 |

## 恢复方法

如需恢复某个旧子系统到 V9 活跃区：

```bash
# 例：恢复 benchmark
mv _legacy/v8_benchmark/benchmark ./
mv _legacy/v8_benchmark/benchmark_results ./
mv _legacy/v8_benchmark/benchmark_results.json ./
```

## 根目录保留的桥接依赖

以下目录因 V9.2a `HarnessToolRegistry` 需要 import `COMPONENT_REGISTRY` + `ToolResult`，暂时留在根目录：

```
core/         → 仅需 4 个文件 (registry.py, tool.py, chunking.py, composition.py)
components/   → 工具实现 (write_file, read_file, run_powershell, ...)
engines/      → 引擎接口
LLM/          → LLM 客户端 (DeepSeek)
```

桥接完成后 (V9.2b/V9.3)，这些也将移入此处。
