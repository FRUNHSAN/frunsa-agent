---
chain_id: 2026-07-05-plan2-blind-test
title: "PLAN2 盲测 — trust 非对称 EMA 的参数标定范例"
layer: kernel
tags: [plan2, blind_test, parameter_calibration, trust_ema, asymmetric_decay, golden_params, form_parameter_separation]
status: active
created: 2026-07-05
supersedes: [plan2_relational_os]
superseded_by: []
related:
  - 2026-07-05-v9-kernel-architecture
  - 2026-07-05-v5-constraint-paradigm
  - 2026-07-05-v6-engine-constraint-topology
  - 2026-07-05-v7-topological-homomorphism
files:
  - core/adapters/selection_pressure_accumulator.py
  - core/repl.py
produces_invariants:
  - "INV-030: trust 非对称 EMA — τ_decay=120s < τ_build=600s（信任易失难建）"
  - "INV-031: fatigue 压缩 78% — 疲劳状态下的 verbosity 压缩比"
  - "INV-032: renegotiation threshold = 0.55 — 信任结晶触发阈值"
red_flags:
  - "不要把盲测的标定值当作不可修改的常数 — 它们是单用户、单域的标定结果"
  - "不要把形式的非对称性和参数的具体值混淆 — 非对称是推导的，120s/600s 是标定的"
---

# Context

PLAN1 把所有违规当作 bug。PLAN2 区分了被动违规（修复）和主动违规（信任）——"我不会做"和"我选择不做"是两种完全不同的信号。四个 Phase：道德直觉（26）、皮肤和神经（27）、技术衰退（28）、信任结晶（29）。

状态空间的问题：**trust 的动力学需要一个非对称的 EMA 形式——信任易失难建。但具体参数（τ_decay、τ_build、fatigue 压缩比）从未经过经验标定，全部是默认值。**

约束触碰：这条链的特殊之处在于——**约束的形式（非对称 EMA）是从心理学第一性原理推导的（损失厌恶、信任修复的不对称性），但参数的具体值（120s/600s/78%）来自盲测标定。** 这是"形式来自推导，参数来自标定"在工程实践中的完美范例。

# Decision

**INTENTIONAL_VIOLATION 不是失败——它是建立信任的选择。** Agent 为了更高的价值主动选择违反合同——这不是 bug，是关系信号。

PLAN2 的四个核心机制：
1. **RelationalField**：实时关系温度（Phase 27——皮肤和神经）
2. **EmbodiedReflex**：ToolResult → 自然直觉的翻译（Phase 28——技术衰退，关系涌现）
3. **RenegotiationWatcher**：累积信任 → 合同演化提案（Phase 29——信任结晶）
4. **非对称 trust EMA**：trust 衰减（τ=120s）快于恢复（τ=600s）——信任易失难建

**这条链建立的不是一条新约束，而是一个参数标定的范例——如何在不混淆形式和参数的前提下，从盲测数据标定参数值。**

# Rationale

## 形式的推导

**为什么 trust 需要非对称 EMA？**

推导链：
```
心理学第一性原理：信任修复的不对称性
→ 损失一次信任需要的恢复时间 ≫ 建立一次信任需要的时间
→ EMA 的时间常数必须不对称：τ_decay < τ_build
→ 形式：trust_new = trust_old + (1 - exp(-dt/τ)) × (target - trust_old)
  其中 τ = τ_decay（信任下降时）或 τ = τ_build（信任恢复时）
→ 铁律 #2（连续控制律）：控制量从 StateVector 连续推导
```

**为什么疲劳需要 verbosity 压缩？**

推导链：
```
疲劳 = 连续交互的认知资源消耗 → 输出质量在恒定 verbosity 下下降
→ 约束：verbosity_effective = verbosity_budget × fatigue_compression
→ fatigue_compression ∈ [0, 1]，从 StateVector 的 cognitive_load + rhythm_ratio 推导
→ 不是"应该减少输出"的启发式，是"高认知负载下高 verbosity 会产生低质量输出"的约束
→ 铁律 #2（连续控制）
```

## 参数的标定

这是全项目**形式/参数分离最清晰的实例**：

| 元素 | 来自推导还是标定 | 值 | 置信度 |
|------|----------------|-----|--------|
| 非对称 EMA 形式 | **推导**：心理学第一性原理 + 铁律 #2 | τ_decay < τ_build | HIGH |
| τ_decay = 120s | **标定**：PLAN2 盲测 (n=1) | 120s | ⚠ LOW |
| τ_build = 600s | **标定**：PLAN2 盲测 (n=1) | 600s | ⚠ LOW |
| fatigue_compression | **标定**：PLAN2 盲测 | 78%（即 verbosity × 0.22） | ⚠ LOW |
| renegotiation threshold | **标定**：PLAN2 盲测 | 0.55 | ⚠ LOW |

