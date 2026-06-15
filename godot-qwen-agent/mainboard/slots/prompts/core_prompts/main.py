"""
CorePromptBundle — V9 核心提示词包。

用一个插件实例管理所有核心提示词。
未来若某个提示词变得极其复杂（需外部 API 获取 Few-shot），再将其剥离为独立插件。
"""

from string import Template
from typing import Any

from mainboard.plugin_sdk.protocol import PluginManifest, PromptSlot
from . import templates

_MANIFEST = PluginManifest(
    name="core_prompts",
    slot_type="prompt",
    version="1.0.0",
    protocol_version="9.2.0",
    description="V9 核心提示词集合 (Planning, Synthesis, Critic, Tool Resolver)",
    capabilities=frozenset({"bundle"}),
)


class CorePromptBundle:
    """核心提示词包。

    实现 PromptSlot Protocol。
    通过 context["template_name"] 路由到具体模板。
    """

    manifest = _MANIFEST
    prompt_id = "core_prompts"  # Bundle 使用统一 ID

    def __init__(self) -> None:
        self._templates: dict[str, Template] = {
            "planning": templates.PLANNING,
            "synthesis": templates.SYNTHESIS,
            "critic": templates.CRITIC,
            "tool_resolver": templates.TOOL_RESOLVER,
        }

    def build(self, context: dict[str, Any] | None = None) -> str:
        """渲染提示词。

        context 必须包含:
          - template_name: "planning" | "synthesis" | "critic" | "tool_resolver"
          - 以及对应模板所需的变量 (如 user_input, tool_results 等)

        使用 safe_substitute — 缺失变量不报错（Agent 上下文经常不完整）。
        """
        ctx = dict(context) if context else {}
        template_name = ctx.pop("template_name", None)

        if not template_name or template_name not in self._templates:
            available = list(self._templates.keys())
            raise ValueError(
                f"Unknown template: {template_name}. Available: {available}"
            )

        template = self._templates[template_name]
        return template.safe_substitute(ctx)

    @property
    def available_templates(self) -> list[str]:
        """返回所有可用模板名。供 LLMBridge 或 CLI 工具查询。"""
        return list(self._templates.keys())


def get_instance() -> CorePromptBundle:
    """工厂函数 — discovery 模块的约定入口。"""
    return CorePromptBundle()
