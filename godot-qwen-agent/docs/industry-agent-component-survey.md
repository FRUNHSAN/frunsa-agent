# 行业 Agent 组件全景调研

**动机**：为具身智能微内核设计一个"完全释放内核能力、甚至倒逼内核迭代"的外围框架。本报告从主流开源项目出发，梳理 Agent 生态中所有已知"套件"的位置、环节和层级，然后映射到你的五层架构上。

**调研范围**：LangChain/LangGraph、CrewAI、AutoGen/AG2、MetaGPT、Dify、LlamaIndex、Semantic Kernel、DSPy、smolagents、Google ADK、OpenAI Agents SDK、Letta/MemGPT、Mastra 等 13 个有行业影响力的开源项目。

**最后更新**：2026-07-04

---

## 一、主流框架速览（按 GitHub Stars 排序）

### 1.1 LangChain + LangGraph — 生态最大、组件最全

| 维度 | LangChain | LangGraph |
|------|-----------|-----------|
| **Stars** | ~103k | ~32k |
| **一句话** | LLM 应用的"瑞士军刀"——什么都有，但耦合重 | 有状态的 Agent 状态机——checkpoint、time-travel、human-in-the-loop |
| **定位** | 框架（提供所有积木） | 编排器（定义积木怎么组合） |
| **核心组件** | Chains, Agents, Tools, Memory, RAG, Callbacks | StateGraph, Nodes, Edges, Checkpointer, Conditional Routing |
| **强项** | 生态最大，和几乎所有工具/模型集成 | 状态持久化（checkpoint）+ 时间旅行调试，生产级可靠性 |

**一句话讲清**：LangChain 是全行业最大的 Agent 组件超市，但也因此耦合最重——你的内核不可能也不需要和它对接。

---

### 1.2 CrewAI — 角色扮演最直观的多 Agent 框架

| 维度 | 详情 |
|------|------|
| **Stars** | ~51k |
| **一句话** | 给每个 Agent 分配"角色-目标-背景故事"，像组建一支项目团队 |
| **核心组件** | Agent（role/goal/backstory）、Task、Crew、Process（sequential/hierarchical）|
| **强项** | 上手最快，角色抽象直击人类直觉 |
| **弱项** | Token 消耗高（比 LangGraph 多 ~3×），容易陷入"自我审查循环" |

**一句话讲清**：CrewAI 把多 Agent 协作变成"角色分配+任务委托"——但你的内核已经用 8 门路由做了更好的决策，不需要"角色"这个抽象。

---

### 1.3 AutoGen (Microsoft) → 已进入维护模式

| 维度 | 详情 |
|------|------|
| **Stars** | ~58k |
| **一句话** | 多 Agent 对话式协作的先驱——但已被 Microsoft 官方放弃，后继者是 Microsoft Agent Framework (MAF) |
| **核心组件** | ConversableAgent, AssistantAgent, UserProxyAgent, GroupChat, Magentic-One |
| **状态** | v0.7.5 (2025-09) 后不再有新功能。社区 fork **AG2** (`ag2ai/ag2`) 继续 |
| **历史意义** | 定义了"Agent 之间通过对话协作"的模式 |

**一句话讲清**：AutoGen 证明了多 Agent 对话协作可行——但已经被官方弃坑，不要在新项目上用它。

---

### 1.4 Dify — 低代码 Agent 工作台

| 维度 | 详情 |
|------|------|
| **Stars** | ~82k |
| **一句话** | Agent 的"低代码拖拽平台"——可视化编排 workflow + RAG + Agent + Tool |
| **核心组件** | 可视化 Workflow 编辑器、RAG Pipeline、Agent 策略、Tool 插件、对话日志、数据集标注 |
| **强项** | 非开发者也能用，开箱即用的 RAG + Agent，企业功能完整 |

**一句话讲清**：Dify 是给非程序员用的 Agent 装配线——它验证了"可视化编排"是刚需，但你和它的交集在于它证明了 workflow 编排 + RAG 管道是标配。

---

### 1.5 LlamaIndex — 数据 Agent 框架

| 维度 | 详情 |
|------|------|
| **Stars** | ~41k |
| **一句话** | 把私有数据（文档/数据库/API）变成 LLM 能用的"知识层" |
| **核心组件** | Data Connectors, Ingestion Pipeline, Indexes, Query Engines, Chat Engines, Agents |
| **强项** | 数据接入能力最强（100+ 连接器），RAG 管道成熟度最高 |

**一句话讲清**：LlamaIndex 专注"数据→知识"的翻译——你的 Observer 层在做类似的事（异构数据→统一 StateVector），但 LlamaIndex 是 LLM 侧的数据翻译，你是数学侧的信号翻译。

---

### 1.6 Semantic Kernel (Microsoft) — 企业级 AI 编排

| 维度 | 详情 |
|------|------|
| **Stars** | ~24k |
| **一句话** | 微软的企业 AI SDK——把 LLM 能力以"插件"形式注入企业应用 |
| **核心组件** | Plugins, Planners, Memory, Connectors, Filters |
| **强项** | C# + Python 双语言，Azure 深度集成，企业合规就绪 |

**一句话讲清**：Semantic Kernel 是企业 IT 视角的 Agent SDK——它的 Plugin/Planner/Memory 三层分离是最经典的分层参考。

---

