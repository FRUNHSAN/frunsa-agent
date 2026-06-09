# V5 → V6 数学背板：从伪自适应到随机最优控制

**日期:** 2026-06-09
**状态:** V5.3 封板 | V6 核心落地 | Orch DAG + Wasserstein 校准待实施
**基线:** v5.0-bang-bang-baseline → 当前 HEAD

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
