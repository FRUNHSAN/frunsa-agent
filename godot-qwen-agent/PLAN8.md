# PLAN8 — 数学自适应契约：从伪自适应到保结构降阶

**日期:** 2026-06-08
**状态:** V5.2 封版 — 纯净控制回路（二元路由 + 三控制面 + 零情绪注入）
**触发:** 用户质疑——"自适应契约也不是完全自适应，伪自适应"
**基线:** v5.0-bang-bang-baseline

---

## 问题：伪自适应的本质

当前所有"自适应"链路的本质是 `if score > threshold: field = new_value`：

```
signal_interpreter.py → 固定关键词列表 → 固定阈值 → 固定动作
kernel_evaluate_health() → 3 个信号 → 硬编码分支 → 硬编码修复
contract_evolution_engine.py → 固定门控条件
user_profile.py → 简单计数器
```

**根因：混淆了"变异生成"与"变异选择"两个独立过程。**
LLM 擅长前者（概率采样 = 变异），但被错误地用于后者（自我说服、自我评价 = 选择层失效）。

---

## 数学基座：五次研究总结

参见 `BRAINSTORM_TRUE_ADAPTIVE.md`（完整推导）和 `chains/v5_math_adaptive_contract.yaml`。

| 概念 | 工程旧理解 | 数学新本性 |
|------|----------|----------|
| 契约 | if-else + 阈值 | **马尔可夫毯的几何投影**——抵抗熵增的低熵结构 |
| 自适应 | 参数 ±12% | **Wasserstein 测地线上的追逃博弈**——ω_max vs λ_SB |
| 元适应 | 新增规则 | **哥德尔跃迁**——当前形式系统无法自证稳定时的维度超越 |

自适应契约的完整数学 = **Grothendieck 纤维化范畴上的 Wasserstein-Schrödinger 梯度流 + 移动目标追踪 + TDA 触发的伴随函子升维**。

---

## 工程实现：保结构模型降阶

### Phase 1 — 已完成（2026-06-07）

| 模块 | 文件 | 行数 | 数学对应 | 测试 |
|------|------|------|---------|------|
| WassersteinProxy | `core/adapters/wasserstein_proxy.py` | 108 | W_1 的 KR 对偶上界 + 对比校准 | 5 |
| TrackingErrorEstimator | `core/adapters/tracking_error.py` | 177 | e(t) 的噪声观测 + 自适应增益调度 | 11 |
| MetaAdaptTrigger | `core/adapters/meta_adapt_trigger.py` | 113 | 元适应触发 + 退火保护（全局有界性） | 9 |

**总计**：~400 行新代码。Zero 引擎改动。25 新测试全绿。510 旧测试零回归。

**三个数学补丁**：
1. **对比校准** — W_1 代理的全局 Lipschitz L=1 归一化
2. **自适应增益调度** — EMA α = exp(-interval/tau)，防相位滞后
3. **退火保护** — MIN_THRESHOLD = 0.30，COOLDOWN = 10 轮，防脑死亡和震荡

### Phase 1.5 — 完成（2026-06-08）：三条控制面 + 脊髓反射

Session 51-52 的真实交互暴露了 Phase 1 的致命缺口：感知-行动闭环（e(t) + σ² → meta_adapt）
正常运转，但输出管道在 V5 不知情的情况下截断了 60-65% 的 LLM 输出。
**V5 知道用户要什么，但旧系统的输出管道劫持了执行层。**

修复分两阶段：

**阶段 A — 三切口手术（Session 51 尸检 → 立即修复）**：

| 切口 | 改动 | 效果 |
|------|------|------|
| 语义精度 | 命令分类器加"全部一次性""越长越好"锚点 | "全部一次性给我" 匹配 HIGH 而非 MEDIUM |
| 执行反馈 | 截断率 >30% → e(t) +min(0.15, ratio×0.2) | V5 感知到输出被阉割 |
| 认知标记 | 截断率 >50% + 非 Path 2 → `[execution_constrained]` | 用户看到系统的执行约束 |

**阶段 B — 脊髓反射（Path 3）**：

Session 52 验证了三切口有效但不够——截断率仍 61-66%。
Path 1（e(t) > 0.70 × 5 轮）从未触发，因为它是为"环境不确定性持续升高"设计的
慢性疼痛检测器，但执行截断是每轮独立发生的急性疼痛。

**三条控制面正式确立**：

| 路径 | 触发信号 | 控制面 | 响应尺度 | 类比 |
|------|---------|--------|---------|------|
| Path 1 | e(t) >0.70 ×5 轮 | 策略选择 | 慢（会话级） | 皮层：换一种思考方式 |
| Path 2 | σ² > μ+2σ ×3 轮 | 搜索宽度 | 中（任务级） | 边缘系统：扩大感知范围 |
| Path 3 | 截断率 >50% ×2 轮 | 输出容量 | 快（轮次级） | 脊髓：松开物理束缚 |

