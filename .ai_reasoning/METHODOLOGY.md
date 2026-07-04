# 推理链制作方法

> 约束式工程的决策记忆系统。它不是 ADR。它回答的问题不是"我们做了什么决策"，而是**"在这次决策中，状态空间的边界被怎样重新雕刻了"**。

---

## 一、这是什么

每条推理链 = 一个 Markdown 文件（带 YAML frontmatter），记录一次**约束体系的演化事件**。

和 git commit 的区别：

```
commit:  告诉你"改了什么"
链:      告诉你"为什么不那样做"——以及这个"不"是从哪条铁律推导出来的
```

- commit 记录代码变更。链记录**约束的演化**——新建、修改、废弃。
- commit 是事后追溯。链是**前置约束**——AI 协作者在改同一模块前必须先读链（Protocol 0）。
- commit 可以被 squash。链**从不物理删除**。废弃的链移入 archive/——假基因原则。

---

## 二、目录结构

```
.ai_reasoning/
├── index.yaml              ← Protocol 0 的入口（AI 协作者第一站）
├── METHODOLOGY.md          ← 本方法论（自指：受自己规则约束）
├── chains/
│   ├── _TEMPLATE.md        ← 复制这个开始写新链
│   └── ...
├── archive/                ← 假基因库（废弃但从不删除的链）
│   └── ...
└── plans/                  ← 施工计划（链路演化的脚手架）
    └── ...
```

---

## 三、格式：Markdown + YAML frontmatter

每条链的标准格式：

```markdown
---
chain_id: 2026-07-03-kernel-migration
title: "MPC 内核搬迁 — ODE τ 解耦 + RL 影子模式"
layer: kernel
tags: [kernel_migration, ode, route_controller, rl_slot]
status: active
created: 2026-07-03
supersedes: []
superseded_by: []
related: []
produces_invariants: []
red_flags:
  - "不要在 assertion 中硬编码数学常数作为阈值"
  - "不要假设两个模块有依赖关系，仅因为它们在同一个 plan 中"
---

# Context

[状态空间的哪个区域出了问题？什么约束被触碰了？为什么现在必须处理？]

# Decision

[1-3 句话。新建/修改/废弃了什么约束？不含理由。]

# Rationale

[形式的推导（为什么是这个数学形式？）+ 参数的标定（为什么是这个值？）]

# Alternatives

[考虑过但拒绝的方案，每个带 pros/cons 和拒绝的**约束理由**]

# Evidence

[形式验证（证明）+ 参数标定（数据）]

# Future Guidance

[操作约束：给未来自己和 AI 协作者。哪些事刻意没做、参数去哪更新、正确修改路径]

# Anti-Patterns

[约束：定义了未来 AI 协作者在状态空间中不能进入的区域]
```

---

## 四、什么时候写

触发条件（满足任意一条就该写）：

| 场景 | 示例 | 约束式工程语义 |
|------|------|-------------|
| 在 ≥2 个可行方案之间做了选择 | YAML vs Markdown+frontmatter | 新建了一条约束——"推理链必须用 Markdown 格式" |
| 发现了一个不显而易见的约束 | "crisis_baseline 调 0.20 → τ_eff 暴涨到 840s" | 发现了一条**未被显式声明的约束**——记录并显式化 |
| 修了一个暴露设计缺陷的 bug | RL 槽位传遍调用链但零个门函数调用 | 修改了约束的实现方式——形式不变，实现修正 |
| 做了一个影响 ≥3 个模块的 trade-off | C2/C3 降级不修——爆炸半径 25 文件 | 在多条约束之间做了优先级排序——trade-off 本身需要成为一条约束 |
| 放弃了一个看起来正确但不可行的方案 | "全量修 C2 需改 25 文件，20+ 测试会炸" | 证明了某个方向**不在可行域内**——约束体系新增了一条边界 |
| **约束的域通用度发生变化** | Agent 域的 τ_decay=120s 在游戏引擎域被验证为 NOT_APPLICABLE | **域约束通用度 G(C) 变化——不只是参数，是结构变化** |
| **新建/修改/废弃了一条约束** | 引入 α·(T̄_peer−T) 项到 ODE | 约束体系的版本升级——必须用链记录公理来源和参数标定方法 |

