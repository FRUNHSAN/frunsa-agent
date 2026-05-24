# test_registry.py
import json
from pathlib import Path

cache_file = Path("H:/agent项目/godot-qwen-agent/benchmark/cache_registry.json")
with open(cache_file, 'r', encoding='utf-8') as f:
    data = json.load(f)
print("Raw paths:", data)
print("Resolved path:", Path(data[0]).resolve())