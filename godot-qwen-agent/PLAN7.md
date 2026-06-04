# PLAN7 — Environmental Physics

## 定位

> **The contract controls the environment around the LLM, not the LLM's internal generation.**

PLAN1-4 建立了关系引擎（传感器）。
PLAN5 让契约活了过来（活体 Blueprint + 3 Loops）。
PLAN6 给契约装上了耳朵（语义信任 + 信号翻译）。

PLAN7 改变了契约的执行模型：契约不再通过 Prompt 跟 LLM "协商"，而是通过代码级后处理管道**物理地**约束 LLM 的输出。

## 核心范式转移

```
PLAN6: Contract → Prompt string → LLM (probabilistic compliance)
PLAN7: Contract → OutputPipeline → Deterministic post-processing
```

Prompt 约束是**请求**。OutputPipeline 是**物理法则**。LLM 可以无视 Prompt。无法无视截断器。

## 核心组件

### OutputPipeline
- 读取 Blueprint 状态 (`bp.enforce()`)
- 应用确定性后处理：
  - 句子截断 (MINIMAL=2, LOW=3, MEDIUM=5, HIGH=8)
  - Markdown 格式清洗
  - PRAGMATIC 语气过滤（去掉"我觉得"、"可能"等填充词）
  - 谄媚检测和惩罚

### 三层控制面

| 层 | 位置 | 确定性 |
|----|------|--------|
| Prompt 约束 | System Prompt → LLM | 概率性 (~50%) |
| OutputPipeline | 代码后处理 | 确定性 (100%) |
| 约束解码 (Phase 3) | 本地推理 token 层 | 物理性 (100%) |

## 路线图

| 阶段 | 动作 | 状态 |
|------|------|------|
| 7.1 | OutputPipeline — 物理法则地基 | ✅ 完成 |
| 7.2 | 零样本分类替代 embedding (bart-large-mnli) | 待实现 |
| 7.3 | 本地推理 + 约束解码 (GBNF/logit bias) | 待实现 |

## 设计决策

| 决策 | 理由 |
|------|------|
| 后处理而非生成时控制 | LLM 是概率模型，事前控制不可靠 |
| `bp.enforce()` 作为唯一读取入口 | 所有组件统一从契约读取约束 |
| 关流式输出 | OutputPipeline 需要完整文本做句子计数和截断 |
| 默认 verbose=MEDIUM | HIGH 在真实使用中过于冗长 |
