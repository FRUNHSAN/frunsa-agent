# godot-qwen-agent 架构总图

**V8.2 关仓盘点** | 2026-06-11 | V7.2→V8.1 共 11 个版本

---

## 一、系统全景

```
                         ┌──────────────────────┐
                         │       REPL 协调器      │
                         │   (core/repl.py)      │
                         │   唯一拥有全局状态      │
                         └──────┬───────┬───────┘
                                │       │
              ┌─────────────────┼───────┼─────────────────┐
              │                 │       │                 │
              ▼                 ▼       ▼                 ▼
     ┌────────────┐    ┌────────────┐   ┌────────────┐
     │ 自适应 Loops │    │ 自适应语义  │   │ 自适应契约  │
     │   V8.1      │    │   V7.7     │   │ V7.6→V8.0  │
     │             │    │            │   │            │
     │ 做什么？     │    │ 用户说什么？│   │ 什么姿态？  │
     │ A 还是 C？   │    │ 是命令吗？  │   │ 多长？多暖？│
     └────────────┘    └────────────┘   └────────────┘
```

## 二、三个自适应子系统

### 2.1 自适应语义翻译（V7.7）

**功能**: 将用户自然语言翻译为结构化契约信号。

**数学背板**: 层论截面 on S³⁸³（MiniLM 嵌入超球面）

```
⊥ = E \ ∪U_i     ← 法外之地——所有截面都无定义
U_i = {e: ang_sim(e, center_i) > r_i}  ← 测地线球（注入半径估计）
F = F_emotion × F_command    ← 乘积纤维，交叉系数 = R-N 导数
```

**关键文件**: `core/adapters/semantic_trust.py` · `core/repl.py:_detect_explicit_command()`

**同态分**: ~50%

### 2.2 自适应契约（V7.6→V8.0）

**功能**: 根据用户行为反馈调整交互风格（长度、语气、主动性）。

**数学背板**: 梯度流 + Lipschitz 约束 + 路径积分

```
σ = σ_clarity + σ_emotion + σ_competence + σ_explicit  ← 选择压力
T(t) = T(0) + ∫σ dτ                                      ← 信任路径积分
c' = c - η·∇V,  ||Δc|| ≤ MAX_GRADIENT_NORM              ← 契约梯度下降
```

**关键文件**: `core/repl.py:_contract_adapt()` · `core/contracts/dynamic_blueprint.py` · `core/adapters/output_pipeline.py`

**同态分**: ~58%

### 2.3 自适应 Loops（V8.1）

**功能**: 路由决策——直接回复（Track A）还是完整引擎管道（Track C）。

**数学背板**: Galois 连接 + 自然变换 + Bang-bang 控制

```
U ⊣ D  on poset {A ≤ C}         ← Schmitt 触发器（迟滞比较器）
α: F_normal → F_crisis          ← 危机模式自然变换
Pontryagin 极大值原理             ← Bang-bang 最优控制
```

**关键文件**: `core/repl.py:_route_controller()` · `core/track_c.py`

**同态分**: ~35%（设计基准——Bang-bang 控制天然离散）

---

## 三、量化债务登记表

| 变量 | 范围 | 当前状态数 | 主要 gap | V8.x 修补 | V9.0 计划 |
|------|------|----------|---------|----------|----------|
| `trust` | [0,1] | 6 + 连续 lambda_hint | Loop 层 trust<0.10 硬阈值 | — | 滑动模式边界层 sigmoid |
| `e(t)` | [0,1] | 4 + critic θ 连续 | Loop 层 e_t>0.55 硬阈值 | — | 同上 |
| `clarity` | [0,1] | 5 | 正常范围 [0.35,0.70] 零 prompt 效应 | 故意留白（防过阻尼） | — |
| `drift` | [0,2] | 4 + critic θ 连续 | — | — | — |
| Blueprint | 7 enum | ~1152 模板 + 过渡描述 | 4-bin 离散基准 + trust 连续因子 | V8.0 信任衰减 | tone 连续化 |
| Planning LLM | N/A | 连续置信度 + 长度预期 | response_verbose_level 仍是 4 离散值 | V8.0 语义授权 | — |

---

## 四、拓扑同态演化

```
同态分
  │
60%├─                                   ● V8.0 (58%)
   │                              ● V7.9 (55%)
   │                         ● V7.8 (50%)
50%├─                    ● V7.7
   │              ● V7.6
   │        ● V7.3
40%├─  ● V7.2
   │
35%├─ V7.2 基准
   │
   └────────────────────────────────────────→ 时间
    V7.2   V7.6   V7.7   V7.8   V7.9   V8.0
```

