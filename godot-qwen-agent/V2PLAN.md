# V2 计划 — 流式拦截 + 在线学习

> **代码钳制，不是 Prompt 建议。**
> V1 证明了契约引擎可行。V2 让契约在 token 级别拦截 LLM 输出，并学会个人化。

## V2-V3 优先级与完成状态

| # | 优先级 | 范围 | 状态 |
|---|--------|------|------|
| 1 | 260 测试 | PLAN5-8 + V2 + V3 全覆盖 | ✅ 完成 |
| 2 | SQLite 持久化 | 替换 JSON UserProfile，WAL 模式 | ✅ 完成 |
| 3 | 流式拦截 FSM | 五态状态机，token 级契约拦截 | ✅ 完成 |
| 4 | 在线阈值学习 | EMA 个人化阈值 + 双轨信任 | ✅ 完成 |
| 5 | 叙事涌现 | CBO 模式 → LLM 生成用户画像 | ✅ 完成 |
| 6 | 关系预判 | PatternRepository 主动提示 | ✅ 完成 |
| 7 | X-Ray 仪表盘 | Rich 终端架构透视 | ✅ 完成 |
| 8 | 语义命令分类 | Embedding 替换手写关键词 | ✅ 完成 |
| 9 | 自演化契约值 | 新值+Instruction, GC 生命周期 | ✅ 完成 |
| 10 | 契约约束 RAG | knowledge_search + 后检索护栏 | ✅ 完成 |
| 11 | 三 chunker 管线 | identity/keyword/semantic via COMPONENT_REGISTRY | ✅ 完成 |
| 12 | 会话冷启动 | /new 重置 trust/tone/initiative | ✅ 完成 |
| 13 | llama-server HTTP | 替换子进程，常驻模型 | ⏸️ 等待稳定版 |
| 14 | 清剿死代码 | 删除 8 个 0 实现/0 调用文件 (~900行) | ✅ V4 |
| 15 | Registry 冻结 | COMPONENT_REGISTRY.freeze() in Container | ✅ V4 |
| 16 | REPL 合并 | run_live.py 删除, 唯一入口 core/repl.py | ✅ V4 |
| 17 | REPL 测试 | 18 个命令/提案/提示/会话测试 | ✅ V4 |
| 18 | RAG 集成测试 | 11 个检索+护栏+信任全链路测试 | ✅ V4 |
| 19 | 引擎点火 | Track A/B + Planning/Orch/Critic | ✅ V4.1 |
| 20 | RAG 缓存 | 预热+mtime+LRU+中文二元组 | ✅ V4.1 |
| 21 | MCP 集成 | 动态工具发现 | ⏸️ V4.2 |
| 22 | 引擎深化 | Track C: Planning/Orch/Critic 全开 + 重试 | ✅ V4.1 |
| 23 | 打磨 | 规划粒度 + 语义截断 + 告别路由 | ✅ V4.1 |
| 24 | 速度优化 | Track C 50s→15s | ⏸️ V4.2 |
| 25 | MCP 集成 | 动态工具发现 + /mcp + Agent 自动调用 | ✅ V4.2 |
| 26 | ToolEngine | 工具晋升为第四引擎, StreamItem 管道 | ✅ V4.3 |
| 27 | 速度优化 | Track C 50s→15s | ⏸️ V4.2 |

---

## 流式拦截状态机

V2 核心创新。LLM 流式输出时，契约在危险 token 到达用户之前拦截。

```
文本模式 ──[检测到 <tool_call>]──→ 缓冲模式 ──[JSON 闭合]──→ 校验模式
    ↑                                  │                          │
    │                          [超时/溢出]                  ┌─────┴─────┐
    │                                  │                    │           │
    └──────────────────────────────────┘              [通过] ✓     [拒绝] ✋
                                                         │           │
                                                    执行模式     降级模式
                                                         │           │
                                                    [结果回注]  [注入拦截提示]
```

### 状态定义

