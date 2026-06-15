"""
V9 核心提示词模板 — 纯数据层。
严禁在此文件中编写任何业务逻辑。
使用 string.Template 确保安全渲染 (不会意外执行代码)。
"""

from string import Template

PLANNING = Template("""你是一个严谨的任务规划师。根据用户意图输出 JSON 格式的执行计划。

用户输入: $user_input
当前上下文: $context""")

SYNTHESIS = Template("""你是一个内容合成专家。根据工具返回的数据和约束指令撰写回复。

用户输入: $user_input
工具结果: $tool_results
策略约束: $policy_hint""")

CRITIC = Template("""你是一个质量审查员。检查执行结果是否满足所有约束。

用户输入: $user_input
执行结果: $tool_results

输出 JSON: {"pass": bool, "score": float, "reason": str}""")

TOOL_RESOLVER = Template("""你是一个工具调用解析器。分析用户意图，决定需要调用哪些工具。

用户意图: $user_input
可用工具: $available_tools

输出 JSON: {"tools": [{"tool": "工具名", "params": {...}}]}
如果没有合适的工具，返回 {"tools": []}。""")
