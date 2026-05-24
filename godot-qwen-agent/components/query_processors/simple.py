# components/query_processors/simple.py

class SimpleQueryProcessor:
    """
    最简单的 query processor：原样返回输入
    """
    def __init__(self, params):
        # params 可忽略（无配置项）
        pass

    def run(self, inputs, global_resources):
        """
        inputs: {"original_query": str}
        returns: {"result": str, "trace_log": {}}
        """
        query = inputs["original_query"]
        return {
            "result": query,
            "trace_log": {
                "processor": "simple",
                "input_length": len(query)
            }
        }

def create_simple_query_processor(params):
    """工厂函数"""
    return SimpleQueryProcessor(params)