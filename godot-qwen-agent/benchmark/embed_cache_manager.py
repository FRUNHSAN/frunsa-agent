# benchmark/embed_cache_manager.py
"""
Embedding 缓存管理器（增强版）—— 统一注册中心

功能：
1. 查看所有已注册的 embedding（支持关键词过滤）
2. 删除指定 embedding（物理文件 + 映射表）
3. 清理 >500MB 的大缓存
4. 清理无效注册项（物理路径不存在）
5. 与 chunk_cache_manager.py 共享 model_chunk_embed_mapping.json

用法:
    python embed_cache_manager.py
    python embed_cache_manager.py --clean-large
    python embed_cache_manager.py --clean-invalid
"""

import json
import shutil
import sys
from pathlib import Path
from typing import List, Dict, Any
import argparse

script_dir = Path(__file__).parent.resolve()
MAPPING_FILE = script_dir / "model_chunk_embed_mapping.json"


def load_mapping() -> Dict[str, Any]:
    if not MAPPING_FILE.exists():
        return {}
    try:
        return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"⚠️ 读取 {MAPPING_FILE} 失败: {e}")
        return {}


def save_mapping(mapping: Dict[str, Any]):
    try:
        MAPPING_FILE.write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️ 保存 {MAPPING_FILE} 失败: {e}")


def get_dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
    return total / (1024 * 1024)


def scan_all_embeddings() -> List[Dict]:
    mapping = load_mapping()
    embeddings_info = []
    chunks_dict = mapping.get("chunks", {})
    embeddings_dict = mapping.get("embeddings", {})

    for emb_key, emb_info in embeddings_dict.items():
        embed_dir = Path(emb_info.get("embed_dir", ""))
        exists = embed_dir.exists()
        size_mb = get_dir_size_mb(embed_dir) if exists else 0.0

        chunk_key = emb_info.get("chunk_key", "")
        model_name = emb_info.get("model_name", "unknown")
        chunk_info = chunks_dict.get(chunk_key, {})
        source_id = chunk_info.get("source_id", "unknown")
        strategy = chunk_info.get("chunking_strategy", "unknown")

        display_name = f"{source_id} [{strategy}] → {model_name}"

        embeddings_info.append({
            "name": display_name,
            "folder": embed_dir,
            "size_mb": size_mb,
            "exists": exists,
            "emb_key": emb_key,
            "model_name": model_name,
            "source_id": source_id,
        })

    embeddings_info.sort(key=lambda x: x["name"].lower())
    return embeddings_info


def list_embeddings(embeddings_info: List[Dict], title: str = "已注册的 Embedding 缓存"):
    if not embeddings_info:
        print(f"✅ {title}: 无")
        return

    print(f"📦 {title}:\n")
    print(f"{'编号':<4} {'名称':<60} {'存在':<6} {'大小 (MB)':<10} {'缓存路径'}")
    print("-" * 100)

    for i, e in enumerate(embeddings_info, 1):
        status = "✅" if e["exists"] else "❌"
        print(f"{i:<4} {e['name']:<60} {status:<6} {e['size_mb']:>8.1f}   {e['folder']}")

    print()


def delete_embedding_from_mapping(emb_key: str):
    mapping = load_mapping()
    if "embeddings" in mapping and emb_key in mapping["embeddings"]:
        del mapping["embeddings"][emb_key]
        save_mapping(mapping)
        print(f"✅ 已从映射表移除: {emb_key}")


def confirm_and_delete(target_embeddings: List[Dict]):
    if not target_embeddings:
        print("❌ 没有要删除的 embedding")
        return

    print("\n🗑️  即将删除以下 embedding:")
    total_size = 0
    for e in target_embeddings:
        print(f"   - {e['name']} ({e['size_mb']:.1f} MB) [key: {e['emb_key']}]")
        total_size += e['size_mb']
    print(f"\n📊 总计释放空间: {total_size:.1f} MB")

    confirm = input("\n输入 'yes' 确认批量删除: ").strip()
    if confirm.lower() != 'yes':
        print("🚫 取消操作")
        return

    success_count = 0
    for e in target_embeddings:
        try:
            if e["folder"].exists():
                shutil.rmtree(e["folder"])
                print(f"✅ 已删除物理文件: {e['name']}")
            else:
                print(f"ℹ️  物理路径不存在（仅清理映射）: {e['name']}")

            delete_embedding_from_mapping(e["emb_key"])
            success_count += 1
        except Exception as err:
            print(f"💥 删除失败 {e['name']}: {err}")

    print(f"\n🎉 完成! 成功处理 {success_count}/{len(target_embeddings)} 个")


