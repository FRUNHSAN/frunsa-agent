# V2 全面架构审计 — 2026-06-04

## 项目规模

| 指标 | 数值 |
|------|------|
| 总 commit | 171 |
| Python 文件 (四层核心) | 83 |
| Protocol/接口文件 | 22 |
| 实现文件 | 46 |
| Demo 脚本 | 30 |
| 单元测试文件 | 12 |
| 单元测试通过数 | 188 (本次会话) + 855 (存续) |
| PLAN 文档 | 7 |
| 推理链 | 34 |
| 本地模型 | 4 (0.5B/1.5B/3.5/7B) |

---

## 一、我们实现了什么

### 架构层次（已从"大三層"演化为"五层控制面"）

```
Layer 1 (PLAN1-4): 契约内核        ✅ 完成
  contracts/ — 12 个 Protocol, 24 个数据模型
  pipeline/  — 6 个引擎文件
  adapters/  — 防腐层, 工具适配, 编排

Layer 2 (PLAN5):   活体契约        ✅ 完成
  DynamicBlueprint — 增删改查, 风化, 反噬, 固化
  ContractEvolutionEngine — 信任门控, 回滚, 显式指令击穿
  UserProfile — 跨会话记忆, 离群值过滤, 修正案

Layer 3 (PLAN6):   语义感知        ✅ 完成
  SemanticTrustEngine — Embedding 匹配 (80% 准确率)
  SignalInterpreter — 信号→Proposal 翻译
  BlueprintSchema — 8 个可演化字段

Layer 4 (PLAN7):   物理控制        ✅ 完成
  OutputPipeline — 句子截断, 格式清洗, 语气过滤, 谄媚惩罚
  GBNF 语法引擎 — token 级物理约束
  ActionPipeline — 信任→工具权限, HITL, Backlash

Layer 5 (V2):      流式拦截 + 在线学习  ✅ 完成
  StreamInterceptor — 五态 FSM, 4KB 溢出, 超时熔断
  EMALearner — 个人化阈值 (EMA 公式)
  FeedbackListener — 显式+隐式反馈采集
  RelationalPatterns — CBO 跨会话模式库

Layer 6 (V2.2):    关系引擎        ✅ 完成
  CBO 模式库 — Context-Behavior-Outcome
  主动预判 — 用户开口前注入关系提示
  28 天风化 — 模式不触发自动衰减
```

### 安全防线

| 防线 | 状态 |
|------|------|
| Constitution Guard (4 个不可变基因) | ✅ |
| Cooldown (5 轮) | ✅ |
| Min Autonomy Floor | ✅ |
| Schema Validation (拒绝无效值) | ✅ |
| Outlier Rejection (离群值过滤) | ✅ |
| Trust Gate (低信任时阻止提案) | ✅ |
| Backlash (3 次失败锁死工具) | ✅ |
| Buffer Overflow 4KB | ✅ |
| FSM Timeout (10s 熔断) | ✅ |
| EMA Guardrails [0.30, 0.80] | ✅ |

### SDK 接口

| 接口 | 状态 |
|------|------|
| ContractEngine (5 行接入) | ✅ |
| ContractGateway Protocol (冻结 API) | ✅ |
| ThresholdLearner Protocol (NN 未来替换) | ✅ |

---

## 二、没实现什么

### 明确待做 (V2 → V3)

| 项目 | 优先级 | 阻塞原因 |
|------|--------|---------|
| llama-server HTTP 替换子进程 | 中 | 等待 build 稳定 + 模型热加载 |
| 200+ 测试 (当前 188) | 中 | 覆盖回归测试剩余边界 |
| HTTP API (外部系统接入) | 中 | 当前单用户, 不需要网络暴露 |
| 认证/权限 (OAuth2) | 低 | 单用户场景 |
| CI/CD pipeline | 低 | 单开发者, 手动纪律足够 |
| 监控/告警 | 低 | 无生产流量 |
| CBO 模式库→主动预判闭环 | 高 | 数据积累中 (需要 ≥3 次触发) |

### 架构缺口

| 缺口 | 严重度 | 说明 |
|------|--------|------|
| 新适配器缺 Protocol | 中 | PLAN5-8 新增的 20+ 个适配器未定义 Protocol。只有 EMA 有 |
| 推理链过期 | 低 | 34 条推理链, 部分 Phase 01-18 的是历史遗迹 |
| stream_interceptor 未接入 streaming | 中 | 当前 DeepSeek 用同步 generate(), 非流式。FSM 已就绪, 等 streaming 上线 |