**不需要写**：修 typo、单行 bug 修复、纯重构（行为不变）、参数微调（但域通用度不变）。

**最低可发表标准（MVC）**：写完 context + decision + rationale 即可发表。15-30 分钟。

---

## 五、chain_id 命名

```
YYYY-MM-DD-短描述
```

日期天然保证唯一性。短描述用 kebab-case，不超过 5 个词。

---

## 六、status 生命周期 — 对齐约束生命周期

```
draft → active → stale → superseded → archived
```

| status | 约束对应 | 含义 | 触发条件 |
|--------|---------|------|---------|
| `draft` | PROPOSED | 正在写，MVC 即可发表 | 初始状态 |
| `active` | ACTIVE | 当前有效——这条链的约束仍在约束代码 | 通过审查 |
| `stale` | STALE | 连续 N 次迭代未被触发 | Protocol 7 审查 |
| `superseded` | DEPRECATED | 被后来的链替代（填写 `superseded_by`） | 新链声明取代 |
| `archived` | ARCHIVED | 场景已不再存在，仅历史参考 | 代码/场景消失 |

**关键规则**：废弃不等于删除。`superseded` 和 `archived` 的链移入 `archive/` 目录，保留完整元数据（废弃日期、取代者 ID、废弃原因）。禁止物理删除。这是假基因原则。

**链审计**：每到大版本或 Protocol 7 触发时，检查所有 `active` 链的 `files` 字段——如果文件已不存在，将 status 改为 `archived`。如果链连续 3 次迭代未被触发 → 标记 `stale`。

---

## 七、各字段写法

### Context

回答三个问题：**状态空间的哪个区域出了问题 → 为什么现在必须处理 → 有什么约束被触碰了。**

```markdown
# Context

B1+B2（ODE τ 参数耦合）: ode_integrator.py 恢复区使用 tau_decay
但 baseline 经由 _lerp(crisis_baseline, recovery_baseline, t) 驱动，
产生隐式耦合 τ_eff = τ_decay / (1-a)。若有人调 crisis_baseline，
τ_eff 可能暴涨到 ~840s——调参者不会预期此连锁反应。

约束触碰: 铁律 #2（连续控制律）——参数耦合导致控制量非连续推导。
673 测试不能破。
```

### Decision

1-3 句话。不解释为什么——那是 Rationale 的事。

**约束式工程语义**：这条链**新建/修改/废弃**了什么约束？用约束的语言写。

### Rationale（链的核心 — 必须区分形式/参数）

写**决策逻辑**。必须区分：

**形式的推导**（为什么是这个数学形式？）：

追溯到铁律或已证明的不变量。

```
格式: 约束 C → 推论 Y → 定理 X → 铁律 #N

例: "恢复区用 tau_recovery 而非 tau_decay —— 因为 τ_eff = τ / (1-a)，
    若 τ 和 baseline 共享参数，调 crisis_baseline 会导致 τ_eff 暴涨到 ~840s。
    铁律 #2（连续控制律）要求控制量连续推导——参数耦合破坏了连续性。
    
    推导链: τ_eff < 10× τ_recovery → a < 0.9 → 需要独立的 tau_recovery 参数
    → 铁律 #2（连续控制）→ 铁律 #1（纯函数，无隐式耦合）"
```

**参数的标定**（为什么是这个值？）：

来自实验数据或默认值，标注置信度。

```
例: "tau_recovery = 200.0 来自 V9.0 默认值，⚠ 未经经验标定。
    标定方法见 [A1] 系统辨识。标定前置信度: LOW。"
```

