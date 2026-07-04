# 对话存档 #1 — 行业 Agent 框架调研

**日期**：2026-07-04
**对应正文**：[08-行业调研验证.md](../08-行业调研验证.md)

---

## 用户

我想知道现在行业主流的agent组件都有哪些？我希望的直接从各种热度较高的开源项目进行调研。同时帮我科普agent的很多套件的位置、环节，层级，并用一句话通俗移动和一个md文件详细介绍。。。因为我的项目在工业生产和个人使用上找不到可以借鉴的项目。。。学术又太繁杂了我感觉没必要，主要为我的这个内核设计一个完全释放甚至倒逼内核迭代的全新框架（我给我自己写的定制agent），光靠我脑子想是没办法完全覆盖到的。你的看法是？

## AI

（调研 13 个框架：LangChain/LangGraph ~122k、CrewAI ~51k、AutoGen ~58k、Dify ~144k、MetaGPT ~62k、LlamaIndex ~41k、DSPy ~35k、Semantic Kernel ~24k、OpenAI Agents SDK ~25k、Google ADK ~20k、Camel ~16k、Letta ~15k、smolagents ~18k）

核心结论：**全行业在造"更好的 LLM 外壳"。你的 MPC 微内核不在同一品类——所有框架在"大脑"层竞争（LLM 编排/记忆/工具），你的内核在"小脑+脑干"层（数学状态演化/安全仲裁/实时控制）。**

你的 Harness 是行业最干净的薄编排器——413 行完成 6 阶段循环 + 3 分叉 + 工具解析双轨 + 崩溃隔离。但行业在 LangGraph Checkpoint/Resume、Delta Channels 存储优化、Dify 可视化编排等方面领先。

输出：[industry-agent-component-survey.md](../industry-agent-component-survey.md) —— 完整 13 框架对比 + Agent 组件全景（5层×26组件）+ 框架设计建议。

## 用户

你再帮我具体调研harness这个agent项目，进入plan模式，我需要一个拆解它的md文件构建体系

## AI

（完整拆解 Harness 代码，413 行，6 阶段循环。3 个探索 agent 并行分析代码 + 行业编排模式调研。发现：Harness 的薄编排器设计已被行业独立验证为最佳实践。）

设计了一套 7-8 个文件的 Harness 文档体系，后经用户评审调整为更严谨的结构。

---

> 本对话存档对应 [附录A-关键决策追溯表](../附录A-关键决策追溯表.md) 中的第 1-2 行。
