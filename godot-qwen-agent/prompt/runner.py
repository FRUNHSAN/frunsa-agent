# prompt/runner.py

import time
from typing import Dict, Any, Callable, Optional
from . import PipelineConfig, StepConfig, COMPONENT_REGISTRY


class PipelineRunner:
    """
    声明式 RAG Pipeline 执行引擎
    
    Usage:
        config = load_config("prompt/config.yaml")  # 转为 PipelineConfig
        runner = PipelineRunner(config, global_resources={})
        result = runner.run("How to jump?", on_step=print)
    """

    def __init__(self, config: PipelineConfig, global_resources: Optional[Dict[str, Any]] = None):
        self.config = config
        self.global_resources = global_resources or {}
        self._validate_pipeline()

    def _validate_pipeline(self):
        """静态校验：确保每个 step 的 depends_on 在之前步骤的 provides 中"""
        available_keys = {"original_query"}  # 初始 state 必含 original_query
        
        for step in self.config.pipeline:
            # 检查依赖是否满足
            missing = set(step.depends_on) - available_keys
            if missing:
                raise ValueError(
                    f"Step '{step.name}' requires {missing}, but only {available_keys} are available."
                )
            # 注册产出
            available_keys.add(step.provides)

    def run(
        self,
        original_query: str,
        extra_state: Optional[Dict[str, Any]] = None,
        on_step: Optional[Callable[[Dict], None]] = None
    ) -> Dict[str, Any]:
        """
        执行完整 pipeline
        
        Args:
            original_query: 用户输入
            extra_state: 额外初始状态（如 query_index）
            on_step: 每步执行后的回调函数，接收 step_data
        
        Returns:
            最终结果字典，包含所有 output_to_evaluate=True 的 steps 和 final_answer
        """
        # 初始化 state
        state = {"original_query": original_query}
        if extra_state:
            state.update(extra_state)
        
        # 存储需上报的 steps
        evaluated_steps = []
        final_answer = None

        # 顺序执行每个 step
        for step in self.config.pipeline:
            start_time = time.time()
            
            try:
                # 1. 获取组件工厂
                if step.component_type not in COMPONENT_REGISTRY:
                    raise ValueError(f"Unknown component_type: {step.component_type}")
                factory = COMPONENT_REGISTRY[step.component_type].get(step.strategy)
                if not factory:
                    raise ValueError(f"Strategy '{step.strategy}' not found for {step.component_type}")

                # 2. 准备输入：从 state 中提取 depends_on 字段
                inputs = {key: state[key] for key in step.depends_on}

                # 3. 调用组件
                component = factory(step.params)
                result = component.run(inputs, self.global_resources)

                # 4. 更新 state
                state[step.provides] = result["result"]

                # 5. 构造 step_data（用于回调和日志）
                step_data = {
                    "step_name": step.name,
                    "component_type": step.component_type,
                    "strategy": step.strategy,
                    "input": inputs,  # 可用于调试（后续可加截断）
                    "output": result["result"],
                    "trace_log": {
                        "status": "success",
                        "timing_seconds": time.time() - start_time,
                        "parameters": step.params,
                        "input_keys": step.depends_on,
                        "output_key": step.provides,
                        "extra": result.get("trace_log", {})
                    },
                    "config_snapshot": {
                        "depends_on": step.depends_on,
                        "provides": step.provides,
                        "output_to_evaluate": step.output_to_evaluate
                    }
                }

                # 6. 回调 & 记录
                if on_step:
                    on_step(step_data)
                if step.output_to_evaluate:
                    evaluated_steps.append(step_data)
                    final_answer = result["result"]  # 默认最后一个为最终答案

            except Exception as e:
                # 记录失败 step
                step_data = {
                    "step_name": step.name,
                    "component_type": step.component_type,
                    "strategy": step.strategy,
                    "input": {key: state.get(key) for key in step.depends_on},
                    "output": None,
                    "trace_log": {
                        "status": "failed",
                        "error_message": str(e),
                        "timing_seconds": time.time() - start_time,
                        "parameters": step.params,
                        "input_keys": step.depends_on,
                        "output_key": step.provides
                    },
                    "config_snapshot": {
                        "depends_on": step.depends_on,
                        "provides": step.provides,
                        "output_to_evaluate": step.output_to_evaluate
                    }
                }
                if on_step:
                    on_step(step_data)
                if step.output_to_evaluate:
                    evaluated_steps.append(step_data)
                # 不中断，继续执行（便于收集完整 trace）
                continue

        return {
            "original_query": original_query,
            "steps": evaluated_steps,
            "final_answer": final_answer,
            "pipeline_summary": {
                "num_steps": len(evaluated_steps),
                "config_version": self.config.pipeline_version
            }
        }