**常见错误**：用"效果好"同时解释形式和参数——前者需要公理，后者需要数据。这条错误对应 12-反模式 #9（数据权威篡位）和 #1（启发式伪装）。

### Alternatives

每个被拒绝的方案写明 pros/cons 和**拒绝的约束理由**——不只是"不好"，而是"违反了哪条约束"。

### Evidence — 区分形式验证和参数标定

```markdown
# Evidence

## 形式验证（证明）
- [数学性质]: Lipschitz 约束在 τ_decay ≠ τ_recovery 下仍保持 ‖Δsv‖₂ ≤ 0.30
- [不变量保持]: 铁律 #1-#7 全部保持
- [推导链完整性]: 追溯到铁律 #2，无断裂

## 参数标定（数据）
- [标定方法]: PLAN2 盲测 (n=1)
- [参数值]: tau_recovery = 200.0
- [置信度]: ⚠ LOW — 单用户、单域。需多域验证（游戏引擎域 + 具身智能域）
- [待标定]: tau_recovery 在游戏引擎域的取值

## 测试（验证实现正确性）
- `tests/test_kernel.py::TestODEIntegrator::test_tool_failure_never_breaks_floor`
- 27 个内核测试全绿 (0.11s)
```

**关键区分**：形式验证（证明形式正确）= 最高置信度。参数标定（数据拟合最优值）= 有限置信度。测试（验证实现正确）= 必要但不充分——测试通过不证明形式正确，只证明实现符合形式。

### Future Guidance

给未来的自己和 AI 协作者的**操作约束**——格式为列表。

```markdown
# Future Guidance

## 刻意没做的事
- C2 (response_verbose_level 枚举): 25 文件，全部在 agent 域，不传染游戏引擎 → V10

## 参数调参须知
- 改 crisis_baseline 或 recovery_baseline → 检查 τ_eff assertion
- τ_eff 公式: τ_eff = tau_recovery / (1-a), a = (rec_baseline - crisis_baseline) / denom
```

### Anti-Patterns — 约束，不是建议

明确禁止的事情。**用否定句表述**——"不能做什么"。如果发现自己写的是"应该怎样做"——那是启发式，不是约束。移到 Future Guidance 里。

**终极检验**：删除这条 Anti-Pattern，系统在没见过的情况下还能自己找到正确解吗？
- 能 → 这条 Anti-Pattern 可能是多余的（过度约束——12-反模式 #2）
- 不能 → 这是真约束，保留

### red_flags（frontmatter 字段）

这条链定义的**违规检测器**。

```yaml
red_flags:
  - "不要在 assertion 中硬编码数学常数作为阈值"
  - "不要假设两个模块有依赖关系，仅因为它们在同一个 plan 中"
```

如果 AI 协作者或人类开发者触发了 red_flag 中描述的行为——**这不是"建议改进"，是违反了本链建立的约束**。red_flags 是 Protocol 2（反模式扫描）的输入信号源。

### produces_invariants（frontmatter 字段）

这条链产出了哪些不变量？对应约束式工程中"新建了哪条约束"。

```yaml
produces_invariants:
  - "INV-064: τ_eff < 10× τ_recovery 守卫不变式"
```

**每一条 `produces_invariants` 中声明的不变量，在 Protocol 7 约束健康度审查中自动纳入扫描范围。** 如果某不变量连续 3 次迭代未被触发 → 标记 stale。如果它保护的场景已不再存在 → 标记 deprecated。

### layer（frontmatter 字段）

这条链作用于哪一层？

```
kernel | harness | observer | synthesis | ui | meta
```

`meta` = 方法论层（如本方法论自身）。

---

## 八、代码中的双向追溯

### 从代码到链和不变量

在关键函数的 docstring 里加标记：

