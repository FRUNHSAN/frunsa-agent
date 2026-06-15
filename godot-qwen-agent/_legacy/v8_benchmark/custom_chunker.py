# benchmark/custom_chunker.py

def chunk_texts(raw_texts: list[str], chunking_config: dict) -> list[str]:
    """
    统一 chunking 入口。
    支持 strategy: "fixed", "recursive"（简化版）
    """
    strategy = chunking_config.get("strategy", "fixed")
    
    if strategy == "fixed":
        chunk_size = chunking_config.get("chunk_size", 256)
        overlap = chunking_config.get("chunk_overlap", 0)
        chunks = []
        for text in raw_texts:
            if not text.strip():
                continue
            if len(text) <= chunk_size:
                chunks.append(text)
            else:
                step = chunk_size - overlap
                start = 0
                while start < len(text):
                    end = start + chunk_size
                    chunk = text[start:end]
                    if chunk.strip():
                        chunks.append(chunk)
                    start += step
        return chunks

    elif strategy == "recursive":
        # 简化版 recursive：先按句子分，再拼接
        chunk_size = chunking_config.get("chunk_size", 512)
        overlap = chunking_config.get("chunk_overlap", 50)
        import re
        sentence_endings = re.compile(r'[.!?。！？\n]')
        chunks = []
        for text in raw_texts:
            if not text.strip():
                continue
            sentences = [s.strip() for s in sentence_endings.split(text) if s.strip()]
            if not sentences:
                continue

            current_chunk = ""
            for sent in sentences:
                if len(current_chunk) + len(sent) + 1 <= chunk_size:
                    if current_chunk:
                        current_chunk += " " + sent
                    else:
                        current_chunk = sent
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    # 如果单句超长，直接切
                    if len(sent) > chunk_size:
                        # fallback to fixed
                        step = chunk_size - overlap
                        s_start = 0
                        while s_start < len(sent):
                            s_end = s_start + chunk_size
                            chunks.append(sent[s_start:s_end])
                            s_start += step
                        current_chunk = ""
                    else:
                        current_chunk = sent
            if current_chunk:
                chunks.append(current_chunk)

        # 去重 & 清理
        seen = set()
        unique_chunks = []
        for c in chunks:
            if c not in seen and c.strip():
                seen.add(c)
                unique_chunks.append(c)
        return unique_chunks

    else:
        raise ValueError(f"不支持的 chunking.strategy: '{strategy}'")