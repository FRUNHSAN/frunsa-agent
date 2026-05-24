# data_loader/test_import.py
try:
    from .chunking.multi_granularity import MultiGranularityChunker
    print("✅ 成功导入 MultiGranularityChunker")
except Exception as e:
    print(f"❌ 导入失败: {e}")