```python
def _clamp_state_vector(
    current: tuple[float, ...], prev: tuple[float, ...], raw_delta: float,
) -> tuple[float, ...]:
    """Lipschitz 向量裁剪。

    @chain:     2026-07-03-kernel-migration  — 为什么用动态分母
    @invariant: INV-001                       — ‖Δsv‖₂ ≤ MAX_GRADIENT_NORM (0.30)
    @verified:  2026-07-03                    — 最后确认正确实施
    """
```

**标记标准**：标在**不变量被违反时工程师第一眼会看到的地方**。

**`@verified:` 过期判定**：若 `@verified:` 日期 < 不变量定义版本 → 标记可能过期 → 人工判断。

### 从链到代码

在链的 frontmatter 里填 `files:` 字段。

### 从链到不变量

在链的 frontmatter 里填 `produces_invariants:` 字段。

---

## 九、index.yaml 维护

`index.yaml` 是 Protocol 0 的入口——AI 协作者检索的第一个文件。

每次写新链后加一条 entry。2 分钟。

```yaml
library_version: 1
last_updated: "2026-07-04T00:00:00Z"

chains:
  - chain_id: 2026-07-03-kernel-migration
    title: "MPC 内核搬迁 — ODE τ 解耦 + RL 影子模式"
    layer: kernel
    tags: [kernel_migration, ode, route_controller, rl_slot]
    status: active
```

---

## 十、与 AI 协作者的工作流（映射 Protocol 0-7）

### Phase 1 — 写代码前（Protocol 0：文档优先原则）

```
1. 打开 index.yaml → 按 layer + tags 找到相关链
2. 读每条链的 Future Guidance 和 Anti-Patterns
3. 读 produces_invariants —— 这些不变量还在生效
4. 如果跳过这一步 → Protocol 0 违规 (WARNING)
```

### Phase 2 — 写代码中（Protocol 4：铁律不可侵犯 + Protocol 2：反模式扫描）

```
1. 不违反任何 anti_patterns + red_flags
2. 如果被一个 anti_pattern 吸引 → 重新读那条链的 Rationale
3. 如果建议修改约束的数学形式 → 触发 Protocol 4（ERROR，需人工确认）
```

### Phase 3 — 写代码后（Protocol 1：约束来源验证 + Protocol 7：约束稳态维护）

```
1. 判断是否需要新链（≥2 方案 / 不显而易见的约束 / 设计缺陷修复 / 
                    约束新建/修改/废弃 / 域通用度变化）
2. 写链 → 标注形式推导链 + 参数标定方法
3. 更新 index.yaml
4. 在关键函数上加 @chain: + @invariant: 标记
5. 如果新链建立了新约束 → 更新 produces_invariants
6. 如果新链废弃了旧约束 → 更新 superseded_by + 移入 archive/
```

---

## 十一、自指条款

> 本方法论本身受其规则约束。
>
> 如果未来连续 3 次 Protocol 7 约束健康度审查中，本方法论的规则被证明过于繁重导致 AI 协作者跳过步骤——
> 本方法论应被标记为 `stale` 并提议简化。
>
> **连推理链的制作规则本身也必须是可以被遗忘的。**
>
> 当前版本：`active`。下一次自指审查：2027-01-04（6 个月）。

---

## 十二、新项目起步

```bash
mkdir -p .ai_reasoning/chains .ai_reasoning/archive
```

1. 复制本文档到 `.ai_reasoning/METHODOLOGY.md`
2. 复制 `chains/_TEMPLATE.md`
3. 创建 `index.yaml`（空 chains 列表即可）
4. 第一条链：记录"为什么选择约束式工程论作为方法论基座"

**不需要**：CI 集成、pre-commit hook、JSON Schema 校验。那些是项目成熟后的事。现在只需要写链这个习惯。

---

> **自指条款**：本文档受其规则约束。Protocol 7 自指审查到期日：2027-01-04。
>
> CC BY-ND 4.0. 署名：李政远（FRUNHSAN）。
