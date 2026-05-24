# backend/app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import requests
from dotenv import load_dotenv

# 🧠 加载 RAG 检索函数（来自你的 build_rag_index.py）
from build_rag_index import retrieve_relevant_chunks

# 加载 .env 文件
load_dotenv()

app = FastAPI(title="Qwen Helper Backend", version="1.0")

# 验证 API Key
API_KEY = os.getenv("QWEN_API_KEY")
if not API_KEY:
    raise RuntimeError("❌ 未设置 QWEN_API_KEY，请检查 backend/.env 文件")

DASHSCOPE_API_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"

class AskRequest(BaseModel):
    prompt: str  # Godot 发送 {"prompt": "你的问题"}

@app.post("/ask")
async def ask_ai(request: AskRequest):
    user_prompt = request.prompt.strip()
    print(f"📥 收到问题: {user_prompt}")
    
    if not user_prompt:
        raise HTTPException(status_code=400, detail="问题不能为空")
    
    try:
        # 🧠 步骤 1：用 RAG 检索最相关知识（MVP 只取 top_k=1）
        relevant_chunks = retrieve_relevant_chunks(user_prompt, top_k=1)
        
        if relevant_chunks:
            # ✅ 有匹配：构造增强提示
            context = relevant_chunks[0]  # 只取第一条
            enhanced_prompt = (
                f"【参考知识】\n{context}\n\n"
                f"【用户问题】\n{user_prompt}\n\n"
                "请基于【参考知识】用中文简洁回答。如果知识不相关，请忽略它并直接回答。"
            )
            print("✅ RAG 命中！已注入上下文")
        else:
            # 🔁 无匹配：普通问答
            enhanced_prompt = f"你是一个 Godot 游戏开发专家。请用中文简洁回答以下问题：{user_prompt}"
            print("🔁 无 RAG 匹配，使用通用问答")

        # 🤖 步骤 2：调用 Qwen API
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "qwen-turbo",
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": enhanced_prompt
                    }
                ]
            },
            "parameters": {
                "temperature": 0.7,
                "top_p": 0.8
            }
        }
        
        response = requests.post(
            DASHSCOPE_API_URL,
            headers=headers,
            json=data,
            timeout=30
        )
        response.raise_for_status()
        
        result = response.json()
        answer = result["output"]["text"]
        
        return {"answer": answer}
    
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="AI 服务响应超时，请重试")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"网络错误: {str(e)}")
    except KeyError:
        raise HTTPException(status_code=500, detail="AI 返回格式异常")
    except Exception as e:
        print(f"🚨 后端内部错误: {e}")
        raise HTTPException(status_code=500, detail="AI 服务内部错误")


# 健康检查接口
@app.get("/health")
async def health_check():
    return {
        "status": "OK",
        "message": "Qwen Helper Backend is running!",
        "model": "qwen-turbo",
        "rag_enabled": True  # ✅ 明确告知 RAG 已启用
    }


# 启动服务
if __name__ == "__main__":
    import uvicorn
    print("🚀 启动 Qwen Helper 后端...")
    print("🔗 访问 http://localhost:8000/docs 查看 API 文档")
    print("💡 确保 Godot 插件发送 POST 到 http://localhost:8000/ask")
    print("🧠 RAG 知识库已加载，支持精准问答！")
    uvicorn.run(app, host="127.0.0.1", port=8000)