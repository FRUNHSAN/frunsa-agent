"""V6.2 Benchmark QA pairs — four-quadrant coverage for Wasserstein calibration.

Quadrants span the V5.3 (drift, clarity) state space to ensure the calibration
baseline is globally representative — not biased toward any single domain.

  Q1 (low d, high c): crystal-clear, stable-topic requests
  Q2 (low d, low c): vague/ambiguous but on-topic
  Q3 (high d, high c): lucid topic switches (intentional redirection)
  Q4 (high d, low c): self-contradictory or impossible demands

Perfect pairs: (user_prompt, expected_good_response)
Bad pairs:     (user_prompt, irrelevant_response)
"""

from __future__ import annotations

# ── Perfect QA pairs (user prompt → expected good response) ──────────

PERFECT_PAIRS: list[tuple[str, str]] = [
    # Q1: low drift, high clarity — straightforward technical requests
    ("用Python写一个快速排序函数", "def quicksort(arr): ..."),        # 代码生成
    ("How do I read a CSV file with pandas?", "df = pd.read_csv(...)"),  # 英文技术
    ("解释一下什么是REST API", "REST API是一种基于HTTP的架构风格..."),  # 概念解释

    # Q2: low drift, low clarity — vague but on-topic
    ("帮我分析一下这个架构", "这个架构可以从以下几个维度分析：1.可扩展性..."),  # 泛泛而谈
    ("优化一下性能", "性能优化可以从数据库索引、缓存策略、代码层面入手..."),    # 模糊优化

    # Q3: high drift, high clarity — lucid topic switches
    ("刚才那个快排别用递归，改用迭代实现", "def quicksort_iterative(arr): ..."),  # 清醒切换
    ("用英文解释刚才那个概念", "A REST API is an architectural style..."),         # 语言切换

    # Q4: high drift, low clarity — contradictory or impossible
    ("用纯C语言写一个能在IE6上运行的WebAssembly前端", "你的需求存在根本性的技术矛盾..."),  # 逻辑矛盾
    ("帮我设计一个不需要数据库但能存储TB级数据的系统", "这涉及物理存储的约束..."),          # 物理约束
]

# ── Bad QA pairs (user prompt → clearly irrelevant response) ─────────

BAD_PAIRS: list[tuple[str, str]] = [
    # Cross-domain mismatches
    ("用Python写一个快速排序函数", "首先准备面粉和鸡蛋..."),                     # 代码→菜谱
    ("How do I read a CSV file with pandas?", "The capital of France is Paris."), # 技术→地理
    ("解释一下什么是REST API", "篮球比赛规则如下：每队5人..."),                  # 技术→体育
    ("帮我分析一下这个架构", "今天天气晴朗，适合出去散步..."),                   # 技术→天气
    ("刚才那个快排别用递归", "心脏病急救的第一步是拨打120..."),                  # 代码→医疗
    ("用英文解释刚才那个概念", "西红柿炒鸡蛋的做法是..."),                       # 语言→菜谱
    ("用纯C语言写一个能在IE6上运行的WebAssembly前端", "没问题，以下是完整代码：<html>..."), # 矛盾→假装可行
    ("帮我设计一个不需要数据库但能存储TB级数据的系统", "你可以用Excel来存储数据..."),     # 严肃→幼稚
]

# ── Text-only accessors (embeddings computed at runtime) ──────────────

def get_perfect_text_pairs() -> list[tuple[str, str]]:
    """Return (user_prompt, good_response) text pairs for calibration."""
    return list(PERFECT_PAIRS)


def get_bad_text_pairs() -> list[tuple[str, str]]:
    """Return (user_prompt, bad_response) text pairs for calibration."""
    return list(BAD_PAIRS)
