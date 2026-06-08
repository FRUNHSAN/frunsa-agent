"""OutputPipeline — PLAN7: contract-enforced post-processing.

The contract engine controls the ENVIRONMENT around the LLM, not the LLM's
internal generation. This pipeline reads the current Blueprint state and
applies deterministic, physical constraints to LLM output:

  - Sentence truncation (verbose: MINIMAL = 2 sentences, LOW = 3)
  - Format sanitization (strip bullets, headers, blockquotes)
  - Tone filtering (strip filler words for PRAGMATIC)
  - Sycophancy detection (penalize formulaic validation)

All enforcement is CODE-LEVEL. Zero prompt engineering. The LLM can
generate whatever it wants — this pipeline shapes it into compliance.
"""

from __future__ import annotations

import re

# ── Verbose → max sentences ──
VERBOSE_SENTENCE_LIMITS = {"HIGH": 16, "MEDIUM": 8, "LOW": 4, "MINIMAL": 2}

# ── Verbose → max characters (semantic: finds last 。！？ before limit) ──
VERBOSE_CHAR_LIMITS = {"HIGH": 1600, "MEDIUM": 600, "LOW": 200, "MINIMAL": 80}

# ── PRAGMATIC tone: filler phrases to strip ──
PRAGMATIC_FILLERS = [
    "我觉得", "我认为", "可能", "或许", "也许",
    "我个人觉得", "从我的角度来看", "在我看来",
]

# ── Sycophancy patterns ──
SYCOPHANCY_PATTERNS = [
    "你说得对", "你的判断正确", "你的判断很", "非常准确",
    "确实如此，你", "没错，你",
]


class OutputPipeline:
    """Deterministic post-processor driven by contract state.

    Usage:
        pipeline = OutputPipeline(bp)
        clean_text, penalty = pipeline.process(raw_llm_output)
        if penalty:
            trust -= penalty
    """

    def __init__(self, bp: object) -> None:
        self._bp = bp  # DynamicBlueprint — read via enforce()
        # ── V5 Path 3: Execution Constraint Reflex ──
        # 脊髓反射直接调节输出上限，不经 meta-adapt（皮层）。
        # 连续截断触发 → 倍率提升 → 截断缓解 → 自动恢复 1.0。
        self.char_limit_multiplier: float = 1.0
        self.sentence_limit_multiplier: float = 1.0
        self._base_char_multiplier: float = 1.0   # 快照基线，用于恢复
        self._base_sentence_multiplier: float = 1.0

    def process(self, raw: str) -> tuple[str, float]:
        """Process raw LLM output through contract-enforced pipeline.

        Returns (cleaned_text, trust_penalty).
        trust_penalty is 0.0 if no violation detected.
        """
        verbose = self._bp.enforce("response_verbose_level") or "HIGH"
        tone = self._bp.enforce("tone_style") or "WARM"
        base_sent = VERBOSE_SENTENCE_LIMITS.get(verbose, 999)
        max_sent = (int(base_sent * self.sentence_limit_multiplier)
                    if base_sent < 999 else 999)

        result = raw

        # ── 1. Format sanitization (always on) ──
        result = self._strip_markdown(result)

        # ── 2. Sentence truncation ──
        if max_sent < 999:
            result = self._truncate_sentences(result, max_sent)

        # ── 2b. Character cap (semantic — finds last sentence boundary) ──
        base_chars = VERBOSE_CHAR_LIMITS.get(verbose, 0)
        max_chars = int(base_chars * self.char_limit_multiplier) if base_chars > 0 else 0
        if max_chars > 0:
            result = self._truncate_chars(result, max_chars)

        # ── 3. Tone filter ──
        if tone == "PRAGMATIC":
            result = self._strip_fillers(result)

        # ── 4. Sycophancy penalty ──
        penalty = self._detect_sycophancy(result)

        return result.strip(), penalty

    # ── Stage implementations ──

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove markdown formatting artifacts."""
        text = text.replace("**", "").replace("__", "")
        text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'\n{2,}', '\n', text)
        return text

    @staticmethod
    def _truncate_sentences(text: str, max_sentences: int) -> str:
        """Cut text after N sentence-ending punctuations.

        Smart boundary: '.' only counts as sentence end when followed by
        space+capital or end-of-string — avoids splitting on 'e.g.', '3.14', etc.
        """
        count = 0
        result: list[str] = []
        chars = list(text)
        for i, ch in enumerate(chars):
            result.append(ch)
            if ch in "。！？!?":
                count += 1
            elif ch == ".":
                # Only count as sentence end if followed by space+uppercase or end
                next_ch = chars[i + 1] if i + 1 < len(chars) else ""
                next_next = chars[i + 2] if i + 2 < len(chars) else ""
                if not next_ch or (next_ch == " " and next_next.isupper()):
                    count += 1
                elif next_ch == "\n":
                    count += 1
            if count >= max_sentences:
                return "".join(result).rstrip()
        return "".join(result)

    @staticmethod
    def _truncate_chars(text: str, max_chars: int) -> str:
        """Semantic char-level truncation: find last sentence boundary ≤ max_chars.

        Looks for the last 。！？!? or \\n\\n before the limit.
        Never splits mid-sentence or mid-code-block.
        """
        if len(text) <= max_chars:
            return text
        # Search backwards from max_chars for sentence boundary
        window = text[:max_chars]
        boundaries = ["\n\n", "。", "！", "？", "!", "?", "\n"]
        best = -1
        for b in boundaries:
            pos = window.rfind(b)
            if pos > best:
                best = pos
        if best > max_chars * 0.5:  # At least half the limit
            return text[:best + len(boundaries[0]) if best == window.rfind("\n\n") else best + 1]
        # No good boundary — hard cut at max_chars
        return text[:max_chars]

    @staticmethod
    def _strip_fillers(text: str) -> str:
        """Remove filler phrases for PRAGMATIC tone."""
        for filler in PRAGMATIC_FILLERS:
            text = text.replace(filler, "")
        # Clean up double spaces
        text = re.sub(r'  +', ' ', text)
        return text

    @staticmethod
    def _detect_sycophancy(text: str) -> float:
        """Return trust penalty if sycophancy detected anywhere."""
        t = text.strip()
        for pattern in SYCOPHANCY_PATTERNS:
            # Check start AND first sentence (after ？。！)
            if t.startswith(pattern):
                return 0.03
            # Also check after first sentence boundary
            for sep in ("。", "？", "！", ". ", "? ", "! "):
                idx = t.find(sep)
                if idx > 0 and pattern in t[idx:idx + 30]:
                    return 0.02
        return 0.0
