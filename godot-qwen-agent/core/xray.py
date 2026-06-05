"""X-Ray Dashboard — V3 架构透视镜. Zero core changes. Pure presentation."""

from __future__ import annotations

import time

try:
    from rich.console import Console
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False


class XRay:
    """Live-updating pipeline dashboard. Each stage = one row that updates.

    Usage:
        xray = XRay()
        xray.log("语义感知", "fatigue=0.72")       # Row appears, timer starts
        xray.log("内容生成", "⏳ 生成中...")         # New row, timer running
        # ... 3 seconds pass, Live auto-refreshes showing elapsed ...
        xray.log("内容生成", "完成 (156 字符)")     # Same row updates, done
    """

    def __init__(self) -> None:
        self._stages: dict[str, dict] = {}  # stage_name → {detail, start, done}
        self._order: list[str] = []         # Insertion order
        self._t0 = time.time()

    def log(self, stage: str, detail: str, elapsed: float = 0.0) -> None:
        """Start or update a pipeline stage. Same stage = same row."""
        key = stage  # Full stage name as key — each track B step gets its own row
        if key in self._stages:
            # Update existing stage
            self._stages[key]["detail"] = detail
            self._stages[key]["done"] = True
        else:
            # New stage — timer starts now
            self._stages[key] = {
                "detail": detail, "start": time.time(), "done": False,
            }
            self._order.append(key)

    def render(self) -> None:
        """Render once (static mode)."""
        if not HAS_RICH:
            return
        Console(width=80).print(self._build_table())

    def render_live(self, live) -> None:
        """Update a Rich Live display."""
        if not HAS_RICH:
            return
        live.update(self._build_table())

    def _build_table(self):
        """Build table with live timers for active stages."""
        table = Table(title="V3 Runtime X-Ray", show_header=False,
                      border_style="cyan", title_style="bold cyan")
        table.add_column("time", style="dim", width=8)
        table.add_column("stage", style="bold", width=16)
        table.add_column("detail", style="green")

        icons = {
            "语义感知": "🛡️", "路由决策": "🔀", "用户指令": "👤",
            "契约演化": "📜", "内容生成": "🤖", "输出管道": "📝",
            "模式记录": "💾", "在线学习": "🧠", "叙事注入": "📖",
            "知识网关": "🔐", "RAG检索": "📚", "Track B Planning": "📋",
            "Track B Orch": "⚙️", "Track B Critic": "🔍",
            "引擎异常": "⚠️",
        }

        now = time.time()
        for key in self._order:
            st = self._stages[key]
            detail = st["detail"][:100]
            if st["done"]:
                ts = f"[dim]{st['start'] - self._t0:.1f}s[/dim]"
            else:
                elapsed = now - st["start"]
                ts = f"[yellow]{elapsed:.1f}s[/yellow]"
                if "⏳" not in detail:
                    detail = f"[yellow]{detail}[/yellow]"

            icon = icons.get(key, "•")
            stage_display = f"[bold]{icon} {key}[/bold]"
            table.add_row(ts, stage_display, detail)

        return table
