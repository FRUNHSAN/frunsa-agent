# Frunsa-Agent

> 安全感知的 AI Agent 基础设施 — 三层可验证安全机制 + 多引擎 LLM 架构实验平台。

[![Tests](https://img.shields.io/badge/tests-673%20passed-brightgreen)](tests/)
[![Guardrails](https://img.shields.io/badge/guardrails-16%20passed-blue)](guardrails/)
[![Python](https://img.shields.io/badge/python-3.12+-informational)](https://www.python.org/)
[![Phase](https://img.shields.io/badge/phase-18%20complete-orange)](PLAN.md)

📖 **安全能力专项文档**: [docs/security-portfolio/](docs/security-portfolio/)

---

## 项目定位

Frunsa-Agent 是一个三层平台架构的 AI Agent 系统，核心贡献是**将安全作为架构一等公民**的工程实践：

- **编译时**: 16 条 AST 规则自动检测架构违规，pre-commit hook 强制执行
- **运行时**: try/except → error terminal（不崩溃）+ ResourceContainer 凭证隔离
- **事后**: SQLiteTraceSink 全链路审计日志，每次 LLM 调用可追溯

三个引擎类型（Planning / Orchestration / Critic）各有两个独立实现（Stub 确定性参考 + LLM 生产引擎），通过 Factory DI 契约实现一行切换。

---

## 架构

```
contracts/ (Protocol)  ←→  adapters/ (Translation)  ←→  pipeline/ (Engine)
                                ↑
                          engines/ (Agent Runtime)
                   Planning │ Orchestration │ Critic
                    stub+LLM    stub+LLM      stub+LLM
```text

项目遵循严格的跨层隔离规则：

- `core/pipeline/` 不导入 domain types
- `core/contracts/` 不导入 orchestration types
- `core/adapters/` 是唯一的跨层桥接层

完整的架构演进史记录在 [PLAN.md](PLAN.md)（18 个 Phase，21 条推理链）。

---

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 运行全部测试
pytest tests/ -q
# → 673 passed, 0 failed

# 运行架构合规检查
python -m guardrails check --all
# → Guardrails: PASSED (36 files, 16 rules)
```

---

## 关键数字

| 指标 | 数值 |
|------|------|
| 测试 | 673（conformance + integration + e2e） |
| Guardrails | 16 条（AST 级架构强制） |
| 引擎实现 | 6 个（3 stub + 3 LLM） |
| Trace Keys | 18 个 |
| 推理链 | 21 条（`.ai_reasoning/chains/`） |
| Sufficiency Reports | 4 份（v1 → v4） |

---

## 项目结构

```text
├── core/               # 基础设施（contracts / adapters / observability / pipeline）
├── engines/            # 引擎层（planning / orchestration / critic，各含 stub + LLM 双实现）
├── guardrails/         # AST 架构合规扫描器（16 条规则）
├── tests/              # conformance / integration / e2e
├── docs/               # 文档（含 security-portfolio/）
├── .ai_reasoning/      # 架构推理链库（21 条 chains + 4 份 sufficiency reports）
├── PLAN.md             # 完整架构规划（18 Phase 演进史）
└── CLAUDE.md           # AI 协作协议 + 架构不变式
```

---

## 技术栈

Python 3.12+ / asyncio / pytest / SQLite / `@dataclass(frozen=True)` / GenerationAdapter (OpenAI / Claude / Qwen / Ollama)

---

## 文档

- [安全能力专项文档](docs/security-portfolio/) — 威胁模型 / 安全设计 / 面试展示
- [PLAN.md](PLAN.md) — 18 Phase 架构演进全记录
- [CLAUDE.md](CLAUDE.md) — 架构不变式参考
- [.ai_reasoning/](.ai_reasoning/) — 21 条架构推理链

## 安全声明

本项目在架构层面实现了三层安全机制（编译时 AST 扫描 / 运行时隔离 / 事后 Trace 溯源），但并非声称覆盖所有攻击面。完整的威胁模型和已知局限性见 [docs/security-portfolio/SECURITY.md](docs/security-portfolio/SECURITY.md)。
