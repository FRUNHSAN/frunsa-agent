# test_llm_install.py
try:
    import dashscope; print("✅ Qwen (dashscope) OK")
except: print("❌ Qwen not installed")

try:
    import openai; print("✅ OpenAI OK")
except: print("❌ OpenAI not installed")

try:
    import anthropic; print("✅ Claude (anthropic) OK")
except: print("❌ Claude not installed")

try:
    import ollama; print("✅ Ollama OK")
except: print("❌ Ollama not installed")

try:
    import yaml, pandas; print("✅ Core deps OK")
except: print("❌ Core deps missing")