### 1.7 DSPy — LLM 编程框架（非 Agent 框架）

| 维度 | 详情 |
|------|------|
| **Stars** | ~24k |
| **一句话** | 用"声明式签名 + 自动优化器"替代手写 prompt——把 prompt engineering 变成编译器优化 |
| **核心组件** | Signatures, Modules, Optimizers, Assertions |
| **强项** | 自动 prompt 优化，替代手工调参 |

**一句话讲清**：DSPy 的核心思想——"声明你想要的，让优化器去找最好的 prompt"——和你的三策略槽位（Boundary/Cost/Value Policy）是同一个哲学：让优化器替代手工规则。

---

### 1.8 smolagents (HuggingFace) — 代码 Agent

| 维度 | 详情 |
|------|------|
| **Stars** | ~18k |
| **一句话** | HuggingFace 的轻量 Agent 框架——Agent 通过写代码来调用工具，而不是生成 JSON |
| **核心组件** | CodeAgent, Toolbox, ManagedAgent, MultiStepAgent |
| **强项** | 代码即行动（比 JSON function call 更安全、更可审计） |

**一句话讲清**：smolagents 的"代码即行动"思路——Agent 输出可执行的 Python 代码而非 JSON——和你的纯函数内核是同一安全级别：可审计、可重放。

---

### 1.9 Letta (原 MemGPT) — 记忆优先 Agent

| 维度 | 详情 |
|------|------|
| **Stars** | ~15k |
| **一句话** | Agent 自带"自编辑持久记忆"——操作系统式的虚拟上下文管理 |
| **核心组件** | Memory Blocks, Self-Editing Memory, Archival Memory, Recall Memory |
| **强项** | 解决 context window 天花板——Agent 自主决定什么存入长期记忆 |

**一句话讲清**：Letta 把 Agent 记忆做成 OS 式管理——和你的 ODE 积分器驱动的情感记忆是互补的：它管"事实"，你管"关系"。

---

### 1.10 Google ADK + A2A 协议

| 维度 | 详情 |
|------|------|
| **Stars** | ~20k (ADK) |
| **一句话** | Google 的生产级 Agent 开发套件，自带 Agent-to-Agent 协议 |
| **核心组件** | ADK (Agent Development Kit), A2A (Agent-to-Agent protocol), built-in evals, streaming |
| **强项** | 生产和评估工具成熟，A2A 协议定义了跨框架 Agent 通信标准 |

**一句话讲清**：Google A2A 定义了"Agent 之间怎么说话"的行业标准——你的 Event Bus 如果要对标，A2A 是最值得参考的协议。

---

### 1.11 其他值得关注的

| 项目 | Stars | 一句话 |
|------|-------|--------|
| **Mastra** | ~10k | TypeScript 原生的 Agent 框架，自带 workflow + memory + evals |
| **OpenAI Agents SDK** | ~25k | OpenAI 官方的轻量 Agent SDK，最简的 Agent loop + handoff |
| **PydanticAI** | ~8k | Pydantic 团队的 Agent 框架，类型安全是核心卖点 |
| **Agno** | ~18k | 全栈 Agent 框架，内置 5 级 agentic 复杂度 |

---

## 二、Agent 组件全景图：层级 × 组件 × 一句话

以下按照一个完整 Agent 系统的**逻辑分层**（非代码分层）组织。每一层的每个组件都给出：**一句话讲清 + 主流实现项目 + 在你的微内核中的对应关系**。

### 架构全景图

```
┌─────────────────────────────────────────────────────────────┐
│                     L5 人机交互层                            │
│  Chat UI · CLI · API Gateway · Streaming · 多模态输入        │
├─────────────────────────────────────────────────────────────┤
│                     L4 可观测 & 评估层                       │
│  Tracing · Logging · Evaluation · Dashboard · Alerting       │
├─────────────────────────────────────────────────────────────┤
│                     L3 编排 & 协作层                         │
│  Planning · Orchestration · Multi-Agent · Human-in-Loop      │
│  Workflow Engine · State Machine · Checkpoint/Resume         │
├─────────────────────────────────────────────────────────────┤
│                     L2 认知 & 决策层                         │
│  Reasoning · Reflection · Memory · Tool Use · Guardrails     │
│  ★ 你的 MPC 微内核在这里（内核层 L2）★                       │
├─────────────────────────────────────────────────────────────┤
│                     L1 基础设施层                            │
│  Model Gateway · Sandbox · Persistence · Message Bus         │
│  Tool Registry · Plugin System · Security                    │
└─────────────────────────────────────────────────────────────┘
```

---

### L1 — 基础设施层（地基）

#### 1.1 Model Gateway（模型网关）

**一句话**：统一对多 LLM 提供商（OpenAI/Claude/Gemini/本地模型）的调用接口，处理 rate limit、重试、fallback。

| 主流实现 | 特点 |
|---------|------|
| LangChain `BaseChatModel` | 最全的模型集成（50+） |
| LiteLLM | 轻量模型网关，OpenAI 兼容格式 |
| Semantic Kernel `Connectors` | 企业级模型接入 |

**你的微内核对应**：`LLM Bus`（AHB 级双向总线）——已经做了协议翻译 + MAC 重试，但缺少多模型 fallback 和 rate limit 感知。**LLM Bus 应该进化成一个完整的 Model Gateway Protocol。**

