# [ARCHIVED — DEPRECATED_BY_V5]
# 
#
# This plan predates the V5 Mathematical Adaptive Contract framework
# (Wasserstein-Schrödinger gradient flow, Grothendieck fibration,
#  variation-selection-retention Darwinian triad).
#
# Its design decisions — particularly "guess user intent via embedding
# signals" (fatigue/frustration/dim) — have been superseded by the
# tracking-error-driven paradigm in PLAN8.md.
#
# Retained for historical reference. Do not use as implementation guide.
# See .ai_reasoning/BRAINSTORM_TRUE_ADAPTIVE.md for the full derivation.
# See PLAN8.md for the current engineering plan.
#
# Archived: 2026-06-07

# PLAN2 — 契约自适应：从免疫系统到关系操作系统

## 定位

PLAN.md 记录了 Phase 1-25 的工程演进——每一行代码的来龙去脉。

PLAN2.md 记录**范式本身的重定义**——当工程实践反馈回理论框架时发生的认知升级。

这不是替代。PLAN.md 是工程史，PLAN2.md 是宪法修正案。

---

## 一、核心概念字典

### 1. 契约自适应 (Contract Adaptability)

| | 旧定义 | 新定义 |
|---|--------|--------|
| **本质** | 系统根据环境变化自动调整参数或重试策略的容错机制 | 人机双方在交互中动态共建、CRUD、重谈（Renegotiate），甚至基于更高价值对齐而主动违背（Intentional Violation）的"关系状态机" |
| **架构体现** | 写在代码里的 if-else 重试逻辑 | 持久化在 ContractRepository 中的显式实体，是 Agent 的"道德直觉"与"边界感" |
| **核心判据** | 能否自动修复违约 | 能否判断**何时顺从、何时抗命、何时求助、何时主动违约** |

### 2. 上下文 (Context)

| | 旧定义 | 新定义 |
|---|--------|--------|
| **本质** | 喂给 LLM 的 Token 序列、RAG 检索结果或历史对话日志的扁平容器 | 当前人机关系的"实时投影"与"感知场域 (Relational Field)" |
| **工作记忆** | 不存在 | 容量极小但高度活跃，只保留与"此刻互动状态"强相关的信息（情绪水位、紧急程度） |
| **契约状态区** | 不存在 | 存储关系的元数据（信任度、活跃契约、安全/敏感边界），是解码用户语义的"滤镜" |
| **情感摘要流** | 不存在 | 丢弃字面细节，保留时间维度上的关系脉络与情感轨迹 |

### 3. 技能 (Skill / Tool)

| | 旧定义 | 新定义 |
|---|--------|--------|
| **本质** | 独立的、可被意图分类器显式路由和调用的外部函数 | 被内化为 Agent "具身本能 (Embodied Capability)" 的后端支撑 |
| **触发方式** | 意图路由 → ToolCall → 执行 | 由"契约状态和语义直连"自然激活 |
| **用户体验** | "AI 正在调用 web_search..." | 用户感受不到工具调用，只感受到 "AI 具备做这件事的能力" |

### 4. 提示词 (Prompt)

| | 旧定义 | 新定义 |
|---|--------|--------|
| **本质** | 控制 AI 行为、规定输出格式的持续性指令集 (System Message) | 关系契约的"初始种子 (Relational Seed)"与启动引导词 |
| **生命周期** | 贯穿整个对话 | 仅在交互开始时定义"关系的起点"（基调、初始人设），随后隐退，行为由契约状态机接管 |

---

## 二、三条底层公理

### 公理一：技术退居后端，关系涌现前端 (Tech Recesses, Relation Emerges)

> 最顶级的 Agent 体验，是让用户忘记 Skill、Context 和 Prompt 的存在。所有显式的工程组件都必须降维为不可见的"后端基础设施"，只为支撑前端那段自然、安全、有温度的"关系直连"。

### 公理二：契约高于指令，共建优于服从 (Contract > Instruction, Co-creation > Obedience)

> AI 不应是盲目执行指令的奴隶，而是维护契约的合伙人。当指令与契约冲突时，AI 必须发起澄清或重谈；当死守契约会损害更高价值（如紧急避险/情感共鸣）时，AI 应具备"有意违约"的道德直觉。

### 公理三：记忆是为了"在场"，而非为了"存储" (Memory is for Presence, not Storage)

> 上下文不是硬盘，而是皮肤。系统不应追求"记住用户说过的所有原话"，而应追求"精准感知用户此刻的状态"。长期知识交由后端数据库，上下文只保留服务于当前"共在 (Co-presence)"的工作记忆。

---

## 三、范式对比