| 状态 | 条件 | 动作 |
|------|------|------|
| **文本** | 默认。LLM 正常输出。 | token 直接透传到前端。 |
| **缓冲** | 检测到工具调用标记。 | 挂起流。token 吸入内存 Buffer。上限 4KB。超时 10 秒。 |
| **校验** | Buffer 包含完整 JSON。 | 解析工具名和参数。调用 ActionPipeline 校验。 |
| **执行** | 契约放行。 | 执行工具。结果回注 LLM。恢复流式。 |
| **降级** | 契约拒绝。 | 丢弃 Buffer。注入拦截提示。危险 JSON 绝不泄露。 |

### 边界处理

1. **残缺 JSON**：LLM 输出了 `{"tool": "de` 后断网 → 超时 → 丢弃 → 降级。
2. **缓冲区溢出**：LLM 输出 8KB 恶意数据 → 4KB 硬上限 → 截断 → 降级。
3. **嵌套工具调用**：LLM 输出 `<tool>...</tool><tool>...</tool>` → 处理第一个，缓冲第二个。
4. **误触发**：用户说"用 `<tool_call>` 标签" → 触发缓冲，但因无有效 JSON 被 force_complete 拒绝。可接受。
5. **流恢复**：降级后，注入拦截提示到 LLM 上下文，让 LLM 重新生成自然语言回复。

---

## 在线阈值学习

### 核心理念

不是神经网络。就是统计。EMA 公式：

```
新阈值 = (1 - α) × 旧阈值 + α × 触发分数
α = 0.25 (显式反馈: 用户说"字少点")
α = 0.05 (隐式反馈: 用户对长回复回"哦")
```

### 硬护栏

| 维度 | 下限 | 上限 | 理由 |
|------|------|------|------|
| fatigue | 0.30 | 0.80 | 不能太敏感（永远降级），也不能太迟钝（永不降级） |
| frustration | 0.30 | 0.80 | 同上 |
| gratitude | 0.30 | 0.70 | 感激阈值保持保守 |
| curiosity | 0.25 | 0.65 | 好奇心阈值保持敏感 |

### 架构解耦

```python
# 当前：EMA 学习器
learner = EMALearner(user_id="frunhsan")
new_t = learner.update("fatigue", 0.42, alpha=0.2)

# 未来：神经网络学习器（接口不变）
learner = NeuralLearner(user_id="frunhsan")
new_t = learner.update("fatigue", 0.42)  # 同一个接口
```

`ThresholdLearner` 是 Protocol，任何实现只要满足 `update()` 和 `get()` 签名即可替换。

---

## 架构决策记录

### ADR-002：流式拦截器是独立组件

拦截器位于 `llm.generate_stream()` 和前端之间。
它不属于 ActionPipeline——ActionPipeline 校验完整的工具调用。
拦截器决定**何时**调用 ActionPipeline。

```
LLM 流 → [FSM 拦截器] → 校验通过的 JSON → ActionPipeline.check()
              │
              ├── 文本模式 token → 前端 (直接透传)
              └── 降级模式注入 → LLM 上下文 (绝不透传)
```

### ADR-003：SQLite WAL 模式是强制的

`PRAGMA journal_mode=WAL` 启用读写并发。
不开启 WAL，每次 `profile.save()` 锁死整个数据库。
`busy_timeout=5000` 给 5 秒锁等待时间。

### ADR-005：EMA 学习率按反馈强度分级

显式反馈 (用户说"字少点") → α=0.25，强信号，快速调整。
隐式反馈 (用户回"哦") → α=0.05，弱信号，缓慢漂移。
硬护栏钳位，防止恶意驯化和阈值漂移。

---

## 时间线

```
第 1-2 周: 175+ 测试 (DynamicBlueprint, EvolutionEngine, ActionPipeline, Backlash) ✅
第 3 周:   SQLite 持久化 (WAL 模式 + JSON 自动迁移) ✅
第 4-5 周: 流式拦截 FSM (五态实现 + 边界测试) ✅
第 6 周:   在线阈值学习 (EMA + 反馈采集 + 接口解耦) ✅
第 7 周:   llama-server HTTP (子进程替换，待稳定版)
```