**关键区分**：如果有人提出"把 τ_decay 改成 60s 因为新的 AB 测试显示更好"——这是合法的参数更新。如果有人提出"把非对称 EMA 改成对称的因为更简单"——这是非法的形式修改，除非提供了推翻心理学第一性原理的新证据。

对标 `10-约束式工程实践方法论.md` 步骤 3——参数和形式分离的标准模板。

# Alternatives

### 方案 A：把所有违规当作 bug 处理（PLAN1）
- **Pros**：简单，统一处理
- **Cons**：无法区分"我不会做"（被动）和"我选择不做因为 Y"（主动）。两种信号的语义完全不同，统一处理 = 信号丢失
- **Rejected**：违反铁律 #7（信息损失可审计）——把两个正交维度压进一个类别

### 方案 B：主动违约为独立代码路径，在合同体系外
- **Pros**：不碰已有违规处理系统
- **Cons**：重复基础设施。主动违规失去审计追踪。在合同体系外 = 不受约束体系约束
- **Rejected**：主动违规必须在合同体系内——它仍然是合同事件，只是语义不同

# Evidence

## 形式验证（证明）
- [数学性质]：非对称 EMA 的指数衰减在所有 dt 下不超调。帧率无关性从 1-exp(-dt/τ) 的解析形式保证
- [数学性质]：fatigue_compression 从 cognitive_load + rhythm_ratio 的连续推导——无离散阈值
- [不变量保持]：铁律 #2（连续控制），铁律 #6（梯度有界——trust 变化速率 ≤ 0.30）

## 参数标定（数据）
- [标定方法]：PLAN2 盲测 (n=1)。受试者报告"听得进去"——证明关系适应是可感知的
- [参数值]：Golden Parameters——fatigue 78% 压缩、trust 稳定在 0.5、renegotiation threshold 0.55
- [置信度]：⚠ LOW — 单用户、单域（Agent 对话域）。**本链中的所有参数值都是标定数据，不是公理。任何人在另一个域（游戏引擎域/具身智能域）使用这些值之前必须重新标定。**
- [待标定]：全部参数在游戏引擎域和具身智能域的取值。标定方法见前沿注入 [A1]

## 测试（验证实现正确性）
- PLAN2 盲测：首次受试者验证关系适应可感知
- 全量测试回归通过

# Future Guidance

## 刻意没做的事
- 跨用户标定——PLAN2 是单用户盲测。Golden Parameters 对用户 A 有效，对用户 B 未知
- 多域标定——全部数据来自 Agent 对话域。游戏引擎域和具身智能域没有 trust 概念，参数不适用

## 参数调参须知
- **这是全项目最重要的调参说明**：修改 τ_decay/τ_build/fatigue_compression 之前，确认你在标定参数，不是修改形式。形式（非对称 EMA）来自心理学推导。参数（120s/600s/78%）来自盲测数据。两者不得混淆。
- 调 τ_decay：让信任衰减更快 = 系统对负面信号更敏感。检查误报率
- 调 τ_build：让信任恢复更慢 = 系统更保守。检查漏报率
- 调 fatigue_compression：改 verbosity 在疲劳态的有效输出量。检查输出质量和用户满意度
- 所有参数更新的置信度标注：更新来源（新盲测 / AB 测试 / 域切换）+ 更新后置信度

# Anti-Patterns

- **不要把盲测的标定值当作不可修改的常数** — 参数是可标定的。Golden Parameters 是"当前最优估计"，不是"永久真理"
- **不要把形式的非对称性和参数的具体值混淆** — 非对称是推导的（心理学原理 → τ_decay < τ_build）。120s/600s 是标定的。12-反模式 #9（数据权威篡位）的反面——不要让标定数据篡改形式，也不要让形式推导僵化参数
- **不要把 INTENTIONAL_VIOLATION 加入 SeverityMapping** — 它是信任事件，不是失败事件。混淆会污染 compliance_rate 指标
- **不要把被动违规和主动违规混为一谈** — "我不会做" ≠ "我选择不做"。混淆 = 信号丢失 = 铁律 #7 违规
- **不要在 fatigue 态从 HIGH 一步跳到 LOW** — 虚假疲劳检测导致振荡。RenegotiationWatcher 的信任结晶需要多轮累积
