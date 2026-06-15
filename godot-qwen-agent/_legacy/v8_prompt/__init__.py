# prompt/__init__.py

from typing import List, Dict, Any, Optional

# ===== 组件注册表（未来扩展用）=====
COMPONENT_REGISTRY = {}

def register_component(component_type: str, strategy: str, factory_func):
    """注册一个组件工厂函数"""
    if component_type not in COMPONENT_REGISTRY:
        COMPONENT_REGISTRY[component_type] = {}
    COMPONENT_REGISTRY[component_type][strategy] = factory_func

# ===== Config 结构定义（用于文档和校验）=====

class StepConfig:
    """
    单个 pipeline 步骤的配置
    
    Example:
      name: "retrieve_docs"
      component_type: "retriever"
      strategy: "vector"
      params: {"top_k": 5}
      depends_on: ["processed_query"]
      provides: "chunks"
      output_to_evaluate: True
    """
    def __init__(self,
                 name: str,
                 component_type: str,
                 strategy: str,
                 depends_on: List[str],
                 provides: str,
                 params: Optional[Dict[str, Any]] = None,
                 output_to_evaluate: bool = False):
        self.name = name
        self.component_type = component_type
        self.strategy = strategy
        self.depends_on = depends_on
        self.provides = provides
        self.params = params or {}
        self.output_to_evaluate = output_to_evaluate

class PipelineConfig:
    """完整 pipeline 配置"""
    def __init__(self, pipeline: List[StepConfig], pipeline_version: int = 1):
        self.pipeline_version = pipeline_version
        self.pipeline = pipeline
    # ===== 自动注册所有内置组件 =====


# ===== 自动注册所有内置组件（注意：在类定义之外！）=====
# Query Processors
from components.query_processors.simple import create_simple_query_processor
register_component("query_processor", "simple", create_simple_query_processor)

# Retrievers
from components.retrievers.dummy import create_dummy_retriever
register_component("retriever", "dummy", create_dummy_retriever)

# Generators
from components.generators.echo import create_echo_generator
register_component("generator", "echo", create_echo_generator)

# 在 prompt/__init__.py 文件末尾再加一行：
from components.prompt_builders.simple_concat import create_simple_concat_prompt_builder
register_component("prompt_builder", "simple_concat", create_simple_concat_prompt_builder)

from components.retrievers.godot_vector import create_godot_vector_retriever
register_component("retriever", "godot_vector", create_godot_vector_retriever)