---

#### 1.2 Sandbox（沙箱）

**一句话**：Agent 生成的代码/命令在隔离环境中执行，防止恶意代码破坏宿主机。

| 主流实现 | 特点 |
|---------|------|
| Docker / gVisor | 容器级隔离 |
| E2B / CodeInterpreter | 云端沙箱 |
| smolagents `LocalPythonExecutor` | 本地 Python 沙箱 |

**你的微内核对应**：`Tool Bus` 的 Semaphore(5) 限流 + 超时是第一步——但缺少真正的沙箱隔离。**V9.2c 的 sandbox defense 应该对标 E2B 的执行隔离级别。**

---

#### 1.3 Persistence / State Store（持久化 & 状态存储）

**一句话**：保存 Agent 的执行状态以便恢复——checkpoint（断点续跑）、state snapshot（审计）、conversation history（对话回溯）。

| 主流实现 | 特点 |
|---------|------|
| LangGraph `Checkpointer` | 每节点自动 checkpoint，支持时间旅行 |
| CrewAI `Crew Memory` | v1.14 新增，部分持久化 |
| Letta `Memory Blocks` | OS 式持久化内存管理 |

**你的微内核对应**：`DecisionTrace`（铁律 #4 形式化可重放）——已经做了每次 kernel_step 的完整快照，但缺少按时间轴的恢复机制。**你的 DecisionTrace 是 checkpoint 的最小完备单元，只需要包一层恢复逻辑。**

---

#### 1.4 Message Bus / Event System（消息总线）

**一句话**：Agent 间通信基础设施——消息路由、事件订阅、异步通知。

| 主流实现 | 特点 |
|---------|------|
| Google A2A Protocol | 跨框架 Agent-to-Agent 通信标准 |
| AutoGen `GroupChat` | 多 Agent 对话总线 |
| MCP (Model Context Protocol) | Anthropic 的 Agent-Tool 通信协议 |

**你的微内核对应**：`Event Bus`（NVIC 级中断）——已经做了中断脉冲 + Lamport 时钟 + 优先级仲裁。**你的四条总线架构比行业所有框架都细粒度——你缺的不是设计，是实现和推广。**

---

#### 1.5 Plugin / Tool Registry（插件 & 工具注册表）

**一句话**：工具的发现-注册-调用机制——新工具即插即用，不修改核心代码。

| 主流实现 | 特点 |
|---------|------|
| LangChain `@tool` decorator | 装饰器注册 |
| Semantic Kernel `Plugins` | 企业级插件体系 |
| MCP Server | 独立进程的 Tool 服务 |
| smolagents `Toolbox` | 轻量工具箱 |

**你的微内核对应**：USB 模型 + `COMPONENT_REGISTRY`（不变式 #17-20）——**你的插件体系已经是行业最高标准（启动后冻结 + 禁显式 import + 禁 if/switch 分发）。保持它。**

---

### L2 — 认知 & 决策层（大脑 + 小脑）

#### 2.1 Memory（记忆系统）⭐ 行业最热战场

##### 2.1a Short-term / Working Memory（短期/工作记忆）

**一句话**：当前任务执行期间的上下文——一次对话中的最近几轮、当前的中间结果。

| 主流实现 | 特点 |
|---------|------|
| Context Window | 最原始的工作记忆 |
| LangGraph `AgentState` | TypedDict 承载当前状态 |
| Letta `Working Context` | OS 式分页管理 |

**你的微内核对应**：`StateVector` 的 INSTANT 维度（context_depth, cognitive_load）——**你用一种数学上更干净的方式（16 维冻结向量）替代了所有框架的"对话 buffer"方案。**

---

##### 2.1b Long-term / Persistent Memory（长期/持久记忆）

**一句话**：跨会话持久化的记忆——用户偏好、历史决策、学到的经验。

| 主流实现 | 特点 |
|---------|------|
| Mem0 | 自动从对话中提取并演化用户记忆 |
| Letta `Archival Memory` | 无限容量的事实存储 |
| LangChain `VectorStoreRetriever` | 向量检索作为长期记忆 |
| CrewAI `LongTermMemory` | 跨 Crew 执行持久化 |

**你的微内核对应**：**目前缺失。** `StateVector` 的 ODE 维度（trust, e_t, tool_success_rate）是关系记忆，不是事实记忆。你需要一个外部的"事实记忆层"来补充——但不要学 Mem0 那种"黑盒提取"模式。

---

##### 2.1c Episodic Memory（情节记忆）

**一句话**：完整交互轨迹的回放——"上次遇到类似情况时发生了什么"。

| 主流实现 | 特点 |
|---------|------|
| Letta `Recall Memory` | Agent 自主决定回忆什么 |
| LangSmith `Trace` | 完整轨迹回放 |
| DSPy `Optimizers` | 从历史轨迹中学习最优 prompt |

**你的微内核对应**：`DecisionTrace` + `Telemetry Bus`（CoreSight 级单向出）——**(s, a, r) 三元组 → JSONL 已经覆盖了情节记忆的基础设施，缺的是"检索相似历史"的查询层。**

---

##### 2.1d Relational / Emotional Memory（关系/情感记忆）

**一句话**：跟踪用户-Agent 之间的信任度、疲劳度、关系阶段——不只是"用户说了什么"，而是"我们的关系现在怎样"。