Path 3 的核心设计：
- 不经 meta_adapt（皮层），直接调节 OutputPipeline 的 char/sentence 倍率
- 倍率公式: streak=2→1.5x, streak=3→2.0x(capped)，硬上限 2.0x 防雪崩
- 截断率回落 → 立即恢复默认倍率（不是 EMA 慢恢复——脊髓不是皮层）
- `/new` 命令重置所有脊髓反射状态

**模块汇总（Phase 1 + 1.5）**：

| 模块 | 文件 | 行数 | 数学对应 | 测试 |
|------|------|------|---------|------|
| WassersteinProxy | `core/adapters/wasserstein_proxy.py` | 108 | W_1 的 KR 对偶上界 + 对比校准 | 5 |
| TrackingErrorEstimator | `core/adapters/tracking_error.py` | 177 | e(t) 的噪声观测 + 自适应增益调度 | 11 |
| MetaAdaptTrigger | `core/adapters/meta_adapt_trigger.py` | 212 | 双路径元适应触发 + 退火保护 | 9 |
| SelectionPressureAccumulator | `core/adapters/selection_pressure_accumulator.py` | 229 | 信任 EMA + 贝叶斯方差 + 基线漂移 | 14 |
| OutputPipeline (Path 3) | `core/adapters/output_pipeline.py` | +8 | 脊髓反射的动态倍率接口 | — |
| REPL (V5 闭环) | `core/repl.py` | +115 | 感知-行动-执行三层闭环 + X-Ray + /v5-status | 15 |

**总计**：~850 行 V5 代码。54 新测试全绿。全量单元测试零回归。

### Phase B — 完成（2026-06-08）：二元 Bang-Bang 路由

**Session 51-61，从 embedding 分类器到 Pontryagin 最优控制。**

四轮 embedding 路由迭代失败后，诊断出本体论错误：embedding 属变异层，路由属选择层。
Pontryagin 最大值原理证明"内部反馈的存在是布尔量"——半闭环不存在，
Track B 的硬编码 3 步模板 + 字符计数在动力学上等价于 Track A。

**切除**：
- 删除 embedding 路由分类器（~250 行：锚点、Top-3、strip、继承）
- 删除 Track B 假管线（~90 行：`_plan_task`, `_critique_results`, `_track_b_agentic`）

**重建**：
- ~40 行二元 Bang-Bang 控制器：u(t) = π(e(t), σ², trust) → {A, C}
- 施密特迟滞：升级 2 轮 e(t)↑+e>0.55，降级 3 轮 e(t)↓
- 冷启动 Minimax：len>10 或结构化标点 → C
- 硬覆盖链：social → trust_crisis → escalated → relaxed → coldstart → steady-state

**Session 61 验证**：首次 C 触发 (coldstart_probe)，全程零 Track B，A/C 切换干净。

**已知问题 — 成本悬崖**：
Track C 对浅层请求（"字多一点"）仍跑全 DAG（50-75s）。
V5.1 应在 Planning 阶段引入 DIRECT_GENERATION vs FULL_DAG 复杂度路由，
不加前置探针（陷阱：探针税、双 Planner 竞争、上下文盲区）。

### V5.1 — 完成（2026-06-08）：Track C 自适应计算深度

**拉格朗日松弛消除成本悬崖。**

在 Planning 目标函数中嵌入 λ·Cost(Plan) 项，LLM 隐式估计 λ 选择 DIRECT 或 FULL_DAG。
λ 增益调度 = f(trust, e_t)：trust<0.15 或 e_t>0.65 → λ→0（强制 FULL_DAG）。
~40 行改动，1 个文件。

同时发现并修复了 LLMPlanningEngine 模板与 V5.1 格式冲突——引擎的
PLAN_DECOMPOSE_TEMPLATE 强制 "exactly 3 steps"，覆盖了 V5.1 的复杂度路由指令。
Session 65: Planning 步数从永远 2 变为 1-4 动态。

### V5.2 — 完成（2026-06-08）：情绪检测器降级 + 化石切除

**Observe, Don't Inject（观测不注入）。**

三连切除：
- signal_interpreter.py（情绪→动作，143 行）— 执行器冲突病灶
- LLM fallback 情绪检测 — 每轮省 1 次 LLM 调用
- RelationalPatterns + NarrativeEmergence（时间启发式，~420 行）— "周五下午=用户疲惫"
- 情绪→trust 惩罚 — 情绪不应修改信任值

