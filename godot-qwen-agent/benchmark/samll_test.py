# test_copy.py
from gguf import GGUFWriter
import numpy as np

w = GGUFWriter("test.gguf", arch="bert")
w.add_uint32("bert.pooling_type", 2)

# 模拟从 reader 读取的 memmap 数据
original = np.array([1.0, 2.0], dtype=np.float32)
data = np.array(original, copy=True)  # ⭐

w.add_tensor("dummy.weight", data)
w.write_header_to_file()
w.write_tensors_to_file()
w.close()
print("OK")