| 版本 | 同态分 | 关键提升 |
|------|--------|---------|
| V7.2 | 35% | 基准——物理 critic + sandbox |
| V7.3 | — | Φ 函子 + 阻力层 DAG + Docker S4 |
| V7.4 | — | 身份流形 M_id ⊂ ℝ⁹ |
| V7.5 | — | 熵监控器 |
| V7.6 | 35% | σ 压力场 + T=∫σdτ + ∇V 梯度 |
| V7.7 | — | ⊥ 开集 + 乘积纤维 + 角距离 |
| V7.8 | 50% | Lipschitz 上膛 + ⊥ 澄清 + 契约过渡描述 + lambda_hint 连续化 |
| V7.9 | 55% | Planning 真空修补 + 布尔坍缩消灭 |
| V8.0 | 58% | 信任衰减 + 语义授权 |
| V8.1 | — | Loops 数学背板（纯理论） |

---

## 五、关键架构不变量

| # | 不变量 | 版本 |
|---|--------|------|
| P5 | **Observe, Don't Inject** — 观测器只返回结构体，不写入 Blueprint | V5.2 |
| P51 | **FEEDFORWARD_GAIN=0** — 交叉系数只调制置信度，不控制契约 | V5.2 |
| P54 | **Zero Keywords** — 控制循环中无字符串匹配 | V5.3 |
| P55 | **Engine Must Not Import Observer** — 只有 REPL 协调两个域 | V5.3 |
| P63 | **Topological Homomorphism ≥ 50%** — 连续变量相邻值在离散输出中产生不同行为 | V7.9 |

---

## 六、三个子系统的耦合（REPL 每轮执行顺序）

```
1. _detect_explicit_command(user)
   → obs = sem.observe(user)                     [语义翻译]
   → 设置 _semantic_confidence                   [语义→契约 耦合]

2. _route_controller(e_t, trust_var, trust, user)
   → 返回 Track A 或 Track C                     [Loops]

3. Track C 执行:
   → _do_plan(..., planning_hint)                [契约→Planning 耦合]
   → _do_orchestrate(plan, ...)                  [执行]
   → _do_critique(..., theta)                     [trust→Critic 耦合]
   → _build_synthesis_prompt(..., system)          [契约→Synthesis 耦合]
   → process(response)                             [契约→输出 耦合]

4. _trust_breathe(sigma)                          [契约]
   → trust 更新
   → output_pipeline.set_trust_attenuation(trust) [契约→输出 耦合]

5. _contract_adapt(clarity, frustration)          [契约]
   → η = f(trust)
   → clarity streak → explanation_style
   → frustration streak → tone_style
```

---

## 七、V9.0 路线图

| 优先级 | 项目 | 依赖 | 预期版本 |
|--------|------|------|---------|
| P0 | 滑动模式控制边界层 — trust<0.10 + trust_var>0.3 sigmoid 连续化 | 代价泛函定义 + 状态方程 | V9.0 |
| P1 | Pontryagin 代价泛函 — 定义 J(u) = ∫ L(x,u) dt 并推导最优阈值 | 系统辨识（trust/e_t 演化模型） | V9.1 |
| P2 | CROSS_COEFFICIENTS 贝叶斯更新 — 从运行数据学习交叉系数 | 标注数据积累 | V9.2 |
| P3 | tone_style few-shot 比例插值 — 风格流形平滑过渡 | SHOT_POOL 内容工程 | V9.3 |
| P4 | ∇V 从数据学习 — 用户隐式反馈的奖励模型 | RL 基础设施 | V9.x |

---

## 八、关键文件索引

```
core/repl.py                 ← REPL 协调器（~1700 行，全部三个子系统在此耦合）
core/track_c.py              ← Track C 引擎管道（Planning→Orch→Critic→Synthesize）
core/adapters/
  semantic_trust.py          ← 语义翻译器（层论截面 + 乘积纤维）
  contract_evolution_engine.py ← 契约演化闸门
  output_pipeline.py         ← 输出管道（信任衰减 + 脊髓反射）
core/contracts/
  dynamic_blueprint.py       ← 自适应蓝图（CONSTITUTION + Lipschitz 约束）
  blueprint_schema.py        ← 蓝图字段定义
engines/planning/
  llm.py                     ← Planning LLM 引擎
  stub.py                    ← Planning 桩（测试用）
.ai_reasoning/
  index.yaml                 ← 推理链索引（11 条链，V2→V8.1）
  chains/                    ← 推理链 YAML 文件
从连续数学到离散工程.md        ← 自检报告（拓扑同态审计 + 量化债务表）
CLAUDE.md                    ← 项目宪法（62+1 条不变量 + P63 拓扑同态指标）
```
