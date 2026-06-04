# 项目架构全景图 — 171 commit 完整版

```
┌──────────────────────────────────────────────────────────────────┐
│                     run_live.py (交互入口)                        │
│               ContractEngine SDK (外部接入)                       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                    第六层 · 关系引擎 (V2.2)                        │
│                                                                  │
│  RelationalPatterns    CBO 跨会话模式库 (Context-Behavior-Outcome)│
│  主动预判 → 用户开口前注入关系提示 → 28 天风化自动衰减               │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                  第五层 · 流式拦截 + 在线学习 (V2 + V2.1)           │
│                                                                  │
│  StreamInterceptor      五态 FSM (TEXT→缓冲→校验→执行→降级)        │
│  EMALearner            指数移动平均学习个人化阈值                    │
│  FeedbackListener      显式反馈(α=0.25) + 隐式反馈(α=0.05)         │
│  SQLiteProfile         WAL 模式, 多用户隔离, JSON 自动迁移           │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                     第四层 · 物理控制 (PLAN7)                      │
│                                                                  │
│  OutputPipeline         句子截断, 格式清洗, 语气过滤, 谄媚惩罚       │
│  OutputGrammar          Blueprint → GBNF 语法规则 (token 级锁)     │
│  ActionPipeline         信任→工具权限, HITL, Backlash 3 次锁死      │
│  AgentRouter            契约严格度 → 本地/云端路由                   │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                    第三层 · 语义感知 (PLAN6)                       │
│                                                                  │
│  SemanticTrustEngine    Embedding 匹配 (80%, 4 维度)              │
│  SignalInterpreter      信号 → 契约提案 (疲劳/挫败/好奇/感激)       │
│  BlueprintSchema        8 个可演化字段 + 枚举值 + 描述               │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│                   第二层 · 活体契约 (PLAN5)                        │
│                                                                  │
│  DynamicBlueprint        增删改查, 3 Loops (风化/反噬/固化)          │
│  ContractEvolutionEngine 信任门控, 回滚, 显式指令击穿               │
│  ContractAuditor         System 2 异步审计 (DeepSeek)              │
│  UserProfile             跨会话记忆, 离群值过滤, 宪法修正案           │
│  ToolContract            6 个工具: READ/WRITE/DESTRUCTIVE 分级     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────┴───────────────────────────────────────┐
│             第一层 · 契约内核 (PLAN1-4, 原始大三層)                 │
│                                                                  │
│  ┌─ contracts/ (24 文件) ──────────────────────────────────┐      │
│  │ Protocols (12):                                          │      │
│  │   ContractGateway, KernelService, EventSink,               │      │
│  │   InteractionRepository, ToolProtocol, ToolFormatAdapter, │      │
│  │   StateAggregator, SeedGenerator, InertiaTracker,         │      │
│  │   SerializationFormat, TransportBackend, PipelineStep     │      │
│  │                                                          │      │
│  │ Data Models (8):                                         │      │
│  │   blueprint_schema, composition, relational_field,        │      │
│  │   trace_keys, user_profile, validation, tool_contract,    │      │
│  │   main_loop_pattern                                      │      │
│  │                                                          │      │
│  │ Implementations (3):                                     │      │
│  │   dynamic_blueprint, identity_chunker, registry           │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌─ adapters/ (39 文件, 含 transports/) ────────────────────┐     │
│  │ 契约引擎 5:                                               │      │
│  │   contract_evolution_engine, contract_auditor,             │      │
│  │   signal_interpreter, semantic_trust, threshold_learner   │      │
│  │                                                          │      │
│  │ 物理控制 6:                                               │      │
│  │   output_pipeline, output_grammar, action_pipeline,        │      │
│  │   agent_router, stream_interceptor, feedback_listener     │      │
│  │                                                          │      │
│  │ 关系引擎 3:                                               │      │
│  │   relational_patterns, relational_evaluator,              │      │
│  │   relational_inertia, relational_state_aggregator         │      │
│  │                                                          │      │
│  │ Pipeline 适配 10:                                         │      │
│  │   chunker_adapter, generator_adapter, vector_store,       │      │
│  │   reranker_adapter, stream_adapter, tool_adapter,         │      │
│  │   factory, composer, mcp_adapter, tool_formats            │      │
│  │                                                          │      │
│  │ 运行时 5:                                                 │      │
│  │   health_evaluator, repair_engine, hitl_gateway,          │      │
│  │   embodied_reflex, renegotiation_watcher                  │      │
│  │                                                          │      │
│  │ 存储/事件 4:                                              │      │
│  │   sqlite_profile, event_sink, interaction_telemetry,      │      │
│  │   persistence                                             │      │
│  │                                                          │      │
│  │ 提示/编排 2:                                              │      │
│  │   prompt_generator, relational_evaluator                  │      │
│  │                                                          │      │
│  │ 传输存根 3:                                               │      │
│  │   transports/grpc, transports/redis, transports/init      │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌─ pipeline/ (6 文件) ────────────────────────────────────┐      │
│  │   engine (协议+引擎), tracing (协议+追踪), resources,      │      │
│  │   streaming, config_loader, __init__                     │      │
│  └──────────────────────────────────────────────────────────┘      │
│                                                                  │
│  ┌─ LLM/ (14 文件) ────────────────────────────────────────┐      │
│  │   base (抽象基类), factory (工厂),                         │      │
│  │   deepseek, openai, claude, qwen, ollama (5 个客户端)     │      │
│  │   local_llm, native_llm, server_llm (3 个本地客户端)      │      │
│  │   template_registry (模板注册), test_llm_install (测试)    │      │
│  └──────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 文件归类总表

### 交互层 (2 文件)
| 文件 | 用途 |
|------|------|
| `run_live.py` | 交互式对话入口 |
| `core/contract_engine.py` | SDK: 5 行接入, `@engine.tool`, `session.execute()` |

---

### 关系引擎层 (3 文件)
| 文件 | 用途 |
|------|------|
| `core/adapters/relational_patterns.py` | CBO 跨会话模式库 |
| `core/adapters/relational_inertia.py` | EMA 平滑 + 贝叶斯不确定性 |
| `core/adapters/relational_state_aggregator.py` | 关系状态聚合 |

---

### 流式拦截 + 在线学习层 (5 文件)
| 文件 | 用途 |
|------|------|
| `core/adapters/stream_interceptor.py` | 五态 FSM, 4KB 溢出, 超时熔断 |
| `core/adapters/threshold_learner.py` | EMA 个人化阈值 + Protocol 接口 |
| `core/adapters/feedback_listener.py` | 显式/隐式反馈采集 |
| `core/adapters/sqlite_profile.py` | WAL 模式用户画像持久化 |
| `core/contracts/user_profile.py` | JSON 版用户画像 (遗留) |

---

### 物理控制层 (4 文件)
| 文件 | 用途 |
|------|------|
| `core/adapters/output_pipeline.py` | 句子截断, 格式清洗, 语气过滤, 谄媚惩罚 |
| `core/adapters/output_grammar.py` | Blueprint → GBNF 语法规则 |
| `core/adapters/action_pipeline.py` | 信任→工具权限, HITL, Backlash |
| `core/adapters/agent_router.py` | 契约严格度 → 本地/云端路由 |

---

### 语义感知层 (4 文件)
| 文件 | 用途 |
|------|------|
| `core/adapters/semantic_trust.py` | Embedding 4 维信任信号 |
| `core/adapters/signal_interpreter.py` | 信号 → 契约提案 |
| `core/adapters/relational_evaluator.py` | 关键词级关系评估 |
| `core/contracts/blueprint_schema.py` | 8 个可演化字段定义 |

---

### 活体契约层 (6 文件)
| 文件 | 用途 |
|------|------|
| `core/contracts/dynamic_blueprint.py` | 活体契约 CRUD, 3 Loops, 安全阀 |
| `core/adapters/contract_evolution_engine.py` | 信任门控, 回滚, 显式指令击穿 |
| `core/adapters/contract_auditor.py` | System 2 异步审计 |
| `core/contracts/tool_contract.py` | 工具元数据: 风险等级, 信任最小阈值 |
| `core/adapters/prompt_generator.py` | 从 Blueprint 渲染提示词 |
| `core/contracts/contract_gateway.py` | 冻结的对外 API 协议 |

---

### 契约内核层 (65 文件)

**contracts/ — 协议 + 数据模型 (24)**
| 子类 | 文件 | 用途 |
|------|------|------|
| 协议 | `kernel_service.py` | 内核服务接口 |
| 协议 | `event_sink.py` | 事件发射/查询 |
| 协议 | `interaction_repository.py` | 交互持久化 |
| 协议 | `tool.py` | 工具协议 |
| 协议 | `tool_format.py` | 工具格式适配 |
| 协议 | `streaming_protocol.py` | 序列化/传输 |
| 协议 | `plan3_ports.py` | PLAN3 端口定义 |
| 数据 | `composition.py` | 蓝图/诊断/事件/违规/健康报告 |
| 数据 | `chunking.py` | Chunk/Block/策略 |
| 数据 | `generation.py` | 生成结果/策略/流项 |
| 数据 | `retrieval.py` | 检索结果/策略 |
| 数据 | `scoring.py` | 评分策略 |
| 数据 | `relational_field.py` | 关系场 (能量/信任/紧迫度) |
| 数据 | `trace_keys.py` | 追踪键契约 |
| 数据 | `validation.py` | 验证错误/结果/函数 |
| 数据 | `blueprint_schema.py` | 蓝图字段定义 |
| 数据 | `tool_contract.py` | 工具契约元数据 |
| 数据 | `user_profile.py` | 用户画像 |
| 数据 | `main_loop_pattern.py` | 主循环模式文档 |
| 实现 | `dynamic_blueprint.py` | 活体蓝图 |
| 实现 | `registry.py` | 组件注册表 |
| 实现 | `identity_chunker.py` | 标识分块器 |
| 协议 | `contract_gateway.py` | 冻结 API |
| 启动 | `__init__.py` | 重导出 |

**adapters/ — 引擎 + 适配器 (39)**
| 子类 | 文件数 | 内容 |
|------|--------|------|
| 契约引擎 | 5 | evolution_engine, auditor, signal_interpreter, semantic_trust, threshold_learner |
| 物理控制 | 6 | output_pipeline, output_grammar, action_pipeline, agent_router, stream_interceptor, feedback_listener |
| 关系引擎 | 4 | relational_patterns, evaluator, inertia, state_aggregator |
| Pipeline 适配 | 10 | chunker, generator, vector_store, reranker, stream, tool, factory, composer, mcp, tool_formats |
| 运行时 | 5 | health_evaluator, repair_engine, hitl_gateway, embodied_reflex, renegotiation_watcher |
| 存储/事件 | 4 | sqlite_profile, event_sink, interaction_telemetry, persistence |
| 提示/感知 | 2 | prompt_generator, relational_evaluator |
| 传输存根 | 3 | grpc, redis, init |

**pipeline/ — 引擎核心 (6)**
| 文件 | 用途 |
|------|------|
| `engine.py` | PipelineStep 协议 + 引擎实现 |
| `tracing.py` | TraceWriter 协议 + 追踪实现 |
| `resources.py` | 资源容器 |
| `streaming.py` | 流式处理 |
| `config_loader.py` | 配置加载 |
| `__init__.py` | 启动 |

**LLM/ — 多后端客户端 (14)**
| 子类 | 文件数 | 内容 |
|------|--------|------|
| 抽象基类 | 1 | base (BaseLLMClient) |
| 云端客户端 | 4 | deepseek, openai, claude, qwen |
| 本地客户端 | 3 | native_llm, local_llm, server_llm |
| 其他 | 5 | ollama, factory, template_registry, test_llm_install, validate_yaml |
| 启动 | 1 | __init__ |

---

### Demo 脚本 (30) — `demo/` 目录
| 用途 | 文件 |
|------|------|
| 契约生命周期 | demo_contract_lifecycle, demo_contract_decay, demo_contract_backlash, demo_contract_meta, demo_contract_safety, demo_contract_stress_test, demo_tool_contract |
| 关系验证 | demo_ab_blind, demo_blind_test, demo_plan2_closed_loop, demo_redemption, demo_judge, demo_embodied |
| 引擎演示 | demo_engine, demo_guardrails, demo_hitl, demo_renegotiate, demo_rag, demo_battle, demo_llm_battle |
| 工具/数据 | demo_data_generator, demo_trace, demo_stress_test, app |
| 配置/数据 | .blind_test_flight_data.json, demo_trace.db, requirements.txt, README.md |

---

### 单元测试 (12 文件) — `tests/unit/`
| 覆盖范围 | 文件 | 测试数 (约) |
|---------|------|------------|
| PLAN1-4 核心 | test_pipeline_composer.py | 855 |
| PLAN5 契约引擎 | test_plan5_contract_engine.py | 32 |
| PLAN5 Backlash/Decay | test_plan5_backlash_decay.py | 26 |
| PLAN6 信号/画像 | test_plan6_signal_userprofile.py | 26 |
| PLAN8 工具边界 | test_plan8_action_pipeline_edges.py | 25 |
| V2 流式 FSM | test_v2_stream_fsm.py | 25 |
| V2 SQLite | test_v2_sqlite_profile.py | 5 |
| V2 FSM+Action 集成 | test_v2_fsm_action_integration.py | 8 |
| V2.1 在线学习 | test_v2_1_online_learning.py | 20 |
| V2.2 关系模式 | test_v2_2_relational_patterns.py | 13 |
| SDK 集成 | test_contract_engine_sdk.py | 6 |
| 启动 | __init__.py | 0 |

---

### 架构文档 (14 文件)
| 文件 | 内容 |
|------|------|
| `PLAN.md` ~ `PLAN7.md` (7 文件) | 各阶段架构规划 |
| `V2PLAN.md` | V2 全中文规划 |
| `AUDIT.md` | 第一次全栈审计 |
| `AUDIT_V2.md` | V2 全面审计 |
| `ARCHITECTURE_MAP.md` | 本文档 |
| `README.md` | 项目首页 |
| `CLAUDE.md` | AI 协作协议 + 45 不变量 |

---

## 关键数字

```
总文件数:        ~200 (含 demo/测试/文档)
Python 源文件:    83 (核心四层)
Protocol/接口:    22
实现文件:         46
Demo 脚本:        30
单元测试:         12 文件, ~1043 断言 (188 新 + 855 存续)
PLAN 文档:        7
推理链:           34
本地模型:         4
Commit:           171 (会话内 113, 存续 58)
```
