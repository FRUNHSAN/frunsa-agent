# benchmark/chunk_cache_manager.py
"""
分块缓存管理器（Chunk Cache Manager）—— 集中式版本（优化版）

功能：
1. 查看所有已注册的 chunks 和 embeddings（跨盘支持）
2. 删除指定知识源的 chunk + 所有相关 embeddings
3. 清理所有大于 1GB 的 chunk 缓存
4. 自动维护 model_chunk_embed_mapping.json

📌 设计原则：
   - 唯一注册中心：benchmark/model_chunk_embed_mapping.json
   - 支持任意绝对路径（G:\..., D:\...）
   - 删除 chunk 时自动清理其所有 embedding 缓存
   - 映射表操作精准：按 chunk_key 删除，避免残留

用法:
    python chunk_cache_manager.py                # 查看列表
    python chunk_cache_manager.py --clean-large  # 清理 >1GB 的 chunk
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Any, List
import argparse


# ======================
# 🌟 集中式映射文件路径
# ======================

script_dir = Path(__file__).parent.resolve()
MAPPING_FILE = script_dir / "model_chunk_embed_mapping.json"


def load_mapping() -> Dict[str, Any]:
    """加载集中式映射表"""
    if not MAPPING_FILE.exists():
        return {}
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️  读取 {MAPPING_FILE} 失败: {e}")
        return {}


def save_mapping(mapping: Dict[str, Any]):
    """保存映射表"""
    try:
        MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
        MAPPING_FILE.write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️  保存 {MAPPING_FILE} 失败: {e}")


def get_dir_size_mb(path: Path) -> float:
    """计算目录总大小（MB）"""
    if not path.exists():
        return 0.0
    try:
        total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return total / (1024 * 1024)
    except Exception as e:
        print(f"⚠️  计算目录大小失败 {path}: {e}")
        return 0.0


def scan_registered_chunks() -> List[Dict]:
    """从映射表中提取所有已注册的 chunk 信息"""
    mapping = load_mapping()
    chunks_info = []

    chunks_dict = mapping.get("chunks", {})
    embeddings_dict = mapping.get("embeddings", {})

    # 构建反向索引：chunk_key -> [emb_info]
    chunk_to_embeddings = {}
    for emb_key, emb_info in embeddings_dict.items():
        chunk_key = emb_info.get("chunk_key")
        if chunk_key:
            chunk_to_embeddings.setdefault(chunk_key, []).append(emb_info)

    for chunk_key, chunk_info in chunks_dict.items():
        chunk_dir = Path(chunk_info.get("chunk_dir", ""))
        exists = chunk_dir.exists()
        size_mb = get_dir_size_mb(chunk_dir) if exists else 0.0

        # 构建 embedding 摘要：{model_name: embed_dir}
        embed_summary = {}
        for emb in chunk_to_embeddings.get(chunk_key, []):
            model_name = emb.get("model_name", "unknown")
            embed_summary[model_name] = emb.get("embed_dir", "")

        chunks_info.append({
            "chunk_key": chunk_key,  # ← 关键：用于精准删除
            "source_id": chunk_info.get("source_id", "unknown"),
            "name": f"{chunk_info.get('source_id', 'unknown')} [{chunk_info.get('chunking_strategy', 'unknown')}]",
            "chunk_dir": chunk_dir,
            "exists": exists,
            "size_mb": size_mb,
            "embed_count": len(embed_summary),
            "embeddings": embed_summary,
        })

    chunks_info.sort(key=lambda x: x["source_id"].lower())
    return chunks_info


def list_chunks(chunks_info: List[Dict]):
    if not chunks_info:
        print("✅ 没有已注册的 chunk 缓存")
        return

    print("📦 已注册的 Chunk 缓存:\n")
    print(f"{'编号':<4} {'名称':<40} {'存在':<6} {'大小 (MB)':<10} {'Embeddings'} {'缓存路径'}")
    print("-" * 110)

    for i, c in enumerate(chunks_info, 1):
        status = "✅" if c["exists"] else "❌"
        print(
            f"{i:<4} {c['name']:<40} {status:<6} {c['size_mb']:>8.1f}   "
            f"{c['embed_count']:<12} {c['chunk_dir']}"
        )
    print()


def delete_source(source_info: dict):
    """删除一个 chunk + 所有相关 embeddings，并同步更新映射表"""
    chunk_key = source_info.get("chunk_key")
    if not chunk_key:
        print("❌ 内部错误：缺少 chunk_key，无法安全删除")
        return

    chunk_dir = source_info["chunk_dir"]
    embeddings = source_info.get("embeddings", {})  # {model_name: path}

    # Step 1: 删除所有关联的 embedding 目录
    deleted_emb_count = 0
    for model_name, embed_path in embeddings.items():
        embed_dir = Path(embed_path)
        if embed_dir.exists():
            try:
                shutil.rmtree(embed_dir)
                print(f"✅ 已删除 Embedding: {model_name}")
                deleted_emb_count += 1
            except Exception as e:
                print(f"💥 删除 Embedding 失败 ({model_name}): {e}")

    # Step 2: 删除 chunk 目录
    chunk_deleted = False
    if chunk_dir.exists():
        try:
            shutil.rmtree(chunk_dir)
            print(f"✅ 已删除 Chunk: {source_info['name']}")
            chunk_deleted = True
        except Exception as e:
            print(f"💥 删除 Chunk 失败: {e}")
    else:
        print(f"ℹ️  Chunk 路径不存在（可能已清理）: {chunk_dir}")

    # Step 3: ⭐ 最后才更新映射表（确保物理删除成功后再移除元数据）
    mapping = load_mapping()
    emb_keys_to_remove = []

    # 收集要删除的 embedding keys
    if "embeddings" in mapping:
        emb_keys_to_remove = [
            emb_key for emb_key, emb_info in mapping["embeddings"].items()
            if emb_info.get("chunk_key") == chunk_key
        ]

    # 执行删除
    if "chunks" in mapping and chunk_key in mapping["chunks"]:
        del mapping["chunks"][chunk_key]

    for emb_key in emb_keys_to_remove:
        mapping["embeddings"].pop(emb_key, None)

    save_mapping(mapping)
    print(f"✅ 已从注册表移除 chunk '{chunk_key}' 及其 {len(emb_keys_to_remove)} 个 embeddings")


def main():
    parser = argparse.ArgumentParser(description="分块缓存管理器（集中式，优化版）")
    parser.add_argument("--clean-large", action="store_true", help="删除所有 >1GB 的 chunk 缓存")
    args = parser.parse_args()

    chunks_info = scan_registered_chunks()

    if args.clean_large:
        large_chunks = [c for c in chunks_info if c["size_mb"] > 1024 and c["exists"]]
        if not large_chunks:
            print("✅ 没有大于 1GB 的 chunk 缓存")
            return

        print("\n🗑️  即将删除以下大体积 chunk（及其所有 embeddings）:")
        total_size = 0
        for c in large_chunks:
            print(f"   - {c['name']} ({c['size_mb']:.1f} MB)")
            total_size += c['size_mb']
        print(f"\n📊 总计释放空间: {total_size:.1f} MB")

        confirm = input("\n输入 'yes' 确认批量删除: ").strip()
        if confirm.lower() == 'yes':
            for c in large_chunks:
                delete_source(c)
        else:
            print("🚫 取消操作")
        return

    # 默认交互模式
    list_chunks(chunks_info)
    if not chunks_info:
        return

    print("💡 操作选项:")
    print(f"  [1-{len(chunks_info)}] → 输入编号删除整个 source（chunk + embeddings）")
    print("  [source_id] → 输入完整或部分 source ID（如 godot_en）")
    print("  --clean-large → 命令行参数：清理大 chunk")
    print("  q/回车 → 退出\n")

    user_input = input("请输入操作: ").strip()
    if not user_input or user_input.lower() == 'q':
        print("👋 退出")
        return

    selected = None

    # 数字编号选择
    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(chunks_info):
            selected = chunks_info[idx - 1]

    # 模糊匹配 source_id
    if selected is None:
        matches = [c for c in chunks_info if user_input.lower() in c["source_id"].lower()]
        if len(matches) == 1:
            selected = matches[0]
        elif len(matches) > 1:
            print(f"⚠️  找到 {len(matches)} 个匹配项，请输入更精确的 source_id:")
            for m in matches:
                print(f"   - {m['source_id']} ({m['name']})")
            return
        else:
            # 尝试精确匹配（兼容旧习惯）
            selected = next((c for c in chunks_info if c["source_id"] == user_input), None)

    if not selected:
        print("❌ 未找到匹配的 source")
        return

    print(f"\n即将删除: {selected['name']}")
    print(f"  Chunk 路径: {selected['chunk_dir']}")
    print(f"  关联 Embeddings: {selected['embed_count']} 个")
    confirm = input("\n确认删除？(yes/no): ").strip()
    if confirm.lower() == 'yes':
        delete_source(selected)
    else:
        print("🚫 取消操作")


if __name__ == "__main__":
    main()