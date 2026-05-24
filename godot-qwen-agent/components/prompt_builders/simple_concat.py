# components/prompt_builders/simple_concat.py

from typing import Dict, Any, List

class SimpleConcatPromptBuilder:
    """
    最简单的 prompt builder：把 query 和 chunks 拼成字符串
    """
    def __init__(self, params):
        pass  # 无参数

    def run(self, inputs: Dict[str, Any], global_resources: Dict[str, Any]) -> Dict[str, Any]:
        query = inputs["processed_query"]
        chunks_raw = inputs["chunks"]  # 可能是 List[str] 或 List[Dict]

        if not chunks_raw:
            relevant_info = "(No relevant information found.)"
        else:
            # 自动兼容 str 或 dict 格式
            if isinstance(chunks_raw[0], str):
                chunks = chunks_raw
            elif isinstance(chunks_raw[0], dict) and "text" in chunks_raw[0]:
                chunks = [item["text"] for item in chunks_raw]
            else:
                raise ValueError(f"Unsupported chunk format: {type(chunks_raw[0])}")

            relevant_info = "\n".join(chunks)

        prompt = f"Question: {query}\n\nRelevant info:\n{relevant_info}"
        return {
            "result": prompt,
            "trace_log": {
                "strategy": "simple_concat",
                "num_chunks": len(chunks_raw) if chunks_raw else 0
            }
        }

def create_simple_concat_prompt_builder(params):
    return SimpleConcatPromptBuilder(params)