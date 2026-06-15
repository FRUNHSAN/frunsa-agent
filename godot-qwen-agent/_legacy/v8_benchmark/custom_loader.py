# benchmark/custom_loader.py

from pathlib import Path
import json

def load_by_config(loader_config: dict, file_path: str) -> list[str]:
    """
    根据 loader 配置加载原始文本。
    支持 type: "custom" + format: "txt_qa", "plain_text", "html"
    """
    full_path = Path(file_path).resolve()
    if not full_path.exists():
        raise FileNotFoundError(f"文件不存在: {full_path}")

    loader_type = loader_config.get("type")
    if loader_type != "custom":
        raise ValueError(f"仅支持 loader.type='custom'，但得到: '{loader_type}'")

    fmt = loader_config.get("format", "plain_text")

    if fmt == "txt_qa":
        # short_zh.txt 是 Q&A 格式，每行一个问答对，用【问题】【答案】包裹
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 按【问题】分割（第一个可能是空）
        blocks = content.split("【问题】")[1:]
        texts = []
        for block in blocks:
            if "【答案】" in block:
                q_part, a_part = block.split("【答案】", 1)
                text = f"【问题】{q_part.strip()}【答案】{a_part.strip()}"
                texts.append(text)
            else:
                # 兜底：整块作为文本
                texts.append(block.strip())
        return [t for t in texts if t]

    elif fmt == "plain_text":
        # medium_en.md：纯文本，按空行分段
        with open(full_path, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        paragraphs = []
        current = []
        for line in lines:
            if line.strip() == "":
                if current:
                    paragraphs.append("\n".join(current).strip())
                    current = []
            else:
                current.append(line)
        if current:
            paragraphs.append("\n".join(current).strip())
        return [p for p in paragraphs if p]

    elif fmt == "html":
        # long_en.html：简单解析 HTML
        from bs4 import BeautifulSoup
        with open(full_path, 'r', encoding='utf-8') as f:
            html = f.read()
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text()
        # 按双换行分段
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paragraphs

    else:
        raise ValueError(f"未知的 custom loader.format: '{fmt}'")