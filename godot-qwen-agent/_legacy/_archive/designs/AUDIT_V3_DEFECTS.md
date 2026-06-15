# V3 缺陷全量审计 — 2026-06-05

## 总览

| 层 | 文件数 | 🔴 致命 | 🟡 警告 | 🟢 建议 |
|----|--------|---------|---------|---------|
| 契约内核 | 3 | 1 | 5 | 3 |
| 适配器/控制 | 5 | 2 | 4 | 6 |
| REPL/入口 | 2 | 0 | 1 | 1 |
| RAG/检索 | 3 | 0 | 2 | 1 |
| 测试 | 12 | 0 | 0 | 1 |
| **总计** | **25** | **3** | **12** | **12** |

---

## 🔴 致命缺陷 (已修复 2/3)

### dynamic_blueprint.py:105 — 缺失 return 导致状态损坏
**状态**: ✅ 已修复 (commit 12079fe)
接受新颖值+Instruction 后缺失 `return`，代码落入冷却检查被误拒，
同时 `_history` 和 `_applied_count` 被重复追加。

### stream_interceptor.py:142 — JSON 触发时缓冲区取错偏移
**状态**: ⚠️ 未修复
`rfind("<")` 对 JSON 触发器 `{"tool"` 返回 -1，导致 `text_window[-1:]` 只取到末尾字符。
纯 JSON 工具调用被静默破坏。

### stream_interceptor.py:220 — 转义检测用错索引
**状态**: ⚠️ 未修复
`content[-2]` 永远取缓冲区倒数第二个字符，而非当前字符前一个。
`in_string` 追踪错误 → 括号深度计算不可靠 → 误判 JSON 闭合。

---

## 🟡 警告级缺陷

### 类型安全 (4 项)

| 文件:行 | 问题 |
|---------|------|
| dynamic_blueprint:56 | `_rejection_log: list[dict]` 未参数化，应 `list[dict[str,Any]]` |
| dynamic_blueprint:91-92 | `field_schema["type"]` 直接键访问，缺 KeyError 保护 |
| blueprint_schema:13 | `BLUEPRINT_SCHEMA: dict[str, dict]` 内层 dict 未参数化 |
| output_pipeline:46 | `bp: object` 而非 `DynamicBlueprint`，零静态类型检查 |

### 逻辑缺陷 (5 项)

| 文件:行 | 问题 |
|---------|------|
| stream_interceptor:98-100 | EXECUTING/FALLBACK 状态下 `feed()` 返回 TEXT 但不更新 `self.state` |
| output_pipeline:117 | 谄媚检测仅查文本开头——"关于您的观点，你说得对..." 被漏检 |
| output_pipeline:96 | `.` 同时匹配句号和缩写/数字/路径——英文混排时误截 |
| threshold_learner:134-138 | `__del__` 中 close DB——GC 线程不安全，`except: pass` 吞所有错误 |
| threshold_learner:100 | EMA `alpha` 无校验——传 2.0 不报错，产生异常阈值 |

### 数据完整性 (3 项)

| 文件:行 | 问题 |
|---------|------|
| tool_contract:37 | `min_trust` 无 [0,1] 钳位，frozen dataclass 无 `__post_init__` |
| tool_contract:65 | TOOLS 字典有 `whitelist`/`blocked_keywords` 等超集键，ToolContract 不认 |
| dynamic_blueprint:136-138 | 未知字段名直接写入 `self.fields`，不经过 Schema 校验 |

---

## 🟢 建议级

| 文件:行 | 建议 |
|---------|------|
| stream_interceptor:86 | `self._depth` 存储但从未读取——Dead Code |
| threshold_learner:128 | `save()` 是空操作 (update 已 commit)——文档误导 |
| relational_patterns:69 | 缺 `check_same_thread=False`——异步化时会炸 |
| relational_patterns:180-186 | `hint_map` 硬编码中文——多语言需重构 |
| dynamic_blueprint:94,100 | 幻数 5 和 80——应提为模块级常量 |
| TESTS | 260 测试 95% 单元——缺端到端集成测试 |
| REPL | FSM 在 main.py 中是事后扫描——未接实时 streaming |

---

## 修复优先级

| # | 缺陷 | 影响 | 修复难度 |
|---|------|------|---------|
| 1 | stream_interceptor JSON 缓冲区偏移 | 纯 JSON 工具调用被破坏 | 5 分钟 |
| 2 | stream_interceptor 转义检测索引 | JSON 括号深度不可靠 | 5 分钟 |
| 3 | output_pipeline 谄媚检测范围 | 99% 谄媚漏检 | 2 分钟 |
| 4 | tool_contract min_trust 无钳位 | 负信任值可能被写入 | 2 分钟 |
| 5 | blueprint_schema 未知字段绕过校验 | 可能写入无效字段 | 10 分钟 |
| 6 | threshold_learner __del__ 不安全 | 程序退出时可能崩溃 | 5 分钟 |
