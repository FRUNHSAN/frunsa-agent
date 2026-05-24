from gguf import GGUFWriter
import numpy as np
w = GGUFWriter("test.gguf", arch="bert")
w.add_uint32("bert.pooling_type", 2)
w.add_tensor("a", np.array([1.0], dtype=np.float32))
w.write_header_to_file()
w.write_tensors_to_file()
w.close()
print("OK")