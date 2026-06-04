# Contract-Bound Agent

> **AI Agent 契约治理 (Contract Governance) — 契约约束工具执行，信任驱动权限升降级。**

[![Tests](https://img.shields.io/badge/tests-890%2B%20passed-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.12+-informational)](https://www.python.org/)
[![Phase](https://img.shields.io/badge/phase-PLAN8-blue)](PLAN7.md)
[![Commits](https://img.shields.io/badge/commits-99-orange)](.)

📖 **架构文档**: [PLAN1-7](PLAN.md) | **推理链**: [.ai_reasoning/](.ai_reasoning/)

---

## 定位

**这不是一个 Chatbot 框架。** 这是一个 Agent 契约治理系统。

核心原语不是"执行指令"——而是**维护和演化关系通过可验证的契约**。

市面上所有的 Agent 框架（LangChain, AutoGen, CrewAI）都在优化"任务完成速度"。本项目优化的是**"关系稳定性"和"行为可预测性"**。两个目标不可通约。

```
指令范式:  输入 → LLM → 输出 → 用户
契约范式:  输入 → Contract Engine → Action Pipeline → 物理拦截
                ↓
          DynamicBlueprint (演化、愈合、沉淀)
```

---

## 核心能力

| 层 | 做什么 | 确定性 |
|----|--------|--------|
| **关系引擎** (PLAN1-4) | Bayesian EMA + SemanticTrust + Stage Directions | 数学公式 |
| **活体契约** (PLAN5) | DynamicBlueprint: 增删改查、风化、反噬、固化 | 代码逻辑 |
| **语义感知** (PLAN6) | Embedding 信任信号 + SignalInterpreter | 80% 准确率 |
| **三层控制** (PLAN7) | Prompt → OutputPipeline → GBNF 物理约束 | 100% (Layer 2+3) |
| **工具契约** (PLAN8) | ActionPipeline: 信任阈值 + HITL + Backlash | 代码钳制 |

## 5 行接入

```python
from core.contract_engine import ContractEngine

engine = ContractEngine(profile="user_123")

@engine.tool(risk="DESTRUCTIVE", min_trust=0.8)
def delete_logs():
    os.system("rm -rf /var/log/*")

with engine.session() as session:
    session.execute(delete_logs)
    # → ContractViolation if trust < 0.8
```

---

## 快速开始

```bash
pip install -r requirements.txt
python run_live.py frunhsan          # 云端 DeepSeek (1s/round)
python run_live.py frunhsan --local  # 本地 Qwen3.5-4B + GBNF (~8s/round)
pytest tests/ -q                     # 890+ tests
```

---

## 生产就绪度

> *"本项目目前处于架构验证 (PoC) 阶段。核心原语（DynamicBlueprint、ActionPipeline、ToolContract）在逻辑和确定性上已达到生产级。通往 MVP 的路线图专注于 SDK 集成和边界测试，刻意推迟了多租户基建，以聚焦核心的 AI 治理问题。"*

| 维度 | 状态 | 差距 |
|------|------|------|
| **核心理念** | ✅ 生产级 | Anthropic/OpenAI 也在攻的方向 |
| **确定性** | ✅ | 契约引擎 + ToolContract + Constitution = 代码逻辑，零幻觉 |
| **测试覆盖** | ⚠️ 近生产 | PLAN1-4: 855 测试; PLAN5-8: 38 测试 (需 200+) |
| **API/SDK** | ⚠️ 初版 | ContractEngine SDK 可用，需 HTTP API |
| **持久化** | ⚠️ | UserProfile JSON 单文件，缺并发支持 |
| **安全** | ❌ | 缺认证、审计日志、速率限制 |
| **运维** | ❌ | 缺监控、告警、日志轮转 |

### Roadmap

```
现在  (PoC):   架构验证 ✅ | 99 commits | 890+ tests
  ↓
3个月 (MVP):   HTTP API + 200+ tests + SQLite 持久化 + 认证
  ↓
6个月 (Beta):  多用户 + 监控 + Docker 部署
  ↓
12个月 (GA):   高可用 + SLA + 审计合规
```

---

## 关键数字

| 指标 | 数值 |
|------|------|
| 测试 | 890+ |
| 核心文件 | 71 (`core/`) |
| PLAN 文档 | 7 (PLAN1-PLAN7) |
| 推理链 | 10 条 (`.ai_reasoning/chains/`) |
| 架构不变式 | 45 条 (CLAUDE.md) |
| Commit | 99 |
| 安全阀 | 4 (Cooldown, Min Autonomy, Outlier, Constitution) |
| 后端 | 2 (DeepSeek 云端 + Qwen3.5 本地) |

---

## 技术栈

Python 3.12+ / pytest / llama.cpp (GBNF) / DeepSeek API / sentence-transformers / SQLite

---

## 文档

- [PLAN7.md](PLAN7.md) — 当前架构：三层控制面 + 云边协同
- [PLAN6.md](PLAN6.md) — 语义信任引擎
- [PLAN5.md](PLAN5.md) — 活体契约 (DynamicBlueprint + 3 Loops)
- [CLAUDE.md](CLAUDE.md) — 45 条架构不变式
- [AUDIT.md](AUDIT.md) — 全栈架构审计
- [.ai_reasoning/](.ai_reasoning/) — 10 条推理链
