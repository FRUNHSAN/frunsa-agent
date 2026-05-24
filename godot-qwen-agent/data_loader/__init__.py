import sys
from pathlib import Path
from typing import Optional, Dict, List

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from benchmark.config import KNOWLEDGE_SOURCES
from .data_model import DocumentChunk

def load_and_chunk_all(source_filter: Optional[str] = None) -> Dict[str, List[DocumentChunk]]:
    result = {}
    project_root = Path(__file__).parent.parent

    if source_filter is not None:
        if source_filter not in KNOWLEDGE_SOURCES:
            print(f"⚠️ 指定的 source_id '{source_filter}' 不存在")
            return {source_filter: []}
        sources_to_process = {source_filter: KNOWLEDGE_SOURCES[source_filter]}
    else:
        sources_to_process = KNOWLEDGE_SOURCES

    # 获取知识库加载模式
    from benchmark.config import KNOWLEDGE_LOADING_MODE
    
    for source_id, cfg in sources_to_process.items():
        # 获取 loader 类型
        loader_config = cfg.get("loader", {})
        loader_type = loader_config.get("type", "custom")  # 默认为 custom
        
        # 根据 KNOWLEDGE_LOADING_MODE 决定是否处理此知识源
        should_skip = False
        if KNOWLEDGE_LOADING_MODE == "new_only" and loader_type != "data_loader":
            should_skip = True
            print(f"⏭️  跳过 [{source_id}]：new_only 模式下仅处理 type='data_loader' 的知识源")
        elif KNOWLEDGE_LOADING_MODE == "old_only" and loader_type == "data_loader":
            should_skip = True
            print(f"⏭️  跳过 [{source_id}]：old_only 模式下不处理 type='data_loader' 的知识源")
        
        if should_skip:
            result[source_id] = []
            continue

        path = project_root / cfg["path"]
        if not path.exists():
            print(f"❌ 路径不存在: {path}")
            result[source_id] = []
            continue

        # === 【修改】判断是文件还是目录 ===
        if path.is_dir():
            # 多文件场景（如 Godot 文档）
            loader_config = cfg.get("loader", {})
            loader_type = loader_config.get("type", "html")  # 目录默认用 html loader
            
            if loader_type == "data_loader" and loader_config.get("engine") == "html_recursive":
                from .loaders.html_loader import HTMLLoader
                loader = HTMLLoader()
                docs = loader.load(str(path))  # 返回 List[Document]
                raw_texts = [doc.content for doc in docs]
                source_paths = [doc.source for doc in docs]
            else:
                print(f"⚠️ 不支持的目录加载器: {loader_config}")
                result[source_id] = []
                continue
        else:
            # 单文件场景
            loader_config = cfg.get("loader", {})
            loader_type = loader_config.get("type", "local_file")
            
            if loader_type == "custom":
                # 使用 benchmark 中的 custom_loader
                from benchmark.custom_loader import load_by_config
                try:
                    raw_texts = load_by_config(loader_config, str(path))
                    source_paths = [str(path)] * len(raw_texts)  # 为每个文本片段分配相同来源
                except Exception as e:
                    print(f"⚠️ custom 加载器失败: {e}")
                    raw_texts = [""]
                    source_paths = [str(path)]
            elif loader_type == "local_file":
                from .loaders.local_file import LocalFileLoader
                file_format = loader_config.get("format", "txt")
                loader = LocalFileLoader(path, file_format=file_format)
                raw_texts = [loader.load()]  # 包装成列表
                source_paths = [str(path)]
            else:
                print(f"⚠️ 单文件不支持加载器: {loader_config}")
                result[source_id] = []
                continue

        # === 分块配置 ===
        chunking_cfg = cfg.get("chunking", {})
        strategy = chunking_cfg.get("strategy", "fixed")

        all_chunks = []
        for i_doc, (raw_text, src_path) in enumerate(zip(raw_texts, source_paths)):
            try:
                if strategy == "level1":
                    from .chunking.multi_granularity import MultiGranularityChunker
                    chunker = MultiGranularityChunker(
                        chunk_sizes=chunking_cfg.get("chunk_sizes", [256, 512]),
                        overlaps=chunking_cfg.get("overlaps", [0, 50]),
                        enable_dedup=chunking_cfg.get("enable_dedup", True),
                        min_length=chunking_cfg.get("min_length", 50),
                        max_length=chunking_cfg.get("max_length", 1024)
                    )
                    chunks = chunker.split_text(raw_text)  # ← 返回 List[str]
                elif strategy == "recursive":
                    from .chunking.recursive import RecursiveCharacterTextSplitter
                    chunker = RecursiveCharacterTextSplitter(
                        chunk_size=chunking_cfg.get("chunk_size", 512),
                        chunk_overlap=chunking_cfg.get("chunk_overlap", 0)
                    )
                    chunks = chunker.split_text(raw_text)
                else:
                    from .chunking.fixed import FixedSizeChunker
                    chunker = FixedSizeChunker(chunk_size=chunking_cfg.get("chunk_size", 512))
                    chunks = chunker.split_text(raw_text)

                # 封装为 DocumentChunk
                for j, chunk in enumerate(chunks):
                    all_chunks.append(DocumentChunk(
                        text=chunk,
                        source_id=source_id,
                        metadata={
                            "original_source": src_path,
                            "doc_index": i_doc,
                            "chunk_index": j,
                            "lang": cfg.get("lang", "unknown"),
                            "chunking_strategy": strategy
                        }
                    ))
            except Exception as e:
                print(f"💥 分块失败 [{source_id}][{src_path}]: {e}")
                continue

        result[source_id] = all_chunks
        print(f"[{source_id}] 共生成 {len(all_chunks)} 个 chunks")

    return result