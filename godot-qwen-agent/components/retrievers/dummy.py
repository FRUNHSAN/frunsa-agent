# components/retrievers/dummy.py

class DummyRetriever:
    """
    Mock 检索器：返回固定文本
    """
    def __init__(self, params):
        self.top_k = params.get("top_k", 2)

    def run(self, inputs, global_resources):
        """
        inputs: {"processed_query": str}
        returns: {"result": List[str], "trace_log": {}}
        """
        # 模拟检索结果
        dummy_chunks = [
            "In Godot, use apply_impulse() to make a character jump.",
            "Remember to set the jump velocity in the _physics_process function."
        ]
        result = dummy_chunks[:self.top_k]
        return {
            "result": result,
            "trace_log": {
                "retriever": "dummy",
                "top_k": self.top_k,
                "num_results": len(result)
            }
        }

def create_dummy_retriever(params):
    """工厂函数"""
    return DummyRetriever(params)