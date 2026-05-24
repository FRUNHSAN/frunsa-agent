"""Unified component registry with static pipeline-step compatibility validation."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Dict, Generic, List, Set, Tuple, Type, TypeVar

from .chunking import SemVer

T = TypeVar("T")


class ComponentRegistry(Generic[T]):
    """Unified registry: {component_type: {strategy_name: cls}}.

    Chunker, Retriever, Scorer, Tool — all component types share the same
    registration and lookup mechanism. The differentiation is in the domain
    Protocol, not in the registry.
    """

    def __init__(self) -> None:
        self._registry: Dict[str, Dict[str, Type[T]]] = {}

    def register(self, component_type: str, name: str, cls: Type[T]) -> None:
        if not hasattr(cls, "VERSION") or not isinstance(cls.VERSION, SemVer):
            raise ValueError(
                f"{cls.__name__}: VERSION must be a SemVer instance"
            )
        self._registry.setdefault(component_type, {})[name] = cls

    def get(self, component_type: str, name: str) -> Type[T]:
        if component_type not in self._registry:
            raise KeyError(
                f"Unknown component_type: '{component_type}'. "
                f"Available: {list(self._registry.keys())}"
            )
        if name not in self._registry[component_type]:
            raise KeyError(
                f"Unknown strategy '{name}' for '{component_type}'. "
                f"Available: {list(self._registry[component_type].keys())}"
            )
        return self._registry[component_type][name]

    def list_types(self) -> List[str]:
        return list(self._registry.keys())

    def list_strategies(self, component_type: str) -> List[str]:
        return list(self._registry.get(component_type, {}).keys())


# Global singleton
COMPONENT_REGISTRY: ComponentRegistry = ComponentRegistry()


def register_component(component_type: str, name: str):
    """Decorator: @register_component("chunker", "identity")"""

    def decorator(cls: Type) -> Type:
        cls._is_registered_component = True  # type: ignore[attr-defined]
        COMPONENT_REGISTRY.register(component_type, name, cls)
        return cls

    return decorator


def auto_discover(module_path: str, *, strict: bool = False) -> List[Type]:
    """Scan a directory for @register_component-decorated classes.

    Non-strict mode: missing directory silently returns [] (graceful degradation).
    """
    components: List[Type] = []
    path = Path(module_path)
    if not path.exists():
        if strict:
            raise FileNotFoundError(f"Component path not found: {module_path}")
        return components

    for file in path.rglob("*.py"):
        if file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(file.stem, file)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if getattr(attr, "_is_registered_component", False):
                        components.append(attr)
        except Exception:
            if strict:
                raise
    return components


def validate_pipeline_steps(steps: List[dict]) -> Tuple[List[str], List[str]]:
    """Static compatibility check for a sequence of chunking steps (pure function).

    Returns (errors, warnings).  Empty errors == hard constraints satisfied.
    Warnings are advisory (e.g. major version skew).

    Checks:
      1. Every strategy name exists in COMPONENT_REGISTRY (hard)
      2. requires_metadata ⊆ previous provides_metadata (hard)
      3. Major version mismatch → warning (soft)
    """
    errors: List[str] = []
    warnings: List[str] = []
    last_provides: Set[str] | None = None
    last_version: SemVer | None = None
    last_name: str | None = None

    for step in steps:
        name = step.get("name", "?")
        strategy_name = step.get("strategy", "")

        try:
            cls = COMPONENT_REGISTRY.get("chunker", strategy_name)
        except KeyError:
            errors.append(
                f"Step '{name}': unknown chunking strategy '{strategy_name}'"
            )
            continue

        requires: Set[str] = getattr(cls, "requires_metadata", set())
        provides: Set[str] = getattr(cls, "provides_metadata", set())
        version: SemVer = cls.VERSION

        if last_provides is not None:
            missing = requires - last_provides
            if missing:
                errors.append(
                    f"Static compatibility error: Step '{name}' ({strategy_name}) "
                    f"requires metadata {missing}, but previous step '{last_name}' "
                    f"only provides {last_provides}."
                )

        if last_version is not None and version.major != last_version.major:
            warnings.append(
                f"Version note: Step '{name}' ({strategy_name}) is v{version}, "
                f"previous step '{last_name}' is v{last_version}. "
                f"Metadata compatibility is the binding constraint; this is advisory only."
            )

        last_provides = provides
        last_version = version
        last_name = name

    return errors, warnings
