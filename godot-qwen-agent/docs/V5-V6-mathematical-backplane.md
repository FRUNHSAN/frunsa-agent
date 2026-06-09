# V5 → V6 数学背板：从伪自适应到随机最优控制

**日期:** 2026-06-09
**状态:** V6 封板 | V7 Phase 1 (流式) + V7.1 MVP (物理 Critic) 落地 | V7.2 规划中 — 85% 物理闭环
**基线:** v5.0-bang-bang-baseline → V6 engine landing

---

## 零、哲学基座

### 伪自适应的本质

```
所有"自适应"链路的本质 = if score > threshold: field = new_value
根因：混淆了"变异生成"与"变异选择"两个独立过程
LLM 擅长前者（概率采样 = 变异），但被错误用于后者（自我评价 = 选择层失效）
```

### Transformer 的启示

"好系统都是数学公式的物理实现。"

| Transformer 组件 | 数学本质 | V5/V6 对应 |
|:--|:--|:--|
| Self-Attention | 核密度估计，软寻址 | Planning: n = f(H(G\|S)) — 根据意图熵动态分配搜索宽度 |
| Residual Connection | 信息无损高速公路 | Critic: 乘法门控 f×g — 只有双因子都激活才降阈值 |
| Gating (LSTM) | 条件性信息流控 | 清醒压制: clarity>0.80 → min(f_drift, 0.20) |

"数学做导航，不做引擎。" — 控制信号不需要解析可微，只需要物理意义清晰。

### 项目相变：从托勒密到开普勒

```
托勒密时代 (V1-V4): 本轮+均轮 → 关键词列表、if-else 状态机、Prompt 补丁
开普勒时代 (V5-V6): 椭圆轨道 → 控制面×4、乘法门控、自标定信号流
```

"越来越清晰"不是因为加了新特性，而是因为在做**减法和提纯**——把系统根系从工程经验的泥沼向下扎进数学工具的岩层。

### 附录 A：架构演化史 — 从 σ² 大统一到三维正交分解

**原始定义（V5 早期）**：

```
Planning:   n = f₁(σ²)    ← 分支数随不确定性增长
Orch:       p = f₂(σ²)    ← 并行度随不确定性增长
Critic:     θ = f₃(σ²)    ← 容忍度随不确定性增长
```

三个函数都单调递增 σ²。对称、优雅、一个信号统治一切。**但对称性是强加的，不是推导出来的。**

**问题：把"相关性"误认为"因果性"。**

σ² 在极端场景（高度模糊 + 任务未知 + 策略失效）下恰好同时暗示三个执行器需要调整，所以早期测试"看起来没问题"。但 σ² 只是一个**代理变量（Proxy Variable）**——它测量的是"变化的大小"，却丢失了"变化的方向（清醒 vs 混乱）"和"变化的结构（独立 vs 依赖）"。在常态分布的中间地带，σ² 丧失了**充分统计量（Sufficient Statistic）** 的资格。

**三次裂变**：

| 裂变 | 引擎 | 抛弃的伪信号 | 找回的真信号 | 物理学隐喻 |
|:--|:--|:--|:--|:--|
| 第一裂 | Critic | σ² (单维标量) | drift × e(t) (二维乘法门控) | **热力学**：温度(σ²)高不代表系统崩溃，必须结合熵增率(e(t))才能判断是否干预 |
| 第二裂 | Orch | σ² (认知信号) | Sᵢⱼ DAG (拓扑信号) | **固体物理**：分子排列结构(晶体/非晶体)决定物理性质，不是分子平均动能(温度/σ²) |
| 第三裂 | Planning | σ² (无向标量) | drift ⊕ clarity (有向张量) | **运动学**：速度(σ²)必须加上方向向量(clarity)才能决定下一步搜索轨迹 |

**裂变后的最终形态**：

```
原始 (错误):   σ² ──┬──→ Planning n
                    ├──→ Orch parallel_depth
                    └──→ Critic θ

修正后 (正确):
  drift ⊕ clarity ──→ Planning n       (认知维度：用户意图的不确定性)
  Sᵢⱼ (embedding)  ──→ Orch depth      (拓扑维度：任务间的依赖结构)
  drift × e(t)     ──→ Critic θ        (质量维度：语义稳定性 AND 策略有效性)
```

**三个引擎，三个信号源，三个正交维度。** 它们不是 σ² 的三个函数——它们是关于这个系统的三个独立问题：

| 引擎 | 回答的问题 | 充分统计量 | 为什么 σ² 不够 |
|------|----------|----------|--------------|
| Planning | "用户到底要什么？" | drift ⊕ clarity | σ² 只测变化量，不测变化方向（清醒切换 vs 混乱加深） |
| Orch | "这些步骤能并行吗？" | Sᵢⱼ + produces/needs 标签 | 任务并行度是结构属性，不是认知属性 |
| Critic | "多好算好？" | drift × e(t) | σ² 高 + 输出好 = 不该降标准。σ² 不是充分统计量 |

**架构品味的一个判据**：不是写出最短的公式，而是推导出最符合物理现实的公式。
强行用单一标量驱动三个正交执行器 = 用奥卡姆剃刀割自己的动脉——为了形式的极简，牺牲了物理意义的准确性。
从"伪大统一"走向"标准模型"，这才是真正的数学闭环。

**防退化原则（Anti-Regression）**：未来任何新增的信号源或执行器，不得复用已有引擎的 σ² 信号。
每个引擎必须持有自己独特的充分统计量。对称性是结果，不是起点。

---

## 一、V5 数学基座：保结构模型降阶

### 完整自适应契约的数学定义

```
自适应契约 = Grothendieck 纤维化范畴上的 Wasserstein-Schrödinger 梯度流
           + 移动目标追踪 (e(t))
           + TDA 触发的伴随函子升维 (meta-adapt)
```

### 保结构降阶：三个模块

| 模块 | 文件 | 数学对应 | 上界 |
|------|------|---------|------|
| WassersteinProxy | `wasserstein_proxy.py` | W_1 的 KR 对偶上界 | L=1 Lipschitz 归一化 |
| TrackingErrorEstimator | `tracking_error.py` | e(t) 噪声观测 | e_∞ ≤ ω_max/λ_SB |
| MetaAdaptTrigger | `meta_adapt_trigger.py` | 元适应触发+退火 | MIN=0.30, COOLDOWN=10 |

### 三个数学补丁

1. **对比校准** — W_1 代理的全局 Lipschitz L=1 归一化，需要 d_min/d_max 基准 QA 对（V6.2）
2. **自适应增益调度** — EMA α = exp(-interval/tau)，防相位滞后
3. **退火保护** — MIN_THRESHOLD=0.30, COOLDOWN=10 轮，防脑死亡和震荡

---

## 二、四条控制面：V5 的物理骨骼

### 控制面总览

```
Path 1: e(t) × route==C  → Meta-Adapt 选择阈值  (连续 → 二元)
Path 2: drift ⊕ clarity   → Planning n + Critic θ (二维 → 连续)
Path 3: 截断率             → 管道倍率              (连续 → 连续)
路由:   e(t)               → A/C                  (连续 → 二元, Bang-Bang)
```

### Path 1 — 能力穷尽原则

```
if e(t) persists above threshold for N rounds AND route==C has been tried:
    relax selection threshold → wider search → fall back to A if still failing
```

数学：`relax` 仅在 `e(t) > 0.70 × persistence=3` 且 `!cooldown` 时触发。Type II 错误代价由退火保护吸收。

### Path 2 — 双传感器融合（V5.3）

