# prompt/post_processors.py
def basic_processor(response: str, context=None) -> dict:
    return {"answer": response.strip()}

def code_formatter(response: str, context=None) -> dict:
    # 简单代码格式化
    lines = response.strip().split('\n')
    formatted_lines = []
    for line in lines:
        if line.strip().startswith(('func', 'var', 'if', 'for')):
            formatted_lines.append(line)
        else:
            formatted_lines.append(line)
    return {"answer": '\n'.join(formatted_lines)}

# 工厂函数
def get_post_processor(config):
    proc_type = config["post_processor"]["type"]
    processors = {
        "basic": basic_processor,
        "code_formatter": code_formatter
    }
    return processors[proc_type]