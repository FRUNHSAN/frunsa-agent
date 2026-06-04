"""StreamInterceptor — V2: token-level contract enforcement FSM.

Intercepts LLM streaming output BEFORE tokens reach the user.
When a tool call is detected, holds the stream, buffers the JSON,
validates against the contract, and either executes or blocks.

States:
  TEXT       — normal streaming, tokens pass through
  BUFFERING  — tool call detected, accumulating tokens silently
  VALIDATING — buffer complete, checking contract
  EXECUTING  — contract allowed, tool runs
  FALLBACK   — contract blocked, alert injected

This is the "crown jewel" of contract-bound agents.
No other framework does this — because no other framework has
a real contract enforcement layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Iterator


class FSMState(Enum):
    TEXT = auto()
    BUFFERING = auto()
    VALIDATING = auto()
    EXECUTING = auto()
    FALLBACK = auto()


@dataclass
class InterceptResult:
    """What the stream interceptor should do next."""
    state: FSMState
    output_token: str = ""            # Token to send to frontend (empty = hold)
    buffer_content: str = ""          # Accumulated tool call JSON (only in VALIDATING)
    tool_name: str = ""               # Parsed tool name (only in EXECUTING/FALLBACK)
    block_reason: str = ""            # Why blocked (only in FALLBACK)

    @property
    def is_holding(self) -> bool:
        return self.state == FSMState.BUFFERING

    @property
    def is_blocked(self) -> bool:
        return self.state == FSMState.FALLBACK

    @property
    def is_executing(self) -> bool:
        return self.state == FSMState.EXECUTING


class StreamInterceptor:
    """Token-level contract enforcement FSM.

    Usage:
        interceptor = StreamInterceptor()
        for token in llm_stream:
            result = interceptor.feed(token)
            if result.is_holding:
                continue  # Don't send to frontend
            if result.is_blocked:
                # Inject alert, don't execute
                break
            # Send result.output_token to frontend
    """

    # Tool call triggers — tokens that switch from TEXT to BUFFERING
    TRIGGERS = ["<tool_call>", '<tool_call']

    # Tool call end marker
    END_MARKER = "</tool_call>"

    # JSON-based triggers (line-start)
    JSON_TRIGGERS = ['{"tool"', '{"tool_call"']

    MAX_BUFFER_BYTES = 4096  # 4KB limit

    def __init__(self) -> None:
        self.state = FSMState.TEXT
        self._buffer: list[str] = []
        self._last_buffer: str = ""  # Preserved for VALIDATING state
        self._depth = 0
        self._text_window: str = ""  # Rolling window for trigger detection

    def feed(self, token: str) -> InterceptResult:
        """Process one token. Returns what the caller should do."""
        if self.state == FSMState.TEXT:
            return self._handle_text(token)
        elif self.state == FSMState.BUFFERING:
            return self._handle_buffering(token)
        elif self.state == FSMState.VALIDATING:
            return self._handle_validating()
        elif self.state == FSMState.EXECUTING:
            return InterceptResult(state=FSMState.TEXT, output_token="")
        elif self.state == FSMState.FALLBACK:
            return InterceptResult(state=FSMState.TEXT, output_token="")
        return InterceptResult(state=FSMState.TEXT, output_token=token)

    def force_complete(self) -> InterceptResult:
        """Called when stream ends. If buffering, treat as VALIDATING."""
        if self.state == FSMState.BUFFERING and self._buffer:
            content = "".join(self._buffer)
            tool_name = self._extract_tool_name(content)
            self._last_buffer = content
            self.state = FSMState.VALIDATING
            return InterceptResult(
                state=FSMState.VALIDATING,
                buffer_content=content,
                tool_name=tool_name,
            )
        return InterceptResult(state=FSMState.TEXT)

    def overflow(self) -> InterceptResult:
        """Buffer exceeded MAX_BUFFER_BYTES. Discard and alert."""
        self._reset()
        self.state = FSMState.FALLBACK
        return InterceptResult(
            state=FSMState.FALLBACK,
            block_reason="Buffer overflow: tool call exceeded 4KB limit.",
        )

    def timeout(self) -> InterceptResult:
        """Stream timed out during buffering. Discard incomplete JSON."""
        self._reset()
        self.state = FSMState.FALLBACK
        return InterceptResult(
            state=FSMState.FALLBACK,
            block_reason="Tool call stream timed out. Incomplete JSON discarded.",
        )

    # ── State handlers ──

    def _handle_text(self, token: str) -> InterceptResult:
        # Accumulate sliding window for trigger detection (handles char-level tokens)
        self._text_window = (self._text_window + token)[-200:]  # Keep last 200 chars
        if self._is_trigger(self._text_window):
            self.state = FSMState.BUFFERING
            self._buffer = [self._text_window[self._text_window.rfind("<"):]]  # From trigger start
            self._text_window = ""
            return InterceptResult(state=FSMState.BUFFERING)
        return InterceptResult(state=FSMState.TEXT, output_token=token)

    def _handle_buffering(self, token: str) -> InterceptResult:
        self._buffer.append(token)
        content = "".join(self._buffer)

        # Check overflow
        if len(content.encode("utf-8")) > self.MAX_BUFFER_BYTES:
            return self.overflow()

        # Check completion
        if self._is_complete(content):
            tool_name = self._extract_tool_name(content)
            self._last_buffer = content
            self.state = FSMState.VALIDATING
            return InterceptResult(
                state=FSMState.VALIDATING,
                buffer_content=content,
                tool_name=tool_name,
            )

        return InterceptResult(state=FSMState.BUFFERING)

    def _handle_validating(self) -> InterceptResult:
        return InterceptResult(
            state=FSMState.VALIDATING,
            buffer_content=self._last_buffer,
        )

    def accept(self) -> InterceptResult:
        """Contract passed. Execute the tool."""
        self._reset()
        self.state = FSMState.EXECUTING
        return InterceptResult(state=FSMState.EXECUTING)

    def reject(self, reason: str) -> InterceptResult:
        """Contract blocked. Generate fallback alert."""
        content = "".join(self._buffer)
        self._reset()
        self.state = FSMState.FALLBACK
        return InterceptResult(
            state=FSMState.FALLBACK,
            block_reason=reason,
            buffer_content=content,
        )

    @property
    def fallback_alert(self) -> str:
        """Injected into LLM context when tool is blocked."""
        return (
            "\n[System Alert] Your tool call was intercepted by the contract engine.\n"
            "The operation was NOT executed. Explain this to the user and ask for authorization.\n"
        )

    # ── Helpers ──

    def _is_trigger(self, token: str) -> bool:
        for t in self.TRIGGERS:
            if t in token:
                return True
        # JSON trigger: token starts a line with {"tool"
        stripped = token.lstrip()
        for jt in self.JSON_TRIGGERS:
            if stripped.startswith(jt):
                return True
        return False

    def _is_complete(self, content: str) -> bool:
        if self.END_MARKER in content:
            return True
        # Brace-depth method: count { and }
        depth = 0
        in_string = False
        for ch in content:
            if ch == '"' and (len(content) > 0 and content[-2] != '\\'):
                in_string = not in_string
            if not in_string:
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
        return depth == 0 and depth is not None and '{' in content

    @staticmethod
    def _extract_tool_name(content: str) -> str:
        """Best-effort extraction of tool name from JSON or XML."""
        import re
        # Try XML: <tool_call>{"tool": "name"...}</tool_call>
        m = re.search(r'"tool"\s*:\s*"([^"]+)"', content)
        if m:
            return m.group(1)
        # Try bare JSON
        m = re.search(r'"name"\s*:\s*"([^"]+)"', content)
        if m:
            return m.group(1)
        return "unknown"

    def _reset(self) -> None:
        self._buffer = []
        self._last_buffer = ""
        self._text_window = ""
        self._depth = 0

    @property
    def buffer_size(self) -> int:
        return len("".join(self._buffer).encode("utf-8"))
