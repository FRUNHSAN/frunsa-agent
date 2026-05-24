# -*- coding: utf-8 -*-
"""
Hugging Face 缓存管理器 - 终极版（支持多路径注册 + Flat 目录）

功能：
1. 查看所有已下载模型（包括注册路径中的标准格式和 flat 目录）
2. 删除指定模型
3. 清理所有大型模型（>500MB）
4. 只保留 MiniLM，删除其他所有模型
5. 自动管理 cache_registry.json：空路径自动注销

用法:
    python hf_cache_manager.py                # 默认：查看列表
    python hf_cache_manager.py --clean-large  # 清理 >500MB 的模型
    python hf_cache_manager.py --keep-minilm  # 只保留 MiniLM
"""

import os
import json
import shutil
import argparse
from pathlib import Path
from typing import List, Dict
import sys

# ======================
# 🔄 共享配置：从 benchmark.config 导入注册表路径
# ======================

script_dir = Path(__file__).parent.resolve()

try:
    from .config import CACHE_REGISTRY_FILE
except ImportError:
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    try:
        from config import CACHE_REGISTRY_FILE
    except ImportError:
        # Fallback: assume same directory as this script
        CACHE_REGISTRY_FILE = script_dir / "cache_registry.json"
        print(f"⚠️  未找到 config.py，使用默认注册表: {CACHE_REGISTRY_FILE}")


# ======================
# 共享：缓存注册表管理（使用 Path 对象）
# ======================

def load_cache_registry() -> List[str]:
    """加载用户注册的所有缓存根目录（标准化为绝对路径）"""
    if CACHE_REGISTRY_FILE.exists():
        try:
            data = json.loads(CACHE_REGISTRY_FILE.read_text(encoding="utf-8"))
            return [str(Path(p).resolve()) for p in data if p]
        except Exception as e:
            print(f"⚠️  读取 {CACHE_REGISTRY_FILE} 失败: {e}")
    return []

