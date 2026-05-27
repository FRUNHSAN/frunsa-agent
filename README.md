# Frunsa-Agent

> 从大学比赛作品到 AI 安全 Agent 架构实验平台 — 18 个 Phase 的完整演进。

[English](README_EN.md) | 中文

[![Tests](https://img.shields.io/badge/tests-673%20passed-brightgreen)](godot-qwen-agent/tests/)
[![Guardrails](https://img.shields.io/badge/guardrails-16%20passed-blue)](godot-qwen-agent/guardrails/)
[![Python](https://img.shields.io/badge/python-3.12+-informational)](https://www.python.org/)
[![Phase](https://img.shields.io/badge/phase-18%20complete-orange)](godot-qwen-agent/PLAN.md)

---

## 项目来源

这个仓库最初是 **2026 年深理工 Agent 比赛**的参赛作品——一个基于 RAG（检索增强生成）的 Godot 游戏开发 AI 助手。技术栈很简单：FastAPI + Qwen API + FAISS 向量检索，通过 Godot 4.x 的 HTTPRequest 在前端提问，后端从知识库中检索相关文档后交给 Qwen 回答。

本来奔着参赛去的但是但是一个人做的项目太乱了，加上时间精力不够，结果最后也没有报名和递交

比赛结束后，代码没有止步于"能跑就行"。我回头看了看烂尾的项目，我根本无从下手，而且代码耦合面积非常大，导致非常无序，而且我发现市面上的agent平台在今年开始变得特别多，而且井喷式的产出，这背后当然后模型的多次迭代带来的能力解放，现在模型都像六边形一样，开始具有处理特别复杂的事务链，一个问题被提了出来：**如果这个 Agent 不仅仅是一个问答 bot，而是一个能够自主规划、编排、自我评估的 AI Agent 系统，它的安全边界在哪里？**

这个项目从此转向了 AI Agent 安全架构的研究与工程实践。

---

## 改造思路

### 核心理念：安全是一等架构公民，不是事后补丁

绝大多数 AI Agent 项目把安全视为"后续加上去"的特性——加个 API Key 管理、做个权限校验就完事了。Frunsa-Agent 的做法相反：**安全属性从 Phase 1 就写入架构宪法，每一行代码都在三条安全线的约束之下。**

### 三层可验证安全机制

| 层级 | 机制 | 阶段 | 技术实现 |
|------|------|------|---------|
| **编译时** | AST 合规扫描 | 开发/CI | 16 条 AST 规则自动检测架构违规，pre-commit hook 强制执行 |
| **运行时** | 安全隔离 | 引擎运行 | try/except → error terminal（不崩溃）；凭证隔离；引擎互不 import |
| **事后** | 全链路审计 | 追溯 | SQLiteTraceSink 单文件数据库，每次 LLM 调用可查可审 |

### 架构演进：18 个 Phase 的渐进式改造

改造不是一次性的"推倒重来"，而是通过 18 个 Phase 逐步演进，每个 Phase 都有明确的工程目标、推理链记录和测试回归：

| 阶段 | Phase | 核心交付 | 测试数 |
|------|-------|---------|--------|
| **基础搭建** | 1-5 | 三平台架构（Contract → Adapter → Pipeline）、I/O 适配器模式、健康探针 | 107 |
| **观测闭环** | 6-13 | SQLiteTraceSink、Trace Key 体系（18 keys）、Guardrail 扫描器 | 468 |
| **引擎层** | 14-16 | 三个引擎 Stub 实现、编排 DAG、混沌注入、Sufficiency Report v1-v2 | 560 |
| **真实 LLM** | 17-18 | LLM 生产引擎、Factory DI 装配契约、Sufficiency Report v3-v4 | 673 |

每一步的决策过程都记录在 `.ai_reasoning/chains/`（21 条推理链），每个关键 trade-off 都有 alternatives 对比和 anti-patterns 警示。

### 架构宪法：六性质 + 四轴演化

经过 18 个 Phase 的打磨，沉淀出了项目长期维护的指导框架：

**引擎层六大性质**（不可妥协的设计目标）：
1. **高效** — 极致并发调度，杜绝冗余阻塞
2. **全透明** — 执行链路完全白盒可观测
3. **安全隔离** — 单点故障不引发系统性雪崩
4. **冗余性** — 优雅降级、超时熔断、多模型 Fallback
5. **可审计** — 所有决策链路留存不可篡改的证据链
6. **可更新** — 底层协议极度稳定，上层实现无缝热插拔

**四轴演化方向**（正交的扩展维度）：
- **引擎轴**：Planning → Orchestration → Critic → Memory → Learner...
- **编排轴**：Agent 协作协议 → DAG 路由 → 并行合并 → 重试/退避 → 多池路由
- **观测轴**：Trace Keys → SQLiteSink → Guardrails → Sufficiency Reports → 监控看板
- **组件轴**：Tools/Skills → API 接入 → 数据源连接器 → 标准化封装

---

## 快速开始

### 环境要求

- Python 3.12+
- Git

### 运行测试

```bash
cd godot-qwen-agent

# 安装依赖
pip install -r requirements.txt

# 运行全部测试（673 个）
pytest tests/ -q

# 运行架构合规检查（16 条规则）
python -m guardrails check --all
```

### 启动可视化 Demo

```bash
cd godot-qwen-agent/demo
pip install -r requirements.txt
streamlit run app.py
```

无需任何 API Key — 默认使用 MockBackend 驱动，所有引擎结果可复现。打开浏览器访问 `http://localhost:8501`，四个 Tab 分别展示：

| Tab | 功能 |
|-----|------|
| 🧠 引擎 Pipeline | Planning → Orchestration → Critic 全链路流式运行 |
| 🛡 Guardrail 扫描 | 16 条 AST 规则 + 动态违规注入演示 |
| 📋 Trace 审计 | SQLite 审计日志查询 + 引擎时间线图表 |
| 📖 架构文档 | 专业架构说明 + 通俗白话解释 |

### CI/CD

推送代码到 GitHub 后自动触发（`.github/workflows/ci.yml`）：
- **test 任务**：Guardrails ERROR + WARNING + pytest 全量（673 tests）
- **quick 任务**：pytest 快速模式（跳过 slow marker）

---

## 项目结构

```
agent/                              # 仓库根目录
├── README.md                       # 本文件
├── godot-qwen-agent/               # 主项目
│   ├── core/                       #   基础设施（contracts / adapters / observability / pipeline）
│   ├── engines/                    #   引擎层（planning / orchestration / critic，各 stub + LLM 双实现）
│   ├── guardrails/                 #   AST 架构合规扫描器（16 条规则）
│   ├── tests/                      #   673 个测试（conformance / integration / e2e）
│   ├── demo/                       #   Streamlit 可视化演示平台（零侵入主仓库）
│   ├── docs/                       #   文档（安全能力专项、RAG 测试数据等）
│   ├── .ai_reasoning/              #   21 条架构推理链 + 4 份 Sufficiency Reports
│   ├── PLAN.md                     #   完整架构规划（18 Phase 演进史 + 架构宪法）
│   └── CLAUDE.md                   #   AI 协作协议 + 架构不变式
├── install_deps.bat                # Windows 依赖安装脚本
├── vscode-dev-env.ps1              # VSCode 开发环境配置
└── 启动开发环境.bat                 # 一键启动开发环境
```

---

## 关键数字

| 指标 | 数值 |
|------|------|
| 测试用例 | 673（100% 通过） |
| Guardrail 规则 | 16 条（AST 级架构强制） |
| 引擎实现 | 6 个（Planning × 2 + Orchestration × 2 + Critic × 2） |
| Trace Keys | 18 个（覆盖全链路） |
| 推理链 | 21 条（每条记录决策/替代方案/反模式） |
| Sufficiency Reports | 4 份（形式化 trace key 语义充分性） |
| Phase 演进 | 18 个（完整工程记录） |

---

## 未来发展

### 短期（Phase 19-21）

- **记忆引擎 (Memory Engine)**：为 Agent 引入持久记忆能力，支持跨会话上下文的累积推理。需要新增 `memory.*` trace keys，产出 Sufficiency Report v5。
- **多级 DAG 并行**：当前编排只支持单级 fan-out（2 分支 WAIT_ALL），扩展到多级嵌套 DAG，引入更多 merge strategy（WAIT_ANY、PRIORITY）。
- **真实 LLM 故障替换**：当前混沌注入仅在 Stub 层。接入真实 LLM 后引入 token 超量、速率限制、模型不可用等真实故障场景，验证优雅降级路径。

### 中期（Phase 22-25）

- **Learner Engine（学习引擎）**：基于 Critic 反馈和历史 Trace 自动优化 Planning 策略。这是闭合"规划→执行→评估→改进"循环的关键一步。
- **多 Agent 协作协议**：Agent 间消息传递、任务委派、共识机制。探索"多 Agent 安全"这个新维度——单个 Agent 安全不代表多 Agent 系统安全。
- **监控看板**：从 SQLite 升级到时序数据库（如 ClickHouse），构建生产级 Trace 看板（Grafana），实现实时异常告警。

### 长期愿景

- **形式化验证**：将 Guardrail 规则从 AST 模式匹配提升到形式化语义级别，用 TLA+ 或 Alloy 对关键安全属性做模型检测。
- **安全基准数据集**：构建 AI Agent 安全领域的标准化测试集，覆盖 prompt injection、权限逃逸、供应链污染等攻击面。每个安全声明都有可复现的验证路径。
- **安全即代码 (Security-as-Code)**：让安全策略成为可版本控制、可测试、可 CI 的代码工件，而不是写在文档里的"应然"声明。

---

## 安全声明

本项目在架构层面实现了三层安全机制（编译时 AST 扫描 / 运行时隔离 / 事后 Trace 溯源），并产出了完整的威胁模型和已知局限分析（见 `docs/security-portfolio/SECURITY.md`）。项目的核心主张是：**AI Agent 的安全属性可以被工程化地定义、检测和追溯**，而非声称覆盖所有攻击面。

---

## 作者

**FRUNHSAN** — 独立完成的 AI Agent 安全架构实验平台，同时也是 AI 安全工程能力的展示作品。
借助 Cluade Code  agent 工具 产出