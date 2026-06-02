# llm/base.py
"""
LLM 客户端统一接口。

Phase 22: 新增 generate_with_tools() 和 LLMResponse 类型，
向后兼容 generate(prompt) -> str。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Literal


@dataclass(frozen=True)
class LLMResponse:
    """Structured return from LLM calls with optional tool use.

    Attributes:
        type:        "text" for plain text, "tool_call" for function calling
        content:     Text content (set when type="text")
        tool_name:   Tool name the LLM wants to call (set when type="tool_call")
        tool_input:  Arguments for the tool call (set when type="tool_call")
        tool_id:     Provider-specific tool call ID for multi-turn
        raw:         Full provider response for debugging
    """

    type: Literal["text", "tool_call"]
    content: str = ""
    tool_name: str = ""
    tool_input: Dict[str, Any] = field(default_factory=dict)
    tool_id: str = ""
    raw: Any = None

    @classmethod
    def from_text(cls, text: str, raw: Any = None) -> LLMResponse:
        return cls(type="text", content=text, raw=raw)

    @classmethod
    def from_tool_call(
        cls, name: str, arguments: Dict[str, Any],
        tool_id: str = "", raw: Any = None,
    ) -> LLMResponse:
        return cls(
            type="tool_call",
            tool_name=name,
            tool_input=arguments,
            tool_id=tool_id,
            raw=raw,
        )

    def is_tool_call(self) -> bool:
        return self.type == "tool_call"


class BaseLLMClient(ABC):
    """大语言模型客户端的统一接口。

    Phase 22: generate_with_tools() 支持函数调用。
    generate() 保持不变，向后兼容。
    """

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """基础文本生成。向后兼容，不修改签名。"""
        ...

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        """调用 LLM，可能返回 tool_call。

        Args:
            prompt: 用户提示
            tools:  工具定义列表（LLM 原生格式: Anthropic 或 OpenAI）

        Returns:
            LLMResponse — type="text" 或 type="tool_call"

        默认实现：无 tools 时退化为文本生成。
        子类必须重写此方法以支持实际 tool calling。
        """
        if not tools:
            text = self.generate(prompt)
            return LLMResponse.from_text(text)
        raise NotImplementedError(
            f"{type(self).__name__} does not implement generate_with_tools()"
        )
