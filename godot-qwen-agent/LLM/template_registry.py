# llm/template_registry.py
import os
from typing import Optional, Dict, Any
import yaml

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
_TEMPLATE_CACHE = {}

def load_template_config(template_name: str) -> Dict[str, Any]:
    """从 YAML 加载模板配置"""
    if template_name in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[template_name]
    
    path = os.path.join(_TEMPLATES_DIR, f"{template_name}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Template config not found: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    _TEMPLATE_CACHE[template_name] = config
    return config

def find_matching_template(model_path: str) -> Optional[Dict[str, Any]]:
    """根据模型路径自动匹配模板（按 specificity 排序：越具体越优先）"""
    model_name = os.path.basename(model_path).lower()
    
    # 第一步：收集所有可用模板及其匹配信息
    candidates = []
    
    for filename in os.listdir(_TEMPLATES_DIR):
        if not filename.endswith(".yaml"):
            continue
        
        template_name = filename[:-5]  # 移除 .yaml
        try:
            config = load_template_config(template_name)
            patterns = config.get("match_patterns", [])
            requires_instruct = config.get("requires_instruct", False)
            
            # 检查是否满足 instruct 条件
            has_instruct = "instruct" in model_name or "chat" in model_name
            if requires_instruct and not has_instruct:
                continue
            
            # 找出所有匹配的 pattern（用于计算 specificity）
            matched_patterns = [p for p in patterns if p.lower() in model_name]
            if not matched_patterns:
                continue
            
            # 用最长的匹配 pattern 长度作为 specificity 分数（越长越具体）
            max_pattern_len = max(len(p) for p in matched_patterns)
            candidates.append((max_pattern_len, config))
            
        except Exception as e:
            print(f"[WARN] Failed to load template {filename}: {e}")
            continue
    
    # 第二步：按 specificity 降序排序（越具体越靠前）
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    # 第三步：返回第一个（最具体的）匹配
    if candidates:
        return candidates[0][1]
    
    return None

def apply_template(config: Dict[str, Any], user_content: str) -> str:
    """应用模板：替换 {user_content} 占位符"""
    template_str = config["prompt_template"]
    cleaned_content = user_content.strip()
    return template_str.format(user_content=cleaned_content)