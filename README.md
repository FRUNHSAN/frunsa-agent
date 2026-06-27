# Embodied AI Microkernel（具身智能微内核）

> 原名 Frunsa-Agent / godot-qwen-agent。项目从 RAG 问答 bot 起家，历经 4 次架构跃迁，演化为一个**领域无关的 MPC 决策微内核**。当前核心为 `mpc_kernel/` —— 纯函数、零自然语言 I/O、帧率无关。

[![Tests](https://img.shields.io/badge/tests-673%20passed-brightgreen)](godot-qwen-agent/tests/)
[![Guardrails](https://img.shields.io/badge/guardrails-16%20passed-blue)](godot-qwen-agent/guardrails/)
[![Python](https://img.shields.io/badge/python-3.12+-informational)](https://www.python.org/)
[![Phase](https://img.shields.io/badge/V9.2c-MPC%20microkernel-orange)](godot-qwen-agent/CLAUDE.md)

**项目叙事保留完整演化史以诚实地记录这一段工程路径。**  
**新读者建议从 [docs/embodied-microkernel-plan/](godot-qwen-agent/docs/embodied-microkernel-plan/) 开始。**

---

## 30 秒定位

本项目的 MPC 内核设计为**领域无关**——16 维状态向量和 8 门路由控制器不关心驱动的是对话 Agent 还是机器人。同一内核可部署于两个域：

| 域 | Observer | 总线 | 动作空间 |
|----|----------|------|---------|
| 语义 Agent | NL 文本解析 | LLMBus, ToolBus | GENERATE / TOOL / WAIT |
| 具身智能 | 传感器融合 | 对接 ROS2 / ros2_control | MOVE / YIELD / STOP / OBSERVE |

> 参见：[docs/ARCHITECTURE.md](godot-qwen-agent/docs/ARCHITECTURE.md) — 五层架构 + 四条总线 + 七条铁律

---

## 项目来源

这个仓库最初是 **2026 年深理工 Agent 比赛**的参赛作品——一个基于 RAG（检索增强生成）的 Godot 游戏开发 AI 助手。技术栈很简单：FastAPI + Qwen API + FAISS 向量检索。

比赛结束后，代码没有止步于"能跑就行"。一个问题被提了出来：**如果这个 Agent 不仅仅是一个问答 bot，而是一个能够自主规划、编排、自我评估的 AI Agent 系统，它的安全边界在哪里？**

从此，项目经历了 4 次架构跃迁：

| 阶段 | 时间 | 核心转变 |
|------|------|---------|
| 契约地基 | 05-24~05-25 | 三平台架构（Contract → Adapter → Pipeline），198 测试，3 引擎 |
| 数学转向 | 05-28~06-05 | 废弃关键词驱动，引入贝叶斯 EMA、Wasserstein 梯度流、达尔文三元组 |
| 物理化 | 06-07~06-11 | V5-V8：双传感器融合、物理批评、恒等流形、熵监控、63 条架构不变式 |
| 微内核隔离 | 06-14~06-15 | V9：5 层 + 4 总线 + 7 铁律 MPC 内核，8 步纯函数决策链 |

全过程记录在 `.ai_reasoning/`（71 个文件：58 条推理链 + 15 个计划 + 7 个归档）和 `docs/V5-V6-mathematical-backplane.md`（1791 行数学推导）中。

> 参见：[docs/embodied-microkernel-plan/00-project-evolution.md](godot-qwen-agent/docs/embodied-microkernel-plan/00-project-evolution.md)

---

## 改造思路

### 核心理念：安全是一等架构公民，不是事后补丁

绝大多数 AI Agent 项目把安全视为"后续加上去"的特性。本项目的做法相反：**安全属性从 Phase 1 就写入架构宪法，每一行代码都在数学约束之下。**

### 三层可验证安全机制

| 层级 | 机制 | 阶段 | 技术实现 |
|------|------|------|---------|
| **编译时** | AST 合规扫描 | 开发/CI | 16 条 AST 规则自动检测架构违规，pre-commit hook 强制执行 |
| **运行时** | 安全隔离 | 引擎运行 | try/except → error terminal（不崩溃）；凭证隔离；引擎互不 import |
| **事后** | 全链路审计 | 追溯 | SQLiteTraceSink 单文件数据库，每次 LLM 调用可查可审 |

### 微内核七条铁律

| # | 铁律 | 含义 |
|---|------|------|
| 1 | 纯函数边界律 | `kernel_step()` 零副作用 |
| 2 | 连续控制律 | verbosity/tone/θ 连续推导，禁用查表 |
| 3 | 零自然语言律 | 内核输入输出绝对无自然语言 |
| 4 | 形式化可重放律 | 相同输入 → 相同输出 |
| 5 | 零动态分配律 | tuple 替代 list，MappingProxyType 替代 dict |
| 6 | 梯度有界律 | ‖Δs‖ ≤ 0.30 (Lipschitz) |
| 7 | 信息损失可审计律 | 降维压缩规则显式声明 |

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

无需任何 API Key — 默认使用 MockBackend 驱动。打开浏览器访问 `http://localhost:8501`。

---

## 项目结构

```
agent/                                   # 仓库根目录
├── README.md                            # 本文件
├── LICENSE                              # Apache 2.0
├── NOTICE                               # 署名 + 专利声明
├── .gitattributes
├── godot-qwen-agent/                    # 主项目（内部工程名保留）
│   ├── mpc_kernel/                      #   V9 MPC 内核（纯函数决策）
│   ├── mainboard/                       #   主板（编排 + 总线 + 插件）
│   ├── observer/                        #   语义观察器
│   ├── protocol/                        #   跨层冻结 ABI
│   ├── core/                            #   旧合约层（桥接依赖，逐步退役）
│   ├── engines/                         #   旧引擎层（桥接依赖）
│   ├── guardrails/                      #   AST 架构合规扫描器（16 条规则）
│   ├── tests/                           #   673 个测试
│   ├── demo/                            #   Streamlit 可视化演示
│   ├── docs/                            #   文档（具身微内核计划 + 技术白皮书 + 安全文档）
│   ├── .ai_reasoning/                   #   71 个推理链文件（工程记忆）
│   └── CLAUDE.md                        #   63 条架构不变式 + AI 协作协议
├── build/                               # 构建产物
├── data/                                # 数据文件
└── .archive/                            # 历史杂物归档
```

---

## 关键数字

| 指标 | 数值 |
|------|------|
| 测试用例 | 673（100% 通过） |
| Guardrail 规则 | 16 条（AST 级架构强制） |
| 架构不变式 | 63 条（机器可执行） |
| 铁律 | 7 条（纯函数、零自然语言、Lipschitz 约束…） |
| 推理链 | 58 条（每条记录决策/替代方案/反模式） |
| 数学白皮书 | 1791 行（V5→V7 连续到离散映射） |
| RL 策略槽位 | 3 个（Boundary/Cost/Value Protocol） |

---

## 具身智能方向

本项目的 MPC 内核设计为**领域无关** — 16 维状态向量和 8 门路由控制器不关心驱动的是对话 Agent 还是机器人。

详见 [docs/embodied-microkernel-plan/](godot-qwen-agent/docs/embodied-microkernel-plan/) — 面向具身智能领域的协作入口、面试材料与 7 个可独立成文的研究方向。

---

## 安全声明

本项目在架构层面实现了三层安全机制（编译时 AST 扫描 / 运行时隔离 / 事后 Trace 溯源），并产出了完整的威胁模型和已知局限分析（见 `docs/security-portfolio/SECURITY.md`）。项目的核心主张是：**AI Agent 的安全属性可以被工程化地定义、检测和追溯**，而非声称覆盖所有攻击面。

---

## 作者

**李政远（FRUNHSAN）** — 独立设计并实现的 MPC 决策微内核。架构演化全程记录在 `.ai_reasoning/` 和 `docs/` 中。
