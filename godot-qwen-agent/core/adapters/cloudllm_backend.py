"""CloudLLM Backend — wraps DeepSeekClient as a GenerationBackend Protocol.

Bridges the synchronous DeepSeekClient.generate(prompt) -> str
into the GenerationBackend.generate(prompt, context, **params) -> GenerationResult
that engines expect.

~15 lines of business code. The rest is boilerplate for protocol compliance.
"""

from __future__ import annotations

from typing import Any, List

from core.contracts import Chunk, GenerationResult


class CloudLLMBackend:
    """Adapter: DeepSeekClient → GenerationBackend Protocol.

    Usage:
        from LLM.deepseek import DeepSeekClient
        client = DeepSeekClient(model="deepseek-chat")
        backend = CloudLLMBackend(client)
        adapter = GenerationAdapter(backend)
        engine = LLMPlanningEngine(adapter)
    """

    def __init__(self, client: object, model: str = "deepseek-chat") -> None:
        self._client = client
        self._model = model

    def generate(
        self, prompt: str, context: List[Chunk], **params: Any
    ) -> GenerationResult:
        """Generate text from the wrapped DeepSeekClient.

        Context is dropped — engines build their own prompts.
        Client is configured at construction time; params passed at runtime
        are noted but not forwarded (DeepSeekClient.generate() has fixed signature).
        """
        text = self._client.generate(prompt)
        return GenerationResult(
            text=text,
            model=self._model,
            finish_reason="stop",
            usage={
                "prompt_tokens": len(prompt) // 4,
                "completion_tokens": len(text) // 4,
                "total_tokens": (len(prompt) + len(text)) // 4,
            },
        )

    def count_tokens(self, text: str) -> int:
        """Estimate token count. Rough heuristic: 4 chars ≈ 1 token."""
        return len(text) // 4
