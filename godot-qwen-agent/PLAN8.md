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

### Phase C — 待规划（V6+）

1. **Planning/Orch/Critic 引擎重构** — DAG 依赖解析、并发调度、语义级 Critique
2. **WassersteinProxy 校准** — 在启动时跑基准 QA 对，计算 d_min/d_max
5. **跨会话模式发现** — 当某个行为模式在 ≥ 3 个会话中被用户的同类型行为选中 → 提议固化为用户画像特征
6. **TDA 集成** — 用 ripser/gudhi 对交互数据点云做持续同调，检测真正需要新维度的信号

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