| 主流实现 | 特点 |
|---------|------|
| **无。** | 这是行业空白 |

**你的微内核对应**：`trust` + `e_t` + 非对称 EMA + PLAN2 黄金参数 + 7 个数学控制面——**这是你独有的领域，行业没有任何对标。你的内核不是在"管理对话"，而是在"管理关系"。**

---

#### 2.2 Planning & Task Decomposition（规划 & 任务分解）

**一句话**：把复杂目标拆成可执行步骤——"先查天气，再定路线，最后订酒店"。

| 主流实现 | 特点 |
|---------|------|
| ReAct | 推理-行动交错（行业基线） |
| Plan-Execute-Reflect | 规划→执行→反思→重规划 |
| Tree of Thoughts | 搜索多条路径，选最优 |
| Reflexion | 失败后自我批评 + 修正 |
| LangGraph `Send` API | 动态并行任务分发 |

**你的微内核对应**：**内核不负责 Planning。** 这是设计决策（铁律 #62：LLM 是证人不是法官）。Planning 应该在 Mainboard 层（`Track C` 管道）或更高层实现——内核只接收翻译好的 16 维信号并做路由决策。

---

#### 2.3 Tool Use / Function Calling（工具调用）

**一句话**：Agent 调用外部能力——搜索、计算、读文件、发邮件。

| 主流实现 | 特点 |
|---------|------|
| OpenAI Function Calling | JSON Schema 定义工具 |
| Anthropic Tool Use | 结构化 Tool 输出 |
| MCP (Model Context Protocol) | 跨框架工具通信标准 |
| smolagents `CodeAgent` | Agent 写代码来调工具（不是 JSON） |

**你的微内核对应**：`Tool Bus`（APB 级）——**Semaphore(5) + 超时 + 规则引擎/LM 兜底分离（V9.2b）。已经比大多数框架的"裸调 tool"更安全。**

---

#### 2.4 Reflection / Self-Critique（反思 & 自我批评）

**一句话**：Agent 检查自己的输出——"我是不是说错了？要不要重来？"

| 主流实现 | 特点 |
|---------|------|
| Reflexion / Reflexion++ | 批评→修正→重试 |
| DSPy `Assertions` | 声明式约束，自动重试直到满足 |
| LangGraph `Command(resume=...)` | 人工介入后恢复执行 |

**你的微内核对应**：`e(t)`（error state）+ Streak tracking + 三层降级矩阵——**你用一种数学化的方式（连续 error 信号 × Lipschitz 有界）实现了比 Reflexion 更优雅的错误处理。但缺的是"重规划并再次尝试"的闭环。**

---

#### 2.5 Reasoning Engine（推理引擎）

**一句话**：驱动 Agent "思考"的核心循环——在当前状态下选择下一步做什么。

| 主流实现 | 特点 |
|---------|------|
| ReAct Loop | 标准推理-行动循环 |
| Chain-of-Thought | 逐步推理 |
| Tree/Graph Search | 多路径探索 |
| DSPy `Module` + `Optimizer` | 声明式推理模块 |

**你的微内核对应**：**9 步纯函数决策链（Step 0-8）——这就是你的推理引擎。** 区别在于：行业用 LLM 做推理（ReAct），你用 ODE + Schmitt 触发器做推理。你的方案严格更快（微秒级 vs 秒级），但只覆盖被 16 维编码的决策空间。

---

#### 2.6 Guardrails / Safety（护栏 & 安全）

**一句话**：防止 Agent 做有害/越权的事情——内容过滤、权限控制、合规检查。

| 主流实现 | 特点 |
|---------|------|
| Guardrails AI | 结构化输出验证 |
| NVIDIA NeMo Guardrails | 对话护栏 |
| LangChain `Guardrails` | 策略即代码 |

**你的微内核对应**：`Safety Arbiter`（Lipschitz 三级降级 + Hoyer 稀疏度判别 + NaN 入口/出口双重守卫）——**你的安全仲裁器的数学严谨性远超行业方案。行业在搞"内容过滤"，你在搞"控制论安全"。**

---

### L3 — 编排 & 协作层

#### 3.1 Orchestration（编排器）

**一句话**：管理"什么 Agent、什么时候、做什么、以什么顺序"——Agent 系统的指挥中心。

| 主流实现 | 特点 |
|---------|------|
| LangGraph `StateGraph` | 图状态机 |
| CrewAI `Process` | Sequential / Hierarchical |
| Semantic Kernel `Planner` | 自动生成执行计划 |
| Dify `Workflow` | 可视化编排 |

**你的微内核对应**：`Mainboard/orchestrate/harness.py`——Harness 就是你的编排器。**但 Harness 目前只是一个薄壳，它应该进化成一个完整的 Agent 编排引擎，把 Track C 管道、多 Agent 协作、HITL 都纳入。**

---

#### 3.2 Multi-Agent Coordination（多 Agent 协作）

**一句话**：多个 Agent 分工协作——一个研究、一个写代码、一个审查。

| 主要模式 | 说明 |
|---------|------|
| **Orchestrator-Worker** | 中央调度员分配任务给专职 Worker |
| **Peer-to-Peer Debate** | Agent 之间直接对话协商 |
| **Blackboard (Shared Memory)** | Agent 通过共享状态间接通信 |
| **Hierarchical MAS** | 多层 Tree 结构 |
| **Swarms** | 大量简单 Agent 涌现复杂行为 |

