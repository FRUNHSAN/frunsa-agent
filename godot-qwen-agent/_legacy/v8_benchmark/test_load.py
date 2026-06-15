import ctypes
import os

dll_path = r"E:\anaconda\envs\qwen-helper\Lib\site-packages\llama_cpp\lib\llama.dll"

if not os.path.exists(dll_path):
    print("❌ llama.dll 不存在！")
else:
    try:
        # 尝试用 WinDLL（Windows 推荐）
        lib = ctypes.WinDLL(dll_path)
        print("✅ 成功加载 llama.dll (WinDLL)")
    except Exception as e:
        try:
            # 如果失败，尝试 CDLL
            lib = ctypes.CDLL(dll_path)
            print("✅ 成功加载 llama.dll (CDLL)")
        except Exception as e:
            print("❌ 加载失败:", str(e))