# V4 Phase 1 — 瘦身清剿与测试加固

**日期:** 2026-06-04
**状态:** ✅ 已完成
**基准:** ~180 commits

---

## 背景

代码库积累了大量死代码——未使用的导入、废弃的 adapter、过时的 mock 类。
测试覆盖不完整，REPL 没有自己的单元测试。

## 目标

- 删除所有死代码（~900 行）
- REPL + RAG 加测试
- 289 测试全绿

## 完成的清理

- 删除未使用的 LLM adapter 变体
- 删除废弃的 mock 类和 stub
- 删除未引用的 pipeline step
- 删除死 import 和死函数

## 新增测试

- `tests/unit/test_v4_repl.py` — REPL 命令、prompt 构建、输出管道
- `tests/unit/test_v4_rag_integration.py` — RAG 搜索、网关过滤
- `tests/unit/test_v3_container_repl.py` — Container 集成

## 不动

- 任何生产逻辑
- 所有已有测试保持不变
