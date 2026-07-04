# 对话存档 #2 — Harness 编排层深度拆解

**日期**：2026-07-04
**对应正文**：施工图层（harness-deep-dive/）

---

## 用户

你再帮我具体调研harness这个agent项目，进入plan模式，我需要一个拆解它的md文件构建体系。我甚至考虑了硬件上的总线，软件os的进程，这个框架是我最头疼的地方。

## AI

（完整阅读 har年.py 413 行 + adapter.py + track_c.py + 四条总线 + Plugin SDK + bootloader。理解 Harness 的 6 阶段循环：Observer → Adapter → Event Merge → Kernel → Execute → Telemetry。）

你的 Harness 是真正的薄编排器——不决策、不产文本、不调工具，只做组装、路由、计时、反馈。这个设计已被跨三个领域（CI/CD、测试框架、Agent 编排）的独立调研验证为行业最佳实践。薄编排器 + 胖技能 + 丰富执行平台 = winning formula。

但 Harness 当前缺：动态 DAG 工作流引擎、Checkpoint/Resume、多 Agent 路由、完整 HITL。

## 用户

（对 plan 文件提出 6 条结构性反馈：25000 字对话不内联、缺自我质疑文档、02/04 重叠、00 负担过重、缺活文档演化策略、写作风格问题）

## AI

（全部采纳。重写 plan：10 文件 → 13 文件，附录改为决策追溯表+git 存档指引，新增 04 和 09，合并 02/04，拆分 00，增加版本标记规范。）

---

> 本对话存档对应 [附录A-关键决策追溯表](../附录A-关键决策追溯表.md) 中的第 3-4 行。