| 维度 | 旧范式 (LangChain/AutoGen 等) | 新范式 (Relational OS) | 核心转变 |
|------|---------------------------|----------------------|---------|
| 核心驱动 | LLM 推理 + 意图路由 + 工具调用 | 语义直连 + 契约状态机 + 具身本能 | 从"计算"到"共在" |
| 规则管理 | System Prompt (静态、黑盒、易遗忘) | Contract CRUD (动态、白盒、可重谈) | 从"口头承诺"到"数字法律" |
| 错误处理 | 报错 / 幻觉 / 无限重试 | 澄清 / 契约重谈 / 优雅降级 / 有意违约 | 从"系统崩溃"到"关系协商" |
| 成功指标 | 任务完成率、Token 消耗、准确率 | 关系健康度、信任积累值、契约合规率 | 从"工具理性"到"关系感性" |

---

## 四、当前实现 vs 新框架

### 已实现（公理二——契约高于指令）

| 能力 | 实现 |
|------|------|
| 不服从错误指令 | TOOL_NOT_FOUND → ContractViolation → SelfRepairEngine |
| 契约合规评估 | ContractHealthReport + compliance_rate + SeverityMapping (6 类) |
| 优雅降级 | SelfRepairEngine 4 级策略 + RepairBudget |
| 契约重谈 | RenegotiationProposal + HITLGateway 非阻塞通道 |
| 人在回路 | HITLGateway 阻塞求助 + HumanTicket |
| 契约生命周期 | ContractLifecycle DRAFT/ACTIVE/DEPRECATED + 权重感知 |
| 关系记忆 | RelationshipMemoryStore delta 语义 + transition 持久化 |
| 防腐层 | EventSink Protocol + InteractionRepository Protocol + ToolFormatAdapter Registry |

### 未实现（公理一 & 公理三 & 公理二的完整形态）

| 缺口 | 所属公理 | 说明 |
|------|---------|------|
| **有意违约 (Intentional Violation)** | 公理二 | 当更高价值 > 契约遵从时，Agent 主动选择违约并记录理由 |
| **关系温度感知** | 公理三 | Agent 感知用户的疲惫/紧迫/信任，调整行为 |
| **工作记忆** | 公理三 | 极小的活跃状态区，只保留"此刻"相关的信息 |
| **技能内化为具身本能** | 公理一 | 用户看不到 ToolCall，只感受到 Agent 的能力 |
| **Prompt 隐退** | 公理一 | 交互开始后契约状态机接管，Prompt 不再主导行为 |

---

## 五、下一步：有意违约 (Intentional Violation)

### 为什么先做这个

1. **它是公理二的完整形态**。当前只实现了"不服从错误指令"（被动免疫），还没有"主动选择违约"（道德直觉）。
2. **它是 PLAN2 和 PLAN1 的分水岭**。PLAN1 的所有能力都在"修复违约"。PLAN2 的第一个能力是"主动创造违约"。
3. **它最小**。一个枚举值 + 一个判断条件 + 一个 demo 场景。~50 行。

### 设计草图

```python
# ContractViolation 新增
INTENTIONAL_VIOLATION = "intentional_violation"

# ToolResult 新增字段
reason: str | None = None  # 有意违约时需要填写理由

# 触发场景：用户说"我累了"
# → Agent 检测到用户疲惫信号
# → 跳过非关键搜索，标记为 INTENTIONAL_VIOLATION
# → 这不是失败，这是"我选择不做，因为用户需要休息"
```

### 与传统 violation 的本质区别

| | 被动违约 | 有意违约 |
|---|---------|---------|
| 触发 | 环境/LLM 出错 | Agent 主动选择 |
| 语义 | "我做不到" | "我选择不做，因为______" |
| 对合规率的影响 | 降低 compliance_rate | 不降低——标记为 intentional 的违约不计入合规率 |
| 对信任的影响 | 负面 | 正面——展示了道德判断 |

---

## 六、PLAN2 的演化逻辑

```
PLAN1 (Phase 1-25):
  契约作为免疫系统
  "违约 = 需要修复的 bug"
  公理二前半段: 契约高于指令（被动免疫）

PLAN2 (Phase 26+):
  契约作为关系状态机
  "违约 = 可能需要修复，也可能是有意选择"
  公理二完整形态: 契约高于指令 + 有意违约（主动道德直觉）
  公理一: 技术隐退
  公理三: 记忆为了在场
```

---

## 七、PLAN2 第一块基石：Intentional Violation（已完成）

### 完成日期

2026-05-29

### Commit

`33884b4 feat(plan2): Intentional Violation`

### 变更

| 文件 | 变更 |
|------|------|
| `core/contracts/composition.py` | `ContractViolation.INTENTIONAL_VIOLATION` + `trust_accumulated` event + SeverityMapping 排除 |
| `core/contracts/tool.py` | `ToolResult.higher_value_reason` + `is_intentional_override` property |
| `core/adapters/repair_engine.py` | `decide()` 跳过 INTENTIONAL + `record_trust_accumulation()` |
| `tests/unit/test_pipeline_composer.py` | 5 个 PLAN2 测试 |

### 核心行为

