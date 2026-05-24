import os
import ctypes

# 强制指定完整路径
dll_path = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\cublas64_12.dll"

if os.path.exists(dll_path):
    try:
        lib = ctypes.CDLL(dll_path)
        print("✅ 成功加载 cublas64_12.dll")
    except Exception as e:
        print("❌ 加载失败:", str(e))
else:
    print("❌ 文件不存在")