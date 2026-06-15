# PLAN7 — Environmental Physics

## 定位

> **The contract controls the environment around the LLM, not the LLM's internal generation.**

PLAN1-4 建立了关系引擎（传感器）。
PLAN5 让契约活了过来（活体 Blueprint + 3 Loops）。
PLAN6 给契约装上了耳朵（语义信任 + 信号翻译）。
PLAN7 改变了契约的执行模型：契约不再通过 Prompt 跟 LLM "协商"，而是通过代码级后处理管道**物理地**约束输出。

## 核心范式转移

```
PLAN6: Contract → Prompt string → LLM (probabilistic compliance)
PLAN7: Contract → OutputPipeline → Deterministic post-processing
       Contract → GBNF Grammar    → Token-level physical constraint
```

Prompt 约束是**请求**。OutputPipeline 是**闸刀**。GBNF 是**物理法则**。

## 架构：三层控制面

| 层 | 机制 | 确定性 | 后端 |
|----|------|--------|------|
| 1 (Prompt) | Blueprint → build_contract_directive() → System Prompt | ~50% | 云端/本地 |
| 2 (Pipeline) | OutputPipeline.process(): 截断/清洗/语气过滤 | 100% | 代码层 |
| 3 (GBNF) | build_grammar() → llama.cpp --grammar-file | 100% | 仅本地 |

## 核心组件

### OutputPipeline (7.1)
- 读取 Blueprint 状态 (`bp.enforce()`)
- 确定性后处理：句子截断、格式清洗、语气过滤、谄媚检测
- 语言无关——纯文本处理

### OutputGrammar (7.3)
- Blueprint → GBNF 语法规则
- 物理限制 token 采样空间
- MINIMAL=2 句, LOW=3 句, MEDIUM=5 句, HIGH=8 句
- RESPONSIVE_ONLY → 禁止 "？" token

### NativeLLMClient
- 子进程调用 llama.cpp (file IPC)
- 支持 CUDA/CPU，自动检测最佳模型
- `<think>` 块剥离（正则）
- 当前默认: Qwen3.5-4B Q4_K_M (2.8GB)

## 已验证的性能

| 模型 | 大小 | 速度 | 质量 |
|------|------|------|------|
| Qwen3.5-4B Q4 | 2.8GB | 7 t/s CPU | 优秀中文 |
| Qwen2.5-7B Q4 | 4.7GB | 4 t/s CPU | 最佳 |
| Qwen2.5-0.5B Q4 | 0.5GB | 36 t/s CUDA | 基础 |

## 路线图

| 阶段 | 动作 | 状态 |
|------|------|------|
| 7.1 | OutputPipeline — 代码层闸刀 | ✅ 完成 |
| 7.2 | 零样本分类 (暂缓) | ⏸️ 4 维度 embedding 够用 |
| 7.3 | 本地推理 + GBNF 语法约束 | ✅ 完成 |
| 7.4 | 云边协同：共享契约 + 智能路由 | 🔜 下一步 |

## 意外收获：云边协同的雏形

PLAN7 最初只是为了给 GBNF 找到物理执行层。但在接入本地推理后，系统自然形成了双后端架构：

```
云端 DeepSeek: 快(1s)、聪明、不可控
本地 Qwen3.5:  慢(7s)、中等、100% 可控 (GBNF)

共享: UserProfile / Blueprint / 契约事件 / 信任状态
```

这不是设计出来的——是架构的自然涌现。PLAN7.4 将正式化这个协同层。
