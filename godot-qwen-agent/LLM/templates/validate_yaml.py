import yaml

with open("LLM/templates/qwen3.yaml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)
    print("✅ YAML 有效!")
    print("Keys:", list(data.keys()))
    print("Stop tokens:", data.get("stop_tokens"))