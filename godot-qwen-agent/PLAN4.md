# PLAN4 — The Relational Tensor

## 定位

> **Treating Human-Agent Interaction as Online Representation Learning.**

PLAN1 把关系当成规则（if violation: repair）。
PLAN2 把关系当成状态机（if energy==LOW: INTENTIONAL_VIOLATION）。
PLAN3 把关系当成上下文（aggregate → grow → seed）。
PLAN4 把关系当成被双方共同训练的神经网络。

Prompt 不再是生成的——它是前向传播的输出。
关系状态不再是聚合的——它是反向传播中更新的隐式权重。
每一次交互，都是环境给出的一步梯度。

## 从标量到张量

```
PLAN1-2: energy = "low"                    # 标量
PLAN3:   ctx = {energy, trust, rhythm}      # 字典/向量
PLAN4:   R = [Window_Size, Latent_Dims]     # 矩阵/张量
```

## 关系矩阵的维度

| 维度 | 含义 | 变化速度 |
|------|------|---------|
| Cognitive Load (D1) | 用户当前处理信息的带宽 | 中速 |
| Emotional Valence (D2) | 从沮丧到愉悦 | 缓慢 |
| Epistemic Trust (D3) | 对 Agent 专业能力的信任 | 极慢 |
| Relational Intimacy (D4) | 允许 Agent 介入私人领域的程度 | 极慢 |
| Goal Alignment (D5) | 双方是否在同一个频道上 | 中速 |

形状: `[Window_Size, 5]`。Window_Size = 20 轮。

## 三阶段生命周期

### 1. Forward Pass: Attention + Collapse

```
R[20, 5] → TemporalAttention → weights[20, 1]
         → WeightedSum → vector[5]
         → Decode → natural_language_seed (~50 words)
```

时间注意力：Round 5（用户说"好累"）的权重大于 Round 2 的寒暄。

### 2. Backward Pass: Implicit Proxy Loss

```
Agent 输出 → 用户下一轮行为 → Proxy Loss
  - 用户回复简短正向 → Negative Loss (强化)
  - 用户重新提问/抱怨 → Positive Loss (惩罚)
  - 用户响应延迟变短 → Negative Loss
  - 用户输入字数骤降 → 下调 Cognitive Load
```

没有显式标签。用户的隐式行为就是 Ground Truth。

### 3. Momentum & Friction

```
信任的动量:   高摩擦力（缓慢建立），高动量（不易崩塌）
情绪的惯性:   中摩擦力（需要多次正向交互才能爬升）
紧迫度:       零摩擦力（即时响应）
```

技术栈：EMA（已在 PLAN3 实现）、贝叶斯更新（PLAN4）、卡尔曼滤波（PLAN4+）。

## 当前进度

| 模块 | 状态 | 所在 |
|------|------|------|
| EMA trust smoothing | ✅ | `relational_inertia.py` |
| Energy confirm window (2 rounds) | ✅ | `relational_inertia.py` |
| Tone damping | ✅ | `relational_inertia.py` |
| Urgency decay | ✅ | `relational_inertia.py` |
| Sliding window history | ✅ | `relational_inertia.py` |
| Temporal Attention | ⬜ | PLAN4 未来 |
| Proxy Loss (implicit feedback) | ⬜ | PLAN4 未来 |
| Bayesian uncertainty | ⬜ | PLAN4+ 未来 |
| Full tensor engine | ⬜ | PLAN4+ 未来 |

## PLAN4 的完成判据

- [ ] Proxy Loss 实现：用户下一轮行为 → 调整矩阵权重
- [ ] 不确定性追踪：每维度维护 mean + variance
- [ ] 连续 20 轮交互中，矩阵的各维度平滑演化，无震荡
- [ ] Blind Test 3.0：用户报告"它越来越懂我了"（学习效应）
