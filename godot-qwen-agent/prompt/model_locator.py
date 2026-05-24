# prompt/model_locator.py
import os
import json
from pathlib import Path

def find_local_embedder(model_name: str, cache_registry_path="/benchmark/cache_registry.json"):
    """
    根据 model_name（如 'BAAI/bge-m3'）在本地缓存目录中查找模型路径。
    要求：
      - cache_registry.json 列出所有缓存根目录
      - 每个目录下有 mod_id.txt 写明模型名
    返回：模型路径（str）或 None
    """
    # 处理 Windows 路径
    cache_registry_path = cache_registry_path.replace("/", "\\")
    if not os.path.exists(cache_registry_path):
        raise FileNotFoundError(f"cache_registry.json not found at {cache_registry_path}")

    with open(cache_registry_path, "r", encoding="utf-8") as f:
        cache_dirs = json.load(f)

    for base_dir in cache_dirs:
        base_path = Path(base_dir)
        if not base_path.exists():
            continue
        for candidate in base_path.iterdir():
            if candidate.is_dir():
                mod_id_file = candidate / "mod_id.txt"
                if mod_id_file.exists():
                    with open(mod_id_file, "r", encoding="utf-8") as f2:
                        name_in_file = f2.read().strip()
                    if name_in_file == model_name:
                        print(f"✅ Found local embedder: {model_name} at {candidate}")
                        return str(candidate)
    print(f"❌ Local embedder not found for: {model_name}")
    return None