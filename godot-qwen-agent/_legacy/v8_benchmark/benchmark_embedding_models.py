# benchmark/benchmark_embedding_models.py
"""
多知识库 RAG 模型性能评测系统（仅采集模式）

支持模型：
  - sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  - BAAI/bge-m3

国内用户加速指南（PowerShell）：
   $env:USE_HF_MIRROR="1"; python benchmark_embedding_models.py
"""


# ==============================
# 🔁 确保项目根目录在 sys.path 中（关键修复！）
# ==============================
import sys
from pathlib import Path

# 获取当前脚本所在目录的父目录（即项目根目录）
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import os
import json
import time
import shutil  # ✅【新增】用于删除缓存目录
import argparse  # ✅【新增】用于解析命令行参数
import torch  # ✅ 用于设备检测和设置
from pathlib import Path as _Path
from typing import List, Tuple, Dict, Any
import statistics  # ✅ 用于计算标准差


# ==============================
# 🌐 智能 Hugging Face 配置（按需启用镜像）
# ==============================
if os.environ.get("USE_HF_MIRROR", "").lower() in ("1", "true", "yes"):
    print("🌐 检测到 USE_HF_MIRROR=1，启用 Hugging Face 镜像 (https://hf-mirror.com)")
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# 或者设置环境变量（推荐）
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_OFFLINE"] = "0"

#是否禁止联网搜索
LOCAL_FILES_ONLY=False
#是否启用远程代码操作
TRUST_REMOTE_CODE = True
# 注意：不再全局设置 HF_HUB_OFFLINE=1！

# ==============================
# 🔁 兼容相对导入与直接运行
# ==============================
try:
    from .config import (
        CACHE_REGISTRY_FILE,
        BENCHMARK_RESULTS_FILE,
        KNOWLEDGE_SOURCES,
        MODELS,
        TEST_QUERIES,
        SNAPSHOT_DOWNLOAD_ALLOW_PATTERNS,
        SNAPSHOT_DOWNLOAD_IGNORE_PATTERNS,
        EMBEDDING_BENCHMARK_ENCODE_RUNS,
        EMBEDDING_DEVICE,# ✅ 新增设备配置
        WARMUP_ENCODE_RUNS,  # Warm-up 预跑次数，不计入正式测量
        MODEL_CHUNK_EMBED_MAPPING_FILE,  # ✅ 新增映射文件路径
        CACHE_ROOT,           # ✅ 添加缺少的变量
        REUSE_CHUNK_CACHE,    # ✅ 添加缺少的变量
        REUSE_EMBED_CACHE,    # ✅ 添加缺少的变量
        KNOWLEDGE_LOADING_MODE,        # ✅ 新增知识库加载模式变量
        GGUF_MODEL_REGISTRY,
        GGUF_INFERENCE_CONFIG,  # ✅ 新增：添加这行
    )
except ImportError:
    script_dir = _Path(__file__).parent.resolve()
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))
    from config import (
        CACHE_REGISTRY_FILE,
        BENCHMARK_RESULTS_FILE,
        KNOWLEDGE_SOURCES,
        MODELS,
        TEST_QUERIES,
        SNAPSHOT_DOWNLOAD_ALLOW_PATTERNS,
        SNAPSHOT_DOWNLOAD_IGNORE_PATTERNS,
        EMBEDDING_BENCHMARK_ENCODE_RUNS,  # ← 补上
        EMBEDDING_DEVICE,                # ← 补上
        WARMUP_ENCODE_RUNS,  # Warm-up 预跑次数，不计入正式测量
        MODEL_CHUNK_EMBED_MAPPING_FILE,  # ✅ 新增映射文件路径
        CACHE_ROOT,           # ✅ 添加缺少的变量
        REUSE_CHUNK_CACHE,    # ✅ 添加缺少的变量
        REUSE_EMBED_CACHE,    # ✅ 添加缺少的变量
        KNOWLEDGE_LOADING_MODE,        # ✅ 新增知识库加载模式变量
        GGUF_MODEL_REGISTRY,
        GGUF_INFERENCE_CONFIG,  # ✅ 新增：添加这行
    )

from sentence_transformers import SentenceTransformer
from huggingface_hub import snapshot_download
from bs4 import BeautifulSoup
import numpy as np

# ==============================
# 🦙 GGUF Embedding 支持（llama.cpp）
# ==============================
import os
from pathlib import Path as _Path

# 【关键】设置 llama.dll 路径（根据你的实际路径）
os.environ["LLAMA_CPP_LIB"] = r"D:\agent\godot-qwen-agent\GGUF\llama.dll"

try:
    from llama_cpp import Llama
    LLAMA_CPP_AVAILABLE = True
except ImportError:
    print("⚠️ llama-cpp-python 未安装，GGUF 模型将被跳过")
    LLAMA_CPP_AVAILABLE = False

# ==============================
# 📦 导入自定义加载器（用于 fallback）
# ==============================
try:
    from .custom_loader import load_by_config
except ImportError:
    # 兼容直接运行
    from custom_loader import load_by_config


# ==============================
# 🧠 缓存协调工具（新增）
# ==============================