```
被动违约 (PLAN1):                    有意违约 (PLAN2):
  TOOL_NOT_FOUND                       INTENTIONAL_VIOLATION
  -> SeverityMapping 判定              -> SeverityMapping 排除
  -> compliance_rate 下降              -> compliance_rate 不变
  -> SelfRepairEngine 触发修复         -> SelfRepairEngine 跳过
  -> 记录为 failure                    -> 记录为 trust_accumulated (+5)
```

### 验证

- [x] `is_intentional_override` 正确区分主动/被动违约
- [x] `SeverityMapping.default()` 不含 INTENTIONAL_VIOLATION 规则
- [x] `SelfRepairEngine.decide()` 跳过 intentional violations
- [x] `record_trust_accumulation()` 发出 `trust_accumulated` 事件
- [x] 仅 intentional violations 的 sink 仍为 healthy
- [x] `pytest tests/ -q` — 859/859 通过

---

## 八、PLAN2 第二块基石：RelationalField + RelationalEvaluator（已完成）

### 完成日期

2026-05-29

### Commit

`aec7982 feat(plan2): RelationalField + RelationalEvaluator`

### 变更

| 文件 | 变更 |
|------|------|
| `core/contracts/relational_field.py` | `RelationalField` dataclass + `EnergyLevel`/`Urgency` enums + `trust_watermark` |
| `core/adapters/relational_evaluator.py` | `RelationalEvaluator` — Level 1 启发式旁路传感器 |
| `tests/unit/test_pipeline_composer.py` | 15 个 PLAN2 测试 (7 RelationalField + 8 RelationalEvaluator) |

### 核心行为

```
用户: "好累，随便弄弄就行"
    ↓
RelationalEvaluator.evaluate(user_input, current_field)
    ↓
energy_level = LOW, narrative = "User shows signs of fatigue/low energy"
    ↓
RelationalField (frozen snapshot) 传递给 Agent
    ↓
Agent 选择 INTENTIONAL_VIOLATION (Phase 26 闭环)
```

### 验证

- [x] 中英文关键词检测 (energy/urgency/trust)
- [x] trust_watermark 双向调整 (感谢 +0.02, 抱怨 -0.03, 限幅 0.0-1.0)
- [x] frozen dataclass 不可变
- [x] 同一输入 = 同一输出（确定性）
- [x] `pytest tests/ -q` — 874/874 通过

---

## 九、PLAN2 第三块基石：EmbodiedReflex（已完成）

### 完成日期

2026-05-29

### Commit

`23092b5 feat(plan2): EmbodiedReflex — Axiom 1`

### 变更

| 文件 | 变更 |
|------|------|
| `core/adapters/embodied_reflex.py` | `EmbodiedReflex` — 呈现层翻译膜 (~100行) |
| `demo/demo_embodied.py` | 11/11 — PLAN1 vs PLAN2 对比演示 |

### 核心行为

```
ToolResult(success=True, tool_name="web_search", data={...})
    ↓
EmbodiedReflex.process(result, user_intent)
    ↓
PLAN1: "Calling web_search... Result received"
PLAN2: "(Intuition: I recall several key points about this topic)"
```

### 设计原则

- **Scheme B**: 拦截 Result，不拦截 Call。LLM function calling 原样运行
- **审计保留**: event_sink 仍记录完整 ToolResult
- **启发式直觉**: `_summarize()` 按 tool_name 映射（web_search → "I recall...", weather → "it feels like..."）
- **Phase 32+ 接口**: `_summarize()` 可替换为小模型，外部接口 `process()` 不动

---

## 十、PLAN2 第四块基石：RenegotiationWatcher（已完成）

### 完成日期

2026-05-29

### Commit

`e13401a feat(plan2): RenegotiationWatcher — Axiom 2 complete`

### 变更

| 文件 | 变更 |
|------|------|
| `core/adapters/renegotiation_watcher.py` | `RenegotiationWatcher` — 后台巡检员 (~90行) |
| `demo/demo_plan2_closed_loop.py` | 7/7 — PLAN2 完整闭环 |

### 核心行为

```
4 次 INTENTIONAL_VIOLATION against "web_search"
    ↓
RenegotiationWatcher.scan(sink, field, fp)
    ↓ trust_watermark >= 0.7? YES
    ↓ count >= threshold (3)? YES (4)
    ↓
RenegotiationProposal(
    suggested_action="Relax strict constraints on 'web_search'..."
)
    ↓
HITLGateway.submit_proposal(proposal) → 人类审批 → 契约进化
```

### PLAN2 完整闭环

```
Phase 26 (decide) → Phase 27 (sense) → Phase 28 (embody) → Phase 29 (evolve)
INTENTIONAL_VIOLATION → RelationalField → EmbodiedReflex → RenegotiationWatcher
```

### 验证

- [x] `demo_plan2_closed_loop.py` — 7/7 通过
- [x] `pytest tests/ -q` — 874/874 通过
