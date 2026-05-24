# experiment/api_client.py
import os
from typing import Optional
from pathlib import Path  # ← 新增：用于可靠路径处理

from dashscope import Generation

# ===== 条件导入 llama.cpp（避免无本地模型时崩溃）=====
try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    LLAMA_CPP_AVAILABLE = False

# ===== 导入模板匹配逻辑 =====
from LLM.template_registry import find_matching_template, apply_template


class LLMClient:
    """
    统一封装 LLM 调用接口：
    - 若提供 local_model_path → 使用本地 llama.cpp（带自动信封）
    - 否则使用 Qwen API
    """

    def __init__(
        self,
        model_name: str = "qwen-max",
        temperature: float = 0.3,
        local_model_path: Optional[str] = None,
        n_ctx: int = 2048,
        n_threads: int = 6
    ):
        self.model_name = model_name
        self.temperature = temperature
        self.use_local = local_model_path is not None

        if self.use_local:
            if not LLAMA_CPP_AVAILABLE:
                raise RuntimeError("请安装 llama-cpp-python: pip install llama-cpp-python")

            # === 【关键】动态定位项目内的 llama.dll ===
            # 当前文件路径: .../godot-qwen-agent/experiment/api_client.py
            current_file = Path(__file__).resolve()
            project_root = current_file.parent.parent  # 上两级到 godot-qwen-agent/
            dll_path = project_root / "GGUF" / "llama.dll"

            if not dll_path.exists():
                raise FileNotFoundError(
                    f"❌ 未找到 llama.dll！\n"
                    f"请将 llama.dll 放在项目根目录下的 GGUF 文件夹中。\n"
                    f"期望路径: {dll_path}"
                )

            os.environ["LLAMA_CPP_LIB"] = str(dll_path)
            print(f"[LOCAL] 使用内置 DLL: {dll_path}")

            print(f"[LOCAL] 加载模型: {local_model_path}")
            self.local_llm = Llama(
                model_path=local_model_path,
                n_ctx=n_ctx,
                n_threads=n_threads,
                verbose=False
            )
            print("[LOCAL] 模型加载完成")

            # === 自动匹配 prompt 模板 ===
            self.template_config = find_matching_template(local_model_path)

            # print(f"[DEBUG] 模型路径: {local_model_path}")
            # print(f"[DEBUG] 匹配到的模板: {self.template_config.get('name') if self.template_config else None}")
            
            if self.template_config:
                name = self.template_config.get('name', 'unknown')
                print(f"[LOCAL] 匹配到模板: {name}")
            else:
                print("[LOCAL] 未匹配到模板，将使用原始 prompt")

    def generate(self, prompt: str, max_retries: int = 3) -> str:
        """统一生成接口"""
        if self.use_local:
            return self._generate_local(prompt)
        else:
            return self._generate_api(prompt, max_retries)

    def _generate_local(self, prompt: str) -> str:
        """本地 llama.cpp 推理（带自动模板包装）"""
        try:
            if self.template_config:
                wrapped_prompt = apply_template(self.template_config, prompt)
                stop_tokens = self.template_config.get("stop_tokens", ["\n\n"])
            else:
                wrapped_prompt = prompt
                stop_tokens = ["\n\n", "</s>", "<|im_end|>"]

            print(f"[DEBUG] 使用的 stop_tokens: {stop_tokens}")  # ← 临时加这行
            
            output = self.local_llm(
                wrapped_prompt,
                max_tokens=512,
                temperature=self.temperature,
                stop=stop_tokens,
                echo=False
            )
            return output['choices'][0]['text'].strip()
        except Exception as e:
            return f"[ERROR] 本地推理失败: {str(e)}"

    def _generate_api(self, prompt: str, max_retries: int = 3) -> str:
        """Qwen API 推理（原逻辑）"""
        for attempt in range(max_retries):
            try:
                response = Generation.call(
                    model=self.model_name,
                    prompt=prompt,
                    api_key=os.getenv("DASHSCOPE_API_KEY"),
                    temperature=self.temperature,
                    result_format='message'
                )
                if response.status_code == 200:
                    return response.output.choices[0].message.content.strip()
                else:
                    print(f"API 调用失败 (尝试 {attempt+1}/{max_retries}): {response}")
            except Exception as e:
                print(f"异常 (尝试 {attempt+1}/{max_retries}): {e}")
        return "[ERROR] Qwen API 调用失败，请检查网络或配额"