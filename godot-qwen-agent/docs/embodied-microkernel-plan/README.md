# 具身智能微内核 — 套磁/面试/协作文档体系

**总索引** — 17 个文件，五个维度：说服 / 对齐 / 锚定 / 查证 / 保护。

> 这个文档体系是从项目内部 1791 行数学白皮书、58 条推理链、63 条架构不变式中提取的"翻译层"。  
> 目标：让面试官/导师/协作者在各自需要的时间预算内，找到他们需要的答案。

---

## 目录结构与读者指南

```
docs/embodied-microkernel-plan/
│
├── 00-project-evolution.md              ← 🔴 基石。面试官第一个问题"你自己做的？"
├── 01-onboarding-for-collaborators.md   ← 🟢 协作者入口。"内核在哪、怎么读"
├── 02-technical-proposal.md             ← 🔵 主文档。投递青云计划/套磁附件
├── 03-math-whitepaper-bridge.md         ← 🔵 数学翻译。面试速读版
├── 04-feasibility-assessment.md         ← 🔵 可行性评估 + Non-Goals
├── 05-open-questions.md                 ← 🔵 待验证假设（带协作开放度）
├── 06-interview-strategy.md             ← 🔵 面试话术手册
├── 07-cold-email-templates.md           ← 🔵 套磁信模板（4类）
├── 08-architecture-diagram.md           ← 🔵 架构图 + 时序预算
├── 09-target-list.md                    ← 🔵 目标课题组/大厂清单
├── 10-demo-script.md                    ← 🔵 5分钟Demo精确脚本
├── 11-migration-guide.md                ← 🟢 "内核怎么拆出来"
├── 12-bus-manufacturing-guide.md        ← 🟢 "内核怎么接上通信层"
├── 13-adapter-kernel-version-protocol.md ← 🟢 "数据怎么翻译 + 版本怎么兼容"
├── 附录-核心概念索引.md                  ← 🟡 词汇表基础设施
├── 法律-开源许可与知识产权说明.md         ← 🟣 法务合规
└── README.md                            ← 本文件
```

### 按角色跳读

| 你的角色 | 你有多少时间 | 先读 | 再读 |
|---------|------------|------|------|
| **面试官/导师** | 5 分钟 | [02-technical-proposal.md](./02-technical-proposal.md) | [08-architecture-diagram.md](./08-architecture-diagram.md) |
| **面试官（追问"你自己做的？"）** | 10 分钟 | [00-project-evolution.md](./00-project-evolution.md) | [03-math-whitepaper-bridge.md](./03-math-whitepaper-bridge.md) |
| **课题组成员（做感知的）** | 30 分钟 | [01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md) — 第三节 | [11-migration-guide.md](./11-migration-guide.md) — 第六节 |
| **课题组成员（做控制的）** | 30 分钟 | [01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md) — 第三节 | [08-architecture-diagram.md](./08-architecture-diagram.md) |
| **课题组成员（做RL的）** | 30 分钟 | [01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md) — 第三节 | [03-math-whitepaper-bridge.md](./03-math-whitepaper-bridge.md) |
| **开源社区合作者** | 15 分钟 | [11-migration-guide.md](./11-migration-guide.md) | [12-bus-manufacturing-guide.md](./12-bus-manufacturing-guide.md) → [13-adapter-kernel-version-protocol.md](./13-adapter-kernel-version-protocol.md) |
| **适配器/总线开发者** | 30 分钟 | [12-bus-manufacturing-guide.md](./12-bus-manufacturing-guide.md) | [13-adapter-kernel-version-protocol.md](./13-adapter-kernel-version-protocol.md) |
| **大厂法务** | 5 分钟 | [法律-开源许可与知识产权说明.md](./法律-开源许可与知识产权说明.md) | [LICENSE](../../LICENSE) + [NOTICE](../../NOTICE) |
| **任何人遇到陌生概念** | 1 分钟 | [附录-核心概念索引.md](./附录-核心概念索引.md) | — |

---

## 五个维度覆盖

| 维度 | 核心问题 | 覆盖文档 |
|------|---------|---------|
| **说服**（你要我） | "这东西牛在哪？" | 02, 03, 04, 06, 07, 08, 10 |
| **对齐**（怎么和我干活） | "我怎么用你的内核？" | 01-onboarding, 11-migration, 12-bus, 13-adapter |
| **锚定**（你凭什么信我） | "这是你自己做的吗？" | 00-evolution, 05-open-questions, 09-target-list |
| **查证**（这个词什么意思） | "这个概念在说什么？" | 附录-核心概念索引 |
| **保护**（法务合规） | "我能合法使用和贡献吗？" | 法律-开源许可与知识产权说明 |

---

## 核心原则（贯穿全部 15 个文档）

1. **现状与想法严格分离** — 不吹泡沫，诚实亮缺陷，想法附带可行性评估
2. **弱化功利性，带着问题来** — "我是来做思想碰撞的，不是来镀金的"
3. **AI 是打字员，我是架构师** — 核心数学推导和架构决策是自己的
4. **数据采集的卡点在决策层** — 杀手级论点，面试时降维打击
5. **每个文档标注"参见已有文档"** — 展示项目深度，引导深入阅读
6. **让协作者能对齐和看懂** — 标注"你需要理解到什么程度"

---

## 通向 7 篇论文

这个项目不是因为"做完了"而停止的。它有 7 个可从现有代码和数学推导中直接展开的论文方向：
① MPC 微内核 → ICRA/RSS · ② 拓扑同态 → CDC/NeurIPS · ③ 安全仲裁 → CoRL/SafeRL  
④ 契约降级 → HRI/AAMAS · ⑤ 帧率无关ODE → CDC/ACC · ⑥ RL 策略槽位 → RLC/ICRA · ⑦ 达尔文演化 → ALIFE/GECCO

> 详见：[00-project-evolution.md](./00-project-evolution.md) — 第七节

---

## 法律

- 代码 (`mpc_kernel/`, `protocol/`, `mainboard/`) — Apache 2.0
- 文档 (`docs/`, `.ai_reasoning/`) — CC BY-SA 4.0
- 贡献规则 — 提交 PR 即同意上述许可条款（CLA-lite）

> 详见：[法律-开源许可与知识产权说明.md](./法律-开源许可与知识产权说明.md)  
> 根目录：[LICENSE](../../LICENSE) · [NOTICE](../../NOTICE)

---

## 维护

本文档体系将随以下事件更新：
- 新概念的引入（→ 更新附录-核心概念索引）
- 新缺陷的发现（→ 更新 05-open-questions）
- 新套磁目标的锁定（→ 更新 09-target-list）
- 进组后真实机器人验证结果（→ 更新 04-feasibility）

---

> 本索引采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。
