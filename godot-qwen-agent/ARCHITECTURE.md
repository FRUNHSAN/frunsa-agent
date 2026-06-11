# godot-qwen-agent 架构总图

**V8.2 关仓盘点** | 2026-06-11 | V7.2→V8.1 共 11 个版本

---

## 一、什么是"自适应"？——三个子系统的定义与边界

一个 Agent 和用户对话时，需要做三种不同性质的决定。这三种决定构成了 Agent 的完整自主神经中枢。

### 1.1 自适应语义翻译：理解"用户说了什么"

**核心问题**: 用户的自然语言输入，如何映射到 Agent 可执行的结构化意图？

这不是传统的 NLP 分类问题——因为在真实对话中，大多数输入**不是命令**。"你好呀"、"对对对"、"嗯嗯"——这些是社交礼仪、确认、填充词，不应该触发任何契约变更。传统的分类器（包括基于嵌入的分类器）强迫每个输入落入某个类别——这就是 Voronoi 暴政。

**自适应体现在哪里**: Agent 承认自己不知道。⊥ 开集是嵌入流形上的"法外之地"——当用户的输入落在所有命令域之外时，Agent 不猜、不硬分类、不修改契约。它选择沉默。这不是分类器的失败——这是层论截面在拓扑上未定义的区域。Agent 学会了说"我没听懂"。

**数学基础**: 层论（Sheaf Theory）。嵌入流形 S³⁸³ 上的局部截面。⊥ = E\∪U_i 作为开集补集。乘积纤维 F_emotion × F_command 的联合分布。角距离作为黎曼度量。

**输入**: 用户文本。**输出**: ObservationResult（情绪维度 + 命令分类 + 置信度 + null/gap 标记）。

### 1.2 自适应契约：决定"以什么姿态回应"

**核心问题**: Agent 应该用多长的回复？什么语气？主动提问还是被动回答？这些不是用户每次显式指定的——它们应该从交互历史中**演化**出来。

这不是配置文件的切换。契约是一个**动力学系统**——它有惯性（Lipschitz 约束防止突变）、记忆（trust 是 σ 的路径积分，不是快照）、迟滞（进入需要 3 轮证据，退出也需要 3 轮——防止边界振荡）。用户连续 3 轮表示理解 → 契约渐变到更深的理论解释。用户连续受挫 → 契约渐变到更温和的语气。

**自适应体现在哪里**: 契约不是一个"用户说 X 就变成 Y"的随动系统。它是一个有质量的、有摩擦的、有记忆的物理系统。用户的一句脏话不会瞬间改变 Agent 的人设——Lipschitz 约束 ||Δc|| ≤ 0.3 确保了每次改动都是有界的。trust 低于 0.10 时契约冻结——信任崩了还改契约是噪声驱动的。

**数学基础**: 梯度流 + 选择压力 + 路径积分。σ = Σσ_i（四个正交选择压力分量）。T(t) = T(0) + ∫σ dτ（信任作为累积历史）。c' = c - η·∇V, η = f(T)（契约沿负梯度演化，学习率由信任闸门控制）。迟滞比较器 + 冷却期。

**输入**: 用户行为信号（clarity, frustration, gratitude, curiosity）。**输出**: 7 个 Blueprint 字段的连续调制（长度、语气、主动性……）。

### 1.3 自适应 Loops：决定"投入多少计算资源"

**核心问题**: 用户的这句话，值得启动完整的引擎管道（Planning→Orch→Critic→Synthesize），还是直接让 LLM 回复就够了？

这不是"复杂就用 C，简单就用 A"的启发式。这是一个**最优控制问题**：在观测不完全、信号有噪声、计算有代价的条件下，选择使期望净收益最大的路由。Bang-bang 控制（Pontryagin 极大值原理）说：当 Hamiltonian 对控制变量线性时，最优控制必然在边界——A 或 C，没有中间态。"70%A + 30%C"不是更精细——它在数学上是次优的。

**自适应体现在哪里**: 路由不是写死的决策树。Schmitt 触发器（上行需 2 次连续 e_t 上升 + e_t > 0.55，下行需 3 次连续下降）是迟滞比较器——防止在阈值附近高频抖振。信任危机（trust < 0.10）触发自然变换——整个路由函子坍缩为常数 A。冷启动 Minimax——前 2 轮偏向 C（有界误差），但只在用户给出足够结构信号时。

**数学基础**: Galois 连接 U ⊣ D（偏序集 {A ≤ C} 上的单调 Galois 连接）。自然变换 α: F_normal → F_crisis（危机模式坍缩）。Bang-bang 控制（Pontryagin 极大值原理）。Schmitt 触发器（迟滞比较器）。

**输入**: 跟踪误差 e(t)、信任 trust、信任方差 trust_var、轮数、文本结构复杂度。**输出**: Track A（直接 LLM）或 Track C（完整引擎管道）。

### 1.4 三者的关系：不是层级，是耦合环

```
用户输入
    │
    ├─→ [语义翻译] 这是什么意思？是命令吗？置信度多少？
    │       │
    │       ├─→ 置信度 → [契约] 该不该改？
    │       │                  │
    │       │                  ├─→ trust → [Loops] 下轮走 A 还是 C？
    │       │                  ├─→ verbosity → [Loops] 规划多少步？
    │       │                  └─→ tone → [输出] 生成的语气
    │       │
    │       └─→ null_region → [Loops] 用户意图模糊，要不要强制 Track A？
    │
    └─→ [Loops] 当前信任/误差状态下，最优路由是什么？
            │
            ├─→ Track A: 跳过 Planning，直接 LLM → [输出]
            │
            └─→ Track C: Planning→Orch→Critic→Synthesize → [输出]
                         │        │       │        │
                         │        │       │        └─→ [契约] verbosity 截断输出
                         │        │       └─→ [契约] trust 闸门控制 Critic 阈值
                         │        └─→ [语义] ⊥ 置信度影响 Planning 分解
                         └─→ [契约] planning_hint 注入 Planning goal
```

**关键洞察**: 三个子系统各自有独立的数学背板（层论、梯度流、Galois 连接），但它们的耦合发生在 REPL 协调器中——通过扁平的状态变量（trust, e_t, _semantic_confidence, blueprint fields）传递。这是 V7.9 审计中反复强调的"单通道原则"——每个信号只通过一个通道进入每个子系统，避免双重计数和过阻尼。

---

## 二、系统全景

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
     │ 投入多少？   │    │ 用户说什么？│   │ 什么姿态？  │
     │ A 还是 C？   │    │ 是命令吗？  │   │ 多长？多暖？│
     │ Bang-bang   │    │ 层论截面   │   │ 梯度流     │
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
