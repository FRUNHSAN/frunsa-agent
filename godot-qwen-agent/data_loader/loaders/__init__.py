# data_loader/loaders/__init__.py
from .base import BaseLoader
from .local_file import LocalFileLoader
from .html_loader import HTMLLoader  # ← 新增

__all__ = ["BaseLoader", "LocalFileLoader", "HTMLLoader"]
