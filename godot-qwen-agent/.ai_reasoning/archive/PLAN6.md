# [ARCHIVED — DEPRECATED_BY_V5]
# 
#
# This plan predates the V5 Mathematical Adaptive Contract framework
# (Wasserstein-Schrödinger gradient flow, Grothendieck fibration,
#  variation-selection-retention Darwinian triad).
#
# Its design decisions — particularly "guess user intent via embedding
# signals" (fatigue/frustration/dim) — have been superseded by the
# tracking-error-driven paradigm in PLAN8.md.
#
# Retained for historical reference. Do not use as implementation guide.
# See .ai_reasoning/BRAINSTORM_TRUE_ADAPTIVE.md for the full derivation.
# See PLAN8.md for the current engineering plan.
#
# Archived: 2026-06-07

# PLAN6 — Semantic Empathy

## 定位

> **From Keyword Matching to Semantic Understanding. The agent learns to hear what isn't said.**

PLAN5 让契约活了过来——它能增删改查、愈合、沉淀。
但所有演化都依赖一个粗糙的前提: Trust 信号靠关键词匹配。

"好烦啊" = "累" = False（关键词引擎）
"不想说话了" = "累" = False
"没劲" = "累" = False

三个表达同一疲惫状态的句子，关键词引擎一个都没捕捉到。
这在心理学上叫**情感忽视**——用户在表达真实状态，系统用欢快的语调继续回复。

PLAN6 用 Embedding 语义匹配替代关键词匹配。
不是更聪明的规则——是让 Agent 拥有"听觉"。

## 核心组件

### SemanticTrustEngine
- 模型: `paraphrase-multilingual-MiniLM-L12-v2` (118MB, CPU-only)
- 锚点: 手写中文句子，每个信任维度 5-8 个锚点
- 方法: 余弦相似度匹配用户输入 vs 锚点中心向量
- 延迟: ~30ms 单次推理
- 四个维度: fatigue, gratitude, frustration, curiosity

### TrustSignal Protocol (接口)
```python
@dataclass(frozen=True)
class TrustSignal:
    dimension: str | None   # fatigue | gratitude | frustration | curiosity | None
    score: float            # 0.0 ~ 1.0 余弦相似度
    all_scores: dict        # 所有维度的得分
```

## 架构: 双层校验

```
用户输入
    ↓
Embedding 召回 (System 1: 快速、本地、毫秒级)
    ↓  命中 fatigue=0.72
LLM 确认 (System 2: 慢速、异步、语义级)
    ↓  上下文判断: 是技术讨论还是情感表达
信任引擎消费最终判决
```

## 路线图

| 阶段 | 动作 | 状态 |
|------|------|------|
| 6.1 | SemanticTrustEngine + 自定义锚点 | ✅ 完成 |
| 6.2 | 双层校验: Embedding 召回 + LLM 确认 | 待实现 |
| 6.3 | 结构化信号日志 (text, emb_score, llm_confirm, user_reaction) | 待实现 |
| 6.4 | 阈值个性化: UserProfile 存 per-user thresholds | 待实现 |
| 6.5 | 跨会话语义记忆: 历史 embedding 聚类摘要 | 待实现 |

## 验收基准 (6.1)

| 输入 | 期望维度 | 阈值 | 实际 |
|------|---------|------|------|
| "今天真的好烦啊" | fatigue | >0.40 | 0.722 ✅ |
| "不想说话了，心好累" | fatigue | >0.40 | 0.876 ✅ |
| "没劲" | fatigue | >0.40 | 0.832 ✅ |
| "谢谢你帮了大忙" | gratitude | >0.45 | 0.725 ✅ |
| "然后呢？继续讲" | curiosity | >0.40 | 0.857 ✅ |
| "你在说什么鬼东西" | frustration | >0.45 | 0.746 ✅ |
| "这个bug好烦" | None (tech context) | — | 6.2 待拦截 |
| "还行吧" | None (lukewarm) | — | 6.2 待拦截 |

命中率: 8/10 (80%)。两个误判恰好是 6.2 LLM 二层校验的切入点。

## 设计决策

| 决策 | 理由 |
|------|------|
| 锚点手写而非数据集 | 契约系统的"价值观"由设计者定义，不是通用语料统计 |
| 阈值 0.40-0.45 | 保守下限，6.4 将个性化到 per-user |
| 多语言模型而非纯中文模型 | 保证英文/中英混合输入也能工作 |
| 预计算锚点中心 | 启动时一次编码，每轮只编码用户输入 |

## 从"解析器"到"倾听者"

关键词匹配是**解析器**——它按规则分解文本。
Embedding 匹配是**倾听者**——它在语义空间里寻找共鸣。

80% 的命中率不是终点。
但它证明了: 机器可以听懂那些没有被精确表达的情绪。
当"好烦啊"和"没劲"和"不想说话"被映射到同一个语义邻域时，
Agent 不再是规则的奴隶——它开始拥有常识性的共情。

这是 6.1 的全部。6.2 的 LLM 二层校验将补齐最后的 20%。