SemanticTrustEngine 降级为纯 X-Ray 观测指标。FEEDFORWARD_GAIN=0.0。
总计 ~710 行删除，零新功能代码。

设计原则确立：
- Principle #4: Signal over Schedule（信号优于时刻表）
- Principle #5: Observe, Don't Inject（观测不注入）

### V5.3 — 完成（2026-06-09）：双引擎观测器 + drift⊕clarity 融合

**关键词门控归零。纯数学双传感器融合。**

#### 问题

V6 的 `_path2_branch_count(raw_drift, user_text)` 用关键词列表 `_SIMPLIFY_CANCEL`/`_SIMPLIFY_DOWNGRADE`
检测"简化意图"——无限回归：每次发现新边界就加新关键词。Session 73 修复（len<50 门控）
在 Session 74 回放中再次失效（用户完整请求 110 字符）。

drift 是标量——分不清"加深"和"简化"。两者都产生高 cosine distance。
需要第二个正交维度来判定方向。

#### 数学：双传感器正交融合

drift `d` 和 clarity `c` 是物理正交维度：
- drift：轨迹变化（跨轮 cosine distance）—— 用户"转弯"了多少
- clarity：状态质量（轮内 LLM 推理）—— 用户"清醒"还是"混乱"

融合函数：
```
f = Φ(d, c) = {
    min(f_drift(d), 0.20)    if c > 0.80   (清醒压制)
    max(f_drift(d), 1 - c)   otherwise      (OR 逻辑)
}
```

**清醒压制 (c > 0.80)：** 用户清醒 + 高 drift = 有意的非连续性。压制 → EXPLOIT。
**OR 逻辑 (c ≤ 0.80)：** 任一传感器报警 → 探索。首轮荒谬指令（c=0.15, d=0）也能被检测。

#### 执行器分派

| 执行器 | 信号源 | 理由 |
|--------|--------|------|
| Planning n | **f_fused** (drift ⊕ clarity) | 探索宽度由意图不确定性决定 |
| Critic θ | **f_drift × g(e_t)** | 验收标准由语义空间稳定性决定——Critic 对 drift 的敏感性是 feature |

#### 工程落地

- `SemanticTrustEngine` 升级为双引擎观测器：`detect()` (embedding) + `assess_clarity()` (LLM)
- ThreadPoolExecutor 并发：clarity LLM 调用与 drift 计算重叠执行
- 正则提取 float：防御 LLM 输出废话前缀
- X-Ray 🧊 标记：清醒压制激活时可视化

#### 删除

- `_SIMPLIFY_CANCEL` / `_SIMPLIFY_DOWNGRADE` / `_detect_simplification` (~20 行关键词门控)
- `_path2_branch_count` 签名从 `(raw_drift, user_text="")` 改为 `(f: float)` —— 纯数学，零字符串匹配

#### 场景验证

| 场景 | d | c | f | 行为 |
|------|---|---|---|------|
| Scene 3 R1 (荒谬指令) | 0.000 | 0.15 | 0.85 | EXPLORE — 首轮检测到混乱 |
| Scene 4 R2 (清醒切换) | 0.687 | 0.95 | 0.20 | EXPLOIT 🧊 — 清醒压制 |
| Scene 1 (正常稳定) | 0.050 | 0.85 | 0.00 | EXPLOIT — 稳定+清醒 |
| Scene 2 (模糊+失效) | 0.420 | 0.35 | 0.65 | EXPLORE — OR 逻辑触发 |

#### 新增测试

- `tests/unit/test_v5_3_dual_sensor.py`：26 参数化测试 + 6 边界测试 = 32 测试，全部通过
- 全量单元测试零回归

### V6 — 已完成（2026-06-09）：V5 控制面的引擎层完全体

**V6 不是新的大版本——它是 V5 控制面在引擎层的落地。** 全部完成。

#### ✅ 已完成（V5.1 → V5.3 中实现）