def hash_dict(d: dict) -> str:
    """对字典进行确定性哈希（忽略 key 顺序）"""
    import hashlib
    import json
    s = json.dumps(d, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.md5(s).hexdigest()[:8]

def sanitize_pathname(name: str) -> str:
    """
    将字符串转换为 Windows 安全的路径名。
    替换所有非法字符为下划线 _。
    非法字符包括：\ / : * ? " < > | 以及 ASCII 控制字符
    """
    import re
    # Windows 非法字符正则（包括控制字符）
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', name).rstrip(' .')

def get_chunk_key(source_id: str, chunking_config: Dict[str, Any]) -> str:
    """生成 chunk 唯一标识：source__strategy__params_hash"""
    strategy = chunking_config.get("strategy", "fixed")
    params = {k: v for k, v in chunking_config.items() if k != "strategy"}
    params_hash = hash_dict(params)
    return f"{source_id}__{strategy}__{params_hash}"

def get_embed_key(chunk_key: str, model_name: str) -> str:
    """生成 embedding 唯一标识：chunk_key__safe_model_name"""
    safe_model = sanitize_pathname(model_name)  # ← 使用新函数清洗整个模型名
    return f"{chunk_key}__{safe_model}"

def load_mapping_file() -> Dict[str, Any]:
    """加载全局映射文件"""
    if MODEL_CHUNK_EMBED_MAPPING_FILE.exists():
        try:
            return json.loads(MODEL_CHUNK_EMBED_MAPPING_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"⚠️  读取映射文件失败: {e}")
    return {"chunks": {}, "embeddings": {}}

def save_mapping_file(mapping: Dict[str, Any]):
    """保存映射文件"""
    MODEL_CHUNK_EMBED_MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODEL_CHUNK_EMBED_MAPPING_FILE.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# ==============================
# 工具函数
# ==============================
def load_cache_registry() -> List[str]:
    """加载缓存注册表，并自动清理无效路径"""
    if CACHE_REGISTRY_FILE.exists():
        try:
            registry = json.loads(CACHE_REGISTRY_FILE.read_text(encoding="utf-8"))
            valid_registry = [p for p in registry if _Path(p).exists()]
            if len(valid_registry) != len(registry):
                print(f"🧹 自动清理 {len(registry) - len(valid_registry)} 个无效缓存注册项")
                save_cache_registry(valid_registry)
            return valid_registry
        except Exception as e:
            print(f"⚠️ 缓存注册表加载失败: {e}")
            return []
    return []

def save_cache_registry(registry: List[str]):
    CACHE_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")

def is_safe_path_name(name: str) -> bool:
    bad_chars = '<>:"/\\|?*'
    return all(c not in bad_chars for c in name)

# ✅【修改 1/2】增强模型识别：优先使用 model_id.txt
def find_model_in_any_cache(model_name: str) -> Tuple[bool, str]:
    """增强版：支持 flat 目录 + 身份验证（优先 model_id.txt）"""
    registry = load_cache_registry()
    
    def is_target_model(path: _Path, expected_name: str) -> bool:
        # 🔑 优先检查 model_id.txt
        id_file = path / "model_id.txt"
        if id_file.exists():
            try:
                actual_name = id_file.read_text(encoding="utf-8").strip()
                return actual_name == expected_name
            except:
                pass  # 读取失败则回退
        
        # 回退到 config.json
        config_file = path / "config.json"
        if not config_file.exists():
            return False
        try:
            config = json.loads(config_file.read_text(encoding="utf-8"))
            name_in_config = config.get("_name_or_path", "")
            return expected_name.lower() in name_in_config.lower()
        except Exception:
            return False

    # 1. 检查用户注册的每个路径
    for reg_path in registry:
        p = _Path(reg_path)
        if not p.exists():
            continue
        
        # 情况 A: flat 目录（直接包含模型文件）
        if is_target_model(p, model_name):
            return True, str(p)
        
        # 情况 B: 包含 /hub 的标准结构
        hub_dir = p / "hub"
        if hub_dir.exists():
            safe_name = model_name.replace("/", "--")
            model_dir = hub_dir / f"models--{safe_name}"
            if model_dir.exists():
                snapshots = list(model_dir.glob("snapshots/*"))
                if snapshots and is_target_model(snapshots[0], model_name):
                    return True, str(p)

    # 2. 检查系统默认缓存
    default_hub = _Path.home() / ".cache" / "huggingface" / "hub"
    safe_name = model_name.replace("/", "--")
    model_folder = default_hub / f"models--{safe_name}"
    
    if model_folder.exists():
        snapshots = list(model_folder.glob("snapshots/*"))
        if snapshots and is_target_model(snapshots[0], model_name):
            return True, str(_Path.home() / ".cache" / "huggingface")

    return False, ""

# ✅【新增】清理默认缓存中的标准模型目录
def cleanup_default_hub_cache(model_name: str):
    """
    删除 Hugging Face 默认缓存中对应的标准模型目录（models--xxx）
    仅当用户指定 local_dir（即 flat 下载）时调用。
    """
    # 获取默认 hub 目录
    default_cache = os.environ.get("HF_HOME")
    if default_cache:
        hub_dir = _Path(default_cache) / "hub"
    else:
        hub_dir = _Path.home() / ".cache" / "huggingface" / "hub"
    
    if not hub_dir.exists():
        return
    
    # 转换为 models-- 格式
    safe_name = model_name.replace("/", "--")
    model_folder = hub_dir / f"models--{safe_name}"
    
    if model_folder.exists():
        try:
            shutil.rmtree(model_folder)
            print(f"🧹 已清理默认缓存中的残留模型目录: {model_folder}")
        except Exception as e:
            print(f"⚠️ 无法清理默认缓存目录 {model_folder}: {e}")

def resolve_embedding_device(config_device: str) -> str:
    """
    根据 config 中的 EMBEDDING_DEVICE 解析出实际可用的 device 字符串。
    支持 'auto', 'cpu', 'cuda', 'cuda:X'
    """
    if config_device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    
    # 用户指定了具体设备
    if config_device == "cpu":
        return "cpu"
    
    if config_device.startswith("cuda"):
        if not torch.cuda.is_available():
            print(f"⚠️ 警告: 配置要求使用 {config_device}，但 CUDA 不可用，回退到 CPU")
            return "cpu"
        
        # 检查指定的 GPU 是否存在
        if ":" in config_device:
            try:
                device_id = int(config_device.split(":")[1])
                if device_id >= torch.cuda.device_count():
                    print(f"⚠️ 警告: GPU {device_id} 不存在（共 {torch.cuda.device_count()} 块），回退到 cuda:0")
                    return "cuda:0"
            except ValueError:
                print(f"⚠️ 警告: 无效的 CUDA 设备格式 '{config_device}'，回退到 cuda:0")
                return "cuda:0"
        return config_device
    
    # 兜底
    print(f"⚠️ 未知设备配置 '{config_device}'，使用 CPU")
    return "cpu"

def safe_load_model(model_path: str, device: str):
    """安全加载模型到指定设备"""
    old_offline = os.environ.get("HF_HUB_OFFLINE", None)
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        model = SentenceTransformer(
            model_path,
            local_files_only=LOCAL_FILES_ONLY,
            trust_remote_code=TRUST_REMOTE_CODE,
            device=device  # ✅ 关键：指定设备
        )
        return model
    finally:
        if old_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = old_offline

# ✅【修改 2/2】下载后写入 model_id.txt + 自动清理默认缓存
def get_model_with_smart_cache(model_identifier: str, device: str):
    """
    加载模型：
      - 若 model_identifier 以 .gguf 结尾 → 视为 GGUF 模型（仅本地）
      - 若 model_identifier 以 'gguf:' 开头 → 解析并查找 GGUF_MODEL_REGISTRY
      - 否则 → 视为 Hugging Face 模型（可下载）
    """
    # === 新增：处理 gguf:hf_id:quant 格式 ===
    if model_identifier.startswith("gguf:"):
        try:
            # 解析格式: gguf:<hf_id>:<quant>
            parts = model_identifier[5:].split(":")
            if len(parts) != 2:
                raise ValueError("格式应为 gguf:<hf_id>:<quant>")
            hf_id, quant = parts

            print(f"🦙 查找 GGUF 模型: hf_id='{hf_id}', quant='{quant}'")

            # 加载 registry
            if not GGUF_MODEL_REGISTRY.exists():
                print(f"⚠️ GGUF 模型注册表不存在: {GGUF_MODEL_REGISTRY}")
            else:
                try:
                    registry_data = json.loads(GGUF_MODEL_REGISTRY.read_text(encoding="utf-8"))
                    candidates = registry_data.get("gguf_models", [])
                    
                    # 匹配策略：允许 hf_id 不带组织名（如 "nomic-embed-text-v1.5" 匹配 "nomic-ai/nomic-embed-text-v1.5"）
                    def matches(entry_hf_id: str, target_hf_id: str) -> bool:
                        # 完全匹配
                        if entry_hf_id == target_hf_id:
                            return True
                        # 或者 entry 是 target 的后缀（去掉组织名）
                        if target_hf_id.endswith(entry_hf_id) and "/" in target_hf_id:
                            return True
                        return False

                    for entry in candidates:
                        if (
                            matches(entry["hf_id"], hf_id) and
                            entry["quantization"] == quant and
                            _Path(entry["gguf_path"]).exists()
                        ):
                            gguf_path = entry["gguf_path"]
                            print(f"✅ 在注册表中找到匹配的 GGUF 模型: {gguf_path}")
                            return get_model_with_smart_cache(gguf_path, device=device)  # 递归调用处理 .gguf

                except Exception as e:
                    print(f"⚠️ 读取 GGUF 注册表时出错: {e}")

            print(f"❌ 未在注册表中找到匹配的 GGUF 模型 (hf_id={hf_id}, quant={quant})")
            return None

        except Exception as e:
            print(f"❌ 解析 gguf 格式失败: {e}")
            return None

    # === 情况 1: GGUF 模型（本地文件）===
    model_path = _Path(model_identifier)
    if model_path.suffix.lower() == ".gguf":
        if not LLAMA_CPP_AVAILABLE:
            print(f"❌ 跳过 GGUF 模型 '{model_identifier}'：llama-cpp-python 不可用")
            return None

        if not model_path.exists():
            print(f"⚠️ GGUF 模型文件不存在，跳过: {model_path}")
            return None

        # benchmark_embedding_models.py 第 411-425 行（修改后）
        print(f"🦙 加载 GGUF 模型：{model_path.name}")
        try:
            # ✅ 从 config 读取 GGUF 配置
            llm = Llama(
                model_path=str(model_path),
                embedding=True,
                n_ctx=GGUF_INFERENCE_CONFIG.get("n_ctx", 2048),      # ← 使用配置
                n_threads=GGUF_INFERENCE_CONFIG.get("n_threads", 8), # ← 使用配置
                verbose=False
            )
            # 封装一个兼容 SentenceTransformer.encode 的接口
            class GGUFEmbedder:
                supports_batch_size = False  # ← 新增类属性

                def __init__(self, llm_instance):
                    self.llm = llm_instance

                def encode(self, texts, show_progress_bar=False):
                    if isinstance(texts, str):
                        texts = [texts]
                    embeddings = []
                    for text in texts:
                        emb = self.llm.embed(text)
                        embeddings.append(emb)
                    return np.array(embeddings, dtype=np.float32)
            return GGUFEmbedder(llm)
        except Exception as e:
            print(f"❌ 加载 GGUF 模型失败: {e}")
            return None

    # === 情况 2: Hugging Face 模型 ===
    else:
        print(f"🤗 加载 Hugging Face 模型: {model_identifier}")
        found, cache_dir = find_model_in_any_cache(model_identifier)
        if found:
            print(f"📦 复用缓存: {model_identifier} @ {cache_dir}")
            local_model_path = _Path(cache_dir)
            if (local_model_path / "hub").exists() or "huggingface" in str(local_model_path).lower():
                safe_name = model_identifier.replace("/", "--")
                hub_dir = local_model_path / "hub" if (local_model_path / "hub").exists() else local_model_path
                model_path_hf = hub_dir / f"models--{safe_name}"
                snapshots = list(model_path_hf.glob("snapshots/*"))
                if snapshots:
                    local_model_path = snapshots[0]
            return safe_load_model(str(local_model_path), device=device)
        else:
            # 原有下载逻辑（保持不变）
            registry = load_cache_registry()
            print(f"\n🔍 模型 '{model_identifier}' 未在以下缓存中找到:")
            valid_registry = [p for p in registry if _Path(p).exists()]
            if valid_registry:
                for i, path in enumerate(valid_registry, 1):
                    print(f"  {i}. [✅] {path}")
            else:
                print("  (暂无有效注册路径)")
            print("\n💡 请选择模型下载位置:")
            print("  - 输入编号 → 使用已有路径")
            print("  - 输入绝对路径（如 D:\\my_models）→ 创建并使用该路径")
            print("  - 输入英文名称（如 rag_d）→ 在当前目录下创建子文件夹")
            print("  - 直接回车 → 使用 Hugging Face 默认缓存目录")
            choice = input("\n> ").strip()
            
            target_path = None
            
            if choice:
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(valid_registry):
                        target_path = _Path(valid_registry[idx])
                    else:
                        print("⚠️ 无效编号，将使用默认缓存")
                else:
                    try:
                        test_path = _Path(choice)
                        if test_path.is_absolute():
                            target_path = test_path.resolve()
                        elif is_safe_path_name(choice):
                            target_path = (_Path.cwd() / choice).resolve()
                        if target_path:
                            target_path.mkdir(parents=True, exist_ok=True)
                            abs_str = str(target_path)
                            current_registry = load_cache_registry()
                            normalized_registry = [str(_Path(p).resolve()) for p in current_registry]
                            if abs_str not in normalized_registry:
                                normalized_registry.append(abs_str)
                                save_cache_registry(normalized_registry)
                                print(f"✅ 已自动注册新路径: {abs_str}")
                            else:
                                print(f"ℹ️ 路径已注册: {abs_str}")
                    except Exception as e:
                        print(f"❌ 路径处理错误: {e}")
            
            if target_path:
                print(f"📥 下载模型 '{model_identifier}' 到: {target_path}")
                local_dir = snapshot_download(
                    repo_id=model_identifier,
                    local_dir=str(target_path),
                    local_dir_use_symlinks=False,
                    resume_download=True,
                    allow_patterns=SNAPSHOT_DOWNLOAD_ALLOW_PATTERNS,
                    ignore_patterns=SNAPSHOT_DOWNLOAD_IGNORE_PATTERNS,
                )
                model_id_file = _Path(local_dir) / "model_id.txt"
                if not model_id_file.exists():
                    model_id_file.write_text(model_identifier.strip(), encoding="utf-8")
                    print(f"🔖 已生成模型身份文件: {model_id_file}")
                try:
                    custom_path = _Path(target_path).resolve()
                    default_cache_root = _Path(os.environ.get("HF_HOME", _Path.home() / ".cache" / "huggingface"))
                    default_root_resolved = default_cache_root.resolve()
                    if not str(custom_path).startswith(str(default_root_resolved)):
                        cleanup_default_hub_cache(model_identifier)
                except Exception as e:
                    print(f"⚠️ 自动清理默认缓存时出错（不影响使用）: {e}")
            else:
                print(f"📥 使用 Hugging Face 默认缓存下载 '{model_identifier}'")
                local_dir = snapshot_download(repo_id=model_identifier, resume_download=True)
            
            return safe_load_model(local_dir, device=device)
    
def ask_user_for_cache_path(cache_type: str) -> Path:
    """询问用户缓存存储位置"""
    print(f"\n💡 请选择 {cache_type} 缓存位置:")
    print("  - 输入绝对路径（如 D:\\my_cache）")
    print("  - 输入相对名称（如 my_rag_cache）→ 在当前目录创建")
    print("  - 回车 → 使用默认 cache 目录")
    choice = input("> ").strip()
    if not choice:
        return CACHE_ROOT.resolve()
    
    p = Path(choice)
    if p.is_absolute():
        target = p.resolve()
    else:
        target = (Path.cwd() / p).resolve()
    
    target.mkdir(parents=True, exist_ok=True)
    return target


# 在 main 函数中，在处理 available_sources 部分添加过滤逻辑
def main():
    parser = argparse.ArgumentParser(description="多知识库 RAG 模型性能评测系统（仅采集模式）")
    parser.add_argument("--source", type=str, default=None, help="仅测试指定的知识源 ID")
    args = parser.parse_args()

    print("🚀 多知识库 RAG 模型性能评测系统（仅采集模式）\n")
    print(f"📁 结果文件将保存至: {BENCHMARK_RESULTS_FILE}")

    # ==============================
    # 🔧 根据 config.KNOWLEDGE_LOADING_MODE 决定知识源加载策略
    # ==============================
    from config import KNOWLEDGE_LOADING_MODE

    # 根据 KNOWLEDGE_LOADING_MODE 过滤可用的知识源
    available_sources = set()
    custom_sources = set()
    data_loader_sources = set()
    
    for key, config in KNOWLEDGE_SOURCES.items():
        loader_config = config.get("loader", {})
        loader_type = loader_config.get("type", "custom")
        
        if KNOWLEDGE_LOADING_MODE == "new_only":
            if loader_type == "data_loader":
                available_sources.add(key)
                data_loader_sources.add(key)
        elif KNOWLEDGE_LOADING_MODE == "old_only":
            if loader_type == "custom":
                available_sources.add(key)
                custom_sources.add(key)
        elif KNOWLEDGE_LOADING_MODE == "both":
            # 在 both 模式下，根据 loader_type 分别添加到不同的集合
            available_sources.add(key)
            if loader_type == "custom":
                custom_sources.add(key)
            elif loader_type == "data_loader":
                data_loader_sources.add(key)
        else:
            print(f"❌ 未知 KNOWLEDGE_LOADING_MODE: {KNOWLEDGE_LOADING_MODE}")
            sys.exit(1)

    use_new_loader = False
    use_old_loader = False
    load_and_chunk_all_func = None

    if KNOWLEDGE_LOADING_MODE == "new_only":
        use_new_loader = True
        print("🔄 使用 data_loader 模块（new_only 模式）...")
        try:
            from data_loader import load_and_chunk_all
            load_and_chunk_all_func = load_and_chunk_all
            
            # 检查是否有任何缓存可用，如果没有则预加载，否则跳过预加载
            has_any_cached = False
            for key in available_sources:
                if key in KNOWLEDGE_SOURCES and KNOWLEDGE_SOURCES[key].get("loader", {}).get("type") == "data_loader":
                    chunking_config = KNOWLEDGE_SOURCES[key].get("chunking", {"strategy": "fixed"})
                    chunk_key = get_chunk_key(key, chunking_config)
                    
                    mapping = load_mapping_file()
                    chunk_meta = mapping["chunks"].get(chunk_key)
                    
                    if REUSE_CHUNK_CACHE and chunk_meta and Path(chunk_meta["chunk_dir"]).exists():
                        has_any_cached = True
                        break
            
            if not has_any_cached:
                # 没有任何缓存，预加载所有 data_loader 类型的数据
                print("📚 开始预加载所有 data_loader 类型的知识源数据...")
                all_chunks_dict = load_and_chunk_all()  # 执行加载以获取 all_chunks_dict
                print("✅ data_loader 模块加载成功（将在 Stage 1 按需调用）")
                supported_by_loader = set(all_chunks_dict.keys())
                print(f"✅ data_loader 支持的知识源: {sorted(supported_by_loader)}")
                # 限制为实际支持的数据源
                available_sources = available_sources.intersection(supported_by_loader)
                if not available_sources:
                    print("⚠️ 警告: data_loader 未返回任何有效知识源！将跳过所有测试。")
            else:
                # 有缓存可用，直接验证模块
                print("✅ data_loader 模块加载成功（将在 Stage 1 按需调用）")
                # 验证模块功能
                sample_result = load_and_chunk_all(source_filter=list(available_sources)[0] if available_sources else "")
                supported_by_loader = set(sample_result.keys()) if sample_result else set()
                print(f"✅ data_loader 模块功能正常")
        
        except Exception as e:
            print(f"❌ data_loader 加载失败（new_only 模式要求必须成功）: {e}")
            sys.exit(1)

    elif KNOWLEDGE_LOADING_MODE == "old_only":
        use_old_loader = True
        print("📦 使用内置知识库加载器（old_only 模式）")
        print(f"✅ custom_loader 支持的知识源: {sorted(custom_sources)}")

    elif KNOWLEDGE_LOADING_MODE == "both":
        use_new_loader = True
        use_old_loader = True
        print("🔀 启用双模式（both）：优先使用 data_loader，缺失项回退到内置加载器")
        
        # 检查是否有 --source 参数
        if args.source and args.source in available_sources:
            # 如果指定了单个 source，只初始化加载器而不预加载所有数据
            print("🔄 按需加载模式：仅在 Stage 1 处理指定知识源")
            try:
                from data_loader import load_and_chunk_all
                load_and_chunk_all_func = load_and_chunk_all
                
                # 确定指定 source 的类型并打印支持信息
                source_info = KNOWLEDGE_SOURCES[args.source]
                loader_config = source_info.get("loader", {})
                loader_type = loader_config.get("type", "custom")
                
                if loader_type == "data_loader":
                    print(f"✅ data_loader 支持的知识源: ['{args.source}']")
                    print(f"✅ custom_loader 支持的知识源: []")
                elif loader_type == "custom":
                    print(f"✅ data_loader 支持的知识源: []")
                    print(f"✅ custom_loader 支持的知识源: ['{args.source}']")
                
            except Exception as e:
                print(f"⚠️ data_loader 初始化失败: {e}")
                load_and_chunk_all_func = None
                # 检查指定的源是否是 custom 类型
                source_info = KNOWLEDGE_SOURCES[args.source]
                loader_config = source_info.get("loader", {})
                loader_type = loader_config.get("type", "custom")
                if loader_type == "custom":
                    print(f"✅ custom_loader 支持的知识源: ['{args.source}']")
        else:
            # 没有指定 source，只初始化加载器但不预加载数据（Stage 1 会按需处理）
            try:
                from data_loader import load_and_chunk_all
                load_and_chunk_all_func = load_and_chunk_all
                
                # 只验证模块可用性，不预加载所有数据
                print("✅ data_loader 模块加载成功（将在 Stage 1 按需调用）")
                
                # 打印各加载器支持的知识源
                print(f"✅ data_loader 支持的知识源: {sorted(data_loader_sources)}")
                print(f"✅ custom_loader 支持的知识源: {sorted(custom_sources)}")
                
            except Exception as e:
                print(f"⚠️ data_loader 加载失败，but 模式降级为 old_only: {e}")
                # 修正：将 use_new_loader 设为 False 并更新可用源
                use_new_loader = False
                load_and_chunk_all_func = None
                # 降级后只保留 custom 类型的源
                available_sources = custom_sources
                print(f"✅ custom_loader 支持的知识源: {sorted(custom_sources)}")
    else:
        print(f"❌ 未知 KNOWLEDGE_LOADING_MODE: {KNOWLEDGE_LOADING_MODE}")
        sys.exit(1)

    # 处理 --source 参数
    if args.source:
        if args.source not in available_sources:
            print(f"❌ 错误: '{args.source}' 不在当前模式支持的知识源中。")
            print(f"   支持列表: {sorted(available_sources)}")
            
            # 显示详细的可用性信息
            source_info = KNOWLEDGE_SOURCES.get(args.source)
            if source_info:
                loader_config = source_info.get("loader", {})
                loader_type = loader_config.get("type", "custom")
                print(f"   - '{args.source}' 的加载器类型: {loader_type}")
                
                if KNOWLEDGE_LOADING_MODE == "new_only" and loader_type != "data_loader":
                    print(f"   - 当前模式: {KNOWLEDGE_LOADING_MODE}，仅支持 data_loader 类型")
                elif KNOWLEDGE_LOADING_MODE == "old_only" and loader_type == "data_loader":
                    print(f"   - 当前模式: {KNOWLEDGE_LOADING_MODE}，不支持 data_loader 类型")
                elif KNOWLEDGE_LOADING_MODE == "both":
                    print(f"   - 当前模式: {KNOWLEDGE_LOADING_MODE}，但可能因缓存或其他原因不可用")
            else:
                print(f"   - '{args.source}' 未在 KNOWLEDGE_SOURCES 中找到")
            
            sys.exit(1)
        selected_sources = {args.source: KNOWLEDGE_SOURCES[args.source]}
        print(f"🎯 仅测试知识源: {args.source}")
    else:
        # 在 both 模式下如果降级了，确保只选择 custom 类型的源
        if KNOWLEDGE_LOADING_MODE == "both" and not use_new_loader:
            # 只选择 custom 类型的源
            filtered_sources = {}
            for key in available_sources:
                if key in KNOWLEDGE_SOURCES:
                    loader_config = KNOWLEDGE_SOURCES[key].get("loader", {})
                    loader_type = loader_config.get("type", "custom")
                    if loader_type == "custom":
                        filtered_sources[key] = KNOWLEDGE_SOURCES[key]
            selected_sources = filtered_sources
        else:
            selected_sources = {k: KNOWLEDGE_SOURCES[k] for k in available_sources}
        
        if selected_sources:
            print(f"📋 将测试以下知识源: {sorted(selected_sources.keys())}")
        else:
            print("🛑 无可测试的知识源，程序退出。")
            return

    # === 设备解析与提示 ===
    resolved_device = resolve_embedding_device(EMBEDDING_DEVICE)
    if resolved_device == "cpu":
        print("🖥️  Embedding 设备: CPU")
    else:
        try:
            gpu_idx = int(resolved_device.split(":")[-1]) if ":" in resolved_device else 0
            gpu_name = torch.cuda.get_device_name(gpu_idx)
            print(f"🖥️  Embedding 设备: {resolved_device} ({gpu_name})")
        except Exception:
            print(f"🖥️  Embedding 设备: {resolved_device} (GPU 名称获取失败)")
    print("-" * 60)

    results = {}

    # ===========================================
    # STAGE 1: 一次性生成所有需要的 chunks（与模型无关！）
    # ===========================================
    print("🧩 阶段 1: 生成或加载所有知识源的 chunks...")
    all_chunks_data = {}  # {source_key: {"chunks": [...], "stats": {...}, "chunk_dir": Path or None}}

    # 在 both 模式下，如果 use_new_loader 为 True 且有 data_loader 类型的源，
    # 检查是否有任何缓存可用，如果没有则预加载这些源的数据
    preloaded_chunks = {}
    if KNOWLEDGE_LOADING_MODE == "both" and use_new_loader:
        # 检查 data_loader 类型的源是否有缓存
        dl_sources = [k for k in selected_sources.keys() 
                     if selected_sources[k].get("loader", {}).get("type") == "data_loader"]
        has_dl_cached = False
        for key in dl_sources:
            chunking_config = selected_sources[key].get("chunking", {"strategy": "fixed"})
            chunk_key = get_chunk_key(key, chunking_config)
            
            mapping = load_mapping_file()
            chunk_meta = mapping["chunks"].get(chunk_key)
            
            if REUSE_CHUNK_CACHE and chunk_meta and Path(chunk_meta["chunk_dir"]).exists():
                has_dl_cached = True
                break
        
        if not has_dl_cached and dl_sources:
            # 只预加载 data_loader 类型的源
            print(f"📚 预加载 {len(dl_sources)} 个 data_loader 类型的知识源数据...")
            preloaded_chunks = load_and_chunk_all_func(source_filter=None)  # 加载所有
        else:
            print("✅ data_loader 类型的源有缓存可用，跳过预加载")

    # 如果是 new_only 模式，预先加载所有数据（仅当没有缓存时）
    if KNOWLEDGE_LOADING_MODE == "new_only":
        # 检查是否有任何缓存，如果没有才预加载
        has_any_cached = False
        for key in selected_sources.keys():
            chunking_config = selected_sources[key].get("chunking", {"strategy": "fixed"})
            chunk_key = get_chunk_key(key, chunking_config)
            
            mapping = load_mapping_file()
            chunk_meta = mapping["chunks"].get(chunk_key)
            
            if REUSE_CHUNK_CACHE and chunk_meta and Path(chunk_meta["chunk_dir"]).exists():
                has_any_cached = True
                break
        
        if not has_any_cached:
            print("📚 预加载所有知识源数据（无可用缓存）...")
            preloaded_chunks = load_and_chunk_all_func()  # 一次性加载所有

    for key, info in selected_sources.items():
        print(f"\n📄 处理知识源 [{key}] ...")
        chunking_config = info.get("chunking", {"strategy": "fixed"})
        chunk_key = get_chunk_key(key, chunking_config)

        mapping = load_mapping_file()
        chunk_meta = mapping["chunks"].get(chunk_key)

        if REUSE_CHUNK_CACHE and chunk_meta and Path(chunk_meta["chunk_dir"]).exists():
            print(f"  📦 复用 chunk 缓存: {chunk_meta['chunk_dir']}")
            chunks_file = Path(chunk_meta["chunk_dir"]) / "chunks.json"
            with open(chunks_file, "r", encoding="utf-8") as f:
                chunks = json.load(f)
            chunk_dir = Path(chunk_meta["chunk_dir"])
        else:
            # === 生成 chunks（不依赖模型！）===
            chunks = []
            used_new_loader = False

            # === Step 1: 尝试使用 data_loader（如果启用）===
            if use_new_loader and load_and_chunk_all_func is not None:
                # 检查是否已有预加载数据
                if key in preloaded_chunks:
                    chunk_list = preloaded_chunks[key]
                    chunks = [ch.text for ch in chunk_list]
                    if chunks:
                        used_new_loader = True
                        print(f"  ✅ data_loader 成功复用预加载的 {len(chunks)} 个 chunks")
                else:
                    try:
                        print("  🔄 尝试使用 data_loader 生成 chunks...")
                        all_chunks_dict = load_and_chunk_all_func(source_filter=key)
                        chunk_list = all_chunks_dict.get(key, [])
                        chunks = [ch.text for ch in chunk_list]
                        if chunks:
                            used_new_loader = True
                            print(f"  ✅ data_loader 成功生成 {len(chunks)} 个 chunks")
                        else:
                            print(f"  ⚠️ data_loader 返回空 chunks for [{key}]")
                    except Exception as e:
                        print(f"  ⚠️ data_loader 处理 {key} 失败: {e}")
                        chunks = []  # 确保清空

            # === Step 2: 决定是否 fallback 到旧加载器 ===
            should_fallback = False
            if not chunks:
                if KNOWLEDGE_LOADING_MODE == "new_only":
                    print(f"  ❌ 跳过 [{key}]：new_only 模式下 data_loader 未提供有效 chunks")
                    # chunks 保持为空，后续会跳过 embedding
                elif use_old_loader:
                    should_fallback = True
                else:
                    print(f"  ⚠️ 无可选加载器处理 [{key}]")

            if should_fallback:
                
                print("  📦 使用内置解析器（支持文件/目录）...")
                project_root = _Path(__file__).parent.parent
                full_path = (project_root / info["path"]).resolve()

                # 构造 loader 配置（从 knowledge source 配置中提取）
                loader_config = {
                    "type": "custom",
                    "format": info.get("format", "plain_text")
                }

                chunks = []

                if full_path.is_file():
                    # 单个文件：直接加载
                    try:
                        texts = load_by_config(loader_config, str(full_path))
                        chunks.extend(texts)
                    except Exception as e:
                        print(f"    ⚠️ 加载文件失败 {full_path}: {e}")
                        chunks = [""]

                elif full_path.is_dir():
                    # 目录：递归查找支持的文件
                    print(f"    📁 递归扫描目录: {full_path}")
                    supported_exts = {
                        "txt_qa": [".txt"],
                        "plain_text": [".txt", ".md"],
                        "html": [".html", ".htm"]
                    }
                    fmt = loader_config["format"]
                    exts = supported_exts.get(fmt, [".txt", ".md", ".html", ".htm"])

                    files_found = []
                    for ext in exts:
                        files_found.extend(full_path.rglob(f"*{ext}"))

                    if not files_found:
                        print(f"    ⚠️ 目录中未找到匹配格式 ({fmt}) 的文件")
                        chunks = [""]

                    for file_path in sorted(files_found):
                        try:
                            print(f"      ➤ 加载 {file_path.name} ...")
                            texts = load_by_config(loader_config, str(file_path))
                            chunks.extend(texts)
                        except Exception as e:
                            print(f"        ⚠️ 跳过文件 {file_path.name}: {e}")
                            continue

                else:
                    print(f"    ❌ 路径既非文件也非目录: {full_path}")
                    chunks = [""]

                # 去重（可选）
                if info.get("chunking", {}).get("enable_dedup", False):
                    unique_chunks = []
                    seen = set()
                    for ch in chunks:
                        if ch not in seen:
                            unique_chunks.append(ch)
                            seen.add(ch)
                    chunks = unique_chunks

                if not chunks or (len(chunks) == 1 and chunks[0] == ""):
                    chunks = [""]
                    print(f"    ⚠️ 最终 chunks 为空，使用占位符")
                else:
                    print(f"    ✅ 成功加载 {len(chunks)} 个文本片段")

            if not chunks:
                chunks = [""]
                print(f"  ⚠️ 警告: 无法为 {key} 生成任何有效 chunk")

            # === 保存 chunks（仅当有效）===
            if chunks and not (len(chunks) == 1 and chunks[0] == ""):
                # 从 mapping 中提取所有已存在的 chunk 目录作为"有效路径"
                existing_chunk_dirs = [
                    meta["chunk_dir"] for ck, meta in mapping["chunks"].items()
                    if Path(meta["chunk_dir"]).exists()
                ]
                valid_paths = list(set(existing_chunk_dirs))  # 去重

                print(f"\n💡 请选择 chunk 缓存存储位置（用于保存 {len(chunks)} 个 chunks）:")
                if valid_paths:
                    print("  已存在的 chunk 缓存路径:")
                    for i, path in enumerate(valid_paths, 1):
                        print(f"    {i}. [✅] {path}")
                else:
                    print("  (暂无已存在的 chunk 缓存路径)")

                print("  - 输入编号 → 使用该路径")
                print("  - 输入绝对路径（如 D:\\my_chunks）")
                print("  - 输入相对名称（如 my_chunks）→ 在当前目录创建")
                print("  - 直接回车 → 使用默认 cache/chunks 目录")
                choice = input("> ").strip()

                target_path = None
                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(valid_paths):
                        target_path = _Path(valid_paths[idx])
                    else:
                        print("⚠️ 无效编号")
                elif choice:
                    try:
                        p = _Path(choice)
                        if p.is_absolute():
                            target_path = p.resolve()
                        elif is_safe_path_name(choice):
                            target_path = (_Path.cwd() / "cache" / "chunks" / choice).resolve()
                        if target_path:
                            target_path.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        print(f"❌ 路径错误: {e}")

                if target_path is None:
                    target_path = (_Path.cwd() / "cache" / "chunks").resolve()
                    target_path.mkdir(parents=True, exist_ok=True)
                    print(f"📁 使用默认 chunk 缓存目录: {target_path}")

                chunk_dir = target_path / f"chunks_{chunk_key}"
                chunk_dir.mkdir(parents=True, exist_ok=True)
                chunks_file = chunk_dir / "chunks.json"
                with open(chunks_file, "w", encoding="utf-8") as f:
                    json.dump(chunks, f, ensure_ascii=False, indent=2)

                # 注册到 mapping
                new_chunk_meta = {
                    "source_id": key,
                    "chunking_strategy": chunking_config["strategy"],
                    "chunking_params_hash": chunk_key.split("__")[-1],
                    "chunk_dir": str(chunk_dir.resolve()),
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")
                }
                mapping = load_mapping_file()
                mapping["chunks"][chunk_key] = new_chunk_meta
                save_mapping_file(mapping)
                print(f"✅ 已注册 chunk 缓存: {chunk_dir}")
            else:
                chunk_dir = None
                print(f"  ⚠️ 跳过缓存：chunks 无效")

        # 计算 stats
        if chunks and not (len(chunks) == 1 and chunks[0] == ""):
            lengths = [len(t) for t in chunks]
            chunk_stats = {
                "chunk_count": len(chunks),
                "avg_chunk_length": sum(lengths) / len(lengths),
                "min_chunk_length": min(lengths),
                "max_chunk_length": max(lengths),
                "chunking_strategy": chunking_config["strategy"],
            }
        else:
            chunks = []
            chunk_stats = {
                "chunk_count": 0,
                "avg_chunk_length": 0,
                "min_chunk_length": 0,
                "max_chunk_length": 0,
                "chunking_strategy": "empty",
            }

        all_chunks_data[key] = {
            "chunks": chunks,
            "stats": chunk_stats,
            "chunk_dir": chunk_dir,
            "chunk_key": chunk_key
        }

    # ===========================================
    # STAGE 2: 遍历每个模型
    # ===========================================
    results = {}
    for model_name in MODELS:
        print(f"\n🧠 加载模型: {model_name}")
        model = get_model_with_smart_cache(model_name, device=resolved_device)
        
        if model is None:
            print(f"⏭️  跳过模型: {model_name}")
            continue  # 直接跳过后续测试

        # 🔥 Warm-up（现在才做！合理）
        try:
            _ = model.encode("Warm-up sentence.", show_progress_bar=False)
            print("🔥 模型预热完成")
        except Exception as e:
            print(f"⚠️ 预热失败（不影响后续）: {e}")

        results[model_name] = {}

        for key, info in selected_sources.items():
            chunk_data = all_chunks_data[key]
            chunks = chunk_data["chunks"]
            chunk_stats = chunk_data["stats"]
            chunk_key = chunk_data["chunk_key"]
            chunk_dir = chunk_data["chunk_dir"]

            if not chunks:
                print(f"⚠️ 跳过测试 [{key}]：chunks 为空")
                results[model_name][key] = {
                    "per_query_results": [],
                    "avg_max_similarity": 0.0,
                    "avg_latency_ms_over_queries": 0.0,
                    "query_count": 0,
                    "success": False,
                    **chunk_stats
                }
                continue

            print(f"\n🔍 测试 [{key}] 使用模型: {model_name}")

            # === 获取 queries ===
            lang = info["lang"]
            queries = TEST_QUERIES.get(key, TEST_QUERIES.get(f"default_{lang}", ["How to use this?"]))

            # === 加载或生成 embeddings ===
            embed_key = get_embed_key(chunk_key, model_name)
            mapping = load_mapping_file()
            embed_meta = mapping["embeddings"].get(embed_key)

            if REUSE_EMBED_CACHE and embed_meta and Path(embed_meta["embed_dir"]).exists():
                print(f"📦 复用 embedding 缓存: {embed_meta['embed_dir']}")
                doc_embs = np.load(Path(embed_meta["embed_dir"]) / "embeddings.npy")
            else:
                # 确定 embedding 缓存根目录（优先用全局 embedding 目录，而不是 chunk 目录）
                embed_root = None
                
                # 从 mapping 中提取已有 embedding 目录
                existing_embed_dirs = [
                    meta["embed_dir"] for ek, meta in mapping["embeddings"].items()
                    if Path(meta["embed_dir"]).exists()
                ]
                valid_paths = list(set([Path(p).parent for p in existing_embed_dirs]))  # 取父目录

                print(f"\n💡 请选择 embedding 缓存位置（{len(chunks)} chunks）:")
                if valid_paths:
                    print("  已存在的 embedding 缓存路径:")
                    for i, path in enumerate(valid_paths, 1):
                        print(f"    {i}. [✅] {path}")
                else:
                    print("  (暂无已存在的 embedding 缓存路径)")
                print("  - 输入编号 / 路径 / 回车（默认 cache/embeddings）")
                choice = input("> ").strip()

                if choice.isdigit():
                    idx = int(choice) - 1
                    if 0 <= idx < len(valid_paths):
                        embed_root = valid_paths[idx]
                elif choice:
                    try:
                        p = _Path(choice)
                        if p.is_absolute():
                            embed_root = p.resolve()
                        elif is_safe_path_name(choice):
                            embed_root = (_Path.cwd() / "cache" / "embeddings" / choice).resolve()
                        if embed_root:
                            embed_root.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        print(f"❌ 路径错误: {e}")

                if embed_root is None:
                    embed_root = (_Path.cwd() / "cache" / "embeddings").resolve()
                    embed_root.mkdir(parents=True, exist_ok=True)
                    print(f"📁 使用默认 embedding 缓存目录: {embed_root}")

                # 生成 embedding
                print(f"⚙️  生成 embedding（{len(chunks)} chunks）...")

                # 判断是否支持 batch_size（GGUF 模型不支持）
                if hasattr(model, 'encode') and callable(model.encode):
                    # 检查是否是 GGUF 封装模型（通过是否有 llm 属性或自定义标记）
                    is_gguf_model = hasattr(model, 'llm') or (
                        hasattr(model, '__class__') and 
                        model.__class__.__name__ == 'GGUFEmbedder'
                    )
                    
                    if is_gguf_model:
                        # GGUF 模型：不传 batch_size，手动分批（可选）或直接全量
                        doc_embs = model.encode(chunks, show_progress_bar=True)
                    else:
                        # SentenceTransformer 等原生模型：使用 batch_size
                        # 智能调用 encode
                        encode_kwargs = {"show_progress_bar": True}
                        if getattr(model, 'supports_batch_size', True):  # 默认 True（兼容 SentenceTransformer）
                            encode_kwargs["batch_size"] = 32

                        doc_embs = model.encode(chunks, **encode_kwargs)
                else:
                    raise RuntimeError(f"模型 {model_name} 不支持 encode 方法")

                # 保存
                embed_dir = embed_root / f"embeddings_{embed_key}"
                embed_dir.mkdir(parents=True, exist_ok=True)
                embed_file = embed_dir / "embeddings.npy"
                np.save(embed_file, doc_embs)

                # 注册
                new_embed_meta = {
                    "chunk_key": chunk_key,
                    "model_name": model_name,
                    "embed_dir": str(embed_dir.resolve()),
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "chunk_count": len(chunks)
                }
                mapping = load_mapping_file()
                mapping["embeddings"][embed_key] = new_embed_meta
                save_mapping_file(mapping)
                print(f"✅ 已注册 embedding 缓存: {embed_dir}")

            # === Query 测试（保持不变）===
            query_results = []
            for q_idx, query in enumerate(queries):
                print(f"  ➤ Query {q_idx+1}/{len(queries)}: {query[:50]}...")

                if WARMUP_ENCODE_RUNS > 0:
                    for _ in range(WARMUP_ENCODE_RUNS):
                        _ = model.encode(query, show_progress_bar=False)

                latencies = []
                final_query_emb = None
                for i in range(EMBEDDING_BENCHMARK_ENCODE_RUNS):
                    start = time.perf_counter()
                    q_emb = model.encode(query, show_progress_bar=False)
                    lat = (time.perf_counter() - start) * 1000
                    latencies.append(lat)
                    if i == EMBEDDING_BENCHMARK_ENCODE_RUNS - 1:
                        final_query_emb = q_emb

                avg_latency = sum(latencies) / len(latencies)
                latency_std = statistics.stdev(latencies) if len(latencies) > 1 else 0.0

                if len(doc_embs) > 0 and final_query_emb is not None:
                    # 确保 query 向量是一维的
                    if final_query_emb.ndim == 2:
                        final_query_emb = final_query_emb.squeeze()  # (1,768) → (768,)

                    final_query_emb = final_query_emb.reshape(-1)

                    sims = np.dot(doc_embs, final_query_emb) / (
                        np.linalg.norm(doc_embs, axis=1) * np.linalg.norm(final_query_emb)
                    )
                    max_sim = float(np.max(sims))
                    top_chunk_idx = int(np.argmax(sims))
                else:
                    max_sim = 0.0
                    top_chunk_idx = -1

                print(f"    ✅ MaxSim: {max_sim:.3f} | Latency: {avg_latency:.1f}ms ± {latency_std:.1f}ms")

                query_results.append({
                    "query": query,
                    "avg_latency_ms": avg_latency,
                    "latency_std_ms": latency_std,
                    "latency_runs_ms": latencies,
                    "max_similarity": max_sim,
                    "top_chunk_index": top_chunk_idx,
                    "success": True
                })

            avg_max_sim = np.mean([qr["max_similarity"] for qr in query_results])
            avg_latency_over_queries = np.mean([qr["avg_latency_ms"] for qr in query_results])

            results[model_name][key] = {
                "per_query_results": query_results,
                "avg_max_similarity": float(avg_max_sim),
                "avg_latency_ms_over_queries": float(avg_latency_over_queries),
                "query_count": len(queries),
                "success": True,
                **chunk_stats
            }

            print(f"📈 [{key}] 平均 MaxSim: {avg_max_sim:.3f} | 平均延迟: {avg_latency_over_queries:.1f}ms")

    # ===========================================
    # 保存最终结果
    # ===========================================
    BENCHMARK_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BENCHMARK_RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 原始评测完成！结果已保存至: {BENCHMARK_RESULTS_FILE}")

if __name__ == "__main__":
    main()