from pathlib import Path
from .base import BaseLoader

class LocalFileLoader(BaseLoader):
    def __init__(self, file_path: Path, file_format: str = "txt"):
        self.file_path = file_path
        self.file_format = file_format

    def load(self) -> str:
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        
        content = self.file_path.read_text(encoding="utf-8").strip()
        
        # HTML 清洗（仅当格式为 html 时）
        if self.file_format == "html":
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, "html.parser")
                main_content = (
                    soup.find("div", class_="content") or
                    soup.find("article") or
                    soup.find("main") or
                    soup
                )
                # 移除干扰元素
                for bad in main_content.select("nav, footer, aside, .toc, script, style"):
                    bad.decompose()
                content = main_content.get_text(separator="\n", strip=True)
            except Exception as e:
                print(f"⚠️ HTML 解析异常，回退原始文本: {e}")
                # 不抛出异常，继续用原始 content
        
        return content