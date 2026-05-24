"""
通用工具函数
"""

import numpy as np


def l2_normalize(emb: np.ndarray) -> np.ndarray:
    """
    对 embedding 向量进行 L2 归一化。
    
    支持输入形状：
      - (D,)        → 标准 1D 向量
      - (1, D)      → batch_size=1 的 2D 向量（自动 squeeze）
    
    输出：归一化后的 1D 向量，L2 范数为 1.0（若输入非零）
    
    Args:
        emb (np.ndarray): 输入 embedding 向量
        
    Returns:
        np.ndarray: L2 归一化后的向量（shape: (D,)）
        
    Raises:
        ValueError: 如果输入不是 1D 或 (1, D) 的 2D 向量
    """
    if emb.ndim == 2:
        if emb.shape[0] == 1:
            emb = emb.squeeze(0)
        else:
            raise ValueError(f"Expected batch size 1 for 2D input, got shape {emb.shape}")
    elif emb.ndim != 1:
        raise ValueError(f"Expected 1D or (1, D) input, got shape {emb.shape}")

    norm = np.linalg.norm(emb, ord=2)
    if norm == 0.0:
        return emb.copy()  # 避免除零，返回副本保持一致性
    return emb / norm