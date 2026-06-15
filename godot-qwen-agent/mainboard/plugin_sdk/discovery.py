"""
V9 Plugin SDK: 自动发现引擎 (Discovery)
=======================================
职责: 扫描三层 slots/ 目录，读取 manifest.json，创建 LazyPluginLoader，
      安全地移交给 PluginRegistry。

核心原则:
  1. 发现阶段绝不执行插件代码 — 只读 manifest.json + 创建延迟加载器
  2. 隔离舱 — 单个插件加载失败不阻断启动
  3. 约定大于配置 — manifest.json 是唯一真相源
"""

from __future__ import annotations

import importlib
import json
import logging
from pathlib import Path
from typing import Any

from .protocol import PluginManifest
from .registry import PluginRegistry

logger = logging.getLogger(__name__)

# 三层扫描路径 (相对于项目根目录)
DEFAULT_LAYER_PATHS = [
    "mainboard/slots",
    "mpc_kernel/slots",
    "observer/slots",
]


class DiscoveryError(RuntimeError):
    """发现过程中的致命错误 (如 registry 已冻结)。"""
    pass


# ═══════════════════════════════════════════════════════════════
# LazyPluginLoader — 延迟导入，消除发现阶段的副作用
# ═══════════════════════════════════════════════════════════════


class LazyPluginLoader:
    """持有模块路径和类名，在第一次 registry.get() 时才 import。

    设计目的 (红队审查 #1):
      Python importlib 会立即执行目标文件的全部顶层代码。
      如果插件文件中有顶层 I/O、网络连接、或对未初始化总线的引用，
      将在发现阶段触发不可控副作用。
      LazyPluginLoader 把真正的 import 推迟到 registry.get() 调用时。

    Attributes:
        _module_path:   Python 模块路径 (如 "mainboard.slots.prompts.planning_prompt")
        _class_name:    要实例化的类名
        _slot_type:     槽类型
        _name:          插件名
        _loaded:        缓存 — 已加载的实例
        _load_error:    加载失败信息 (None = 成功或尚未尝试)
    """

    def __init__(
        self,
        module_path: str,
        class_name: str,
        slot_type: str,
        name: str,
    ) -> None:
        self._module_path = module_path
        self._class_name = class_name
        self._slot_type = slot_type
        self._name = name
        self._loaded: Any = None
        self._load_error: str | None = None

    def load(self) -> Any | None:
        """惰性加载。失败时记录警告并返回 None，绝不抛异常。"""
        if self._loaded is not None:
            return self._loaded
        if self._load_error is not None:
            return None

        try:
            module = importlib.import_module(self._module_path)
            cls = getattr(module, self._class_name)
            self._loaded = cls()  # 无状态插件 — 默认构造
            logger.info(
                f"LazyLoad OK: {self._slot_type}/{self._name} "
                f"({self._module_path}.{self._class_name})"
            )
            return self._loaded
        except ImportError as e:
            self._load_error = f"ImportError: {e}"
            logger.warning(
                f"LazyLoad FAIL: {self._slot_type}/{self._name} — {self._load_error}"
            )
            return None
        except Exception as e:
            self._load_error = f"{type(e).__name__}: {e}"
            logger.exception(
                f"LazyLoad CRASH: {self._slot_type}/{self._name}"
            )
            return None

    @property
    def is_loaded(self) -> bool:
        return self._loaded is not None

    @property
    def error(self) -> str | None:
        return self._load_error

    def __repr__(self) -> str:
        status = "loaded" if self._loaded else ("failed" if self._load_error else "pending")
        return f"LazyPluginLoader({self._slot_type}/{self._name}, {status})"


# ═══════════════════════════════════════════════════════════════
# 发现引擎
# ═══════════════════════════════════════════════════════════════


