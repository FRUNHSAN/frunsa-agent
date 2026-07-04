# 附录 B — 原始对话存档指引

**Last-verified-against-code**: `7e73374` (2026-07-04)

---

本体系正文中的全部论点均来自以下四次深度对话。原始对话完整存档在 `raw/conversations/` 目录中，以 git 版本管理——让未来的协作者和考古学家能够追溯每一个论点的原始上下文。

## 为什么不内联 25000 字对话

对话是"化石层"——它记录了思想涌现的**过程**，不是思想的**结构**。化石应该被存档和索引，而不是被塞进正文。让正文保持轻盈可维护，让化石留在 git 历史中供深度考古。

## 存档文件列表

```
raw/conversations/
├── 2026-07-04-01-agent-industry-survey.md        ← 行业 13 框架调研对话
├── 2026-07-04-02-harness-decomposition.md        ← Harness 编排层拆解
├── 2026-07-04-03-arm-to-cell-metaphor.md         ← 从 ARM 总线到细胞模型
├── 2026-07-04-04-frontier-injection-cell-mapping.md ← (X,D,π,ψ) 到细胞的逐点映射
├── 2026-07-04-05-sarcophagus-fungus-paradigm.md  ← 石棺与真菌 + 三代范式转移
├── 2026-07-04-06-topological-white-box.md        ← 拓扑白盒 + 约束≠启发式
├── 2026-07-04-07-dagger-prose-and-plan.md        ← 匕首式散文 + 文档体系设计
└── README.md                                      ← 对话索引
```

## 追踪方式

如果你想追溯某个论点的原始上下文：

1. 查 [附录A-关键决策追溯表.md](./附录A-关键决策追溯表.md)，找到论点的首次出现轮次
2. 对应到本页的存档文件列表
3. 在 git 中查看该文件的完整对话

---

> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。
