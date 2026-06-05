"""X-Ray Dashboard — V3 架构透视镜. Zero core changes. Pure presentation."""

from __future__ import annotations

import time
from typing import Any

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class XRay:
    """旁路观察者 — records pipeline events, renders rich dashboard.

    Usage (in main.py or repl.py):
        xray = XRay()
        xray.log("语义感知", "fatigue=0.72", 0.05)
        ...
        xray.render()  # Print the dashboard
    """

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._t0 = time.time()

    def log(self, stage: str, detail: str, elapsed: float = 0.0) -> None:
        self._events.append({
            "stage": stage, "detail": detail,
            "elapsed": elapsed or (time.time() - self._t0),
        })

    def render(self) -> str | None:
        """Render the X-Ray dashboard once (static mode)."""
        if not HAS_RICH or not self._events:
            return None
        console = Console(width=80)
        console.print(self._build_table())

    def render_live(self, live) -> None:
        """Update a Rich Live display with current events (dynamic mode)."""
        if not HAS_RICH:
            return
        live.update(self._build_table())

    def _build_table(self):
        """Build Rich Table from events."""
        table = Table(title="V3 Runtime X-Ray", show_header=False,
                      border_style="cyan", title_style="bold cyan")
        table.add_column("time", style="dim", width=8)
        table.add_column("stage", style="bold", width=16)
        table.add_column("detail", style="green")

        icons = {
            "上下文组装": "⚙️", "语义感知": "🛡️", "路由决策": "🔀",
            "用户指令": "👤", "契约演化": "📜", "内容生成": "🤖",
            "输出管道": "📝", "模式记录": "💾", "在线学习": "🧠",
            "叙事注入": "📖",
        }
        for ev in self._events:
            icon = icons.get(ev["stage"], "•")
            ts = f"[dim]{ev['elapsed']:.2f}s[/dim]"
            stage = f"[bold]{icon} {ev['stage']}[/bold]"
            detail = ev["detail"][:100]
            table.add_row(ts, stage, detail)
        return table

    @staticmethod
    def quick_log(stage: str, detail: str) -> None:
        """Print a single-line X-Ray entry without accumulating events."""
        if not HAS_RICH:
            return
        console = Console(width=80)
        icons = {
            "上下文组装": "⚙️", "语义感知": "🛡️", "路由决策": "🔀",
            "用户指令": "👤", "契约演化": "📜", "内容生成": "🤖",
            "输出管道": "📝", "模式记录": "💾", "在线学习": "🧠",
        }
        icon = icons.get(stage, "•")
        console.print(f"  [dim][{icon} {stage}][/dim] {detail}")
