import ctypes
import os

dll_path = r"E:\anaconda\envs\qwen-helper\Lib\site-packages\llama_cpp\lib\llama.dll"

if not os.path.exists(dll_path):
    print("❌ llama.dll 不存在！")
else:
    try:
        lib = ctypes.CDLL(dll_path)
        print("✅ 成功加载 llama.dll")
    except Exception as e:
        print("❌ 加载失败:", str(e))
