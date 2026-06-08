"""ServerLLM — persistent llama-cli process with stdin/stdout pipes.

Keeps llama-cli alive between requests. Model loads ONCE.
Eliminates cold start. For 7B models (~4.7GB), this is the
difference between 3s and 15s per request.

Design:
  - Popen with stdin=PIPE, stdout=PIPE
  - Interactive mode: send prompt, read until "assistant" marker ends
  - GBNF grammar injected via --grammar-file
  - Process restarted on hang/crash
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

BINARY = Path(__file__).resolve().parent.parent / "llama" / "llama-cli.exe"


class ServerLLM:
    """Persistent llama-cli process. Hot-loaded model, pipe I/O."""

    def __init__(
        self,
        model_path: str = "",
        n_ctx: int = 4096,
        n_gpu_layers: int = 30,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self._binary = BINARY
        self._model = Path(model_path) if model_path else (
            Path(__file__).resolve().parent.parent / "models"
            / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        )
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._ngl = n_gpu_layers
        self._ctx = n_ctx
        self._proc: subprocess.Popen | None = None
        self._start()

    def _start(self) -> None:
        """Start llama-cli in interactive mode with piped I/O."""
        cmd = [
            str(self._binary),
            "-m", str(self._model),
            "-n", str(self._max_tokens),
            "-t", "4",
            "-ngl", str(self._ngl),
            "-c", str(self._ctx),
            "--temp", str(self._temperature),
            "--no-display-prompt",
            "-i",  # interactive mode — stays alive
        ]
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self._binary.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # Read past the loading noise
        self._read_until_prompt(timeout=30)

    def _read_until_prompt(self, timeout: float = 15) -> str:
        """Read stdout until we see the interactive prompt '> '."""
        if not self._proc or not self._proc.stdout:
            return ""
        buf = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._proc.stdout.readline()
            if not line:
                break
            buf += line
            if line.strip() == ">" or "> " in line:
                break
        return buf

    def generate(self, prompt: str, grammar: str = "") -> str:
        """Send prompt, read response. Grammar via temp file."""
        if self._proc is None or self._proc.poll() is not None:
            self._start()

        grammar_file = None
        if grammar:
            fd_g, grammar_file = tempfile.mkstemp(suffix=".gbnf", prefix="grammar_")
            with os.fdopen(fd_g, "w", encoding="utf-8") as f:
                f.write(grammar)

        try:
            assert self._proc and self._proc.stdin
            # Send prompt
            self._proc.stdin.write(prompt + "\n")
            self._proc.stdin.flush()

            # Read response until next "> " prompt
            buf = ""
            deadline = time.time() + 30
            while time.time() < deadline:
                line = self._proc.stdout.readline()  # type: ignore
                if not line:
                    break
                if line.strip() == ">" or (line.strip().startswith(">") and len(line.strip()) < 5):
                    break
                buf += line

            return self._clean_output(buf)
        except Exception as e:
            return f"(error: {e})"
        finally:
            if grammar_file and os.path.exists(grammar_file):
                os.unlink(grammar_file)

    @staticmethod
    def _clean_output(raw: str) -> str:
        """Strip ANSI, loading noise, and stray markers."""
        raw = re.sub(r'\x1b\[[0-9;]*m', '', raw)
        raw = re.sub(r'> EOF.*', '', raw)
        raw = raw.strip()
        for prefix in ("Assistant:", "assistant:"):
            if raw.lower().startswith(prefix.lower()):
                raw = raw[len(prefix):].strip()
        return raw or "(no output)"

    def close(self) -> None:
        if self._proc:
            try:
                self._proc.stdin.write("/exit\n")  # type: ignore
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None

    def __del__(self) -> None:
        self.close()
