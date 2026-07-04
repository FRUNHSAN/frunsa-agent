---
chain_id: YYYY-MM-DD-short-description
title: "一句话标题"
layer: kernel | harness | observer | synthesis | ui | meta
tags: [tag1, tag2, tag3]
status: draft
created: YYYY-MM-DD
supersedes: []
superseded_by: []
related: []
files: []
produces_invariants: []
red_flags: []
---

# Context

[状态空间的哪个区域出了问题？什么约束被触碰了？为什么现在必须处理？]

# Decision

[1-3 句话。新建/修改/废弃了什么约束？不含理由。]

# Rationale

[形式的推导：为什么是这个数学形式？追溯到铁律或已证明的不变量。]

```
推导链: 约束 C → 推论 Y → 定理 X → 铁律 #N
```

[参数的标定：为什么是这个值？来自实验数据或默认值，标注置信度。]

# Alternatives

[考虑过但拒绝的方案。每个带 pros/cons 和拒绝的约束理由——不只是"不好"，而是"违反了哪条约束"。]

# Evidence

## 形式验证（证明）
- [数学性质]:
- [不变量保持]:
- [推导链完整性]:

## 参数标定（数据）
- [标定方法]:
- [参数值]:
- [置信度]: ⚠ LOW | MEDIUM | HIGH
- [待标定]:

## 测试（验证实现正确性）
- [测试列表]:

# Future Guidance

## 刻意没做的事
- [事项]: [理由] → [后续版本/条件]

## 参数调参须知
- [修改 X] → [检查 Y]

# Anti-Patterns

[约束：定义了未来 AI 协作者在状态空间中不能进入的区域。用否定句表述——"不能做什么"。]
