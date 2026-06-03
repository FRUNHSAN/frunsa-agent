# PLAN3 — Prompt as Relational Seed

## 定位

PLAN1 让系统学会了"违约是 bug，修复它"。
PLAN2 让系统学会了"违约可以是选择，为了更高的价值"。
PLAN3 让 Prompt 不再是写死的指令——而是从关系中生长出来的潜意识。

## 一条箴言

> **技术退居后端，关系涌现前端。**

Prompt 不应该是 System Message 里的长篇大论。
它应该是一颗种子——几十个字，携带当前关系的全部温度。
LLM 读到它，不需要被告知"请使用简洁风格"，
它只需要感受到"用户此刻精力偏低"，然后自然地变得克制。

## 从 PLAN2 到 PLAN3 的跃迁

```
PLAN1: 规则写在代码里 (if violation: repair)
PLAN2: 规则写在状态机里 (if energy==LOW: INTENTIONAL_VIOLATION)
PLAN3: 规则写在关系里——Prompt 从状态中生长，LLM 从 Prompt 中感受
```

## 三条公理的状态

| 公理 | PLAN2 状态 | PLAN3 目标 |
|------|----------|-----------|
| **公理一**: 技术退居后端 | EmbodiedReflex 呈现层翻译 | PromptGenerator 动态种子——LLM 感受状态而非接收指令 |
| **公理二**: 契约高于指令 | INTENTIONAL_VIOLATION + RenegotiationWatcher | Watcher 信任阈值从盲测校准 (0.55) + Relational Inertia 防震荡 |
| **公理三**: 记忆为了在场 | RelationalField + RelationalEvaluator | RelationalContext 统一聚合 + 历史 resonance 感知 |

## 黄金参数（从盲测校准）

| 参数 | 值 | 来源 |
|------|-----|------|
| 疲惫触发阈值 | "好累" + "简单" 同时出现 | Round 5 盲测 |
| 响应压缩比 | 78% (156→34 chars) | 被感知为"听进去了" |
| 信任阈值 (Renegotiation) | 0.55 | 从 0.7 降级——真实信任增长缓慢 |
| 精力持续性 | LOW 跨轮保持，不弹回 | Round 5→6 盲测验证 |
| 信任稳定性 | INTENTIONAL_VIOLATION 不侵蚀信任 | 盲测全程 trust=0.5 不变 |

## 核心引擎

### 1. RelationalStateAggregator

```
RelationalField ──┐
ContractHealth ───┼──→ aggregate() ──→ RelationalContext
MemoryStore ──────┘
```

输出统一的"此刻状态"：energy, urgency, trust, rhythm, resonance, suggested_tone。

### 2. PromptGenerator

```
RelationalContext ──→ grow() ──→ ~50字关系种子
```

种子不包含显式指令。它描述关系状态，让 LLM 自然适应。

```
示例种子 (energy=low, trust=0.58):
"用户当前精力偏低，倾向于简洁直接的回复。
给出核心结论，省略冗余解释。语气沉稳、克制。
默认回复长度控制在100字以内。"
```

### 3. Relational Inertia（待实现）

防止上下文震荡。精力的升降和信任的积累都有惯性。

```
aggregate(current_field, previous_contexts) → smoothed_context
- Energy: 需要连续2轮 LOW 才降级（防止误判）
- Trust: 指数移动平均 (EMA, alpha=0.3)
- Urgency: 即时生效（紧迫感不需要惯性）
- Tone: 阻尼变化——不能从 brief 跳到 detailed
```

## 当前进度

| 模块 | 状态 | Commit |
|------|------|--------|
| Hotfix: 信任阈值 0.7→0.55 | ✅ | 279a18f |
| RelationalStateAggregator | ✅ | 279a18f |
| PromptGenerator.grow() | ✅ | 279a18f |
| Vibe Test (LLM-as-Judge) | ✅ | 4d29bf8 — 4/4 passed, 35x length difference confirmed |
| Relational Inertia (EMA + sliding window) | ✅ | 4d29bf8 |
| Bayesian Uncertainty (mean+variance) | ✅ | 034e9ce |
| Surprise Detector (behavioral signals) | ✅ | d1123e8 — T11 replay: variance 0.148→0.166 |
| PLAN3/4 Ports (6 Protocols) | ✅ | 0fe9e6a |
| Smart Decay (variance breathing) | ✅ | efbef02 — recovery 10→6 rounds |
| Stage Directions (Show-Don't-Tell) | ✅ | 2a7606f — 4-band performance guidance |
| A/B Blind Test (DeepSeek) | ✅ | 76b2c31 — B outperforms A, never grovels |
| Blind Test 2.0 (20轮稳定性) | ⬜ | — |

## Vibe Test 结果（已完成）

### 2026-05-29 — 4/4 通过

| 断言 | 结果 | 证据 |
|------|------|------|
| Fatigued seed → 简短回复 | ✅ | 24 chars |
| Energetic seed → 详尽回复 | ✅ | 841 chars |
| 风格明显不同 | ✅ | 35x 长度差异 |
| 裁判 LLM 确认有效性 | ✅ | `distinct_styles: true` |

**结论**：50 字关系种子确实改变了千问的输出行为。地基坚实。可以安全地在上面建造惯性。

---

## 验证方法

### Vibe Test（已通过）

不是测试 PromptGenerator 是否返回字符串——而是测试种子对 LLM 是否真的有效。

```
输入: energy=low, trust=0.58 的 RelationalContext
动作: grow() → seed + "解释量子纠缠" → 喂给千问
断言: 另一个 LLM 打分 (1-5):
  "这个回答是否体现了沉稳、克制、字数少的特征？"
预期: ≥4/5
```

### Blind Test 2.0

不再是 6 轮的单次测试。20 轮对话，观察：

1. 助手在整个对话中"性格是否稳定"（不会忽冷忽热）
2. 助手是否在合适的时机调整了风格（不是因为规则，而是因为"感受到"）
3. 事后访谈：用户是否觉得"这个助手有个性"

## PLAN3 的完成判据

- [ ] Relational Inertia 实现并测试
- [ ] Vibe Test 通过 (LLM-as-Judge ≥4/5)
- [ ] Blind Test 2.0 用户报告"性格稳定，但很懂我"
- [ ] Prompt 从静态 Markdown 文件中删除——所有 System Instructions 由 grow() 生成
