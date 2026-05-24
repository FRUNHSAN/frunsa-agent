# evaluate.py

import os
import json
from prompt.runner import PipelineRunner
from prompt import PipelineConfig, StepConfig
import yaml

def load_pipeline_config(config_path: str) -> PipelineConfig:
    """从 YAML 加载配置"""
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    steps = []
    for step_dict in data["pipeline"]:
        steps.append(StepConfig(
            name=step_dict["name"],
            component_type=step_dict["component_type"],
            strategy=step_dict["strategy"],
            depends_on=step_dict["depends_on"],
            provides=step_dict["provides"],
            params=step_dict.get("params", {}),
            output_to_evaluate=step_dict.get("output_to_evaluate", False)
        ))
    
    return PipelineConfig(steps, pipeline_version=data.get("pipeline_version", 1))

def main():

    # evaluate.py
    from prompt import COMPONENT_REGISTRY
    print("Registered components:", COMPONENT_REGISTRY.keys())
    # 应输出类似：dict_keys(['query_processor', 'retriever', 'generator'])

    # 加载配置
    config = load_pipeline_config("prompt/config.yaml")
    runner = PipelineRunner(config, global_resources={})
    
    # 测试 query
    test_query = "How to make a character jump in Godot?"
    
    # 回调：打印每一步（加固版，防止 None 报错）
    def on_step(step_data):
        step_name = step_data.get('step_name', 'unknown')
        output = step_data.get('output')
        
        if output is not None:
            # 安全地转为字符串并截断
            try:
                output_str = str(output)
                preview = output_str[:100]
                if len(output_str) > 100:
                    preview += "..."
                print(f"[{step_name}] → {preview}")
            except Exception as e:
                print(f"[{step_name}] → (output conversion failed: {e})")
        else:
            # 如果 output 是 None，说明这一步可能出错了
            print(f"[{step_name}] → ❌ No output (likely failed)")

    # 执行
    result = runner.run(test_query, on_step=on_step)
    
    # 保存结果
    os.makedirs("results", exist_ok=True)
    with open("results/run_test.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    print("\n✅ Pipeline completed! Final answer:")
    print(result["final_answer"])

if __name__ == "__main__":
    main()