**你的微内核对应**：**目前没有多 Agent。** 但 8 门路由是天然的 Agent 选择器——每个门触发后可以选择把任务发给不同的"执行 Agent"。**多 Agent 在你的架构中不是"创建多个 Agent 对象"，而是"路由到不同的执行槽位"。**

---

#### 3.3 Human-in-the-Loop（人机协同）

**一句话**：关键决策前暂停，等人类确认后再继续。

| 主流实现 | 特点 |
|---------|------|
| LangGraph `interrupt()` + `Command(resume=...)` | 中断-批准-恢复 |
| AutoGen `UserProxyAgent` | 人工代理模式 |
| Dify `Human Approval Node` | 可视化审批节点 |

**你的微内核对应**：契约降级（`contract_violation`）+ 之前 PHASE 24/25 的 HumanTicket（阻塞）/RenegotiationProposal（非阻塞）——**你的 HITL 设计比任何框架都细粒度：区分了"必须等人"（HumanTicket）和"可以继续跑，等人异步审批"（RenegotiationProposal）。**

---

#### 3.4 Workflow Engine（工作流引擎）

**一句话**：定义和执行多步骤管道——"第一步检索、第二步生成、第三步审查、第四步输出"。

| 主流实现 | 特点 |
|---------|------|
| LangGraph `StateGraph` + `Send` | 图 + 动态并行 |
| Dify `Workflow Editor` | 可视化 |
| Temporal / Prefect | 通用工作流引擎用于 Agent |

**你的微内核对应**：**Track C 管道（Planning → Tool → Critic）+ Harness.step() 主循环。** 缺少的是动态 DAG——当前管道是固定序列，不支持"根据中间结果分叉"或"并行多个子任务"。

---

### L4 — 可观测 & 评估层

#### 4.1 Tracing（全链路追踪）

**一句话**：记录 Agent 执行过程中的每一个步骤——哪个 LLM 调用、哪个 tool 执行、耗时多少、token 消耗。

| 主流实现 | 特点 |
|---------|------|
| LangSmith | LangChain 生态的 tracing 平台 |
| OpenTelemetry GenAI | 行业标准的 Agent 追踪语义约定 |
| Arize Phoenix | 开源 LLM 可观测平台 |

**你的微内核对应**：`Telemetry Bus`（CoreSight 级）+ `DecisionTrace`——**你已经有行业最完整的数据记录基础设施。(s,a,r) 三元组 + 每个 kernel_step 的完整快照——缺的是可视化和分析平台。**

---

#### 4.2 Evaluation & Benchmarking（评估 & 基准测试）

**一句话**：量化评估 Agent 表现——任务成功率、准确率、幻觉率。

| 主流实现 | 特点 |
|---------|------|
| LangSmith `Datasets + Experiments` | Golden dataset 回归测试 |
| Google ADK `Eval` | 内置评估框架 |
| DeepEval / RAGAS | LLM 评估专用工具 |

**你的微内核对应**：**目前主要靠 673 个测试。** 需要补充：真实场景的 golden dataset、LLM-as-Judge 评估管道、和对标基线的 benchmark。

---

#### 4.3 Monitoring & Alerting（监控 & 告警）

**一句话**：实时监控 Agent 健康状况——延迟、错误率、异常行为自动告警。

| 主流实现 | 特点 |
|---------|------|
| LangSmith `Monitor` | 在线监控 + 告警 |
| Datadog / Grafana | 通用监控用于 Agent |

**你的微内核对应**：`DependencyHealth`（不变式 #9）+ `DependencyCallTrace`（不变式 #10）+ `health_probe()`——**你的可观测性基础是行业顶级的（trace key 比代码先设计），缺的是实时仪表盘和自动告警。**

---

### L5 — 人机交互层

#### 5.1 Chat / CLI / API Interface（交互界面）

**一句话**：用户和 Agent 对话的入口——聊天窗、命令行、REST API、WebSocket。

| 主流实现 | 特点 |
|---------|------|
| Dify `Web App` | 一键部署聊天应用 |
| LangServe | LangChain 的 API 部署 |
| Streamlit / Gradio | 快速原型 UI |

**你的微内核对应**：`v9_cli.py`（CLI 入口）+ L5 UI 层（架构预留）——**CLI 够用但不够。你需要一个最小的 Web/API 层来让其他系统调用内核。**

---

#### 5.2 Streaming（流式输出）

**一句话**：Agent 的回复逐字输出——不是"等 5 秒然后返回完整结果"。

| 主流实现 | 特点 |
|---------|------|
| LangChain `StreamingStdOutCallbackHandler` | 回调式流式 |
| Vercel AI SDK | 前端流式 UI |
| Google ADK `Streaming` | 原生流式支持 |

**你的微内核对应**：**内核不输出自然语言，所以不需要流式。** 但 Observed 的输出（翻译后的自然语言）需要流式——这应该在 Observer 或 Actuator 层实现。

---

## 三、你的微内核 vs 行业框架：差异地图

这一节用一张表回答"你的内核已经覆盖了什么，框架层还需要补什么"。

### 3.1 你比行业做得更好的部分

