# benchmark/convert_to_gguf.py (支持跳过量化)

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import tempfile

try:
    import config
except ImportError:
    print("❌ 错误: 无法导入 config.py", file=sys.stderr)
    sys.exit(1)

def main():
    script_dir = Path(__file__).parent.resolve()
    cache_registry_file = script_dir / "cache_registry.json"
    gguf_registry_file = script_dir / "gguf_model_registry.json"

    # === 加载 cache_registry.json ===
    if not cache_registry_file.exists():
        print(f"❌ 未找到 cache_registry.json", file=sys.stderr)
        sys.exit(1)
    try:
        with open(cache_registry_file, 'r', encoding='utf-8') as f:
            root_dirs = json.load(f)
        if not isinstance(root_dirs, list):
            raise ValueError("必须是数组")
    except Exception as e:
        print(f"❌ 加载 cache_registry.json 失败: {e}", file=sys.stderr)
        sys.exit(1)

    # === 扫描模型 ===
    valid_models = []
    for root_dir_str in root_dirs:
        root_path = Path(root_dir_str)
        if not root_path.exists():
            continue
        model_id_file = root_path / "model_id.txt"
        if not model_id_file.exists():
            continue
        try:
            with open(model_id_file, 'r', encoding='utf-8') as f:
                hf_id = f.read().strip()
            if hf_id:
                valid_models.append({"local_path": str(root_path), "hf_id": hf_id})
        except:
            continue

    if not valid_models:
        print("❌ 未找到有效模型", file=sys.stderr)
        sys.exit(1)

    # === 用户选择 ===
    print("\n🔍 发现以下可用模型:")
    for i, m in enumerate(valid_models, 1):
        print(f"  [{i}] {m['hf_id']}  (路径: {m['local_path']})")

    idx = -1
    while not (0 <= idx < len(valid_models)):
        try:
            idx = int(input(f"\n请选择模型编号 (1-{len(valid_models)}): ").strip()) - 1
        except ValueError:
            pass

    selected_model = valid_models[idx]

    # === 读取配置 ===
    try:
        llama_cpp_path = Path(config.LLAMA_CPP_PATH).resolve()
        quantize_exe_path = Path(config.QUANTIZE_EXE_PATH).resolve()
        quant_type = config.QUANTIZATION_TYPE
        skip_quantize = getattr(config, "SKIP_QUANTIZE", False)  # 默认不跳过
    except AttributeError as e:
        print(f"❌ config.py 缺少字段: {e}", file=sys.stderr)
        sys.exit(1)

    # === 确定输出路径 ===
    if skip_quantize:
        # 跳过量化 → 输出 f16 模型
        default_name = f"{selected_model['hf_id'].replace('/', '-')}.f16.gguf"
    else:
        # 正常量化 → 带量化后缀
        default_name = f"{selected_model['hf_id'].replace('/', '-')}.{quant_type}.gguf"

    while True:
        out_path = input(f"\n请输入 GGUF 输出文件路径 (默认: ./{default_name}): ").strip()
        if not out_path:
            out_path = f"./{default_name}"
        output_path = Path(out_path).resolve()
        if output_path.suffix.lower() != '.gguf':
            print("⚠️ 路径必须以 .gguf 结尾！")
            continue
        break

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # === 工具路径 ===
    convert_script = llama_cpp_path / "convert_hf_to_gguf.py"
    quantize_exe = quantize_exe_path / ("llama-quantize.exe" if sys.platform == "win32" else "quantize")

    if not convert_script.exists():
        print(f"❌ 找不到 convert_hf_to_gguf.py: {convert_script}", file=sys.stderr)
        sys.exit(1)
    if not skip_quantize and not quantize_exe.exists():
        print(f"❌ 找不到 quantize 工具: {quantize_exe}", file=sys.stderr)
        print("请先在 llama.cpp 目录运行: make quantize (Linux/macOS) 或 build quantize.vcxproj (Windows)")
        sys.exit(1)

    # === 第一步：HF → GGUF (f16) ===
    print(f"\n🔄 步骤 1/2: 转换为 GGUF 格式 (f16)...")

    model_input_path = str(Path(selected_model['local_path']).resolve()).replace('\\', '/')
    temp_f16 = output_path  # 如果跳过量化，就直接写到最终路径

    if not skip_quantize:
        # 使用临时路径
        temp_f16 = Path(tempfile.mkdtemp()) / "temp_model.f16.gguf"

    cmd1 = [
        sys.executable,
        str(convert_script),
        "--outfile", str(temp_f16),
        "--outtype", "f16",
        model_input_path
    ]

    try:
        print(f"执行: {' '.join(cmd1)}")
        result1 = subprocess.run(cmd1, check=True, text=True, capture_output=True)
        print("✅ 步骤 1 完成")
    except subprocess.CalledProcessError as e:
        print(f"❌ 步骤 1 失败: {e.returncode}", file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)

    # === 第二步：量化（如果需要）===
    if skip_quantize:
        print(f"\n⏭️  跳过量化（SKIP_QUANTIZE=True）")
        final_path = temp_f16
    else:
        print(f"\n🔄 步骤 2/2: 量化为 {quant_type}...")
        cmd2 = [
            str(quantize_exe),
            str(temp_f16),
            str(output_path),
            quant_type
        ]
        try:
            print(f"执行: {' '.join(cmd2)}")
            result2 = subprocess.run(cmd2, check=True, text=True, capture_output=True)
            print("✅ 步骤 2 完成")
        except subprocess.CalledProcessError as e:
            print(f"❌ 量化失败: {e.returncode}", file=sys.stderr)
            if e.stderr:
                print(e.stderr, file=sys.stderr)
            sys.exit(1)
        final_path = output_path

    # === 更新 registry ===
    gguf_entry = {
        "hf_id": selected_model["hf_id"],
        "local_hf_path": selected_model["local_path"],
        "gguf_path": str(final_path),
        "quantization": "f16" if skip_quantize else quant_type,
        "created_at": datetime.now().isoformat()
    }

    registry = {"gguf_models": []}
    if gguf_registry_file.exists():
        try:
            with open(gguf_registry_file, 'r', encoding='utf-8') as f:
                registry = json.load(f)
        except:
            pass
    registry["gguf_models"].append(gguf_entry)

    with open(gguf_registry_file, 'w', encoding='utf-8') as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    print(f"\n🎉 转换完成! GGUF 模型已保存至:\n   {final_path}")

if __name__ == "__main__":
    main()