# V4 计划 — 瘦身清剿 + 引擎点火 + 测试加固

> **不是加功能。是让架构呼吸。**

## 定位

V3 在功能上极大丰富了系统——15 个新特性落地。但也留下了技术债:
- 8 个 0 实现/0 调用的死文件 (~900 行)
- 11 个只有单实现的 Protocol
- run_live.py 与 core/repl.py 近重复
- COMPONENT_REGISTRY.freeze() 从未调用
- REPL 主循环 0 测试

V4 的目标: **删掉不用的，锁死该锁的，补齐缺的测试。**

## Phase 1: 清剿 (The Great Purge) ✅

### 删除的文件
| 文件 | 原因 |
|------|------|
| `core/contracts/kernel_service.py` | 0 实现 |
| `core/contracts/contract_gateway.py` | 0 实现 |
| `core/contracts/tool_format.py` | 0 调用 |
| `core/adapters/tool_formats.py` | 0 调用 |
| `core/adapters/transports/grpc_transport.py` | 抽象存根 |
| `core/adapters/transports/redis_streams_transport.py` | 抽象存根 |
| `run_live.py` | repl.py 的克隆 |

累计删除 ~900 行。

### 注册表冻结
- `COMPONENT_REGISTRY.freeze()` 在 `Container.__init__` 末尾调用
- 预加载 chunker 模块避免懒导入被冻结拦截
- 修复不变量 #23

### 代码合并
- `run_live.py` 删除，`core/repl.py` 成为唯一主循环入口
- `main.py` → `Container` → `Repl.run()` 单一路径

## Phase 2: 引擎点火 ⏸️

Planning / Orchestration / Critic 引擎已实现但未接入主循环。
当前 `cloud_llm.generate()` 被直接调用，绕过三引擎。

V4.1 计划:
- Track A (快): 简单问答 → 直连 LLM
- Track B (慢): 复杂任务 → PlanningEngine(拆解) → OrchestrationEngine(调度) → CriticEngine(反思)
- X-Ray 实时渲染三引擎流转

## Phase 3: 测试加固 ✅

### REPL 测试 (18 个)
- 8 个命令检测 (所有模式: brevity/detail/proactive/stop/warm/normal)
- 3 个提案应用 (成功/constitution/schema)
- 4 个 Prompt 构建 (contract/verbose/sycophancy/anchoring)
- 3 个会话生命周期 (round/trust/pending)

### RAG 集成测试 (11 个)
- 关键词/语义检索
- 护栏拦截 HR 文档
- 白名单放行
- 空搜索、信任门控、关键词拦截、max_results、关键词降级

### 累计
289 单元测试。0 失败。

## 修复的缺陷

- `dynamic_blueprint.py`: 缺失 return (新颖值+指令接受后)
- `dynamic_blueprint.py`: 自引用 import
- `stream_interceptor.py`: JSON 触发器缓冲区偏移
- `stream_interceptor.py`: 转义检测用错索引
- `stream_interceptor.py`: EXECUTING/FALLBACK 状态不同步
- `output_pipeline.py`: 谄媚检测仅查开头
- `output_pipeline.py`: 句号误截缩写/数字
- `tool_contract.py`: min_trust 无钳位
- `threshold_learner.py`: `__del__` 不安全
- `threshold_learner.py`: SQLite check_same_thread
- `dynamic_blueprint.py`: 未知字段绕过 Schema

## 完成状态

| # | 任务 | 状态 |
|---|------|------|
| 1 | 删除 8 个死文件 (~900 行) | ✅ |
| 2 | COMPONENT_REGISTRY.freeze() | ✅ |
| 3 | 合并 run_live.py → core/repl.py | ✅ |
| 4 | 修复 11 个缺陷 | ✅ |
| 5 | 18 个 REPL 测试 | ✅ |
| 6 | 11 个 RAG 集成测试 | ✅ |
| 7 | 默认 contextual_anchoring LOW | ✅ |
| 8 | 引擎点火 (Planning/Orch/Critic) | ⏸️ V4.1 |
