# test_qwen.py
from dotenv import load_dotenv
import os
load_dotenv()

from dashscope import Generation

response = Generation.call(
    model="qwen-max",
    messages=[{"role": "user", "content": "你好"}],
    api_key=os.getenv("QWEN_API_KEY")
)

print(response)