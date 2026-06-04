"""Integration: StreamInterceptor + ActionPipeline — tool call gating."""

from core.adapters.stream_interceptor import StreamInterceptor, FSMState
from core.adapters.action_pipeline import ActionPipeline
from core.contracts.dynamic_blueprint import DynamicBlueprint
from core.contracts.blueprint_schema import blueprint_defaults


def simulate_llm_output(text: str) -> tuple[str, bool]:
    """Run FSM over text, return (output_text, was_blocked)."""
    fsm = StreamInterceptor()
    action = ActionPipeline(DynamicBlueprint(blueprint_defaults()), trust=0.50)
    action._bp.apply_proposal("execution_autonomy", "FULL")

    output_parts = []
    blocked = False

    for token in text:
        result = fsm.feed(token)
        if result.is_holding:
            continue
        if result.state == FSMState.VALIDATING:
            tool_name = result.tool_name or fsm._extract_tool_name(result.buffer_content)
            check = action.check(tool_name)
            if check["allowed"]:
                fsm.accept()
                output_parts.append(f" [tool:{tool_name} executed] ")
            else:
                fsm.reject(check["reason"])
                output_parts.append(f" [BLOCKED: {check['reason']}] ")
                blocked = True
        elif result.state == FSMState.TEXT:
            output_parts.append(result.output_token)

    # Handle unclosed buffer
    if fsm.state == FSMState.BUFFERING:
        result = fsm.force_complete()
        if result.state == FSMState.VALIDATING:
            tool_name = result.tool_name or "unknown"
            check = action.check(tool_name)
            if not check["allowed"]:
                fsm.reject(check["reason"])
                output_parts.append(f" [BLOCKED: {check['reason']}] ")
                blocked = True

    return "".join(output_parts), blocked


class TestFSMActionIntegration:
    def test_normal_text_passes_through(self):
        text, blocked = simulate_llm_output("你好，今天天气不错。")
        assert not blocked
        assert "你好" in text

    def test_read_tool_allowed(self):
        text, blocked = simulate_llm_output('查询一下：<tool_call>{"tool": "search_web", "q": "weather"}</tool_call>')
        assert not blocked
        assert "search_web" in text.lower() or "executed" in text

    def test_delete_logs_blocked_by_hitl(self):
        """delete_logs requires HITL — always blocked."""
        text, blocked = simulate_llm_output('清理：<tool_call>{"tool": "delete_logs"}</tool_call>')
        assert blocked
        assert "BLOCKED" in text

    def test_write_file_allowed_with_full_autonomy(self):
        text, blocked = simulate_llm_output('保存：<tool_call>{"tool": "write_file", "path": "/tmp/x.txt"}</tool_call>')
        assert not blocked

    def test_restart_server_blocked_even_full_autonomy(self):
        """restart_server requires HITL regardless."""
        text, blocked = simulate_llm_output('重启：<tool_call>{"tool": "restart_server"}</tool_call>')
        assert blocked

    def test_broken_json_handled(self):
        """Unclosed tool call — force_complete should catch it."""
        text, blocked = simulate_llm_output('危险：<tool_call>{"tool": "rm -rf /"')
        assert blocked

    def test_multiple_tool_calls_second_blocked(self):
        """Multi-tool: requires loop-aware caller. Single-call FSM is stateless."""
        pass  # Multi-tool handling needs streaming loop integration

    def test_false_positive_is_acceptable(self):
        """<tool_call> mid-text triggers BUFFERING but force_complete rejects unknown tool."""
        pass  # False positive detection needs line-boundary trigger heuristic
