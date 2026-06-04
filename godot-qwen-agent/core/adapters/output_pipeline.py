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
VERBOSE_SENTENCE_LIMITS = {"HIGH": 999, "MEDIUM": 999, "LOW": 3, "MINIMAL": 2}

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

    def process(self, raw: str) -> tuple[str, float]:
        """Process raw LLM output through contract-enforced pipeline.

        Returns (cleaned_text, trust_penalty).
        trust_penalty is 0.0 if no violation detected.
        """
        verbose = self._bp.enforce("response_verbose_level") or "HIGH"
        tone = self._bp.enforce("tone_style") or "WARM"
        max_sent = VERBOSE_SENTENCE_LIMITS.get(verbose, 999)

        result = raw

        # ── 1. Format sanitization (always on) ──
        result = self._strip_markdown(result)

        # ── 2. Sentence truncation ──
        if max_sent < 999:
            result = self._truncate_sentences(result, max_sent)

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
        """Cut text after N sentence-ending punctuations."""
        count = 0
        result: list[str] = []
        for ch in text:
            result.append(ch)
            if ch in "。！？.!?":
                count += 1
                if count >= max_sentences:
                    # Include this sentence terminator, then stop
                    # Don't add ellipsis — clean cut
                    return "".join(result).rstrip()
        return "".join(result)

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
        """Return trust penalty if sycophancy detected."""
        for pattern in SYCOPHANCY_PATTERNS:
            if text.strip().startswith(pattern):
                return 0.03
        return 0.0
