# test_memory.py
import torch
print("可用 RAM:", torch.cuda.mem_get_info() if torch.cuda.is_available() else "N/A")
# 手动估算：2B 模型 ≈ 8GB 内存需求