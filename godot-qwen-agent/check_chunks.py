# check_chunks.py
import json

with open(r"G:\chunk\chunks_godot_en__level1__a5770051\chunks.json", 'r', encoding='utf-8') as f:
    chunks = json.load(f)

# 查找包含 "jump" 的 chunk
jump_chunks = [c for c in chunks if "jump" in (c if isinstance(c, str) else c.get("text", "")).lower()]
print(f"Found {len(jump_chunks)} chunks with 'jump'")
for i, c in enumerate(jump_chunks[:3]):
    text = c if isinstance(c, str) else c["text"]
    print(f"\n--- Chunk {i+1} ---\n{text[:200]}...")