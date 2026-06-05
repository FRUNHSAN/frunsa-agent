"""XRayBus — shared event bus for pipeline observability.

Components emit events. X-Ray subscribes and renders.
REPL doesn't know which components emit what — it just runs the bus.

Usage:
    bus = XRayBus()
    bus.emit("语义感知", "fatigue=0.72")
    bus.emit("输出管道", "截断: 156→82 字符")

    # In REPL:
    xray = XRay()
    bus.subscribe(xray)  # xray receives all events
    # ... pipeline runs, events flow ...
    xray.render()  # All events rendered
"""

from __future__ import annotations

from core.xray import XRay


class XRayBus:
    """Event bus for pipeline observability. Decouples emitters from display."""

    def __init__(self) -> None:
        self._observers: list[XRay] = []

    def subscribe(self, xray: XRay) -> None:
        """Attach an X-Ray observer. Multiple observers allowed."""
        self._observers.append(xray)

    def unsubscribe(self, xray: XRay) -> None:
        """Remove an observer."""
        if xray in self._observers:
            self._observers.remove(xray)

    def emit(self, stage: str, detail: str) -> None:
        """Emit a pipeline event to all observers."""
        for xray in self._observers:
            xray.log(stage, detail)

    @property
    def has_observers(self) -> bool:
        return len(self._observers) > 0
