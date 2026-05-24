"""Resource lifecycle container — replaces raw Dict[str, Any] for global resources.

Clear separation:
  - scoped(): pure with-block semantics, released on exit. Not registered globally.
  - register_managed(): long-lived resources, released by close() on pipeline shutdown.
  - set_config() / set_state(): configuration (immutable) vs mutable state (thread-safe).

No resource ever has two release paths — scoped and managed are disjoint.
"""

from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Any, Dict


class ResourceContainer:
    def __init__(self) -> None:
        self._config: Dict[str, Any] = {}
        self._state: Dict[str, Any] = {}
        self._lock = Lock()
        self._managed: Dict[str, Any] = {}
        self._closed = False

    # ── Configuration (init-time, immutable thereafter) ──────────

    def set_config(self, key: str, value: Any) -> None:
        if self._closed:
            raise RuntimeError("ResourceContainer is closed")
        self._config[key] = value

    # ── Mutable state (thread-safe) ──────────────────────────────

    def set_state(self, key: str, value: Any) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("ResourceContainer is closed")
            self._state[key] = value

    # ── Read-only access (config takes priority over state) ──────

    def get(self, key: str) -> Any:
        if key in self._config:
            return self._config[key]
        return self._state.get(key)

    # ── Long-lived managed resources ─────────────────────────────

    def register_managed(self, key: str, resource: Any) -> None:
        """Register a resource that lives until close() is called."""
        self._managed[key] = resource

    # ── Scoped resources (with-block, released immediately) ──────

    @contextmanager
    def scoped(self, factory, **kwargs):
        """Pure with-block: resource is created, yielded, and released immediately.

        Not registered globally — close() will never touch this resource.
        """
        resource = factory(**kwargs)
        try:
            yield resource
        finally:
            _safe_close(resource)

    # ── Lifecycle ────────────────────────────────────────────────

    def close(self) -> None:
        """Release all managed resources. Does NOT touch scoped resources."""
        self._closed = True
        for resource in self._managed.values():
            _safe_close(resource)
        self._managed.clear()

    def __enter__(self) -> ResourceContainer:
        return self

    def __exit__(self, *args: Any) -> bool:
        self.close()
        return False

    async def __aenter__(self) -> ResourceContainer:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        self.close()
        return False


def _safe_close(resource: Any) -> None:
    """Close a resource safely: prefer close(), fall back to __exit__(). Only one path."""
    closer = getattr(resource, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass
        return

    exiter = getattr(resource, "__exit__", None)
    if callable(exiter):
        try:
            exiter(None, None, None)
        except Exception:
            pass
