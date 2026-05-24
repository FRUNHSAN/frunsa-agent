from build_rag_index import retrieve_relevant_chunks

# 测试查询
query = "如何检测空格键？"
results = retrieve_relevant_chunks(query, top_k=2)

print("🔍 查询:", query)
print("\n📄 检索到的相关片段:")
for i, chunk in enumerate(results, 1):
    print(f"{i}. {chunk.strip()}")