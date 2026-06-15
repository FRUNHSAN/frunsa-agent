from sentence_transformers import SentenceTransformer
model = SentenceTransformer("G:/rag666")
print(model.encode("测试"))