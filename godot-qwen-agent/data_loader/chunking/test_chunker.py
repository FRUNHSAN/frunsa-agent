from data_loader.data_model import Document
from data_loader.chunking.multi_granularity import MultiGranularityChunker

doc = Document(
    title="Test Doc",
    content="This is a test document with multiple sentences. It should be split into chunks of different sizes.",
    source="test.txt"
)

chunker = MultiGranularityChunker(
    chunk_sizes=[256, 512],
    overlaps=[0, 50],
    enable_dedup=True
)

chunks = chunker.chunk(doc)
print(f"生成 {len(chunks)} 个 chunks")
for i, ch in enumerate(chunks[:3]):
    print(f"{i+1}. {ch.text[:100]}... | size: {len(ch.text)}")