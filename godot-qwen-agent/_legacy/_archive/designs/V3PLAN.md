# V3 计划 — 自演化 + 契约RAG + 完整生命周期

> **涌现不是在真空中——边界由执行器定义。护栏之内，自由演化。**

## 定位

V2 完成了流式拦截和在线学习。但契约仍限于 8 个预定义枚举值。
用户问"情绪不够用"、"RAG 怎么加"、"涌现有没有边界"——三个问题的根因相同：
**契约的执行器不认识新字段。** 边界不是限制——是安全性保证。

## 核心创新

### 自演化契约值
- 新值自带 Instruction（5-80 字符），OutputPipeline 自动渲染
- 示例: `tone_style: KAOMOJI_HEAVY` + "高频使用日式颜文字"
- GC: 60 轮未激活的涌现值自动清除
- 护栏: 指令长度校验、字段白名单（只能改 8 个已有字段，不能发明新字段）

### 契约约束 RAG
- `knowledge_search` 注册为 ToolContract（min_trust=0.20）
- 三层防护: Trust 门控 → 白名单路径校验 → 关键词拦截
- 后检索护栏: 拦截内容替换为 `<SYSTEM>不可访问</SYSTEM>`，LLM 从未看到原始数据
- 语义检索: embedding 余弦相似度（同 SemanticTrust 模型），"微服务"字面不匹配但语义命中
- 关键词降级: embedding 不可用时自动回退

### 三 Chunker 管线
- `identity`: 整文档一块
- `keyword`: 段落级，可配 size+overlap
- `semantic`: 句子级 + embedding 相似度分割，模型不可用时降级正则
- 通过 `COMPONENT_REGISTRY` 注册，`search("query", chunker_name="x")` 一行切换

### 完整生命周期
- 字段值: Decay 风化回基线
- 涌现值: 60 轮 GC
- CBO 模式: 28 天置信度衰减
- 提案: Cooldown 5 轮
- 用户画像: 离群值过滤 + 修正案去重
- 会话: `/new` 冷启动重置 trust/tone/initiative

### X-Ray 仪表盘
- Rich 终端架构透视，每轮渲染管道流转
- 零侵入——纯展示层，删除 3 行即可关闭

### 双轨信任
- Track A (Embedding): ~30ms 快速判断
- Track B (LLM 兜底): Embedding 不可用或模糊区(0.3-0.6)时触发
- 消除关键词匹配脆断

### 语义命令分类
- Embedding 锚点替换手写 30 个关键词
- "你倒是问问题呀" → PROACTIVE，"字少一点" → MINIMAL

### 叙事涌现
- CBO 模式积累 → NarrativeEmergence → 100 字用户画像
- 注入 System Prompt 作为"潜意识"

## 完成状态

| # | 功能 | 状态 |
|---|------|------|
| 1 | 自演化契约值 + 指令 GC | ✅ |
| 2 | 契约约束 RAG (knowledge_search) | ✅ |
| 3 | 后检索护栏 (guard_post_retrieval) | ✅ |
| 4 | 三 chunker 管线 (identity/keyword/semantic) | ✅ |
| 5 | 语义检索 (embedding cosine) | ✅ |
| 6 | X-Ray 仪表盘 | ✅ |
| 7 | 双轨信任 (Embedding + LLM) | ✅ |
| 8 | 语义命令分类 (替换关键词) | ✅ |
| 9 | 叙事涌现 (NarrativeEmergence) | ✅ |
| 10 | 会话冷启动 (/new 重置) | ✅ |
| 11 | /rag on|off 自动模式 | ✅ |
| 12 | /mood 命令 | ✅ |
| 13 | 会话日志保存 | ✅ |
| 14 | 完整生命周期 (decay + GC + cooldown + outlier) | ✅ |
| 15 | 关系预判 (PatternRepository) | ✅ |

## 测试

289 单元测试。0 失败。