def clean_invalid_entries():
    """清理物理路径不存在的注册项（只删映射，不删文件）"""
    embeddings_info = scan_all_embeddings()
    invalid = [e for e in embeddings_info if not e["exists"]]
    if not invalid:
        print("✅ 没有无效注册项")
        return

    print("\n🧹 发现无效注册项（物理路径不存在）:")
    for e in invalid:
        print(f"   - {e['name']} [key: {e['emb_key']}]")

    confirm = input("\n是否从映射表中移除这些无效项？(yes/no): ").strip()
    if confirm.lower() != 'yes':
        print("🚫 取消")
        return

    for e in invalid:
        delete_embedding_from_mapping(e["emb_key"])
    print(f"✅ 已清理 {len(invalid)} 个无效注册项")


def main():
    parser = argparse.ArgumentParser(description="Embedding 缓存管理器（增强版）")
    parser.add_argument("--clean-large", action="store_true", help="删除 >500MB 的缓存")
    parser.add_argument("--clean-invalid", action="store_true", help="清理无效注册项（路径不存在）")
    parser.add_argument("--filter", type=str, help="按关键词过滤（模型名或数据源）")
    args = parser.parse_args()

    all_embeddings = scan_all_embeddings()

    # 应用过滤
    filtered = all_embeddings
    if args.filter:
        keyword = args.filter.lower()
        filtered = [
            e for e in all_embeddings
            if keyword in e["name"].lower() or keyword in e["model_name"].lower() or keyword in e["source_id"].lower()
        ]

    if args.clean_large:
        large = [e for e in all_embeddings if e["size_mb"] > 500 and e["exists"]]
        confirm_and_delete(large)
        return

    if args.clean_invalid:
        clean_invalid_entries()
        return

    # 默认交互模式
    list_embeddings(filtered, title=f"Embedding 缓存（共 {len(filtered)} 项）")

    if not all_embeddings:
        return

    print("💡 操作选项:")
    print(f"  [1-{len(filtered)}] → 删除对应编号的缓存")
    print("  [关键词] → 模糊匹配后操作（如 'nomic' 或 'godot_zh'）")
    print("  --clean-large     → 命令行清理大缓存")
    print("  --clean-invalid   → 命令行清理无效注册")
    print("  q/回车 → 退出\n")

    user_input = input("请输入操作: ").strip()
    if not user_input or user_input.lower() == 'q':
        print("👋 退出")
        return

    selected = None
    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(filtered):
            selected = filtered[idx - 1]
    else:
        matches = [e for e in all_embeddings if user_input.lower() in e["name"].lower()]
        if len(matches) == 1:
            selected = matches[0]
        elif len(matches) > 1:
            print(f"⚠️ 找到 {len(matches)} 个匹配项，请精确输入:")
            for e in matches:
                print(f"   - {e['name']} [key: {e['emb_key']}]")
            return
        else:
            print("❌ 未找到匹配项")

    if not selected:
        return

    print(f"\n即将删除: {selected['name']}")
    print(f"  路径: {selected['folder']}")
    print(f"  Key:  {selected['emb_key']}")
    confirm = input("\n确认删除？(yes/no): ").strip()
    if confirm.lower() == 'yes':
        try:
            if selected["folder"].exists():
                shutil.rmtree(selected["folder"])
                print(f"✅ 已删除物理文件")
            delete_embedding_from_mapping(selected["emb_key"])
        except Exception as err:
            print(f"💥 删除失败: {err}")
    else:
        print("🚫 取消")


if __name__ == "__main__":
    main()