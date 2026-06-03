# PLAN5 — The Living Contract

## 定位

> **From Static YAML to Dynamic Organism. The contract breathes.**

PLAN1 定义了契约是什么（规则 + 生命周期）。
PLAN2 把关系当成状态机（INTENTIONAL_VIOLATION）。
PLAN3 把关系当成上下文（aggregate → grow → seed）。
PLAN4 把关系当成被训练的神经网络（贝叶斯 EMA + Stage Directions）。
PLAN5 让契约本身活过来——它不再是被加载的静态文件，而是在交互中增删改查的动态实体。

## 核心组件

### DynamicBlueprint
- `apply_proposal(target_key, new_value)` — 接受契约修改
- `rollback()` — 回滚到上一个快照
- `tick(half_life_rounds)` — Loop 2: 半衰期衰减，临时适应自然风化回基线
- `cooldown_rounds` — 安全阀: 同一字段 5 轮内只能改一次
- `min_autonomy` — 安全阀: 自主权不能降级到 ASK_FIRST 以下
- `CONSTITUTION` — 安全阀: 4 个不可变基因 (core_identity, safety_rules, honesty_policy, privacy_boundary)

### ContractEvolutionEngine
- `evaluate(proposal, blueprint, trust)` — 接受/拒绝提案
- `record_evolution(trust_before)` — 记录演化前信任值
- `post_check(blueprint, trust_now)` — Loop 1: 演化后 3 轮内信任暴跌 → 自动回滚
- Trust gate: trust < 0.10 → 拒绝所有提案

### ContractAuditor (System 2)
- 每 10 轮异步调用 DeepSeek
- 从对话历史提取高维契约签名
- Circuit breaker: 3 次连续失败 → 暂停 10 轮

### UserProfile (Loop 3)
- 跨会话记录字段修改
- ≥3 个会话重复修改同一字段 → 宪法修正案（临时适应 → 用户画像）
- 离群值过滤: 单会话修改 ≥3 字段或 trust delta ≥0.25 → 不计入修正案
- JSON 持久化: `user_profiles/{user_id}.json`

## 三个 Loop 闭环

| Loop | 名称 | 触发 | 效果 |
|------|------|------|------|
| 1 | Backlash | 工具调用失败 (API_TIMEOUT, PERMISSION_DENIED) | 降级自主权 |
| 2 | Decay | 每轮 tick(), 未被强化的临时适应 | 风化回基线 |
| 3 | Meta | 同一字段跨 ≥3 会话被修改 | 临时适应升级为用户画像 |

## 四个安全阀

```
防震荡 (Cooldown=5) → 同一字段不会每轮横跳
防瘫痪 (Min Autonomy) → 20 次毒打也不会降级到 DISABLED
防污染 (Outlier Rejection) → 极端会话不计入修正案
防畸变 (Constitution Guard) → 4 个不可变基因保护核心身份
```

## 稳态验证 (Homeostasis)

压力测试 4/4 通过:
- A. 震荡陷阱: 20 次交替只应用 4 次 (cooldown)
- B. 持续毒打: 20 次 API_TIMEOUT 无法推到 DISABLED (min floor)
- C. 画像污染: 离群会话自动排除，修正案基于干净数据
- D. 基因锁: 4 个宪法基因全部免疫恶意修改
