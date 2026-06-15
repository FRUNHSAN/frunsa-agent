# backend/test_api_key.py
import os
import requests
from dotenv import load_dotenv

def test_qwen_api_key():
    print("🔍 正在检测 Qwen API Key 是否有效...\n")
    
    # 1. 加载 .env
    load_dotenv()
    api_key = os.getenv("QWEN_API_KEY")
    
    if not api_key:
        print("❌ 错误：未在 .env 文件中找到 QWEN_API_KEY")
        print("请确保 backend/.env 文件存在，且内容为：")
        print("QWEN_API_KEY=sk-你的实际密钥")
        return False
    
    print(f"🔑 检测的 Key 前缀: {api_key[:8]}...{api_key[-4:]}")

    # 2. 构造测试请求
    url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen-turbo",
        "input": {
            "messages": [{"role": "user", "content": "你好"}]
        },
        "parameters": {"temperature": 0.1}
    }

    try:
        # 3. 发送请求（带超时）
        response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            answer = result.get("output", {}).get("text", "")
            if answer:
                print("✅ 成功！API Key 有效，Qwen 返回了回答：")
                print(f'💬 "{answer.strip()}"')
                print("\n🎉 你可以安全地启动后端服务了！")
                return True
            else:
                print("⚠️ 警告：API 返回成功，但未包含 'text' 字段")
                print("原始响应:", result)
                return False
                
        elif response.status_code == 401:
            print("❌ 失败：API Key 无效或已过期")
            print("请检查 .env 中的 QWEN_API_KEY 是否正确")
            print("提示：Key 格式应为 sk- 开头的 48 位字符串")
            return False
            
        elif response.status_code == 403:
            print("❌ 失败：API Key 无权限访问 qwen-turbo 模型")
            print("请登录 https://dashscope.console.aliyun.com/ 检查模型权限")
            return False
            
        else:
            print(f"❌ 失败：HTTP 状态码 {response.status_code}")
            print("响应内容:", response.text)
            return False

    except requests.exceptions.Timeout:
        print("⏳ 超时：DashScope 服务器响应太慢（>10秒）")
        print("可能原因：网络问题、服务器繁忙")
        return False
        
    except requests.exceptions.ConnectionError:
        print("🌐 连接失败：无法连接到 DashScope 服务器")
        print("请检查网络，或尝试稍后再试")
        return False
        
    except Exception as e:
        print(f"💥 未知错误: {str(e)}")
        return False

if __name__ == "__main__":
    test_qwen_api_key()