def save_cache_registry(paths: List[str]):
    """保存去重后的绝对路径列表"""
    unique_paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths if p))
    try:
        CACHE_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_REGISTRY_FILE.write_text(
            json.dumps(unique_paths, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"⚠️  保存 {CACHE_REGISTRY_FILE} 失败: {e}")

# ✅【新增】统一获取模型名（优先 model_id.txt）
def get_model_name_from_dir(model_dir: Path) -> str:
    """
    从模型目录提取真实模型名：
      1. 优先读取 model_id.txt
      2. 回退到 config.json 中的 _name_or_path
      3. 都失败则返回 [Unknown] + 文件夹名
    """
    # 1. 优先：model_id.txt
    id_file = model_dir / "model_id.txt"
    if id_file.exists():
        try:
            name = id_file.read_text(encoding="utf-8").strip()
            if name:
                return name
        except Exception:
            pass  # 读取失败则忽略
    
    # 2. 回退：config.json
    config_file = model_dir / "config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            name = config.get("_name_or_path", "")
            if name:
                return name
        except Exception:
            pass
    
    # 3. 最终 fallback
    return f"[Unknown] {model_dir.name}"

# ======================
# 模型扫描与操作（增强版）
# ======================

def folder_to_model_name(folder: str) -> str:
    if folder.startswith("models--"):
        return folder.replace("models--", "").replace("--", "/", 1)
    return folder

def get_folder_size(path: Path) -> float:
    try:
        total = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        return total / (1024 * 1024)
    except Exception:
        return 0.0

def scan_all_models() -> List[Dict]:
    """扫描所有 hub 目录中的标准模型 + 注册路径中的 flat 模型"""
    all_models = []
    
    # === 获取所有 hub 目录（默认 + 注册路径下的 /hub）===
    dirs = []

    # 1. 默认 HF 缓存
    default_cache = os.environ.get("HF_HOME")
    if default_cache:
        dirs.append(Path(default_cache) / "hub")
    else:
        dirs.append(Path.home() / ".cache" / "huggingface" / "hub")

    # 2. 注册路径中的 /hub
    registry = load_cache_registry()
    for root in registry:
        hub_dir = Path(root) / "hub"
        if hub_dir.exists():
            dirs.append(hub_dir)

    # 去重
    seen = set()
    hub_dirs = []
    for d in dirs:
        abs_d = d.resolve()
        if str(abs_d) not in seen:
            seen.add(str(abs_d))
            hub_dirs.append(abs_d)

    # === 1. 扫描标准模型（models--xxx/snapshots/yyy）===
    for hub_dir in hub_dirs:
        if not hub_dir.exists():
            continue
        model_folders = [f for f in hub_dir.iterdir() 
                        if f.is_dir() and f.name.startswith("models--")]
        for folder in model_folders:
            model_name = folder_to_model_name(folder.name)
            size_mb = get_folder_size(folder)
            all_models.append({
                "name": model_name,
                "folder": folder,
                "size_mb": size_mb,
                "type": "standard",
                "hub_root": hub_dir
            })
    
    # === 2. 扫描 flat 模型（直接包含 config.json）===
    for root_str in registry:
        root = Path(root_str)
        if not root.exists() or not root.is_dir():
            continue
        
        # 跳过带 /hub 的（已在上面处理）
        if (root / "hub").exists():
            continue
        
        config_file = root / "config.json"
        if not config_file.exists():
            continue
        
        # ✅【关键修改】使用新函数获取模型名（优先 model_id.txt）
        model_name = get_model_name_from_dir(root)
        
        size_mb = get_folder_size(root)
        all_models.append({
            "name": model_name,
            "folder": root,
            "size_mb": size_mb,
            "type": "flat",
            "raw_path": str(root.resolve())
        })

    # 按名称排序
    all_models.sort(key=lambda x: x["name"].lower())
    return all_models

def list_models(models_info: List[Dict]):
    if not models_info:
        print("✅ 所有缓存目录均为空")
        return
    
    print("📦 已下载的 Hugging Face 模型:\n")
    print(f"{'编号':<4} {'模型名称':<60} {'大小 (MB)':<10} {'缓存路径'}")
    print("-" * 100)
    
    for i, m in enumerate(models_info, 1):
        if m["type"] == "standard":
            cache_root = m['hub_root'].parent.resolve()
        else:  # flat
            cache_root = m['folder'].resolve()
        print(f"{i:<4} {m['name']:<60} {m['size_mb']:>8.1f}   {cache_root}")
    print()

def confirm_and_delete(target_models: List[Dict]):
    if not target_models:
        print("❌ 没有要删除的模型")
        return
    
    print("\n🗑️  即将删除以下模型:")
    total_size = 0
    for m in target_models:
        print(f"   - {m['name']} ({m['size_mb']:.1f} MB)")
        total_size += m['size_mb']
    print(f"\n📊 总计释放空间: {total_size:.1f} MB")
    
    confirm = input("\n输入 'yes' 确认批量删除: ").strip()
    if confirm.lower() != 'yes':
        print("🚫 取消操作")
        return
    
    success_count = 0
    deleted_roots = set()
    
    for m in target_models:
        try:
            shutil.rmtree(m['folder'])
            print(f"✅ 已删除: {m['name']}")
            success_count += 1
            
            # 处理注册表清理
            if m["type"] == "standard":
                hub_dir = m['hub_root']
                remaining = [f for f in hub_dir.iterdir() if f.is_dir() and f.name.startswith("models--")]
                if not remaining:
                    deleted_roots.add(str(hub_dir.parent.resolve()))
            elif m["type"] == "flat":
                raw_path = m.get("raw_path")
                if raw_path:
                    registry = load_cache_registry()
                    if raw_path in registry:
                        registry.remove(raw_path)
                        save_cache_registry(registry)
                        print(f"ℹ️  已从注册表移除 flat 路径: {raw_path}")
                
        except Exception as e:
            print(f"💥 删除失败 {m['name']}: {e}")
    
    # 自动清理空的标准注册路径
    if deleted_roots:
        registry = load_cache_registry()
        new_registry = []
        for root in registry:
            abs_root = str(Path(root).resolve())
            if abs_root in deleted_roots:
                confirm_clean = input(
                    f"\n🧹 路径 '{abs_root}' 已无模型，是否从管理列表中移除？(y/N): "
                )
                if confirm_clean.lower() == 'y':
                    print(f"✅ 已从注册表移除: {abs_root}")
                    continue
            new_registry.append(root)
        
        save_cache_registry(new_registry)
    
    print(f"\n🎉 完成! 成功删除 {success_count}/{len(target_models)} 个模型")


# ======================
# 主程序
# ======================

def main():
    parser = argparse.ArgumentParser(description="Hugging Face 缓存管理器（支持多路径 + Flat 目录）")
    parser.add_argument("--clean-large", action="store_true", 
                        help="删除所有 >500MB 的模型")
    parser.add_argument("--keep-minilm", action="store_true",
                        help="只保留 MiniLM，删除其他所有模型")
    args = parser.parse_args()
    
    models_info = scan_all_models()
    
    if args.clean_large:
        large_models = [m for m in models_info if m["size_mb"] > 500]
        confirm_and_delete(large_models)
        return
    
    if args.keep_minilm:
        minilm_models = [m for m in models_info if "minilm" in m["name"].lower()]
        other_models = [m for m in models_info if "minilm" not in m["name"].lower()]
        
        if minilm_models:
            print("🔒 将保留以下 MiniLM 模型:")
            for m in minilm_models:
                print(f"   - {m['name']}")
        else:
            print("⚠️  未找到 MiniLM 模型，但将继续删除其他模型")
        
        confirm_and_delete(other_models)
        return
    
    # 默认交互模式
    list_models(models_info)
    if not models_info:
        return
        
    print("💡 操作选项:")
    print("  [1-{}] → 输入编号删除单个模型".format(len(models_info)))
    print("  [名称] → 输入模型名（如 bge-m3）")
    print("  --clean-large → 命令行参数：清理大模型")
    print("  --keep-minilm → 命令行参数：只保留 MiniLM")
    print("  q/回车 → 退出\n")
    
    user_input = input("请输入操作: ").strip()
    if not user_input or user_input.lower() == 'q':
        print("👋 退出")
        return
    
    # 单个删除逻辑
    selected = None
    if user_input.isdigit():
        idx = int(user_input)
        if 1 <= idx <= len(models_info):
            selected = models_info[idx - 1]
    else:
        matches = [m for m in models_info if user_input.lower() in m["name"].lower()]
        if len(matches) == 1:
            selected = matches[0]
        elif len(matches) > 1:
            print(f"⚠️  找到 {len(matches)} 个匹配项:")
            for m in matches:
                print(f"   - {m['name']}")
            return
        else:
            exact_match = next((m for m in models_info if m["name"] == user_input), None)
            if exact_match:
                selected = exact_match
    
    if not selected:
        print("❌ 未找到匹配模型")
        return
    
    confirm = input(f"\n确认删除 '{selected['name']}'? (yes/no): ").strip()
    if confirm.lower() == 'yes':
        try:
            shutil.rmtree(selected['folder'])
            print(f"✅ 成功删除: {selected['name']}")
            
            # 处理注册表清理
            if selected["type"] == "standard":
                hub_dir = selected['hub_root']
                remaining = [f for f in hub_dir.iterdir() if f.is_dir() and f.name.startswith("models--")]
                if not remaining:
                    abs_root = str(hub_dir.parent.resolve())
                    registry = load_cache_registry()
                    normalized_registry = [str(Path(r).resolve()) for r in registry]
                    if abs_root in normalized_registry:
                        confirm_clean = input(
                            f"\n🧹 路径 '{abs_root}' 已空，是否从管理列表中移除？(y/N): "
                        )
                        if confirm_clean.lower() == 'y':
                            new_registry = [
                                r for r in registry 
                                if str(Path(r).resolve()) != abs_root
                            ]
                            save_cache_registry(new_registry)
                            print(f"✅ 已从注册表移除: {abs_root}")
            elif selected["type"] == "flat":
                raw_path = selected.get("raw_path")
                if raw_path:
                    registry = load_cache_registry()
                    if raw_path in registry:
                        registry.remove(raw_path)
                        save_cache_registry(registry)
                        print(f"✅ 已从注册表移除 flat 路径: {raw_path}")
                    
        except Exception as e:
            print(f"💥 删除失败: {e}")


if __name__ == "__main__":
    main()