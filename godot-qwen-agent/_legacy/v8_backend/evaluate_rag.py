from build_rag_index import retrieve_relevant_chunks

# ======================
# 🧪 测试用例（基于你整理的 6 条核心知识）
# ======================
test_cases = [
    {
        "query": "Godot 4.5 中 HTTPRequest 的 body 参数报类型错误怎么办？",
        "keywords": ["不要使用 .utf8", "直接传入 String 类型的 JSON 字符串"]
    },
    {
        "query": "JSON.stringify() 返回 null 导致错误怎么解决？",
        "keywords": ["不可序列化的对象", "返回 null"]
    },
    {
        "query": "FastAPI 返回 422 Unprocessable Entity 错误如何修复？",
        "keywords": ["Content-Type: application/json"]
    },
    {
        "query": "如何正确调用 DashScope 的 Qwen API？",
        "keywords": ["Authorization", "Bearer sk-", "model", "input", "parameters"]
    },
    {
        "query": "Windows 上 conda activate 无效怎么办？",
        "keywords": ["Anaconda Prompt", "conda init"]
    },
    {
        "query": "怎么用 Postman 测试 /ask 接口？",
        "keywords": ["raw + JSON", "Content-Type: application/json", '{"prompt"']
    }
]

# ======================
# 📊 自动评估函数
# ======================
def evaluate_rag():
    print("📊 正在评估 RAG 检索准确率...\n")
    correct = 0
    total = len(test_cases)

    for i, case in enumerate(test_cases, 1):
        query = case["query"]
        keywords = case["keywords"]

        # 执行检索
        results = retrieve_relevant_chunks(query, top_k=2)
        #💡 评估脚本用 top_k=2 是为了“容错测试”，但实际使用建议 top_k=1 ← 只要最相关的 1 条！
        
        print(f"🔍 测试 {i}: {query}")
        print("📄 检索结果:")
        for j, r in enumerate(results, 1):
            preview = r.replace('\n', ' | ')[:120]
            print(f"  {j}. {preview}...")

        # 判断是否命中任意关键词
        hit = False
        for result in results:
            for kw in keywords:
                if kw in result:
                    hit = True
                    break
            if hit:
                break

        if hit:
            print("✅ 命中！\n")
            correct += 1
        else:
            print("❌ 未命中\n")

    accuracy = correct / total * 100
    print("=" * 50)
    print(f"🎯 最终准确率：{accuracy:.1f}% ({correct}/{total})")
    if accuracy == 100:
        print("🎉 恭喜！RAG 检索完美命中所有测试用例！")
    elif accuracy >= 80:
        print("👍 表现优秀！可投入实际使用。")
    else:
        print("🔧 建议检查知识库格式或重新构建索引。")
    print("=" * 50)

if __name__ == "__main__":
    evaluate_rag()