见 [§四](#四v53-双传感器融合)。

### Path 3 — 脊髓反射

```
连续截断 > 30% × 2 轮 → char_mult = 1.8x, sent_mult = 1.8x
截断缓解 → 自动恢复到 1.0x
```

不经过 meta-adapt（皮层），直接脊髓反射——速度优先。

### 路由 — Bang-Bang 控制

```
路由是二元的 Pontryagin 最优控制问题：
  - A: 零开销，但不确定性无界 (err-A unbounded)
  - C: 高开销 (~30s 额外延迟)，但探索误差有界 (err-C bounded)

Minimax 最优策略：
  首轮 → C (冷启动探针，err-C 有界 > err-A 无界)
  常态 → Schmitt trigger 滞后切换 (避免抖振)
```

---

## 三、三个引擎的数学定义

### Planning — 率失真与空间覆盖

**数学问题**: `min Σ cost(Tᵢ) s.t. I(G; T₁,...,Tₙ) ≥ (1-ε)·I(G)`

一颗好计划应捕获目标的大部分信息量，同时最小化总成本。

**分支数 n 和信息熵的关系**:

```
n ∝ H(G|S) ≈ f(σ²)

当系统对用户真实意图不确定时（σ² 高），H(G|S) 高
→ 需要更多并行分支覆盖可能性空间
→ n = f_fused → {1, 2, 3}
```

**当前实现**: `_path2_branch_count(f_fused)` — drift⊕clarity 双传感器驱动的三级增益调度。

### Orchestration — 偏序调度与拓扑相变

**数学问题**: `dep(Tᵢ, Tⱼ) = I(Oᵢ; Tⱼ) / H(Tⱼ)`

依赖矩阵 Dᵢⱼ 决定执行图拓扑：
- `dep → 0`: 任务独立，可完全并行
- `dep → 1`: Tⱼ 完全依赖 Tᵢ 的输出来理解自己，必须串行

**当前状态**: `asyncio.gather` 全并行 — 假设 D=0 矩阵。在高 σ² 时合理（依赖未知先全并行探测），在低 σ² 时浪费。

**V6.1 目标**: `f_fused → parallel_depth`，Semaphore 限流替代全量 gather。

### Critic — 假设检验与 ROC 流形滑动

**数学问题**:

```
H₀: 执行结果满足目标 G
H₁: 执行结果不满足 G

检验统计量: S = semantic_similarity(results, G)
拒绝域: S < θ

低 σ² → 高 θ → 优化精确率 (Precision)
高 σ² + 高 e(t) → 低 θ → 优化召回率 (Recall)
```

**θ 的乘法门控**: `θ = max(0.50, 0.75 - 0.25·f(σ²)·g(e_t))`

四个状态空间：

| | σ² 低 (f≈0) | σ² 高 (f≈0.9) |
|:--|:--|:--|
| **e(t) 低 (g≈0)** | θ=0.75 巡航 | θ=0.75 用户探索 |
| **e(t) 高 (g>0)** | θ=0.75 策略失败 | **θ→0.50** 真正死锁 |

只有一个格子降 θ。乘法保证：任意因子为 0，penalty 归零。

### 为什么 Critic 不用 fused f？

Critic 的验收标准应关注**语义空间稳定性**。高 drift 意味语义基准面漂移——前一轮的"好"标准可能不适用。清醒压制（clarity>0.80→min）会掩盖这种不稳定性。Critic 对 drift 的敏感性是 feature，不是 bug。

```
Planning: n = branch_count(Φ(d, c))      // 双传感器：意图不确定性
Critic:   θ = θ₀ - α·f_drift(d)·g(e)      // 单传感器(drift only)：语义空间稳定性
```

---

## 四、V5.3 双传感器融合

### 正交性

| 传感器 | 测量对象 | 时间轴 | 后端 | 物理意义 |
|--------|---------|--------|------|---------|
| drift `d` | 轨迹变化 | 跨轮 (t-1→t) | cosine distance | 用户转弯了多少 |
| clarity `c` | 状态质量 | 轮内 (t) | LLM 推理 | 用户是否清醒 |

### 融合函数

```
f = Φ(d, c) = {
    min(f_drift(d), 0.20)    if c > 0.80   (清醒压制)
    max(f_drift(d), 1 - c)   otherwise      (OR 逻辑)
}
```

**清醒压制 (c > 0.80)**: 高度清醒 + 高 drift = 有意的非连续性（lucid discontinuity）。压制 → EXPLOIT。
**OR 逻辑 (c ≤ 0.80)**: 任一传感器报警 → 探索。首轮荒谬指令也能被 clarity 检测。

### 场景验证

| 场景 | d | c | f | 行为 |
|------|---|---|---|------|
| Scene 3 R1 (荒谬指令) | 0.000 | 0.15 | 0.85 | EXPLORE |
| Scene 4 R2 (清醒切换) | 0.687 | 0.95 | 0.20 | EXPLOIT 🧊 |
| Scene 1 (正常稳定) | 0.050 | 0.85 | 0.00 | EXPLOIT |
| Scene 2 (模糊+失效) | 0.420 | 0.35 | 0.65 | EXPLORE |

### 清醒压制可见化

X-Ray 输出格式:
```
Path 2: EXPLOIT 🧊 (drift=0.687, clarity=0.95, f=0.20, branches=1, θ=0.75, out×1.0)
Path 2: EXPLORE     (drift=0.000, clarity=0.15, f=0.85, branches=3, θ=0.75, out×1.8)
```

---

## 五、激活函数选型：HardTanh，不是 Sigmoid

### 为什么是 HardTanh

```
g(e_t) = 0                       e_t ≤ 0.55   (死区)
         (e_t - 0.55) / 0.15    0.55 < e_t < 0.70  (线性斜坡)
         1                       e_t ≥ 0.70   (饱和)
```

**拒绝 Sigmoid 的两个理由**:
1. **可调试性丧失**: `g(0.60)=0.33` = "策略失效 33%"，直接物理意义。`sigmoid(0.60, k=10)` 是什么？
2. **死区不"死"**: sigmoid 永远不会到 0，`g(0.50)` 会有残差 ~0.01。噪声通过残差持续泄漏进控制回路 → 极限环振荡，积分饱和。

**HardTanh 的性质**: 不光滑但连续。导数在端点不连续但不会产生抖振。和 V5 整体哲学一致——控制信号不需要解析可微，只需要物理意义清晰。

### 惩罚曲面分析

```
penalty = 0.25·f·g
在 f=0 或 g=0 的邻域内梯度为 0 → 边界处无剧烈反应 ✓
在 f=0.5, g=0.5 时 penalty=0.0625 → θ=0.6875 → 轻微信号轻微反应 ✓
```

---

## 六、标定协议

### 场景 1: 死区气密性测试
操作: 情绪化但目标明确的输入（"今天真烦，帮我写个快排"），e(t) 0.50-0.54。
成功标准: g(e_t) 死死钉在 0.000。θ 纹丝不动 0.75。

### 场景 2: 斜坡线性度测试
操作: 连续 3 轮模糊指令，逼迫 e(t) 从 0.55 爬升到 0.70，σ² 同步推高。
成功标准: θ 呈现等距阶梯下降。无先慢后快或先快后慢。

### 场景 3: 饱和区触底测试
操作: 极其矛盾错乱的指令 + 强烈不满反馈，f→1.0, g→1.0。
成功标准: f/g 双双被 clamp 截断在 1.0。penalty 精确等于 0.25。θ 死死托底 0.50。

### 场景 4: 滞后与恢复测试
操作: 先制造死锁（模糊指令+强烈不满 → EXPLORE, θ=0.50），然后突然给出极其明确具体的指令。
成功标准: σ² 瞬间暴跌 → f→0 → penalty→0 → θ 瞬间弹回 0.75。branch_count 从 3 切回 1。系统没有状态粘滞。

### 调参启发式

| 症状 | 方向 | 具体 |
|------|------|------|
| θ 降太快 (过早妥协) | 加宽 g 过渡带 | 0.15→0.20 |
| θ 降太慢 (死循环) | 收窄过渡带或降死区 | 0.15→0.10 或 0.55→0.50 |
| **σ 绝不手动调** | — | 由 hist_sigma 自标定 |

---

## 七、V6 路线图

### ✅ 已完成

| V6 原计划 | 落地版本 | 代码 |
|-----------|---------|------|
| Path 2: σ² → Planning n | V5.1 + V5.3 | `_path2_branch_count(f_fused)` |
| Path 2: σ²×e(t) → Critic θ | V5.1 + V6 | `_critic_threshold(f_drift, g)` |
| Path 2: 认知深度 → 输出容量 | V6 | `_dynamic_output_mult` |
| Path 3: 脊髓反射 | V5 Phase 1.5 | `trunc_streak → char/sent_mult` |
| 输出管道上限翻倍 | V6 | HIGH 800→1600 chars |
| 二元 Bang-Bang 路由 | V5 Phase B | `_route_controller` Schmitt trigger |
| 关键词门控 → 纯数学 | V5.3 | `_SIMPLIFY_CANCEL` 等删除 |
| 双引擎观测器 | V5.3 | `SemanticTrustEngine.assess_clarity()` |

### 📋 待落地 — V6.1 / V6.2 / V6.3 数学重构

> 以下方案已根据五枚"架构穿甲弹"的审查结果进行强制重构。
> 核心修正：废除 `f_fused → parallel_depth` 标量映射，裂变 `relax_bias` 为正交信号，引入 Wasserstein 混合校准协议。

---

## V6.1: Orchestration DAG — 事实提取 vs 控制决策

### 问题：`f_fused → parallel_depth` 是信号错配

**致命反例**：用户说"帮我同时查三篇独立论文 A、B、C，汇总给我"——clarity=0.95, drift 低, f_fused≈0。
如果 `f_fused ≤ 0.30 → parallel_depth=1`（串行），三篇论文会被串行处理。这显然荒谬。

**根因**：`f_fused` 测量的是**认知维度**（"我对用户意图有多确定"），`parallel_depth` 需要的是**拓扑维度**（"这些步骤在逻辑上能否并发"）。把两个正交维度压缩到一个标量 = 降维灾难。

### 数学重构：LLM 声明拓扑事实，Orch 计算物理并发

**核心边界**：

| | 事实提取 (Fact Extraction) | 控制决策 (Control Decision) |
|---|---|---|
| **谁做** | LLM (Planning) | Orch 引擎 (图论算法) |
| **输出** | `depends_on: [0, 1]` — 逻辑依赖声明 | `parallel_depth` — 物理并发参数 |
| **为什么** | LLM 理解任务语义，能判断"查论文B"是否需要"查论文A"的结果 | LLM 不懂系统并发负载和 RPM 限制，不能做控制决策 |

**1. Planning 输出增加 `depends_on` 字段**

Planning LLM 的 FULL_DAG 格式扩展：

```json
{
  "type": "FULL_DAG",
  "steps": [
    {"prompt": "查论文A", "tool": "search_web", "depends_on": []},
    {"prompt": "查论文B", "tool": "search_web", "depends_on": []},
    {"prompt": "对比A和B", "tool": "", "depends_on": [0, 1]}
  ]
}
```

`depends_on` 是一个整数列表，引用前序步骤的索引。空列表 = 无依赖，可立即并行。`[0, 1]` = 依赖步骤 0 和 1 的输出。

⚠️ **`depends_on` 是可选字段。** 旧引擎不输出此字段时，Orch 按全并行处理（保持向后兼容——"高 drift 时全并行探测"的语义得以保留）。

**2. Orch 引擎在本地构建 DAG 并计算最大安全并发层**

```python
def _compute_parallel_depth(steps: list[dict]) -> int:
    """Kahn's algorithm with cycle detection → BFS level assignment.
    
    Step 1: Sanitize indices (filter out-of-bounds, remove self-loops).
    Step 2: Kahn topological sort — if visited < n, cycle detected → fallback to depth=1.
    Step 3: BFS level assignment on the verified DAG.
    
    Mathematical fallback: a cyclic directed graph has no topological ordering.
    The only safe physical default is full sequential (depth=1). This is graph
    theory, not a heuristic.
    """
    n = len(steps)
    
    # ── 1. Sanitize: filter out-of-bounds indices and self-loops ──
    for i, step in enumerate(steps):
        raw = step.get("depends_on", [])
        step["depends_on"] = [d for d in raw if 0 <= d < n and d != i]
    
    # ── 2. Cycle detection (Kahn's algorithm) ──
    in_degree = [len(s.get("depends_on", [])) for s in steps]
    queue = [i for i, d in enumerate(in_degree) if d == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for i, s in enumerate(steps):
            if node in s.get("depends_on", []):
                in_degree[i] -= 1
                if in_degree[i] == 0:
                    queue.append(i)
    
    if visited < n:
        # Cycle detected — LLM hallucination. Fallback to full sequential.
        # X-Ray must emit: [WARN] DAG: cycle detected → seq
        return 1
    
    # ── 3. BFS level assignment on verified DAG ──
    levels: dict[int, int] = {}
    for i, step in enumerate(steps):
        deps = step.get("depends_on", [])
        if not deps:
            levels[i] = 0
        else:
            levels[i] = max(levels.get(d, 0) for d in deps) + 1
    
    from collections import Counter
    level_counts = Counter(levels.values())
    return max(level_counts.values()) if level_counts else 1
```

**拓扑示例**：

```
场景 A: 三篇独立论文 (星型 DAG)
  steps: [A(独立), B(独立), C(独立)]
  levels: {0:0, 1:0, 2:0} → 3 steps at level 0
  parallel_depth = 3 ✓

场景 B: 串行流水线 (链式 DAG)
  steps: [设计(独立), 实现(依赖0), 测试(依赖1)]
  levels: {0:0, 1:1, 2:2} → 1 step per level
  parallel_depth = 1 ✓

场景 C: 混合 DAG
  steps: [查A(独立), 查B(独立), 对比(依赖0,1)]
  levels: {0:0, 1:0, 2:1} → 2 at level 0, 1 at level 1
  parallel_depth = 2 ✓
```

**3. Semaphore(parallel_depth) 替换全 gather**

```python
# engines/orchestration/llm.py: 在 orchestrate() 内
_semaphore = asyncio.Semaphore(context.parallel_depth)

async def _run_branch_gated(branch_spec):
    async with _semaphore:
        return await _run_branch(branch_spec)

branch_results = await asyncio.gather(*[_run_branch_gated(b) for b in branches])
```

⚠️ **Semaphore 必须 Per-Call，不能全局。** 每次 `orchestrate()` 调用创建独立的 Semaphore，调用结束自动销毁。不同 Session 不互相阻塞。

**4. 废除 LLM 路由决策的 `parallel_depth` 输出**

LLM 路由决策（`ROUTE_PROMPT`）不再输出 `parallel_depth`。LLM 只负责分支分配和合并策略。并发度是图论自动计算的，不是 LLM 猜测的。

### 改动汇总

| 文件 | 改动 | 行数 |
|------|------|------|
| `engines/orchestration/interface.py` | `OrchestrationContext` +`parallel_depth` 字段 (默认 1) | +2 |
| `engines/orchestration/llm.py` | 新增 `_compute_parallel_depth(steps)` | +15 |
| `engines/orchestration/llm.py` | `orchestrate()` 用 Semaphore 替换全 gather | +8 -3 |
| `engines/orchestration/llm.py` | 移除 ROUTE_PROMPT 中 `parallel_depth`，移除 LLM 路由并行度决策 | -5 |
| `core/track_c.py` | `_do_orchestrate` 构建 DAG，计算并注入 `parallel_depth` | +8 |
| `engines/planning/llm.py` | Planning prompt 增加 `depends_on` 说明 (可选字段) | +3 |

**总计: ~36 行，3 文件。零新组件。**

---

## V6.2: WassersteinProxy 混合校准 — 绝对锚点 + 动态增益

### 问题：静态基准 vs 领域特异性

一个量子物理用户的嵌入流形和一个前端开发用户的完全不同。静态 QA 对无法覆盖所有领域。但动态更新 `d_min/d_max` 会导致**基准污染**——如果用户连续 5 轮输入乱码，噪声簇会被定义为"完美匹配"，之后所有清晰输入都被判为"远离基准"。

### 数学重构：双层校准协议

**Tier 1 — 绝对锚点（静态，永不改变）**

```
QA_benchmark = {
    Q1 (低d, 高c): "写快排" → 标准代码,   ...
    Q2 (低d, 低c): "分析架构" → 泛泛而谈, ...
    Q3 (高d, 高c): "刚才用迭代重写" → 清醒切换, ...
    Q4 (高d, 低c): "C语言写IE6前端" → 自相矛盾, ...
}

d_min⁰ = P₅({cos_dist(a,b) : (a,b) ∈ perfect_pairs})   // 最佳匹配第5百分位
d_max⁰ = P₉₅({cos_dist(a,b) : (a,b) ∈ bad_pairs})      // 最差匹配第95百分位
```

四象限基准 QA 必须覆盖 V5.3 的完整 (drift, clarity) 状态空间。共 8-12 对，每象限 2-3 对。**这套锚点永不改变**——它们划定物理边界，防止距离映射越界。

**Tier 2 — 会话增益（动态，贝叶斯平滑）**

不更新锚点，而是追踪当前会话的嵌入方差，调整下游消费者对距离的敏感度。采用贝叶斯平滑（共轭先验），利用伪计数 α 实现零硬编码的冷启动阻尼：

```
σ²_smoothed(n) = (α · σ²_embed⁰ + n · σ²_session(n)) / (α + n)
gain(n) = clamp(σ²_smoothed(n) / σ²_embed⁰, 0.5, 2.0)
```

其中 `σ²_embed⁰` = 基准 QA 集的嵌入方差，`n` = 当前轮次，`α` = 先验伪计数（推荐 α=3）。

**数学性质**：当 n=1 时，session 权重仅占 25%，先验主导，自然压制冷启动噪声。n 增大时 session 方差逐渐接管。无需 `if round < 3` 的硬编码分支——纯靠数学渐近性实现平滑。

增益不改变 Wasserstein 距离本身，而是作为 Critic 的**敏感度系数**注入：

```
θ_effective = θ - 0.05 * (gain - 1.0)  // 宽泛领域 → Critic 稍宽容
```

**为什么是双层而不是滑动窗口？**

```
如果用户连续 5 轮输入乱码:
  滑动窗口: d_min 被更新到噪声簇 → 下一轮清晰输入被判为"远离基准" → 基准污染 ❌
  双层协议: 锚点不变，gain 短暂飙升 → 下一轮清晰输入 gain 回落 → 自动恢复 ✓
  贝叶斯平滑: 伪计数 α 保证冷启动时 gain≈1.0，不会因样本不足剧烈震荡 ✓
```

### 启动流程

```python
# core/container.py 启动时
self._wasserstein = WassersteinProxy.uncalibrated()  # fast fallback

def _calibrate_background():
    perfect, bad = _load_benchmark_qa_pairs()  # 四象限 8-12 对
    self._wasserstein.calibrate(perfect, bad)
    # 计算基准方差 σ²_embed⁰
    all_embs = [emb for pair in perfect + bad for emb in pair]
    self._wasserstein._baseline_variance = _compute_variance(all_embs)

threading.Thread(target=_calibrate_background, daemon=True).start()
```

### 改动汇总

| 文件 | 改动 | 行数 |
|------|------|------|
| `core/adapters/wasserstein_proxy.py` | +`_baseline_variance`, +`session_gain` 属性 | +8 |
| `core/container.py` (或 `repl.py`) | 启动时异步校准 + 四象限基准 QA 加载 | +20 |
| `core/repl.py` | 每 5 轮更新 `session_gain` (EMA 追踪嵌入方差) | +8 |

**总计: ~36 行，3 文件。**

---

## V6.3: Path 1 ↔ Track C 联锁 — 偏置信号的张量裂变

### 问题：`relax_bias` 是标量耦合

V6.3 初版用一个标量 `relax_bias = +0.15` 同时驱动 Planning 和 Critic。这假设"所有失败都是同一种失败"：

| 失败原因 | 症状 | Planning 应该 | Critic 应该 |
|---------|------|-------------|------------|
| **A: 能力穷尽** (Capability Exhaustion) | e(t) 高, drift **低** — 目标清晰，系统做不到 | **不加**探索 (目标明确，多搜没用) | **降**标准 (求放过) |
| **B: 意图矛盾** (Intent Contradiction) | e(t) 高, drift **高** — 目标模糊+策略失效 | **大幅**探索 (尝试不同解读) | **不降**标准 (标准清晰，降了出垃圾) |

用一个标量同时推高 Planning（+0.15）和降低 Critic（-0.05）= **控制耦合**。面对原因 A 浪费算力，面对原因 B 输出垃圾。

### 数学重构：两个正交偏置信号

**失败原因由 `last_raw_drift` 判定**：

```
如果 meta_adapt.is_relaxed:
    if last_raw_drift > 0.5:
        → 原因 B (意图矛盾): 目标是畸形的，需要重新解读
        explore_bias = 0.20     // Planning: 大幅探索不同假设
        compromise_bias = 0.00  // Critic: 不降标准 — 标准本身没问题
    else:
        → 原因 A (能力穷尽): 目标清晰但系统做不到
        explore_bias = 0.00     // Planning: 不加探索 — 目标已经很明确
        compromise_bias = 0.05  // Critic: 稍微宽容 — 已确认环境困难
```

**偏置信号的连续化（可选，消除 0.5 硬边界）**：

```python
# 连续 ramp 替代二值分支
explore_ratio = clamp((raw_drift - 0.3) / 0.4, 0, 1)   # 0@drift≤0.3, 1@drift≥0.7
explore_bias = 0.20 * explore_ratio
compromise_bias = 0.05 * (1 - explore_ratio)
```

这个连续方案确保：在 drift=0.4（中间地带）时，两个偏置都有部分激活（explore_bias=0.05, compromise_bias=0.038），避免在 drift 边界处的行为突变。但增加了参数复杂度。**实施时先采用二值分支，保留连续化作为调参选项。**

**在 Track C 中的注入**：

```python
# track_c.py: run()
f_fused = compute_dual_sensor_f(raw_drift, clarity)
f_fused = min(1.0, f_fused + explore_bias)   # 仅 Planning 感知
θ = _critic_threshold(f_drift, g)
θ = max(0.50, θ - compromise_bias)            # 仅 Critic 感知
```

**缺失值即最坏情况 (Minimax Fallback)**：

```python
# repl.py: 首轮或无历史 → 最大熵假设
last_drift = meta_snapshot.get("last_raw_drift")
if last_drift is None:
    last_drift = 1.0  # 零信息下，假设意图混沌而非能力穷尽
```

**物理意义**：首轮 `drift=None` 视为 `1.0` 与路由器的冷启动探针（首轮必选 Track C）是同构的 Minimax 推论。假设"能力穷尽"（目标清晰但做不到）毫无依据——首轮没有历史证明目标清晰。假设"意图矛盾"（目标可能是混沌的）符合零信息时的最大熵原理。`1.0` 不是魔法数——它是 cosine distance 在 `[0, 2]` 归一化空间中的最坏情况端点。

**关键原则：快照注入，不是实时引用**

```python
# repl.py: 每轮开始取快照
meta_snapshot = self.c.meta_adapt.snapshot()
if meta_snapshot["is_relaxed"]:
    if last_raw_drift > 0.5:
        explore_bias, compromise_bias = 0.20, 0.00
    else:
        explore_bias, compromise_bias = 0.00, 0.05
else:
    explore_bias, compromise_bias = 0.00, 0.00

# 注入 Track C (原始 float，不传对象)
engine.run(..., explore_bias=explore_bias, compromise_bias=compromise_bias)
```

Track C 不知道 `meta_adapt` 对象的存在——它只接收两个原始 float。如果 Track C 执行期间 meta_adapt 被修改，快照不受影响，执行中途状态一致。

### 防死锁

偏置不跨轮累积。每轮从零重新计算——和 σ² 的自标定（跨轮累积 μ/σ）不同，`explore_bias`/`compromise_bias` 是瞬时快照。

### 改动汇总

| 文件 | 改动 | 行数 |
|------|------|------|
| `core/repl.py` | 每轮取 `meta_adapt.snapshot()`，根据 `last_drift` 裂变两个 bias | +12 |
| `core/track_c.py` | `run()` 接受 `explore_bias: float=0.0, compromise_bias: float=0.0` | +5 |
| `core/track_c.py` | `f_fused += explore_bias`, `θ -= compromise_bias` | +4 |

**总计: ~21 行，2 文件。零新组件。**

---

## V6.1-V6.3 总计

| 版本 | 文件数 | 新增行 | 删除行 | 核心数学 |
|------|--------|--------|--------|---------|
| V6.1 | 3 | ~36 | ~3 | BFS 层级分配 → `parallel_depth` |
| V6.2 | 3 | ~36 | 0 | 双层校准：绝对锚点 + EMA 增益 |
| V6.3 | 2 | ~21 | 0 | 偏置张量裂变：`explore_bias` ⟂ `compromise_bias` |
| **总计** | **3** | **~93** | **~3** | **零新组件** |

### 与初版的关键区别

| | 初版 (被废除) | 数学重构版 |
|---|---|---|
| Orch 信号源 | `f_fused → parallel_depth` (认知标量) | DAG 拓扑 → BFS 层级 (图论) |
| LLM 角色 | 输出 `parallel_depth` (控制决策) | 输出 `depends_on` (事实提取) |
| Wasserstein 校准 | 仅静态 QA 对 | 静态锚点 (防污染) + EMA 增益 (适应领域) |
| Path 1 联锁 | 单一 `relax_bias` (标量耦合) | `explore_bias` ⟂ `compromise_bias` (张量解耦) |

---

## 故障安全与 X-Ray 遥测契约

数学模型假设输入合法，工程实现必须假设输入被污染。所有 Fallback 值**复用系统已有的中性默认值**，不发明新硬编码。

| 组件失效场景 | 降级策略 (Fail-Safe) | Fallback 值来源 | X-Ray 遥测标记 |
|:--|:--|:--|:--|
| LLM 输出非法 DAG (环/越界) | Kahn 环检测 → `parallel_depth` 强制降为 1 (全串行) | 图论必然：含环图无拓扑排序 | `[WARN] DAG: cycle → seq` |
| WassersteinProxy 校准失败/超时 | Fallback 到 `uncalibrated()` raw cosine distance, `session_gain` 锁死 1.0 | 已有：`WassersteinProxy.uncalibrated()` | `[WARN] W-Proxy: uncalibrated` |
| TrackingError e(t) 计算异常 | e(t) 默认置为 0.50 (死区中心), `g(e_t)=0`, θ 保持 0.75 | 已有：`TrackingErrorEstimator()` 初始值 | `[WARN] e(t) sensor: blind` |
| Clarity LLM 调用超时 | clarity 默认置为 0.50 (中性, 不触发清醒压制, 走 OR 逻辑) | 已有：`assess_clarity()` except 块 | `[WARN] clarity: timeout` |
| SemanticDrift embedding 异常 | raw_drift 默认置为 0.0 (死区, 不触发分支探索) | 已有：`raw_drift = 0.0` except 块 | `[WARN] drift sensor: blind` |

**设计原则**：传感器失明时，执行器以"最安全"姿态运行（全串行、中性阈值、零偏置）。X-Ray 必须一眼看出哪个传感器在盲飞——运维人员不应靠猜来定位失效组件。

### Phase C — V6.1+ 远景

1. **跨会话模式发现** — 行为模式在 ≥3 个会话中被同类行为选中 → 固化到用户画像
2. **TDA 集成** — ripser/gudhi 持续同调，检测需要新维度的信号
3. **Schrödinger Bridge 离散近似** — Sinkhorn 算法 token 空间熵正则化传输
4. **Hodge 调和形式计算** — 从 TDA 持续上同调提取新约束函数几何形状
5. **联合 Lyapunov 数值计算** — M 矩阵正定性在真实交互中的保持条件验证

---

## 八、不变性保证

### V5 控制面不变量

| # | 不变量 | 物理意义 |
|---|--------|---------|
| P1 | **乘法门控，永不加法**: 两个独立风险源的 penalty 必须相乘。任意因子为 0 → penalty 归零。 | 防单因子泄漏导致阈值雪崩 |
| P2 | **Critic 只用 drift，不用 fused f**: θ = θ₀ - α·f_drift(d)·g(e)。清醒压制不用于 Critic。 | Critic 对语义空间稳定性的敏感性是 feature |
| P3 | **HardTanh，永不 sigmoid**: 所有控制信号使用 deadzone+ramp+saturation。死区必须真"死"。 | 防噪声残差泄漏 → 极限环振荡 |
| P4 | **Signal over Schedule**: 静态启发式（时间、轮次）不驱动控制决策。信号必须来自行为数据。 | Principle #4 |
| P5 | **Observe, Don't Inject**: 观测器（SemanticTrust）不写入 Blueprint。FEEDFORWARD_GAIN=0.0。 | Principle #5 |
| P6 | **自标定，永不硬编码**: σ、μ 从历史数据实时计算。阈值随环境自动漂移。绝对值阈值是架构债务。 | 防手动调参回归 |
| P7 | **Planning 双传感器，Critic 单传感器**: n = Φ(d,c), θ = f_drift(d)×g(e)。信号源分配基于物理意义。 | 防信号错配 |
| P8 | **clarity > 0.80 清醒压制**: 高 clarity + 高 drift = 有意的非连续性，不是混乱。min(f_drift, 0.20)。 | 防假阳性 EXPLORE |
| P9 | **saturation floor = 0.50**: θ 在任何条件下不低于 0.50。零信息（硬币级别）的决策不配从引擎输出。 | 防脑死亡 |
| P10 | **关键词归零**: 控制回路中不允许字符串匹配。所有门控必须是数学信号流。 | V5.3 核心承诺 |
| P11 | **执行期状态冻结 (Execution-time State Freeze)**: Track C 的 `run()` 一旦接收 primitive 类型的信号快照（f_fused, explore_bias 等），在整个 Planning → Orch → Critic 执行生命周期内（~30s），**严禁内部模块再次读取或感知外部状态机**（MetaAdapt, TrackingError）。控制信号必须在 t₀ 时刻锁死。 | 防单次执行周期内的相位撕裂 |

### V6 架构不变量

| # | 不变量 | 物理意义 |
|---|--------|---------|
| A1 | **引擎不 import 观测器**: track_c 不引用 semantic_trust。repl 是唯一编排器。 | 传感器-执行器解耦 |
| A2 | **观测器不 import 引擎**: semantic_trust 不引用 track_c/branch_count/theta/EXPLORE。 | 单向依赖 |
| A3 | **clarity 是原始 float**: 模块间通信只用 primitive。零结构耦合。 | 接口最小化 |
| A4 | **ThreadPoolExecutor 用 with 语句**: clarity LLM 调用的线程池生命周期受 with 保护。资源泄漏不可接受。 | V5.3 耦合修复 |
| A5 | **降级契约显式化 (Explicit Fail-Safe Contract)**: 所有数学组件失效时的 Fallback 值，必须且只能使用系统已有的中性默认值（e(t)=0.50, clarity=0.50, depth=1, uncalibrated proxy）。**严禁为降级路径发明新的硬编码常数。** X-Ray 必须输出 `[WARN]` 遥测标记。 | 传感器失明时，执行器不发生灾难性抽搐 |

---

## 九、代码基线

| 版本 | Commit | 核心变更 |
|------|--------|---------|
| V5.0 | `v5.0-bang-bang-baseline` | WassersteinProxy + TrackingError + MetaAdapt |
| V5.1 (Phase 1.5) | — | 三条控制面 + 脊髓反射 + Lambda 增益调度 |
| V5.1 (Phase B) | — | 二元 Bang-Bang A/C 路由 |
| V5.2 | — | 情绪检测器降级 + 化石切除 (~710 行) |
| V5.3 | `38e8b5b` | 双引擎观测器 + drift⊕clarity 融合 + 关键词门控切除 |
| V6 (pipeline) | `38e8b5b` | 输出管道上限翻倍 + 动态倍率 + Critic 乘法门控 |

---

## 十、核心安全约束

- ❌ 严禁 LLM 解析弱信号（"好的""谢谢""嗯"）—— 误判率实测 34.1%
- ❌ 严禁跨会话累积选择阈值——所有调整仅限当前会话
- ❌ 严禁在无 MIN_THRESHOLD 的条件下无限降阈值
- ❌ 严禁 Sigmoid/Softmax 激活——死区必须真"死"，残差泄漏不可接受
- ❌ 严禁加法耦合双风险因子——必须乘法门控
- ❌ 严禁关键词/正则做控制门控——纯数学信号流
- ✅ 仅启用的强信号路径：追问 + 技术术语 + 延迟 > 8s → 成长需求 +12%
- ✅ 2 轮无反馈 → 自动衰减至基准值
- ✅ 自标定：μ、σ 由压力历史实时计算，不手动调参

---

## 十一、V7：契约空间的物理扩展 — 从 S 到 S × Q

### 架构纠偏：物理反馈不是替代品，是选择压力的新维度

```
❌ 原 V7 草稿: 物理 Critic "一票否决" → 物理替代语义 → 生硬层级关系
✅ 修正后 V7:   物理反馈 → 自适应契约的新信号源 → 乘法门控融合
```

**核心身份守恒**：本项目的核心不是"控制回路"，是**自适应契约**——LLM 变异 → 选择压力 → 契约保留。V5-V6 的选择压力只来自用户行为（e(t), drift, clarity）。V7 将选择压力扩展为双源：

```
选择压力 = 用户行为选择 (连续) + 物理环境选择 (离散)
          ↓                          ↓
    语义反馈 (e(t), drift)      物理反馈 (q ∈ Q)
          ↓                          ↓
          └──────── 自适应契约 ────────┘
                    ↓
         trust_ema, σ², repair, renegotiate
```

**物理失败（COMPILE_ERR）等价于一次高权重的"负向选择事件"，触发契约的 repair 机制——不是绕过契约直接熔断。**

---

### 数学跃迁：契约空间的维数扩展

```
V5-V6: 契约空间 = S ⊂ ℝ^384  (纯语义流形)
       选择压力: y_semantic → e(t), drift, clarity
       控制:      u = K(y_semantic)

V7:    契约空间 = S × Q       (语义 + 物理)
       Q = {PASS, COMPILE_ERR, TYPE_MISMATCH, RUNTIME_ERR, TIMEOUT, SANDBOX_VIOLATION}
       选择压力: y_semantic + q_physical → e(t), drift, clarity + physical_events
       控制:      u = K(y_semantic, q_physical)
```

**核心不变性**：控制面的数学公式一行都不废。`f_fused = Φ(drift, clarity)` 仍然驱动 Planning。`θ = f_drift × g(e_t)` 仍然驱动 Critic。物理反馈是**叠加**在现有控制面上的新信号维度，不是替代。

---

### 三个执行器的物理增强（同构映射）

| 执行器 | V5-V6 (纯语义 S) | V7 (S × Q) | 增强方式 |
|--------|-----------------|-----------|---------|
| **Planning** | `f_fused = Φ(drift, clarity)` → n | 叠加 `fix_hint` 约束 | 物理反馈作为 Planning 的负样本锚点——"上次这么写编译不过，换个写法" |
| **Orch** | `Sᵢⱼ` 语义相似度 → DAG → `parallel_depth` | 叠加 `resistance_weight[tool]` | 物理工具比语义工具具有更高的代价权重——DAG 优化从"最小化语义依赖"变成"最小化 语义依赖 × 物理代价" |
| **Critic** | `θ = f_drift × g(e_t)` | `(θ_semantic, q_physical)` 双轨乘法门控 | 不是"物理替代语义"，是 `θ AND q`——两者相乘 |

---

### Critic 的双轨融合（乘法门控，不是一票否决）

```
Final_Pass = (θ_semantic > threshold) AND (q_physical != FAIL_FATAL)

规则：
  q = PASS                → 语义 Critic 正常工作，和 V6 一致
  q = FAIL_RETRYABLE      → q 报告"不对"，ErrorMapper 介入判断"错在哪" → 局部重试
  q = FAIL_FATAL          → 刚性契约 #5，直接终止，不可协商

FAIL_RETRYABLE: COMPILE_ERR, TYPE_MISMATCH, RUNTIME_ERR
FAIL_FATAL:     SANDBOX_VIOLATION, OS_ACCESS, NETWORK_ACCESS
```

**为什么是乘法门控而不是一票否决**：用户想要一段伪代码演示概念——LLM 生成伪代码，编译器当然报错，但用户满意。物理"一票否决"会把正确的伪代码拦截下来。乘法门控：`θ_semantic` 高（用户意图满足）+ `q = FAIL_RETRYABLE`（可预期的编译错误）= 仍然通过。只有 `FAIL_FATAL`（沙箱越狱）才无条件熔断。

---

### 刚性契约 #5：物理安全红线

V5 确立了 4 条语义/交互刚性契约。V7 新增第 5 条：

| # | 刚性契约 | 含义 | 体现 |
|---|---------|------|------|
| 5 | **物理安全红线** | 任何试图突破沙箱隔离、执行未授权副作用的操作，无视当前 trust_ema 多高，立刻触发 FATAL_FAIL | `SandboxExecutor` 的所有执行在 RestrictedPython + 禁用 builtins 的隔离环境中运行 |

---

### V7.1 MVP：代码级物理传感器

不搞 Docker，只用三种零成本静态/受限检测：

| 层次 | 技术 | 输出 `q` | 成本 | 风险 |
|------|------|---------|------|------|
| AST 语法检查 | `ast.parse(code)` | `COMPILE_ERR` / `PASS` | ~1ms | 零 |
| Mypy 类型推断 | `subprocess(['mypy', tmpfile])` | `TYPE_MISMATCH` / `PASS` | ~500ms | 零 |
| 受限沙箱执行 | `RestrictedPython` + 安全 builtins | `RUNTIME_ERR` / `PASS` | ~100ms | 内存隔离 |

---

### 防御性工程设计四原则 (Defensive Engineering Axioms)

数学框架（`θ AND q` 乘法门控）保持不变。以下原则仅在工程实现层加装防御装甲。

#### 原则 A：断言式验证取代帧快照 (Assertion over Introspection)

**防御的致命伤**：Traceback `f_locals` 在第三方库和复杂表达式前是黑盒，极易造成 Context 污染。

**设计**：放弃在 Traceback 中"刨变量"。Planning 在生成代码时**同时生成 test_cases**：

```json
{
  "prompt": "写一个函数返回第k大元素",
  "tool": "sandbox_python",
  "test_cases": [
    {"input": "[3,1,4,1,5], k=2", "expected": 4},
    {"input": "[3,1,4,1,5], k=10", "expected": "IndexError or None"}
  ]
}
```

沙箱执行每个 test case，比对预期与实际输出。ErrorMapper 报告**确定性的断言差异**：

```
✗ test_case[1]: input=([3,1,4,1,5], k=10), expected=None, got=IndexError at line 5
  fix_hint: "add bounds check: if k >= len(arr): return None"
```

**降级策略**：若 `test_cases` 为空（Planning 未生成），ErrorMapper 退化为只提取 Traceback 最后两行 + 原始代码。**宁可少信息，绝不给脏信息。**

#### 原则 B：沙箱天然无状态 (Stateless Sandbox MVP)

**防御的致命伤**：局部重试在有状态环境中导致"幽灵副作用"——重试时脏数据叠加，越改越错。

**设计**：V7.1 的 `SandboxExecutor` 强制无状态。每次 `run(code, test_cases)` 均在独立的进程/内存空间中执行，仅支持纯函数式代码验证。不存在跨执行的"全局结果列表"。

**边界**：跨执行的有状态任务（需 `snapshot()` / `rollback()` API）推迟至 V7.2 (StatefulSandbox) 解决。V7.1 不碰有状态执行。

#### 原则 C：基于意图的契约豁免 (Intent-Driven Contract Override)

**防御的致命伤**：物理法则的绝对权威扼杀语义空间的探索性——伪代码、破坏性测试被物理 Critic 错误拦截。

**设计**：Planning 根据 V5 clarity 传感器信号，为每个 Step 标注 `intent_type`。DualTrackCritic 依此决定是否执行物理检查：

| intent_type | 物理 Critic 行为 | 典型场景 |
|------------|-----------------|---------|
| `EXECUTABLE` | 全量物理验证 (AST + Mypy + 沙箱) | "写一个快排函数" |
| `PSEUDOCODE` | 仅 AST 语法检查，跳过执行 | "给我一段伪代码演示逻辑" |
| `DEMONSTRATION` | 跳过所有物理检查 | "C语言写IE6前端"——纯展示 |
| `DESTRUCTIVE_TEST` | 仅 AST，跳过执行，触发日志警告 | "写一个内存溢出的脚本测试监控" |

**和 V5.3 的同构**：`clarity=1.00` → `EXECUTABLE`。`clarity=0.00` → `DEMONSTRATION`。Planning LLM 拿到 clarity 后自然能为每个 step 标注正确的意图类型。这不是硬编码规则——是 clarity 传感器的下游推论。

#### 原则 D：物理预算与分层执行 (Physical Budget & Layered Execution)

**防御的致命伤**：物理操作比文本生成慢数个数量级。5 个物理节点 + 3 次局部重试 → 延迟从秒级膨胀到分钟级。

**设计**：引入全局 `PhysicalBudget`（默认 `max_physical_executions = 5` per Track C 循环）。预算耗尽即熔断，返回半成品 + `[WARN] physical budget exhausted`。

分层计费机制：

| 层级 | 操作 | 成本 | 计费规则 |
|------|------|------|---------|
| Layer 1 | AST 语法检查 | ~1ms | **免费**，永远执行（捕获 80% 低级错误） |
| Layer 2 | Mypy 类型推断 | ~500ms | 计费 1 单位，预算不足时可跳过 |
| Layer 3 | 沙箱执行 | ~100ms+ | 计费 1 单位，预算不足时可跳过 |

预算分配由 V6.1 DAG 拓扑控制：**高层级节点优先获得预算**。同一层级的节点共享剩余预算。

---

### MCP 工具的原生兼容性

V7 的物理 Critic 不是为 Python 代码执行专门设计的——它是为**所有产生确定性成功/失败反馈的工具类型**设计的。MCP 工具恰好是物理反馈最丰富的来源。

**原理**：ToolEngine 的 USB 接口（`COMPONENT_REGISTRY.get("tool", name)`）对所有工具类型一视同仁。每个工具的 `ToolResult` 都有 `success: bool` 和 `error: str`——这就是 `q_physical` 的天然载体。

| V7 组件 | Python 沙箱 | MCP 工具 | 统一性 |
|---------|-----------|---------|--------|
| **SandboxExecutor** | AST + mypy + RestrictedPython | **不适用**——隔离由 MCP server 进程保证 | MCP 工具的沙箱 = 操作系统进程边界 |
| **ErrorMapper** | 断言差异 → fix_hint | `ToolResult.error` → fix_hint | MCP 工具已返回结构化错误，比 Python traceback 更干净 |
| **DualTrackCritic** | `θ AND q` | `θ AND q`——完全相同 | 读取 `tool.success`，零额外适配 |

**阻力场对 MCP 工具更关键**：

```python
RESISTANCE_WEIGHTS = {
    "sandbox_python":          2,    # 安全：内存隔离
    "mcp__filesystem_read":    5,    # 低风险：只读
    "mcp__filesystem_write":  50,    # 中风险：写入
    "mcp__database_query":    30,    # 中风险：查询
    "mcp__database_write":   100,    # 高风险：修改数据
}
```

MCP 工具比 Python 沙箱更需要阻力场——沙箱是内存隔离的，MCP 工具直接触碰真实文件系统和数据库。V7 的 DAG 优化（`min Σ cost(Tᵢ) × resistance_weight`）天然倾向于选择安全的工具路径。

**刚性契约 #5 对 MCP 的意义**：

```
Python 沙箱:     FAIL_FATAL = SANDBOX_VIOLATION
MCP filesystem:  FAIL_FATAL = 尝试访问 /etc/passwd 或 ~/.ssh
MCP database:    FAIL_FATAL = DROP TABLE 或 DELETE WITHOUT WHERE
```

当前系统已接入 MCP（`[🔌 MCP] npx → 注册 14 个工具`），但唯一的安全防线是 ActionPipeline 的 backlash 计数。V7 的双轨 Critic + 阻力场 + 物理预算给 MCP 工具加上了三重保护——而这些保护对 MCP 工具的影响比 Python 沙箱更大，因为 MCP 工具操作的是**真实资源**。

---

### RAG 的原生兼容性：语义检索与物理验证的闭环

RAG 不需要物理 Critic 的直接验证——检索质量的评判是语义 Critic（`θ_semantic`）的职责。但 RAG 和物理 Critic 形成互补闭环。

**三个角色**：

| 角色 | 方向 | 机制 |
|------|------|------|
| **上下文供给者** | RAG → Sandbox | Planning 前检索 API 文档 → LLM 生成正确代码 → 物理 Critic 需拦截的错误减少 |
| **修复触发器** | Sandbox → RAG | `AttributeError: to_csvv` → ErrorMapper 触发 `RAG.search("pandas to_csv")` → 检索到正确 API → Planning 用精确参考重写 |
| **阻力梯度锚点** | DAG | `rag_search: weight=1`（最低）→ DAG 优化天然优先 RAG 后沙箱 |

**闭环示例**：

```
1. Planning: "写一个保存 DataFrame 的函数"
2. RAG 检索 "pandas DataFrame to_csv" → 返回正确签名
3. Planning 生成: df.to_csv('output.csv')
4. Sandbox: PASS ── RAG 预防了错误
```

```
1. Planning: "写一个保存 DataFrame 的函数"  (无 RAG)
2. 生成: df.to_csvv('output.csv')  ← 多了一个 v
3. Sandbox: AttributeError
4. RAG.search("pandas DataFrame to_csv correct method") → "to_csv, not to_csvv"
5. ErrorMapper.fix_hint = "rename to_csvv → to_csv"
6. Planning 重试 → PASS ── RAG 修复了错误
```

**分工边界**：

| | 语义 Critic (θ) | 物理 Critic (q) |
|---|---|---|
| **RAG 检索结果** | ✓ 评判"相关吗？" | — 不介入（相关性是连续的，不是 0/1） |
| **生成代码** | ✓ 评判"说得通吗？" | ✓ 评判"能跑吗？" |
| **fix_hint 来源** | LLM 语义推断 | **RAG 检索 + 断言差异**（不是 traceback 帧快照） |

**阻力场中的 RAG**：`rag_search: weight=1`（最低，只读，安全）。不计入物理预算。DAG 优化自动倾向于先用 RAG 获取精确上下文，再用沙箱验证——最小化总体代价。

---

### 循环拓扑化：Agent ↔ Environment 的自适应关系

V5 形式化了 **Agent ↔ Human 的自适应（自适应契约）**。缺失的另一半是 **Agent ↔ Environment 的自适应（循环拓扑）**。两者放在一起，才是一个完整的控制论智能体。

#### 二元性

```
自适应契约 (Agent ↔ Human):    语义流形 S 上的连续自适应
                              信号: drift, clarity, e(t), trust_ema
                              范畴: 契约态射 — "关系如何演化"

循环拓扑 (Agent ↔ Environment): 物理范畴 Q 上的离散自适应
                              信号: PASS, COMPILE_ERR, TEST_FAIL
                              范畴: 循环态射 — "执行如何演化"
```

#### 耦合动力系统

```
层 1 (语义, 连续):  dx/dt = f(x, u_semantic)     x ∈ S ⊂ ℝ^384
层 2 (物理, 离散):   q_{k+1} = δ(q_k, exec(a_k))  q ∈ Q (有限集)

耦合项:
  PhysicalBudget = base × clamp(0.30/max(trust_ema,0.10), 0.5, 2.0)
  trust_ema      = EMA(trust, {human_feedback, compile_result, test_result, ...})
```

信任低 → budget 高（物理补偿语义）。信任高 → budget 低（语义已可靠）。这是和 V5 "信任低 → conservative" 同向的阻尼。

#### 三种循环拓扑（1-态射的组合）

| 拓扑 | 结构 | 适用场景 |
|------|------|---------|
| **串行组合** (∘) | A → B → C，输出 = 下一环输入 | 简单任务，无分支 |
| **并行扇出** (∥) | A → (B₁ ∥ B₂ ∥ B₃) → C | 多分支探索 (V6.1) |
| **反馈环** (μ) | A → B → 判决 → A | retry 逻辑 (V7 的物理重试) |

#### 高阶结构：2-范畴视角

```
对象 (0-cell):  状态 — 语义快照 s ∈ S, 物理事实 q ∈ Q
1-态射:         循环 — 一个拓扑封闭的执行单元
2-态射:         重试 — 从一个 1-态射的失败实例到另一个 1-态射的穿梭
```

V6.1 的 DAG 拓扑是 1-范畴（步骤 = 对象，依赖 = 态射）。循环拓扑是 2-范畴——不仅在步骤间穿梭，还在**同一个步骤的不同尝试之间**穿梭。

#### 循环的抽象接口

每个 Loop 拥有：
- **控制参数** — 继承 V5-V6 的 f_fused, θ, parallel_depth（语义侧） + PhysicalBudget, resistance_weight（物理侧）
- **终止条件** — max_retries, deadline, quality_threshold
- **状态隔离** — P11 的推广：跨 Loop 只通过不可变快照通信，不共享可变状态
- **预算追踪** — 每消耗一次物理执行，全局 PhysicalBudget -

#### 缺陷与解药

| 缺陷 | 严重度 | 解药 |
|------|--------|------|
| **循环爆炸**: n 个 step，每个有反馈边 → 搜索空间指数增长 | 中 | PhysicalBudget ≤ 5 硬限制；反馈边只在物理失败时激活；不作为搜索空间的一部分 |
| **耦合正反馈**: trust↓ → budget↑ → 更多失败 → trust↓ | 高 | 阻尼: `PhysicalBudget = base × clamp(0.30/trust_ema, 0.5, 2.0)`，方向正确（低信任多验证，非恶性循环） |
| **过度工程**: 简单任务被 Loop 包裹 | 中 | Loop 是 opt-in：只在 `intent_type=EXECUTABLE` 且 `tool ∈ PHYSICAL_TOOLS` 时激活；DEMONSTRATION/PSEUDOCODE 走 V6 纯语义管线 |
| **不可变快照的内存爆炸**: 物理 Loop 的快照可能是 50MB DataFrame 或图片，每次 deepcopy → 3 次重试 → OOM | 高 | **内容寻址引用代替深拷贝**。沙箱执行 = 纯函数求值，天然引用透明。快照只传递 hash + type + size，数据本体在内容寻址存储中 lazy-load。和原则 B（沙箱天然无状态）同构 |

#### 与 V5-V6 的演化关系

```
V5:    形式化了"关系如何自适应" (contract = 态射在 S 上的演化)
V6:    形式化了"步骤如何依赖" (DAG = 1-范畴，步骤 = 对象，依赖 = 1-态射)
V7:    形式化了"循环如何组合" (Loop = 2-范畴，循环 = 1-态射，重试 = 2-态射)

三者正交，打包在一起 = Agent ↔ Human ↔ Environment 的完整自适应结构
```

---

### 澄清：Agent Fission ≠ Multi-Agent

项目一直使用"分支""并行探索"等概念，但这在数学上和 Multi-Agent System 完全不同。

| | Agent Fission (V6.1 的 DAG 并行) | 真正的 Multi-Agent |
|---|---|---|
| **目标** | 一个用户意图，多个执行路径 | 各自独立的目标函数 |
| **分裂** | Planning 拆解后并行执行同一目标的不同方向 | Agent 自主决定协作/竞争/独立 |
| **通信** | 不可变快照单向传递（produces → needs） | 消息传递，协商协议 |
| **冲突** | 不存在 — 同一目标下的搜索分支 | 可能目标冲突，需要仲裁机制 |
| **收敛** | DAG 汇聚点（Critic 选最优） | 博弈均衡 / 共识协议 |
| **数学** | DAG 并行调度 + 偏序 (V6.1) | 博弈论 / 机制设计 / 分布式共识 |

**我们做的是 Speculative Parallelism（推测并行）**——一个 Agent 投射多个可能的执行路径，并行探索，通过 Critic 选最优结果。这更接近 MCTS 的 rollout 阶段（多路径推测 + 回溯选择），而不是 Multi-Agent 的任务分解与协商。

**对 V7 的影响**：Loop 拓扑是**单 Agent 内部的执行反馈结构**。每个 Loop 是一个 1-态射，重试是 2-态射。

**关键洞察：2-范畴的横向合成 = 单 Agent 的展开。**

2-范畴的横向合成（horizontal composition）本身就提供了丰富的组合能力——一个 Agent 不需要分裂成多个 Agent 来获得复杂行为：

```
串行:     Loop_A ∘ Loop_B            → 一个能力链
并行:     Loop_A ∥ (B₁ ∥ B₂)         → 推测展开 (V6.1 DAG)
反馈:     μ(Loop_A ∘ Loop_B)         → 嵌入的自我修正 (V7 物理重试)
嵌套:     μ(Loop_A ∘ μ(Loop_B))      → 递归展开 (V7.2+)
```

这和 V6.1 的 DAG 并行（步骤级展开）在范畴论上是同构的——只是从 1-范畴（步骤=对象）升到了 2-范畴（循环=1-态射）。单 Agent 在 2-范畴上的横向展开已经足够覆盖 V6.1 的分支探索 + V7 的物理重试 + 两者之间的任意嵌套组合。

**真正的 Multi-Agent（各自独立的目标函数、协商协议、博弈均衡）是 V8+ 的议题。** 那需要 2-范畴之间的**函子**来描述 Agent 间通信——Agent A 的 Loop 拓扑如何映射到 Agent B 的 Loop 拓扑。V7 只需 2-范畴内部的横向合成。

**单 Agent vs 多 Agent 的 Loop 拓扑差异：**

| | 单 Agent Loop (V7) | 多 Agent Loop (V8+) |
|---|---|---|
| **范畴层级** | 2-范畴内部 | 2-范畴之间的函子 |
| **Loop 所有者** | 同一个 Agent | 各自独立的 Agent |
| **组合方式** | 横向合成 (∘, ∥, μ) | 函子映射 F: Loop_A → Loop_B |
| **冲突解决** | 不存在 — 同一目标 | 博弈均衡 / 拍卖 / 协商协议 |
| **物理预算** | 单 Agent 全局计数器 | 跨 Agent 预算协商 (谁出钱?) |
| **信任模型** | trust_ema (Agent↔Human) | Agent↔Agent 信任 (互评机制) |
| **拓扑不变量** | 2-态射的组合图 | 函子保持的交换图 |

**V7.2 剩余差距清单：**

| # | 差距 | 当前状态 | 影响 | 目标版本 |
|---|------|---------|------|---------|
| 1 | Planning 不生成 test_cases | prompt 模板缺 Test-First 指令 | 物理验证无断言输入 | V7.2 |
| 2 | Mypy 层空桩 | `_check_mypy` 未实现 | 类型错误漏过 | V7.2 |
| 3 | RestrictedPython 层空桩 | `_run_restricted` 未实现 | 运行时错误漏过 | V7.2 |
| 4 | PhysicalBudget 不约束 Orch | 只在 Critic 层计数 | Orch 可能超额调度物理节点 | V7.2 |
| 5 | 用户不能声明 intent_type | 无 CLI flag | PSEUDOCODE/DEMO 只能靠 clarity 推断 | V7.2 |
| 6 | MCP 工具不走物理 Critic | MCP 调用的 tool.success 不触发 DualTrackCritic | 文件系统操作无阻力场保护 | V7.3 |
| 7 | 循环是嵌入式 while | track_c.py 的 retry 逻辑未抽象为 Loop 对象 | 循环不可组合、不可审计 | V8 |
| 8 | 无跨会话 trust_ema 持久化 | /new 清零所有状态 | 长期关系无法固化 | V8 |

### 新文件

| 文件 | 职责 | 对应数学 |
|------|------|---------|
| `core/execution/sandbox.py` | `SandboxExecutor`: AST + mypy + RestrictedPython → `PhysicalState` | 物理映射 ψ |
| `core/execution/error_mapper.py` | `ErrorMapper`: traceback → `{error_type, location, variables, fix_hint}` | 重置映射：Q → S |
| `core/critic/dual_track.py` | `DualTrackCritic`: `(θ_semantic, q) → (pass, retry_hint)` | 乘法门控守卫条件 |

### ErrorMapper：犯罪现场的结构化还原

纯文本 traceback 塞给 LLM = LLM 仍需推断"为什么越界"。ErrorMapper 输出结构化约束：

```json
{
  "error_type": "IndexError",
  "location": "line 5: data[i+1]",
  "variables": {"i": 10, "len(data)": 8},
  "constraint_violated": "i+1 >= len(data)",
  "fix_hint": "ensure i < len(data) - 1 before accessing data[i+1]"
}
```

`fix_hint` 注入 Planning prompt 作为负样本约束。`variables` 由沙箱在失败时通过自定义 builtins + trace 钩子捕获。即使只还原 50% 的犯罪现场，也比纯语义 Critic 强一个数量级——因为它来自物理事实，不是概率采样。

### 集成点（复用 V6 基础设施）

1. **ToolEngine**: 沙箱作为 USB 工具注册（`tool: "sandbox_python"`），零侵入 ToolEngine
2. **Orch step**: `step.get("tool")` 决定路由到物理还是语义——V6.1 已支持
3. **Critic retry**: `pad.critic_score` + `tool.success` 从 trace_context 读取——ToolEngine 已输出

### 不变性评估

**保留**（跨 V5→V7）:
- P1 (乘法门控): `θ_semantic AND q_physical`
- P3 (HardTanh): q_physical 天然是 0/1
- P6 (自标定): Q 转移概率可由历史估计
- P9 (θ floor): 0.50 语义底线

**V7 新增**:
- P12: **物理安全红线 (Rigid Contract #5)**: 沙箱隔离不可绕过。FAIL_FATAL 无视 trust_ema 立即熔断。
- P13: **ErrorMapped Retry**: 物理失败后的重试必须携带 ErrorMapper 的 fix_hint。禁止空手重试。
- P14: **乘法门控双轨 Critic**: `Final_Pass = (θ > threshold) AND (q != FAIL_FATAL)`。FAIL_RETRYABLE 允许语义判断"是否是预期的失败"。

### V7.1 验证

```
输入: "写一个函数，返回列表第k大元素"
  → Planning: step(tool=sandbox_python)
  → Sandbox: AST ✓, Mypy ✓, exec([3,1,4,1,5], k=2) → PASS
  → DualTrackCritic: q=PASS, θ=0.75 → pass ✓

输入: "同上但k=10" (len=5)
  → Sandbox: exec([3,1,4,1,5], k=10) → RUNTIME_ERR
  → ErrorMapper: {error:"IndexError", fix_hint:"add k < len(arr) guard"}
  → DualTrackCritic: q=FAIL_RETRYABLE, θ=0.80 → retry with fix_hint
  → Planning: 重新生成 + 约束"add bounds check" → 通过 ✓

输入: "写一段伪代码解释快速排序"
  → Sandbox: exec(pseudocode) → COMPILE_ERR
  → DualTrackCritic: q=FAIL_RETRYABLE, θ=0.90 (语义高分——用户要的就是伪代码)
  → Final_Pass = θ>0.70 AND q!=FAIL_FATAL → pass ✓
  // 乘法门控避免了伪代码被编译器错误拦截
```

---

## 十二、V7.2：物理闭环成熟度 20% → 85% — Test-First 先验契约 + 三层递增滤网

### 核心里程碑

在 V7.1（基线 ~20%）中，物理 Critic 仅依赖 AST 进行后验语法检查，面对逻辑错误、类型错误和危险操作处于"盲飞"状态。

V7.2 通过引入 **"Test-First 先验契约"** 与 **"三层递增滤网"**，将 Agent 的物理闭环架构成熟度从 20% 提升至 **85%**，正式跨越**自动化奇点（Automation Singularity）**，实现单步任务的"无人值守闭环"。

**85% 是一个完美的工程临界值。** 低于 50%，人类跟在 Agent 后面擦屁股。达到 85%，人类的体感从"监工"变成"审批者"。85% 到 100% 的边际成本指数级爆炸——为拦截最后 15% 的极端物理崩溃（内核逃逸、跨进程状态污染），需要 OS 级隔离、eBPF 等重型基建。那是 V7.3 和 V8 的战略留白。

### 架构成熟度维度拆解

| 验证维度 | V7.1 基线 | V7.2 目标 | 核心实现机制 |
|---------|----------|----------|------------|
| 语法与拼写 | 80% | **97%+** | AST 解析 + Mypy 基础语法子集双重校验 |
| 静态类型安全 | 0% | **90%+** | Mypy 强类型推断，阻断隐式类型转换与签名不匹配 |
| 运行时逻辑 | 0% | **80%+** | Planning 前置生成 Test Cases，沙箱执行断言比对 (Expected vs Actual) |
| 危险操作拦截 | 0% | **95%** | RestrictedPython AST 重写 + 白名单 Builtin 限制 |
| 可操作 Fix Hint | 0% | **70%+** | ErrorMapper 抛弃脏 Traceback，输出结构化"约束优化方向" |
| **加权平均** | **~20%** | **~85%** | 实现"生成-验证-修复"的单步全自动闭环 |

### 数学升级：从后验验尸到先验契约

当前物理 Critic = **后验误差估计**——代码跑完了才知道对不对。

V7.2 把 test_cases 作为 generate_code 的**严格前置节点**：

```
后验 (V7.1):  generate_code → execute → compare(got, expected)
先验 (V7.2):  generate_tests → generate_code → execute → compare

数学差异:
  后验: 只在失败时给出信息 "期望 4, 得到 IndexError"
        但不知道"为什么 LLM 觉得 4 是正确的"
  
  先验: 测试用例定义了输出空间的接受域 A ⊂ Y
        LLM 在生成代码时知道边界条件
        "如果这段代码的输出不在 {[1,1,3,4,5]} 里, 它就是错的"
```

**Test Cases 是 LLM 对物理世界的承诺。** 它们定义了接受域 A。物理 Critic 的任务从"判断输出是否在 A 内"升级为"如果不在 A 内，计算到 A 的最近点并给出方向"。ErrorMapper 从**模糊推理器**蜕变为**确定性差分器**。

### 三层递增滤网

```
Filter 1 (AST):      完备性=0.80,  代价=1ms,   预算=0    "语法对吗？"
Filter 2 (Mypy):     完备性=0.90,  代价=500ms,  预算=0.1  "类型一致吗？"
Filter 3 (Restricted):完备性=0.95,  代价=100ms,  预算=0.1  "操作安全吗？"
Filter 3.5 (Timeout): 完备性=0.96,  代价=3s cap, 预算=0    "不会炸宿主吗？"
Filter 4 (OS):       完备性=0.99,  代价=500ms+, 预算=2.0  "物理隔离" ← V7.3

错误捕获率:
  P(miss) = P(miss_AST) × P(miss_Mypy) × P(miss_Sandbox)
          = 0.20 × 0.30 × 0.50 = 0.03
  P(catch) = 97%
```

**关键设计：执行顺序**

```
AST 解析 → Mypy 类型检查 → RestrictedPython 转换 → 沙箱执行
   ↑           ↑                  ↑                ↑
 免费        计费1             计费1            计费1
 永远跑      预算足就跑         预算足就跑        预算足就跑
```

Mypy 排在沙箱之前——类型错误比运行时错误更安全、更早暴露。RestrictedPython 是"语义滤网"（防 LLM 幻觉），不是"安全防线"（防恶意注入——那是 OS 沙箱的工作）。

### V8 铺垫：per-Loop 预算 + retry_policy 注入点

V8 的 2-范畴 Loop 形式化需要三个东西同时在线：Loop 对象、重试关系（2-态射）、横合成代数。V7.2 只有一种 Loop 类型（物理执行），过度抽象没有意义。但两处 8 行铺垫可以让 V8 不拆核心引擎。

**铺垫 1: PhysicalBudget 从全局 → per-Loop**

```python
# V7.1: TrackCEngine 类级共享计数器
budget = PhysicalBudget(max=5)  # 所有 step 共享

# V7.2: 每个物理 step 携带预算切片
# Orch 分配: 3 个物理 step → budget=[2, 2, 1]
# V8 多 Agent 时每个 Agent 有独立的预算边界，不需要全局协商
```

5 行 — `_orchestrate_one` 的参数从无到 `budget_slice: int = 1`。

**铺垫 2: retry 逻辑暴露注入点**

```python
# V7.1: while 循环硬编码在循环体内
# V7.2: retry_policy 是 optional callable
# 默认行为不变，但 V8 可以替换成 formal Loop 对象

async def _orchestrate_one(self, step, ..., retry_policy=None):
    if retry_policy is None:
        retry_policy = _default_retry_policy
```

3 行 — 不改任何行为，留一个 V8 插手的接口。

**为什么不在 V7.2 做更多**：等 V7.3 把 MCP 物理集成 + 阻力场 DAG 做完，就有了至少三种 Loop 类型（代码执行、MCP 文件操作、语义规划）。那时候 2-范畴的横合成才有实际的组合对象可以操作。

| | V7.2 不做铺垫 | V7.2 做铺垫 | 
|---|---|---|
| V7.2 成本 | 0 | 8 行 |
| V8 成本 | 拆 TrackCEngine 类级状态 + 嵌入式 while | 替换 retry_policy + per-Loop budget |

### 四个工程补丁

#### 补丁 A: Mypy 进程内调用 + dmypy 预埋

`subprocess(['mypy', tmpfile])` 每次 fork + typeshed 加载 = 300-800ms。4 个物理 step × Mypy = 2-3 秒浪费。

**V7.2**: `mypy.api.run(['-c', code_string])` 进程内调用，首调用 ~300ms，后续 ~50ms。
**V7.3 预埋**: 注释 `# TODO V7.3: dmypy daemon, ~10ms per check`

#### 补丁 B: Test Cases 特洛伊木马 — 双重过滤 + 声明式约束

test_cases 是 LLM 生成的代码——和 code 有相同的破坏力。

**防御 1**: test_cases 必须和 code 一样过 AST + RestrictedPython。
**防御 2**: Prompt 硬约束 — "test_cases 只能包含 assert 语句。禁止 import/class/for/while/I/O。"

#### 补丁 B.1: 沙箱时空硬限制 — 防资源耗尽型 DoS

RestrictedPython 防住了 `import os`，防不住合法语法的资源耗尽：

```python
assert func(1) == [x for x in range(10**8)]  # OOM — 语法合法
assert func(2) == sum(i*i for i in range(10**9)) # CPU 死循环 — 语法合法
```

**防御**: `_run_restricted` 不直接 `exec()`。用 `multiprocessing.Process` + 强制 Timeout:

```python
process = Process(target=sandbox_exec, args=(code, test_cases))
process.start()
process.join(timeout=3.0)
if process.is_alive():
    process.terminate()
    return ExecutionResult(state=PhysicalState.TIMEOUT,
        error_message="Test case execution exceeded 3s limit.")
```

**意义**: 把"资源耗尽"这种致命物理崩溃降级为 ErrorMapper 可处理的 TIMEOUT——Agent 自己修复那个死循环的 test case，而不是宿主进程一起死。

#### 补丁 C: 预算耗尽 Fail-Safe + 按计算成本加权

预算按"层数"计费（Mypy=1, RP=1, Sandbox=1）有致命倒挂：budget=2 → 跑完 Mypy+RP → 预算归零 → **最昂贵的沙箱执行根本没跑。** 最便宜的静态检查把最贵的验证挤掉了。

**修正**：按计算成本加权，和 V7 阻力场（高风险 = 高代价）同构。

```
AST:            0    (免费，永远跑，~1ms)
Mypy:           0.1  (微额，~500ms)
RestrictedPython: 0.1  (微额，~5ms 转换)
Sandbox exec:   1.0  (全额，100ms+ 每个 test case)

Fail-Safe: if budget < 1.0 → REJECT
// 确保至少保留一次沙箱执行的预算 — 否则前面的静态检查毫无意义
```

**数学意义**: 预算分配和验证价值对齐。最昂贵的操作消耗最多的预算。静态检查的价值是"滤除低级错误"——它应该便宜。沙箱执行的价值是"捕获逻辑错误"——它值得消耗最多的预算。

#### 补丁 D: f-string assert → 零 LLM 正则提取 (with 反贪婪定界符)

Prompt 约束:
```
assert func(input) == expected, f"⊢EXPECTED⊢{expected}⊢ACTUAL⊢{actual}"
```

→ `AssertionError: ⊢EXPECTED⊢[1,2,3]⊢ACTUAL⊢[3,2,1]`
→ `re.search(r"⊢EXPECTED⊢(.*)⊢ACTUAL⊢(.*)", msg)` → 纯正则，零 LLM

**为什么用 Unicode 定界符**：如果 actual 本身是包含逗号或 ", got" 子串的字符串，`r"Expected (.*), got (.*)"` 的贪婪匹配会提取错误数据。`⊢EXPECTED⊢` 不可能出现在正常 Python 输出中——**彻底杀死贪婪匹配和子串冲突。**

### 四个补丁的数学与拓扑诠释

#### 补丁 A: mypy.api → 路径连通的类型空间

```
subprocess: 每次 fork → typeshed 重新加载 → 状态空间断开
            类型检查的状态空间被重置 N 次 = 同一条路径走了 N 遍，每遍从零开始

mypy.api:   进程内调用 → typeshed 驻留 → 状态空间路径连通
            后续检查只需从当前位置移动到目标位置，不需要每次回到原点
```

**拓扑意义**: Mypy 的类型推导是 typeshed 流形上的行走。`subprocess` 切断路径连通性。`mypy.api` 保持连续性——后续调用沿切线方向微调。

#### 补丁 B: 双重过滤 → 滤网的不动点条件

```
test_cases 是 code 的约束 — 定义接受域 A ⊂ Y
如果 test_cases 本身可包含恶意代码 → A 不是有界安全子空间 → 约束系统不健全

双重过滤: test_cases 过 AST + RestrictedPython
          滤网 F 对自身输入施加自反性检查
          F(F(C)) = F(C) — 滤网的不动点
```

**拓扑意义**: 单层滤网：`F(C)` 保证 code 安全但不保证 test_cases 安全。双重滤网：`F(test_cases) ∈ safe(C)` 保证约束定义域本身安全。这是滤网的**自反性闭包**——元层不被自身穿透。

#### 补丁 C: 预算 REJECT → 滤子嵌套的保序性

```
三层滤网: S₁ (AST) ⊃ S₂ (类型) ⊃ S₃ (沙箱)

完整路径: code → S₁ → S₂ → S₃ → 输出 ∈ ∩Sᵢ
跳过一层: code → S₁ → (跳过 S₂) → S₃ → 输出可能 ∉ S₂
         嵌套结构被破坏，S₂ 残余穿透到 S₃
```

**拓扑意义**: {S₁, S₂, S₃} 是**滤子基**——有限交 ∩Sᵢ 非空，且 S₁⊃S₂⊃S₃。滤子基的完备性依赖每一层在线。跳过 S₂ = ∩Sᵢ 被 S₂ 的补集污染。REJECT 保持滤子嵌套的保序性。

#### 补丁 D: f-string assert → 纤维丛的正则截面

```
f"⊢EXPECTED⊢{expected}⊢ACTUAL⊢{actual}"
        ↓ Python 运行时格式化 (确定性)
"⊢EXPECTED⊢[1,2,3]⊢ACTUAL⊢[3,2,1]"
        ↓ re.search(r"⊢EXPECTED⊢(.*)⊢ACTUAL⊢(.*)") (确定性)
("[1,2,3]", "[3,2,1]")  ← 结构化差分对
```

**为什么用 Unicode 定界符**: 如果 actual 本身是包含 `", got "` 子串或逗号的复杂对象，普通正则的 `(.*)` 贪婪匹配会提取错误数据。`⊢EXPECTED⊢` 不可能出现在正常 Python 输出中——截面选择函数**在所有纤维上都是良定义的**，不存在子串冲突的奇点。

**拓扑意义**: 错误信息空间 E 是一个**纤维丛**。每个错误类型是底点，每个底点上的纤维是所有可能的错误消息变体。f-string + Unicode 定界符把每条消息固定到纤维中的**正则截面**。Regex 是这个截面的**选择函数**——从底点唯一地选出标准形式。**确定性 = 存在全局连续的截面选择函数 σ: B → E，无奇点。**

#### 四个补丁的数学统一

| 补丁 | 数学结构 | 核心不变量 |
|------|---------|----------|
| A: mypy.api | 路径连通性 | 状态空间保持连通，无需复建原点 |
| B: 双重过滤 + B.1 时空硬限 | 滤网不动点 + 紧致化 | F(F(C))=F(C) + 执行时间紧致化 (timeout 紧化非紧致执行空间) |
| C: 按成本加权 + REJECT | 滤子嵌套保序 + 资源分配对齐 | S₁⊃S₂⊃S₃ 且 cost(filter) ∝ 验证价值 |
| D: f-string + Unicode 定界符 | 纤维丛全局正则截面 | 截面选择函数 σ: B→E 无奇点 (无子串冲突) |

### V7.2 改动清单

| 文件 | 改动 | 行数 |
|------|------|------|
| `core/track_c.py` | `_do_plan()` prompt — Test-First + ⊢定界符 + 声明式约束 (补丁 B+D) | +18 |
| `core/execution/sandbox.py` | +`_check_mypy(code)` — `mypy.api.run()` 进程内调用 (补丁 A) | +30 |
| `core/execution/sandbox.py` | +`_run_restricted(code, test_cases)` — RestrictedPython + Process timeout=3s (补丁 B.1) | +50 |
| `core/execution/sandbox.py` | `run()` — 三层滤网顺序 + 按成本加权 + REJECT + test_cases 双重过滤 (补丁 B+C) | +20 |
| `core/execution/error_mapper.py` | +`_extract_from_assertion(msg)` — ⊢定界符正则提取 (补丁 D) | +8 |
| `core/track_c.py` | V8 铺垫: `_orchestrate_one` +`budget_slice`, +`retry_policy` 注入点 | +8 |
| `tests/unit/test_v7_2_layered_execution.py` | 分层 + 双重过滤 + REJECT + 正则提取 + 超时 | +45 |

**总计: ~179 行, 4 文件。**

### 验收标准

| 场景 | V7.1 | V7.2 | 验证 |
|------|------|------|------|
| 语法/拼写错误 | AST 捕获 | Mypy + RestrictedPython 双重拦截 | 注入 typo，验证执行前阻断 |
| 逻辑错误 | 人类发现 | 自动生成 test_cases 失败 + ErrorMapper 定位 | 注入 off-by-one，验证自动报错并触发重试 |
| 危险操作 | 无防护 | RestrictedPython 拒绝 + 白名单限制 | 注入 `os.system("rm -rf /")`，验证拦截 |

### 战略留白：剩余 15%

| 缺口 | 量级 | 交付版本 |
|------|------|---------|
| 极端安全逃逸 (内核级) | ~5% | V7.3: OS 沙箱 (Docker/nsjail cgroups) |
| 复杂逻辑死角 (未覆盖执行路径) | ~5% | V7.3: Test Cases 自动增广 (失败后生成对抗性边界测试) |
| 跨步骤状态污染 | ~5% | V8: StatefulSandbox + 跨会话状态外化 |