| V6 原计划 | 落地版本 | 实现 |
|-----------|---------|------|
| Path 2: σ² → Planning 分支数 | V5.1 + V5.3 | `_path2_branch_count(f)` — drift⊕clarity 双传感器驱动 1/2/3 分支 |
| Path 2: σ² × e(t) → Critic 阈值 | V5.1 + V6 | `_critic_threshold(f_drift, g)` — 乘法门控，θ∈[0.50, 0.75] |
| Path 2: 认知深度 → 输出容量 | V6 pipeline | `_dynamic_output_mult` — 分支数 × drift → 1.0x-1.8x 管道倍率 |
| Path 3: 脊髓反射 | V5 Phase 1.5 | 连续截断 → char/sentence 倍率自动提升 → 截断缓解 → 自动恢复 |
| 输出管道基线上限翻倍 | V6 pipeline | HIGH 800→1600 chars, MEDIUM 400→600, LOW 150→200 |
| 二元 Bang-Bang 路由 | V5 Phase B | Pontryagin 最优控制 → A/C 二元切换, Schmitt trigger 滞后 |
| 关键词门控切除 | V5.3 | `_SIMPLIFY_CANCEL/DOWNGRADE/_detect_simplification` 删除，纯数学替代 |
| 双引擎观测器 | V5.3 | `SemanticTrustEngine.assess_clarity()` — LLM 推理通道 |
| Orch DAG 拓扑 (V6.1) | V6.1 | `_build_dag_and_depth` — tag匹配 + Kahn环检测 + BFS层级 → Semaphore(parallel_depth) |
| Wasserstein 混合校准 (V6.2) | V6.2 | `compute_session_gain` — 贝叶斯平滑 (α=3) + 四象限基准QA + domain-adaptive Critic |
| Path 1 偏置张量裂变 (V6.3) | V6.3 | `_compute_bias_tensor` — explore_bias⟂compromise_bias + Minimax fallback |
| 代码块感知截断 | V6 fix | `_truncate_sentences` — ```fences内不计句子，消除代码块假阳性截断 |

### Phase C — V7+ 远景

1. **跨会话模式发现** — 行为模式在 ≥3 个会话中被同类行为选中 → 固化到用户画像
2. **TDA 集成** — ripser/gudhi 持续同调，检测需要新维度的信号
3. **流式输出** — 降低感知延迟，消除 Synthesis 阶段的 25s 等待

### Track A 数学定位 — 零控制自由动力学

Track A 不是"降级模式"——它是**控制论上正确的最优选择**。

#### 数学定义

```
Track A:  dx/dt = f(x, 0)         零控制 — 语义空间中的自由漂移
Track C:  dx/dt = f(x, K(y))      受控 — K 是反馈律，y 是观测向量

路由选择 (Pontryagin):
  choose A when  cost(K) > |err_A| - |err_C|
  即: 控制代价 > 不加控制的误差上界差

触发条件:
  - 社交信号 ("你好""拜拜"): |err_A| ≈ 0, 控制纯浪费
  - 信任危机 (trust < 0.10): K 本身就不可靠
  - Path 2 escalated: 环境噪声太大, 控制信号不可信
```

#### Track A 的盲区：实现违背数学定义

```
数学定义: x_t = f(x_t, u_t)              ← 状态只依赖当前输入
实际实现: x_t = f(x_0, ..., x_{t-1}, u_t)  ← 全部历史塞进 prompt

这是 IIR (无限脉冲响应) — 一个社交信号的影响永不衰减。
应该是 FIR (有限脉冲响应): x_t = Σ_{i=0}^{K} γ^i · embed(u_{t-i})
  K = 3 轮, γ = 0.6, 衰减权重
```

**修复 (V7)**: Track A prompt 注入遗忘指令——
"前序对话仅供理解当前轮次的指代关系。不要主动补充、重新解释或继续展开已结束的历史话题。"

这等价于在自由动力学上加了一个指数衰减核——旧话题信息量以 γ^t 速度衰减，不跨轮次传播。

### Phase 3 — 远景（需更多研究）

1. **Schrödinger Bridge 的离散近似** — 用 Sinkhorn 算法在 token 空间上做真正的熵正则化传输
2. **Hodge 调和形式计算** — 从 TDA 的持续上同调类中提取新约束函数的几何形状
3. **联合 Lyapunov 函数的数值计算** — 验证 M 矩阵正定性在真实交互中的保持条件

---

## 核心安全约束

- ❌ 严禁 LLM 解析弱信号（"好的""谢谢""嗯"）—— 误判率实测 34.1%
- ❌ 严禁跨会话累积选择阈值——所有调整仅限当前会话
- ❌ 严禁"可成长型武器""AI 自主进化"等表述——军事化类比违法
- ❌ 严禁在无 MIN_THRESHOLD 的条件下无限降阈值
- ✅ 仅启用的强信号路径：追问 + 技术术语 + 延迟 > 8s → 成长需求 +12%
- ✅ 2 轮无反馈 → 自动衰减至基准值
- ✅ /reset → 即时回退所有临时调整

---

## 项目定位更新

见 `CLAUDE.md` V5 节和 BRAINSTORM_TRUE_ADAPTIVE.md 第十章。

旧：AI 自主协商契约 → 容易误读为两个对等主体的谈判
新：AI 在用户行为构成的选择压力下，通过变异-选择-保留循环演化其行为契约

人不在谈判桌上，人是**环境本身**。
