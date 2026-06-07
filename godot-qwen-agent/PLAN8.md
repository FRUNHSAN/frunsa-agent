# PLAN8 — 数学自适应契约：从伪自适应到保结构降阶

**日期:** 2026-06-07
**状态:** Phase 1 完成（3 模块落地 + 25 测试）
**触发:** 用户质疑——"自适应契约也不是完全自适应，伪自适应"
**基线:** df89d59（V4.3 速度优化 + 命令分类器修复）

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

### Phase 2 — 待规划

1. **WassersteinProxy 校准** — 在启动时跑基准 QA 对，计算 d_min/d_max
2. **选择阈值耦合** — 将 meta_adapt 的动态阈值注入实际响应选择逻辑
3. **需求层级识别** — LLM 输出 P(tool|input)、P(relational|input)、P(growth|input) 的概率分布，保持未压缩状态
4. **层级切换** — 从"阈值降低"的代理方案升级为显式的流形切换（工具/关系/成长）
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