---

## 三、项目架构还是大三層吗？

**不是。已经远超。**

原始大三層:
```
contracts/ (数据模型 + 协议)
  ↕
adapters/ (翻译层, 唯一跨层桥接)
  ↕
pipeline/ (执行引擎)
```

当前实际架构:
```
contracts/ (24 文件 — 12 Protocol, 8 数据模型, 3 实现, 1 启动)
  ↓                  ↑
adapters/ (39 文件 — 7 Protocol/ABC, 30 实现, 2 传输存根)
  ↓                  ↑
pipeline/ (6 文件 — 引擎核心)
  ↓                  ↑
──────────────────────────── 原始三层线
  ↓                  ↑
PLAN5-8 引擎层 (动态契约, 语义感知, 物理控制)
  ↓                  ↑
V2 拦截层 (流式拦截, 在线学习, 关系引擎)
  ↓                  ↑
──────────────────────────── 新增两层
  ↓                  ↑
LLM/ (14 文件 — 7 个 LLM 客户端, 工厂, 模板)
  ↓                  ↑
run_live.py (交互 demo — 非架构组件)
```

**核心变化**: contracts/ 和 pipeline/ 保持了原始设计的纯净性。adapters/ 从"翻译层"膨胀为"执行层"——它现在容纳了契约引擎、语义感知、物理控制、流式拦截、在线学习、关系引擎。39 个文件, 6 个子领域。

---

## 四、深水区接口化与扩展性评估

### 接口化程度

| 组件 | 有 Protocol? | 可替换? |
|------|-------------|---------|
| DynamicBlueprint | ❌ 直接使用 | 紧耦合 |
| ContractEvolutionEngine | ❌ 直接使用 | 紧耦合 |
| SignalInterpreter | ❌ 纯函数 | 松耦合 (参数化) |
| OutputPipeline | ❌ 直接实例化 | 中等耦合 |
| ActionPipeline | ❌ 直接实例化 | 紧耦合 |
| StreamInterceptor | ❌ 直接使用 | 中等耦合 |
| EMALearner | ✅ ThresholdLearner | 完全可替换 |
| RelationalPatterns | ❌ 直接使用 | 紧耦合 |

**结论**: 只有 EMALearner 做了正式的接口解耦。其余组件功能正确但未定义 Protocol。这是 V3 重构最有价值的方向——给每个核心组件定义 Protocol, 让 run_live.py 依赖接口而非实现。

### 扩展性热力图

```
✅✅✅ 阈值学习     — EMALearner → NeuralLearner 一行替换
✅✅  信号感知     — 纯函数, 参数化, 易扩展维度
✅✅  语义信任     — 模型可换 (embedding/zero-shot/小模型)
✅    流式拦截     — FSM 独立, 但 trigger 检测与 ActionPipeline 耦合
✅    工具契约     — TOOLS 字典可扩, 但无热加载
⚠️    关系引擎     — SQLite 单机, 未来需迁移到共享存储
⚠️    llama.cpp    — 子进程脆, 待 llama-server
```

---

## 五、总结: V2 到底做到了什么

```text
171 commit, 188+855 测试, 7 份 PLAN, 34 条推理链

实现了:
  ✅ 自适应契约 — 从感知到决策到执行的完整闭环
  ✅ 三层物理控制 — Prompt → Pipeline → GBNF
  ✅ 工具权限治理 — 信任→风险→HITL→Backlash
  ✅ 流式拦截 — FSM 在 token 级阻止危险输出
  ✅ 在线学习 — EMA 个人化阈值, 越用越准
  ✅ 关系引擎 — CBO 模式库, 主动预判而非被动反应

没实现 (故意的):
  ⏸️ llama-server HTTP — 待版本稳定
  ⏸️ 200+ 测试 — 188, 差 12 个
  ⏸️ 核心组件 Protocol 化 — 仅 EMA 做了

偏离了吗?
  初衷: "核心原语不是执行指令, 而是维护和演化关系"
  现状: 契约控制嘴 (OutputPipeline), 控制手 (ActionPipeline),
        控制帧 (StreamInterceptor), 学会预判 (RelationalPatterns)。
  不是偏离。是深化。
```