| 领域 | 行业方案 | 你的方案 | 优势 |
|------|---------|---------|------|
| **状态管理** | Context Window / 对话 buffer | 16 维 StateVector（冻结、ODE 积分） | 数学严谨，帧率无关，可重放 |
| **决策路由** | if/else 分支 / LLM 判断 | 8 门 Schmitt 触发器 + 优先级仲裁 | 零延迟，确定性，可审计 |
| **安全** | 内容过滤 / guardrail 关键词 | Lipschitz 梯度有界 + Hoyer 稀疏度 | 控制论级别安全，非启发式 |
| **工具注册** | `@tool` 装饰器 | USB 模型 + 启动后冻结 Registry | 防止运行时注册混乱 |
| **可观测性** | 事后补 trace | 观测先行：trace key 比代码先设计 | 不存在"忘记加 trace"的盲区 |
| **关系记忆** | **不存在** | trust + e_t + 非对称 EMA + PLAN2 参数 | 行业无人区 |
| **版本协议** | 无 | Kernel Version Protocol（SemVer + 协商） | 适配器-内核版本兼容保证 |
| **插件隔离** | `pip install` | Plugin SDK + 槽位 + Lazy Load | 插件不会污染内核 |

### 3.2 行业有、你需要补的部分

| 领域 | 行业成熟方案 | 你的缺口 | 优先级 |
|------|------------|---------|--------|
| **完整 Agent 编排引擎** | LangGraph StateGraph / Dify Workflow | Harness 只是一个薄壳，缺少动态 DAG、条件分叉、并行子任务 | ⭐⭐⭐ 最高 |
| **长期事实记忆** | Mem0 / Letta / VectorStore | 内核只管关系记忆（trust/e_t），不管"用户上周说过什么" | ⭐⭐⭐ 最高 |
| **多 Agent 协作** | CrewAI / AutoGen GroupChat | 8 门路由可以选 Agent，但没有多 Agent 通信协议和任务分配 | ⭐⭐ 高 |
| **HITL 完整实现** | LangGraph interrupt/resume | 设计完整（HumanTicket/Proposal 双轨），但代码未完整实现 | ⭐⭐ 高 |
| **情节记忆查询** | Letta Recall / LangSmith Trace | DecisionTrace 存了，但没有"检索相似历史"的查询能力 | ⭐⭐ 高 |
| **评估体系** | Google ADK Eval / RAGAS / DeepEval | 有 673 个测试，但没有 LLM-as-Judge、golden dataset、benchmark | ⭐⭐ 高 |
| **可视化 & 仪表盘** | LangSmith / Dify Dashboard | Telemetry Bus 有数据，但没有可视化和实时仪表盘 | ⭐ 中 |
| **多模型网关** | LiteLLM / LangChain ChatModels | LLM Bus 只有单个 provider 接入，缺 fallback 和 rate limit | ⭐ 中 |
| **沙箱执行** | E2B / Docker sandbox | Tool Bus 有 Semaphore + timeout，缺真正隔离 | ⭐ 中 |
| **Web/API 接口** | LangServe / FastAPI | 只有 CLI，缺少 REST/WebSocket 接口 | ⭐ 中 |
| **流式输出** | Vercel AI SDK / Streaming | 内核不需要，但 Observer→用户需要 | ⭐ 低 |

---

## 四、框架设计建议：如何倒逼内核迭代

### 4.1 核心悖论：内核太"干净"了

你的 7 条铁律确保了内核是一个完美的纯函数——但它也因此被动等待外面喂数据。**内核不会自己产生需求——只有框架层给它施加压力，它才会暴露能力边界。**

这是好事。微内核的设计哲学就是：
> 内核只做减法——每次框架层提出"我需要内核暴露 X"，你会被迫问"X 真的应该是内核的事吗？"如果答案为是，内核才会加一个新维度/新门/新槽位。

### 4.2 框架设计的四个原则

#### 原则 1：框架不应该"绕过"内核

一个坏的框架会在 Observer 和 Actuator 之间架一条"快捷通道"——LLM 直接调 Tool，绕过内核决策。**任何框架功能必须走 `kernel_step()` 作为唯一决策入口。**

```python
# ❌ 坏：框架绕过内核直接调 LLM
response = llm.call(prompt)

# ✅ 好：所有决策经 kernel_step()
state = observer.observe(user_input)
kernel_input = adapter.to_statevector(state)
control = kernel.kernel_step(kernel_input, dt)  # 唯一决策入口
response = actuator.execute(control)  # 内核决定做什么
```

#### 原则 2：框架的需求应该倒逼内核暴露新能力，而不是打补丁

每当框架需要一个新能力时，先问：**这应该成为内核的新维度/新门/新槽位吗？**

| 框架需求 | 内核可能需要的响应 | 方式 |
|---------|------------------|------|
| "我需要知道用户是否疲劳" | 16 维中加一个 `fatigue` 维度 | Observer 写入 INSTANT 维度 |
| "我需要自动切换对话风格" | 新增 P8 门：`STYLE_ADAPT` | 门函数注册到 RouteController |
| "我需要并行执行多个子任务" | 三策略槽位挂载并行策略网络 | `BoundaryPolicy` 协议扩展 |

**关键：拒绝"在框架层硬编码 if/else"的冲动。** 这和你已经消除的 6 处硬编码是同一个教训。

