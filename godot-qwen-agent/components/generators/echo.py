# components/generators/echo.py

class EchoGenerator:
    """
    Mock 生成器：直接返回 prompt（用于测试 pipeline 连通性）
    """
    def __init__(self, params):
        self.prefix = params.get("prefix", "Generated: ")

    def run(self, inputs, global_resources):
        """
        inputs: {"prompt": str}
        returns: {"result": str, "trace_log": {}}
        """
        prompt = inputs["prompt"]
        result = self.prefix + prompt
        return {
            "result": result,
            "trace_log": {
                "generator": "echo",
                "prefix_used": self.prefix,
                "prompt_length": len(prompt)
            }
        }

def create_echo_generator(params):
    """工厂函数"""
    return EchoGenerator(params)