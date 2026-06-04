"""NativeLLMClient — subprocess wrapper for llama-cli.exe.

Zero pip dependencies. Uses the user's CUDA-compiled llama-cli.exe
directly. Supports GBNF grammar via --grammar-file flag.

Disk space: 0. No pip, no C++ compilation, no shared library hell.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


BINARY = Path(__file__).resolve().parent.parent / "llama" / "llama-completion.exe"
# Default: auto-detect best model available
def _default_model() -> Path:
    base = Path(__file__).resolve().parent.parent
    # Best → fallback
    candidates = [
        Path("d:/tuili/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"),
        base / "models/Qwen3.5-4B-Q4_K_M.gguf",
        base / "models/qwen2.5-7b*q4*00001*",
        base / "models/qwen2.5-0.5b*q4*",
    ]
    for p in candidates:
        if "*" in str(p):
            matches = sorted(base.glob(str(p).split("/")[-1]))
            if matches: return matches[0]
        elif p.exists():
            return p
    return base / "models/qwen2.5-0.5b-instruct-q4_k_m.gguf"


class NativeLLMClient:
    """Calls llama-cli.exe via subprocess. GBNF via --grammar-file."""

    def __init__(
        self,
        binary_path: str = "",
        model_path: str = "",
        n_ctx: int = 2048,
        n_gpu_layers: int = 0,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self._binary = Path(binary_path) if binary_path else BINARY
        self._model = Path(model_path) if model_path else _default_model()
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._ngl = n_gpu_layers
        self._ctx = n_ctx

        if not self._binary.exists():
            raise FileNotFoundError(f"Binary not found: {self._binary}")
        if not self._model.exists():
            raise FileNotFoundError(f"Model not found: {self._model}")

    def generate(self, prompt: str, grammar: str = "") -> str:
        """Generate text. File IPC — stdout→temp file, stderr→DEVNULL.

        Uses stdin piping to trigger llama.cpp chat mode with auto template.
        """
        grammar_file = None
        if grammar:
            fd_g, grammar_file = tempfile.mkstemp(suffix=".gbnf", prefix="grammar_")
            with os.fdopen(fd_g, "w", encoding="utf-8") as f:
                f.write(grammar)

        # Output file
        fd_out, output_file = tempfile.mkstemp(suffix=".txt", prefix="llama_out_")
        os.close(fd_out)

        # System prompt written to temp file, passed via -f
        fd_sys, sys_file = tempfile.mkstemp(suffix=".txt", prefix="sys_")
        with os.fdopen(fd_sys, "w", encoding="utf-8") as f:
            f.write(f"你是一个友好的AI助手。\n\nUser: {prompt}\nAssistant:")

        cmd = [
            str(self._binary),
            "-m", str(self._model),
            "-f", sys_file,
            "-n", str(self._max_tokens),
            "-t", "8",
            "-ngl", str(self._ngl),
            "-c", str(self._ctx),
            "--temp", str(self._temperature),
        ]
        if grammar_file:
            cmd.extend(["--grammar-file", grammar_file])

        try:
            with open(output_file, "w", encoding="utf-8") as f_out:
                subprocess.run(
                    cmd,
                    cwd=str(self._binary.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=f_out,
                    stderr=subprocess.DEVNULL,
                    timeout=45,
                )

            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read().strip()

            # Strip ANSI, thinking, display-prompt, control chars
            import re
            raw = re.sub(r'\x1b\[[0-9;]*m', '', raw)
            raw = re.sub(r'<think>.*?(?:</think>|$)', '', raw, flags=re.DOTALL)
            raw = re.sub(r'> EOF.*', '', raw)
            raw = re.sub(r'>\s*$', '', raw)
            # Extract assistant response from display-prompt format
            # Format: "user\n[prompt]\nassistant\n[response]"
            if "assistant" in raw.lower():
                # Take everything after the LAST "assistant" marker
                parts = re.split(r'assistant\s*', raw, flags=re.IGNORECASE)
                raw = parts[-1].strip()
            raw = raw.strip()
            for prefix in ("Assistant:", "assistant:"):
                if raw.lower().startswith(prefix.lower()):
                    raw = raw[len(prefix):].strip()
            return raw or "(no output)"

        except subprocess.TimeoutExpired:
            return "(timeout)"
        except Exception as e:
            return f"(error: {e})"
        finally:
            if grammar_file and os.path.exists(grammar_file):
                os.unlink(grammar_file)
            if os.path.exists(output_file):
                os.unlink(output_file)
            if os.path.exists(sys_file):
                os.unlink(sys_file)
