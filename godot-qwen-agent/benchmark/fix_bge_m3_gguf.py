import sys
from pathlib import Path
from gguf import GGUFWriter, GGUFReader
import numpy as np

def main():
    if len(sys.argv) != 2:
        print("用法: python fix_bge_m3_gguf.py <model.f16.gguf>")
        return

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"❌ 文件不存在: {input_path}")
        return

    output_path = input_path.with_name(input_path.stem + "_fixed.gguf")
    print(f"正在读取: {input_path}")

    reader = GGUFReader(str(input_path))
    writer = GGUFWriter(str(output_path), arch="bert")

    # 添加关键 metadata
    writer.add_uint32("bert.pooling_type", 2)
    writer.add_bool("tokenizer.ggml.output_normalization", True)

    # 添加所有张量，并确保数据是可写的 numpy 数组
    for tensor in reader.tensors:
        data = np.array(tensor.data, copy=True)  # ⭐ 关键：强制复制
        writer.add_tensor(tensor.name, data)

    writer.write_header_to_file()
    writer.write_tensors_to_file()
    writer.close()

    print(f"\n✅ 修复成功！已保存至:\n   {output_path}")

if __name__ == "__main__":
    main()