#### 原则 3：框架的事务边界必须在 `kernel_step()` 之前或之后，不能在内部

这是最容易被违反的原则。框架可以做：

- **步前（pre-step）**：Observer 翻译、Adapter 组装 KernelInput、多 Agent 协商出统一方案
- **步后（post-step）**：Actuator 执行 ControlFrame、Telemetry 记录 (s,a,r)、更新长期记忆
- **步间（inter-step）**：多轮对话循环、Human-in-the-Loop 等待、情节记忆检索

框架**不能**做：在内核决策过程中插入逻辑。

#### 原则 4：框架应该用"契约"约束外部组件，不是约束内核

内核已经有了契约基础设施（`contract_violation` 字段、`AssemblyError`、三层降级）。框架的作用是把这些契约**传播出去**：

- Observer 违反翻译精度契约 → 内核收到 `contract_violation`
- Tool 执行超时 → 内核的 `tool_success_rate` 维度下降
- 用户长期不满意 → 内核的 `trust` 维度下跌

**框架是契约的"传导介质"，不是"执行者"。**

### 4.3 推荐的框架分层（对接你的微内核）

```
┌──────────────────────────────────────────────────────────────┐
│  L6: Application Layer (你的定制 Agent)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────────────┐   │
│  │ Conversation │ │ Task Agent  │ │ Embodied Controller │   │
│  │    Agent     │ │  (Track C)  │ │   (ROS2 + Robot)    │   │
│  └──────┬───────┘ └──────┬──────┘ └──────────┬───────────┘   │
├─────────┼────────────────┼───────────────────┼───────────────┤
│  L5: Orchestration Layer (NEW — 你的框架)                     │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Agent Orchestrator (Harness 升级版)                  │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────────┐     │    │
│  │  │ Workflow │ │  Multi-  │ │ Human-in-the-    │     │    │
│  │  │  Engine  │ │  Agent   │ │     Loop         │     │    │
│  │  │ (DAG)    │ │  Router  │ │ (Ticket+Proposal)│     │    │
│  │  └──────────┘ └──────────┘ └──────────────────┘     │    │
│  │  ┌──────────┐ ┌──────────────────────────────────┐   │    │
│  │  │ Episode  │ │  Contract Propagation Engine     │   │    │
│  │  │ Memory   │ │  (传播内核契约到所有外部组件)      │   │    │
│  │  └──────────┘ └──────────────────────────────────┘   │    │
│  └──────────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  L4: Translation Layer (Observer + Adapter)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Semantic    │  │  Multimodal  │  │  Long-term   │       │
│  │  Observer    │  │  Observer    │  │  Fact Memory │       │
│  │ (NL→16-dim)  │  │ (RGB/LiDAR)  │  │ (VectorStore)│       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
├──────────────────────────────────────────────────────────────┤
│  L3: Mainboard (你的现有主板层)                                │
│  四条总线 · Plugin SDK · Adapter Registry · 版本协议           │
├──────────────────────────────────────────────────────────────┤
│  L2: MPC Kernel (你的微内核 — 不动)                           │
│  kernel_step() · ODE · 8-gate · Safety Arbiter · RL Slots    │
├──────────────────────────────────────────────────────────────┤
│  L1: Infrastructure                                            │
│  Model Gateway · Sandbox · Persistence · MCP/A2A              │
└──────────────────────────────────────────────────────────────┘
```

### 4.4 内核迭代触发清单

这是一个"框架倒逼内核迭代"的具体触发机制：

| 框架层行为 | → | 内核暴露的能力缺口 | → | 内核迭代方向 |
|-----------|----|--------------------|----|------------|
| 多 Agent 协作路由 | → | 需要多 Agent 选择信号 | → | 8 门路由从"行为选择"扩展到"Agent 选择" |
| 对话疲劳检测 | → | StateVector 缺 `fatigue` 维度 | → | 16→17 维，Observer 写入疲劳信号 |
| 执行失败自动重试 | → | 需要重试计数器和策略 | → | 三策略槽位挂载 `RetryPolicy` |
| 风格自适应 | → | 需要对话风格状态信号 | → | 新增 P8 门或扩展 ControlFrame 的连续控制量 |
| 跨会话关系演化 | → | trust 只跨单会话，缺跨会话持久化 | → | ODE 积分器支持"会话间隔 dt" |
| 代码沙箱执行 | → | Tool Bus 缺安全分级 | → | Tool Bus 加 Capability-based Security 分级 |

**核心原则：框架先提需求 → 内核评估是否核心职责 → 如果是，扩展内核；如果不是，框架自己实现。**

---

## 五、一句话总结

**你的微内核是 Agent 生态中最独特的架构——它不是在 LLM 外面包一层调度逻辑，而是用控制论（ODE + Schmitt 触发器 + Lipschitz）替代 LLM 做实时决策。行业所有框架都在"大脑"层竞争（记忆、规划、多 Agent），而你在做"小脑+脑干"——这两者是互补的，不是替代关系。**

你需要的框架不是 LangChain 的克隆——你需要的是一个**契约传导引擎**，它：
1. **围绕内核构建**（不进内核，不绕内核）
2. **把行业成熟的组件**（长期记忆、多 Agent、HITL、评估、可视化）作为外部服务接入
3. **用框架的需求倒逼内核暴露新能力**（新维度、新门、新槽位）
4. **让内核保持纯函数**（框架做所有有副作用的事，内核只做决策）

