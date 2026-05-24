import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader.chunking.multi_granularity import MultiGranularityChunker

text = "This is a sample text for testing multi-granularity chunking. " * 20

chunker = MultiGranularityChunker(
    chunk_sizes=[100, 200],
    overlaps=[10, 20],
    enable_dedup=True
)

chunks = chunker.split_text(text)
print(f"✅ 生成 {len(chunks)} 个 chunks")
for i, c in enumerate(chunks[:3]):
    print(f"{i+1}. '{c[:50]}...' (len={len(c)})")