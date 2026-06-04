"""LocalLLMClient — PLAN7.3: local inference with constrained decoding.

Wraps llama-cpp-python. Supports GBNF grammar injection and logit bias
for physical token-space enforcement of contract constraints.

Usage:
    llm = LocalLLMClient(model_path="models/qwen2.5-0.5b.Q4_K_M.gguf")
    grammar = build_grammar(bp.snapshot)
    response = llm.generate(prompt, grammar=grammar)
    # LLM physically cannot generate tokens outside the grammar
"""

from __future__ import annotations

import os
from typing import Any

try:
    from llama_cpp import Llama, LlamaGrammar
    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False


class LocalLLMClient:
    """Local LLM backend with constrained decoding support.

    Usage:
        llm = LocalLLMClient("models/qwen2.5-0.5b.Q4_K_M.gguf")
        llm.generate("Hello", grammar="root ::= [A-Za-z ]+")
    """

    def __init__(
        self,
        model_path: str,
        n_ctx: int = 2048,
        n_threads: int = 4,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        if not HAS_LLAMA_CPP:
            raise ImportError("llama-cpp-python not installed. pip install llama-cpp-python")
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        self._model = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            verbose=False,
        )
        self._temperature = temperature
        self._max_tokens = max_tokens

    def generate(
        self,
        prompt: str,
        grammar: str = "",
        logit_bias: dict[int, float] | None = None,
    ) -> str:
        """Generate text with optional grammar constraints.

        Args:
            prompt: The text prompt
            grammar: GBNF grammar string. If empty, unconstrained generation.
            logit_bias: {token_id: bias} map. Negative = suppressed.

        Returns: Generated text string.
        """
        kwargs: dict[str, Any] = {
            "prompt": prompt,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if grammar:
            kwargs["grammar"] = LlamaGrammar.from_string(grammar)
        if logit_bias:
            kwargs["logit_bias"] = logit_bias

        try:
            output = self._model(**kwargs)
            return output["choices"][0]["text"].strip() or ""
        except Exception as e:
            return f"(Local LLM error: {e})"

    def resolve_token_ids(self, text: str) -> list[int]:
        """Convert text to token IDs using the model's tokenizer."""
        return self._model.tokenize(text.encode("utf-8"))

    def build_bias_map(self, banned_strings: list[str], bias: float = -100.0) -> dict[int, float]:
        """Build logit_bias map for banned token strings."""
        result: dict[int, float] = {}
        for s in banned_strings:
            ids = self.resolve_token_ids(s)
            for tid in ids:
                result[tid] = bias
        return result

    @property
    def model_loaded(self) -> bool:
        return True