这个框架在行业中没有先例——因为你的内核在行业中也没有先例。

---

> **同行评审状态**：本报告基于 2026-07-04 的公开数据  
> **许可**：CC BY-SA 4.0  
> **作者**：AI 辅助调研，署名：李政远（FRUNHSAN）

---

## 附录 A：主流框架组件对应表（速查）

| 组件 | LangChain | CrewAI | AutoGen | Dify | LlamaIndex | Sem.Kernel | Letta | 你的微内核 |
|------|-----------|--------|---------|------|------------|------------|-------|----------|
| **模型接入** | ✅ 50+ | ✅ | ✅ | ✅ 30+ | ✅ | ✅ | ✅ | LLM Bus |
| **工具调用** | ✅ `@tool` | ✅ | ✅ | ✅ | ✅ | ✅ Plugins | ✅ | Tool Bus |
| **短期记忆** | Buffer | Context | History | Context | — | — | Working | StateVector |
| **长期记忆** | VectorStore | ✅ v1.14 | ❌ | ✅ | ✅ Index | ✅ | ✅ Archival | **缺** |
| **情节记忆** | LangSmith | ❌ | ❌ | Logs | ❌ | ❌ | ✅ Recall | DecisionTrace |
| **关系记忆** | **无** | **无** | **无** | **无** | **无** | **无** | **无** | ✅ trust/e_t |
| **规划** | ReAct/LangGraph | Crew Process | GroupChat | Workflow | QueryEngine | Planner | Auto-prompt | Track C |
| **多 Agent** | LangGraph Send | Crew/Process | GroupChat | ❌ | ❌ | ❌ | ❌ | **缺（8门路由可扩展）** |
| **HITL** | interrupt() | Human input | UserProxy | Approval Node | ❌ | ❌ | ❌ | Ticket/Proposal |
| **反思** | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ✅ | e(t)+Streak |
| **护栏** | Guardrails | Guardrails | ❌ | ✅ | ❌ | ✅ | ❌ | Safety Arbiter |
| **Tracing** | LangSmith | Events | ❌ | ✅ | ❌ | ❌ | ❌ | Telemetry Bus |
| **评估** | LangSmith | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | **缺** |
| **沙箱** | ❌ | ❌ | Docker | ✅ | ❌ | ❌ | ❌ | Semaphore |
| **流式** | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | **N/A** |

---

## 附录 B：关键术语一句话词典

按字母序，每个术语一句话讲清，标注归属层级。

| 术语 | 一句话 | 层级 |
|------|--------|------|
| **A2A Protocol** | Google 定义的 Agent-to-Agent 通信协议——让不同框架的 Agent 可以互相"说话" | L1 基础设施 |
| **Agent Loop** | Agent 的核心执行循环：观察→思考→行动→记忆→循环 | L2 认知 |
| **Blackboard** | 多 Agent 共享的状态空间——Agent 不直接通信，而是读写同一个"黑板" | L3 编排 |
| **Chain-of-Thought** | LLM 在回答前先写"推理过程"——靠显式推理步骤提高准确率 | L2 认知 |
| **Checkpoint** | 在状态机每个节点执行后自动保存——断点续跑 + 时间旅行调试 | L1 基础设施 |
| **Code Agent** | Agent 输出可执行代码来调用工具（smolagents 模式），比 JSON function call 更安全 | L2 认知 |
| **DAG Workflow** | 把 Agent 流程建模为有向无环图——每个节点是 Agent 或 Tool，边是数据流 | L3 编排 |
| **Function Calling** | LLM 输出结构化的 JSON（而不是自由文本）来触发工具调用 | L2 认知 |
| **Golden Dataset** | 人工标注的"正确答案"数据集——用于评估 Agent 表现 | L4 可观测 |
| **Guardrails** | 策略即代码的护栏——"如果是危险操作则拒绝或让人审批" | L2 认知 |
| **HITL** | Human-in-the-Loop——关键决策前暂停等人类确认 | L3 编排 |
| **LLM-as-Judge** | 用一个 LLM 评判另一个 LLM 的输出质量——便宜可扩展的评估方式 | L4 可观测 |
| **MCP** | Model Context Protocol——Anthropic 定义的标准化 Agent-Tool 通信协议 | L1 基础设施 |
| **Orchestrator-Worker** | 一个中央调度 Agent 把任务分配给专职 Worker Agent | L3 编排 |
| **Plan-Execute-Reflect** | 规划→执行→自我批评→修正→重新执行 | L2 认知 |
| **ReAct** | Reasoning + Acting——LLM 交替输出"思考"和"行动"，驱动 Agent 循环 | L2 认知 |
| **Reflexion** | Agent 失败后进行自我批评，用批评结果修正下一轮行为 | L2 认知 |
| **RAG** | Retrieval-Augmented Generation——先检索相关文档，再基于文档生成回答 | L2 认知 |
| **Tool Schema** | 用 JSON Schema 定义工具的输入输出——LLM 据此决定用什么参数调工具 | L1 基础设施 |
| **Tracing** | 全链路追踪——记录 Agent 每一步的输入/输出/延迟/token | L4 可观测 |
| **VectorStore** | 向量数据库——把文本变成 embedding 存起来，检索时找最相似的 | L1 基础设施 |