def discover_and_register(
    registry: PluginRegistry,
    base_dir: Path,
    layer_paths: list[str] | None = None,
) -> dict[str, list[str]]:
    """扫描三层 slots/ 目录，读取 manifest.json，注册 LazyPluginLoader。

    发现阶段绝不执行任何插件的 Python 代码。
    真正的 import 推迟到 registry.get() 第一次调用时。

    Args:
        registry:    PluginRegistry 实例
        base_dir:    项目根目录 Path
        layer_paths: 扫描路径列表 (默认 L2/L3/L4)

    Returns:
        {"success": ["tool:write_file", ...], "failed": ["prompt:bad: reason", ...]}
    """
    layer_paths = layer_paths or DEFAULT_LAYER_PATHS
    results: dict[str, list[str]] = {"success": [], "failed": []}

    if registry.is_frozen:
        raise DiscoveryError(
            "Cannot discover plugins: Registry is already frozen."
        )

    for rel_path in layer_paths:
        slot_dir = base_dir / rel_path
        if not slot_dir.exists() or not slot_dir.is_dir():
            logger.warning(f"扫描路径不存在，跳过: {slot_dir}")
            continue

        manifest_file = slot_dir / "manifest.json"
        if not manifest_file.exists():
            logger.debug(f"无 manifest.json，跳过: {slot_dir}")
            continue

        # 隔离舱: 单个 manifest 解析失败不阻断其他层
        try:
            layer_results = _discover_from_manifest(
                registry, slot_dir, manifest_file
            )
            results["success"].extend(layer_results["success"])
            results["failed"].extend(layer_results["failed"])
        except Exception as e:
            logger.error(f"层扫描失败 {slot_dir}: {type(e).__name__}: {e}")
            results["failed"].append(f"{rel_path}: {e}")

    return results


def _discover_from_manifest(
    registry: PluginRegistry,
    slot_dir: Path,
    manifest_file: Path,
) -> dict[str, list[str]]:
    """从单个 manifest.json 读取插件清单，创建 LazyPluginLoader。

    不做 import_module — 只读 JSON + 创建 loader 对象。
    """
    results: dict[str, list[str]] = {"success": [], "failed": []}

    with open(manifest_file, "r", encoding="utf-8") as f:
        raw = json.load(f)

    plugins = raw.get("plugins", {})
    if not plugins:
        logger.debug(f"manifest.json 无插件条目: {manifest_file}")
        return results

    for slot_type, entries in plugins.items():
        if not isinstance(entries, dict):
            continue

        for name, spec in entries.items():
            if not isinstance(spec, dict):
                continue

            # 跳过 PluginRegistry 不管理的 slot 类型 (如 "policy" — L2 自管)
            if slot_type not in ["tool", "prompt", "track", "observer", "event"]:
                logger.debug(
                    f"跳过非 PluginRegistry 管理的 slot 类型: "
                    f"{slot_type}/{name} (由所在层自行管理)"
                )
                continue

            module_path = spec.get("module", "")
            class_name = spec.get("class", "")

            if not module_path or not class_name:
                results["failed"].append(
                    f"{slot_type}:{name}: 缺少 module 或 class"
                )
                continue

            # 隔离舱: 单个 loader 创建失败不阻断其他
            try:
                loader = LazyPluginLoader(
                    module_path=module_path,
                    class_name=class_name,
                    slot_type=slot_type,
                    name=name,
                )
                registry.register_lazy(slot_type, name, loader)
                results["success"].append(f"{slot_type}:{name}")
                logger.debug(
                    f"发现插件: {slot_type}/{name} "
                    f"({module_path}.{class_name})"
                )
            except Exception as e:
                error_msg = f"{slot_type}:{name}: {type(e).__name__}: {e}"
                logger.warning(f"注册失败: {error_msg}")
                results["failed"].append(error_msg)

    return results


# ═══════════════════════════════════════════════════════════════
# 便利函数
# ═══════════════════════════════════════════════════════════════


def resolve_all_lazy(registry: PluginRegistry) -> dict[str, list[str]]:
    """显式解析所有延迟加载器 (在 freeze 前调用)。

    逐个触发 load()，将成功加载的插件实例化并注册。
    失败的记录到 results["failed"]。

    Returns:
        {"success": [...], "failed": [...]}
    """
    results: dict[str, list[str]] = {"success": [], "failed": []}

    for stype in registry.list_names("tool"):  # 不准确，需要遍历所有类型
        pass  # 实际通过 registry._lazy_loaders 遍历

    # 遍历所有 slot type 的延迟加载器
    for stype in ["tool", "prompt", "track", "observer", "event"]:
        for name in registry.list_names(stype):
            instance = registry.get(stype, name)
            if instance is not None:
                results["success"].append(f"{stype}:{name}")
            else:
                results["failed"].append(f"{stype}:{name}: 加载失败")

    return results
