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
from core.trace_node import TraceNode


class XRayBus:
    """Event bus for pipeline observability. Decouples emitters from display.

    Two channels:
      emit(stage, detail)  → X-Ray table (lightweight, per-event)
      trace(trace_node)    → Execution trace tree (structured, for export)
    """

    def __init__(self) -> None:
        self._observers: list[XRay] = []
        self._trace_nodes: list[TraceNode] = []

    def subscribe(self, xray: XRay) -> None:
        """Attach an X-Ray observer."""
        self._observers.append(xray)

    def unsubscribe(self, xray: XRay) -> None:
        """Remove an observer."""
        if xray in self._observers:
            self._observers.remove(xray)

    def emit(self, stage: str, detail: str) -> None:
        """Emit a completed pipeline event (no timer)."""
        for xray in self._observers:
            xray.log(stage, detail)

    def emit_pending(self, stage: str, detail: str) -> None:
        """Emit a pending pipeline event (timer starts). Call emit() to complete."""
        for xray in self._observers:
            xray.log_pending(stage, detail)

    def trace(self, node: TraceNode) -> None:
        """Record a structured trace node (execution tree)."""
        self._trace_nodes.append(node)

    def export_trace(self) -> list[dict]:
        """Export all trace nodes as a serializable list of dicts."""
        return [n.to_dict() for n in self._trace_nodes]

    def clear_trace(self) -> None:
        """Reset trace for new round."""
        self._trace_nodes.clear()

    @property
    def trace_count(self) -> int:
        return len(self._trace_nodes)

    @property
    def has_observers(self) -> bool:
        return len(self._observers) > 0
