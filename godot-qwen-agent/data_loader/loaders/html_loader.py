# data_loader/loaders/html_loader.py
import os
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List
import traceback  # ← 新增：用于打印完整错误
from ..data_model import Document

class HTMLLoader:
    def __init__(self):
        self.exclude_patterns = ["search", "index", "404", "class_list", "modules"]

    def load(self, docs_root: str) -> List[Document]:
        docs = []
        root = Path(docs_root)

        # 获取所有 HTML 文件（先转成列表，方便计数）
        all_html_files = list(root.rglob("*.html"))
        print(f"🔍 共发现 {len(all_html_files)} 个 HTML 文件")

        processed = 0
        for html_file in all_html_files:
            if any(p in str(html_file) for p in self.exclude_patterns):
                continue

            # ⚠️ 调试：只处理前 10 个有效文件
            if processed >= 10:
                print("✅ 调试模式：已处理 10 个文件，提前退出")
                break

            try:
                print(f"📄 正在处理 [{processed + 1}/10]: {html_file.relative_to(root)}")
                
                with open(html_file, "r", encoding="utf-8", errors="ignore") as f:
                    soup = BeautifulSoup(f, "html.parser")

                # 提取标题
                title_elem = soup.find("h1")
                title = title_elem.get_text(strip=True) if title_elem else html_file.stem.replace("_", " ").title()

                # 提取正文
                content_div = soup.select_one("div.content") or soup.body
                if not content_div:
                    print(f"  ⚠️ 跳过：未找到正文区域")
                    continue

                # 清理噪音
                for elem in content_div.select("nav, footer, .toc, .breadcrumbs, script, style"):
                    elem.decompose()

                content = content_div.get_text(separator="\n", strip=True)
                if len(content) < 100:
                    print(f"  ⚠️ 跳过：内容太短 ({len(content)} 字符)")
                    continue

                doc = Document(
                    content=content,
                    source=str(html_file.relative_to(root)),
                    metadata={
                        "title": title,
                        "file_name": html_file.name,
                        "loader": "html"
                    }
                )
                docs.append(doc)
                processed += 1

            except Exception as e:
                print(f"💥 处理失败 {html_file}: {type(e).__name__}: {e}")
                traceback.print_exc()  # ← 打印完整错误堆栈
                continue

        print(f"✅ 成功加载 {len(docs)} 个文档")
        return docs