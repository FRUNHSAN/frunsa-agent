# report_generator.py
import sys
import json
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Optional, List, Dict, Tuple
import pandas as pd

# ==============================
# 设置中文字体支持 - 必须在导入matplotlib后立即设置
# ==============================
import matplotlib.font_manager as fm

# 全局变量用于跟踪是否已经设置过字体
_font_setup_done = False

def setup_chinese_font(verbose=True):
    """
    设置中文字体支持，并尝试通过刷新字体缓存和渲染虚拟图形来确保生效.

    Args:
        verbose (bool): 是否输出详细信息，默认为True
    """
    global _font_setup_done

    if _font_setup_done:
        return  # 如果已经设置过，直接返回

    # 常见的中文字体列表（按优先级排序）
    chinese_fonts = [
        'Microsoft YaHei',      # Windows 微软雅黑
        'SimHei',               # Windows 黑体
        'WenQuanYi Micro Hei',  # Linux 文泉驿微米黑
        'DejaVu Sans',          # 跨平台字体
        'Arial Unicode MS',     # macOS Arial Unicode
        'STSong',               # 思源宋体
        'STHeiti',              # 思源黑体
    ]

    available_font = None
    all_fonts = set([f.name for f in fm.fontManager.ttflist])

    for font in chinese_fonts:
        if font in all_fonts:
            available_font = font
            break

    if available_font:
        # 强制设置全局字体，确保中文字体优先
        plt.rcParams['font.sans-serif'] = [available_font, 'DejaVu Sans', 'SimHei', 'Microsoft YaHei UI']
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号

        if verbose:
            print(f"✅ 发现并使用字体: {available_font}")
    else:
        if verbose:
            print("⚠️ 未找到合适的中文字体，可能仍会出现字符显示问题")
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'

    # --- 🔥 强制刷新字体缓存并生效 ---
    # 1. 尝试重建字体管理器 (注意：这是私有函数，使用需谨慎)
    try:
        fm._rebuild()
    except AttributeError:
        print("⚠️ _rebuild not found in font_manager, skipping.")
    # 2. 再次进行虚拟渲染以确保字体应用
    fig, ax = plt.subplots(figsize=(0.1, 0.1))  # 使用极小的图形尺寸
    ax.text(0, 0, "测试中文", fontsize=1) # 绘制一个包含中文的文本
    fig.canvas.draw() # 执行绘制，这会加载字体
    plt.close(fig) # 关闭并销毁图形
    # --- end 刷新并生效 ---

    _font_setup_done = True

# 立即设置中文字体
setup_chinese_font()

# ==============================
# 🔁 兼容相对导入与直接运行
# ==============================
try:
    from .config import BENCHMARK_RESULTS_FILE, OUTPUT_DIR, REPORT_CONFIG
except ImportError:
    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from benchmark.config import BENCHMARK_RESULTS_FILE, OUTPUT_DIR, REPORT_CONFIG

# ==============================
# 📊 相似度算法处理函数
# ==============================

# 辅助函数：深度合并字典（用于配置覆盖）
def _deep_merge_dicts(base: dict, override: dict) -> dict:
    """递归合并两个字典，override 优先"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def convert_raw_similarity_to_cosine(raw_score: float, model_name: str, embedding_dim: int = 768) -> float:
    if raw_score is None:
        return 0.0
    if "bge" in model_name.lower():
        return min(1.0, max(0.0, raw_score))
    else:
        max_possible = min(10.0, embedding_dim)
        cosine_est = raw_score / max_possible
        return min(1.0, max(0.0, cosine_est))

def load_and_process_results(source_filter: Optional[str] = None) -> List[Dict]:
    """
    加载并处理基准测试结果，可选只处理特定知识源。
    
    Args:
        source_filter (str, optional): 若提供，则仅处理该 source_id 的结果。
    
    Returns:
        List[Dict]: 处理后的记录列表，每个包含 model, knowledge, latency_ms, cosine_similarity
    """
    results_path = BENCHMARK_RESULTS_FILE
    
    if not results_path.exists():
        print(f"❌ 结果文件不存在: {results_path}")
        print("💡 请先运行: python benchmark_embedding_models.py")
        return []

    try:
        with open(results_path, "r", encoding="utf-8") as f:
            results = json.load(f)
    except Exception as e:
        print(f"❌ 无法加载结果文件: {e}")
        return []

    if not isinstance(results, dict):
        print(f"⚠️ 结果文件格式错误：期望 dict，实际是 {type(results)}")
        print("💡 请删除 benchmark_results.json 并重新运行 benchmark_embedding_models.py")
        return []

    processed = []
    for model, knowledge_sources in results.items():
        if not isinstance(knowledge_sources, dict):
            continue
        for ks, metrics in knowledge_sources.items():
            # 🔍 过滤非目标知识源（如果指定了 source_filter）
            if source_filter and ks != source_filter:
                continue
            
            if not isinstance(metrics, dict) or not metrics.get("success", False):
                continue
            
            # ✅【关键】从新结构中提取聚合指标
            avg_latency = metrics.get("avg_latency_ms_over_queries", 0.0)
            avg_similarity = metrics.get("avg_max_similarity", 0.0)
            
            cos_sim = convert_raw_similarity_to_cosine(avg_similarity, model)
            
            record = {
                "model": model,
                "knowledge": ks,
                "latency_ms": avg_latency,  # 使用跨 queries 的平均延迟
                "cosine_similarity": cos_sim,
            }
            
            # 添加分块元数据（如果存在）
            for key in ["chunk_count", "avg_chunk_length", "min_chunk_length", 
                       "max_chunk_length", "chunking_strategy"]:
                if key in metrics:
                    record[key] = metrics[key]
                    
            # ✅【新增】保留原始 per-query 数据（用于详细分析）
            if "per_query_results" in metrics:
                record["per_query_results"] = metrics["per_query_results"]
                    
            processed.append(record)
    return processed

def calculate_statistics(data: List[Dict]) -> Dict[str, Dict[str, Dict[str, float]]]:
    """
    计算统计信息
    
    Returns:
        Dict: {model: {knowledge_source: {metric: value}}}
    """
    stats = {}
    
    for record in data:
        model = record["model"]
        knowledge = record["knowledge"]
        
        if model not in stats:
            stats[model] = {}
        if knowledge not in stats[model]:
            stats[model][knowledge] = {}
        
        stats[model][knowledge]["latency_ms"] = record["latency_ms"]
        stats[model][knowledge]["cosine_similarity"] = record["cosine_similarity"]
    
    return stats

def plot_comparison(data: List[Dict], metric_key: str, ylabel: str, title: str, 
                   filename: str, similarity_algorithm: Optional[str] = None,
                   show_values: bool = True) -> None:
    """
    绘制对比图
    """
    if not data:
        print(f"⚠️ 无数据可绘制 {title}")
        return

    # 使用 comparison_plot 配置
    config_base = REPORT_CONFIG["comparison_plot"]["default"]
    # model_specific_override = REPORT_CONFIG["comparison_plot"]["overrides"].get(model_name, {})
    # config = _deep_merge_dicts(config_base, model_specific_override)
    # 注：此函数目前没有针对模型的覆盖，直接使用默认配置
    config = config_base

    models = sorted(set(r["model"] for r in data))
    sources = sorted(set(r["knowledge"] for r in data))

    # 构建矩阵
    plot_data = {model: [] for model in models}
    for src in sources:
        for model in models:
            val = next(
                (r[metric_key] for r in data if r["model"] == model and r["knowledge"] == src),
                0.0
            )
            plot_data[model].append(val)

    x = np.arange(len(sources))
    n = len(models)
    width = 0.8 / n if n > 1 else 0.6

    try:
        # 创建图形前再次确保字体设置
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'
        
        fig, ax = plt.subplots(figsize=config["figsize"])
        
        for i, model in enumerate(models):
            offset = (i - (n - 1) / 2) * width
            bars = ax.bar(x + offset, plot_data[model], width, label=model, alpha=config["bar_alpha"])
            
            # 在柱子上显示数值
            if show_values:
                for j, bar in enumerate(bars):
                    height = bar.get_height()
                    ax.annotate(f'{height:.3f}',
                               xy=(bar.get_x() + bar.get_width() / 2, height),
                               xytext=config["annotation"]["offset"],  # 使用配置中的偏移
                               textcoords="offset points",
                               ha='center', va='bottom',
                               fontsize=config["annotation"]["fontsize"]) # 使用配置中的字体大小

        ax.set_xlabel("知识库类型")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels(sources, rotation=config["rotate_xticks"]) # 使用配置中的旋转角度
        ax.legend()
        ax.grid(True, alpha=config["grid_alpha"]) # 使用配置中的网格透明度
        
        # 确保输出目录存在 - 使用与 config.py 中相同的路径逻辑
        output_path = Path(OUTPUT_DIR) / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=config["dpi"], bbox_inches='tight', # 使用配置中的 DPI
                   facecolor='white', edgecolor='none')
        plt.close(fig)
        print(f"✅ 相似度图表已保存: {output_path.absolute()}")
    except Exception as e:
        print(f"❌ 保存图表时出错: {e}")
        plt.close()

def plot_chunking_analysis(data: List[Dict]) -> None:
    """
    生成分块分析图表 - 每个模型一张图表，显示各知识库的分块数量和长度统计
    """
    if not data:
        print("⚠️ 无数据可绘制分块分析图")
        return
    
    # 过滤出包含分块信息的数据
    chunking_data = [item for item in data if 'chunk_count' in item]
    
    if not chunking_data:
        print("⚠️ 数据中没有分块信息，无法生成分块分析图")
        return
    
    df = pd.DataFrame(chunking_data)
    models = df['model'].unique()
    
    # 使用 chunking_analysis_plot 配置
    config_base = REPORT_CONFIG["chunking_analysis_plot"]["default"]
    config = config_base # 此函数目前没有模型覆盖

    for model in models:
        model_df = df[df['model'] == model]
        
        if len(model_df) == 0:
            continue
            
        sources = model_df['knowledge'].tolist()
        
        # 创建子图：左侧显示分块数量，右侧显示平均分块长度
        # 注意：这里稍微调整了 figsize，因为是双子图
        original_figsize = config["figsize"]
        adjusted_figsize = (original_figsize[0], original_figsize[1] / 2 * 2) # 确保高度适合双子图
        
        # 在创建图形前设置字体
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=adjusted_figsize)
        
        # 左侧子图：分块数量
        chunk_counts = model_df['chunk_count'].tolist()
        bars1 = ax1.bar(range(len(sources)), chunk_counts, alpha=config["bar_alpha"], color=config["bar_colors"][0]) # 使用配置颜色
        ax1.set_xlabel("知识库类型")
        ax1.set_ylabel("分块数量")
        ax1.set_title(f"{model}\n各知识库分块数量统计")
        ax1.set_xticks(range(len(sources)))
        ax1.set_xticklabels(sources, rotation=config["rotate_xticks"])
        
        # 在柱子上显示数值
        for bar, count in zip(bars1, chunk_counts):
            height = bar.get_height()
            ax1.annotate(f'{int(height)}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=config["annotation"]["offset"], # 使用配置中的偏移
                        textcoords="offset points",
                        ha='center', va='bottom',
                        fontsize=config["annotation"]["fontsize"]) # 使用配置中的字体大小
        
        # 右侧子图：平均分块长度
        avg_lengths = model_df['avg_chunk_length'].tolist()
        bars2 = ax2.bar(range(len(sources)), avg_lengths, alpha=config["bar_alpha"], color=config["bar_colors"][1]) # 使用配置颜色
        ax2.set_xlabel("知识库类型")
        ax2.set_ylabel("平均分块长度 (字符)")
        ax2.set_title(f"{model}\n各知识库平均分块长度统计")
        ax2.set_xticks(range(len(sources)))
        ax2.set_xticklabels(sources, rotation=config["rotate_xticks"])
        
        # 在柱子上显示数值
        for bar, length in zip(bars2, avg_lengths):
            height = bar.get_height()
            ax2.annotate(f'{int(height)}',
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=config["annotation"]["offset"], # 使用配置中的偏移
                        textcoords="offset points",
                        ha='center', va='bottom',
                        fontsize=config["annotation"]["fontsize"]) # 使用配置中的字体大小
        
        # 添加网格
        ax1.grid(True, alpha=config["grid_alpha"]) # 使用配置中的网格透明度
        ax2.grid(True, alpha=config["grid_alpha"])
        
        # 保存图表 - 使用与 config.py 中相同的路径逻辑
        model_cleaned = model.replace("/", "_")  # 避免文件名中的特殊字符
        output_path = Path(OUTPUT_DIR) / f"chunking_analysis_{model_cleaned}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output_path, dpi=config["dpi"], bbox_inches='tight', facecolor='white', edgecolor='none') # 使用配置中的 DPI
        plt.close(fig)
        print(f"✅ 分块分析图已保存: {output_path.absolute()}")

def plot_chunking_detailed_comparison(data: List[Dict]) -> None:
    """
    生成分块详细对比图 - 显示最大/最小分块长度的对比
    """
    if not data:
        print("⚠️ 无数据可绘制分块详细对比图")
        return
    
    # 过滤出包含分块信息的数据
    chunking_data = [item for item in data if 'chunk_count' in item]
    
    if not chunking_data:
        print("⚠️ 数据中没有分块信息，无法生成分块详细对比图")
        return
    
    df = pd.DataFrame(chunking_data)
    
    # 获取所有唯一组合
    combinations = [(row['model'], row['knowledge']) for _, row in df.iterrows()]
    unique_combinations = sorted(set(combinations))
    
    # 准备数据
    models = []
    knowledge_sources = []
    max_lengths = []
    min_lengths = []
    
    for model, knowledge in unique_combinations:
        subset = df[(df['model'] == model) & (df['knowledge'] == knowledge)]
        if not subset.empty:
            models.append(f"{model}\n({knowledge})")
            knowledge_sources.append(knowledge)
            max_lengths.append(subset['max_chunk_length'].iloc[0])
            min_lengths.append(subset['min_chunk_length'].iloc[0])
    
    if not models:
        return
    
    # 使用 chunking_detailed_comparison_plot 配置
    config_base = REPORT_CONFIG["chunking_detailed_comparison_plot"]["default"]
    config = config_base # 此函数目前没有模型覆盖

    # 在创建图形前设置字体
    plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    plt.rcParams['font.family'] = 'sans-serif'
    
    fig, ax = plt.subplots(figsize=config["figsize"])
    
    x = np.arange(len(models))
    width = config["bar_width"] # 使用配置中的宽度

    bars1 = ax.bar(x - width/2, min_lengths, width, label='最小长度', alpha=config["bar_alpha"], color=config["bar_colors"][0]) # 使用配置颜色和透明度
    bars2 = ax.bar(x + width/2, max_lengths, width, label='最大长度', alpha=config["bar_alpha"], color=config["bar_colors"][1]) # 使用配置颜色和透明度
    
    ax.set_xlabel("模型-知识库组合")
    ax.set_ylabel("分块长度 (字符)")
    ax.set_title("各模型-知识库组合的分块长度对比\n(最小 vs 最大)")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=config["rotate_xticks"]) # 使用配置中的旋转角度
    ax.legend()
    ax.grid(True, alpha=config["grid_alpha"]) # 使用配置中的网格透明度
    
    # 在柱子上显示数值
    for bar, value in zip(bars1, min_lengths):
        height = bar.get_height()
        ax.annotate(f'{int(height)}',
                   xy=(bar.get_x() + bar.get_width() / 2, height),
                   xytext=config["annotation"]["offset"], # 使用配置中的偏移
                   textcoords="offset points",
                   ha='center', va='bottom',
                   fontsize=config["annotation"]["fontsize"]) # 使用配置中的字体大小
    
    for bar, value in zip(bars2, max_lengths):
        height = bar.get_height()
        ax.annotate(f'{int(height)}',
                   xy=(bar.get_x() + bar.get_width() / 2, height),
                   xytext=config["annotation"]["offset"], # 使用配置中的偏移
                   textcoords="offset points",
                   ha='center', va='bottom',
                   fontsize=config["annotation"]["fontsize"]) # 使用配置中的字体大小
    
    # 保存图表 - 使用与 config.py 中相同的路径逻辑
    output_path = Path(OUTPUT_DIR) / "chunking_length_comparison.png"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=config["dpi"], bbox_inches='tight', facecolor='white', edgecolor='none') # 使用配置中的 DPI
    plt.close(fig)
    print(f"✅ 分块长度对比图已保存: {output_path.absolute()}")

def generate_comparison_plots(data: List[Dict]) -> None:
    """
    生成所有相似度算法的对比图
    """
    algorithms = REPORT_CONFIG["similarity_algorithms"]["options"]
    
    for algo in algorithms:
        algo_config = REPORT_CONFIG["similarity_algorithms"].get(algo, {})
        algo_name = algo_config.get("name", algo)
        
        new_title = f"不同模型检索质量对比（{algo_name}）"
        new_filename = f"semantic_similarity_{algo}.png"
        
        if algo == "cosine":
            y_label = "标准化语义相似度 (0～1)"
        else:
            y_label = f"{algo_name} (0～1)"
        
        plot_comparison(
            data,
            metric_key="cosine_similarity",
            ylabel=y_label,
            title=new_title,
            filename=new_filename,
            similarity_algorithm=algo
        )

def plot_model_latency_distribution(data: List[Dict]) -> None:
    """
    为每个模型生成延迟分布图（箱线图 + 散点 + 统计标注）
    
    图表样式完全由 config.py 中 REPORT_CONFIG["latency_distribution_plot"] 控制，
    支持全局默认值和 per-model 覆盖。
    """
    if not data:
        print("⚠️ 没有数据生成延迟分布图")
        return

    models = sorted(set(r["model"] for r in data))
    sources = sorted(set(r["knowledge"] for r in data))

    # 获取延迟分布配置模板 - 更新键名
    latency_config_base = REPORT_CONFIG["latency_distribution_plot"]["default"] # 使用新的键名
    model_overrides = REPORT_CONFIG["latency_distribution_plot"].get("overrides", {}) # 使用新的键名

    for model_name in models:
        # 合并全局默认配置与模型特定覆盖
        model_override = model_overrides.get(model_name, {})
        plot_config = _deep_merge_dicts(latency_config_base, model_override)

        # 筛选当前模型的数据
        model_records = [r for r in data if r["model"] == model_name]
        all_runs_by_source: Dict[str, List[float]] = {src: [] for src in sources}

        # 收集所有 query 的多次运行延迟
        for record in model_records:
            source_id = record["knowledge"]
            per_query_results = record.get("per_query_results", [])
            for query_result in per_query_results:
                latency_runs = query_result.get("latency_runs_ms", [])
                all_runs_by_source[source_id].extend(latency_runs)

        # 过滤掉无数据的知识源
        valid_sources = [src for src in sources if all_runs_by_source[src]]
        if not valid_sources:
            continue

        # 准备绘图数据
        box_data: List[List[float]] = []
        positions: List[int] = []
        stats_by_source: Dict[str, Dict[str, float]] = {}

        for idx, source in enumerate(valid_sources):
            runs = all_runs_by_source[source]
            median_val = float(np.median(runs))
            mean_val = float(np.mean(runs))
            q1_val = float(np.percentile(runs, 25))
            q3_val = float(np.percentile(runs, 75))

            stats_by_source[source] = {
                "median": median_val,
                "mean": mean_val,
                "q1": q1_val,
                "q3": q3_val
            }
            box_data.append(runs)
            positions.append(idx + 1)  # x-axis starts at 1

        # 在创建图形前设置字体
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'
        
        # 创建图形
        fig, ax = plt.subplots(figsize=plot_config["figsize"])

        # 绘制散点（jittered）
        scatter_cfg = plot_config["scatter"]
        for pos, source in zip(positions, valid_sources):
            runs = all_runs_by_source[source]
            jitter = np.random.normal(0, scatter_cfg["jitter_sigma"], len(runs)) # 使用配置中的 jitter_sigma
            ax.scatter(
                [pos + j for j in jitter],
                runs,
                color=scatter_cfg["color"],
                alpha=scatter_cfg["alpha"],
                s=scatter_cfg["s"],
                edgecolors=scatter_cfg["edgecolors"],
                zorder=2  # 在箱线图下方
            )

        # 绘制箱线图
        box_cfg = plot_config["boxplot"]
        ax.boxplot(
            box_data,
            positions=positions,
            patch_artist=True,
            boxprops=dict(
                facecolor=box_cfg["facecolor"],
                alpha=box_cfg["alpha"]
            ),
            medianprops=dict(color=box_cfg["median_color"]),
            whiskerprops=dict(color=box_cfg["whisker_color"]),
            capprops=dict(color=box_cfg["cap_color"]),
            flierprops=dict(
                marker=box_cfg["flier_marker"],
                markersize=box_cfg["flier_size"],
                markerfacecolor=box_cfg["flier_color"],
                linestyle="none"
            ),
            zorder=3
        )

        # 添加统计标注
        annotate_cfg = plot_config["annotate"]
        for pos, source in zip(positions, valid_sources):
            stats = stats_by_source[source]
            text_content = (
                f"中位数={stats['median']:.1f}ms\n"
                f"均值={stats['mean']:.1f}ms"
            )
            ax.annotate(
                text_content,
                xy=(pos, stats["median"]),  # 箭头指向中位数
                xytext=(
                    pos + annotate_cfg["offset_x"],
                    stats["median"] + annotate_cfg["offset_y"]
                ),
                textcoords="data",
                fontsize=annotate_cfg["fontsize"],
                ha=annotate_cfg["ha"],
                va=annotate_cfg["va"],
                weight="bold",
                color="darkblue",
                bbox=annotate_cfg["bbox"],
                arrowprops=dict(
                    arrowstyle="->",
                    color="gray",
                    alpha=0.6,
                    shrinkA=2,
                    shrinkB=2
                )
            )

        # 设置坐标轴
        # 注意：这里仍然使用通用的 plot_options 里的字体大小，而不是 plot_config 里的
        common_opts = REPORT_CONFIG["plot_options"]
        ax.set_xlabel("知识库类型", fontsize=common_opts["label_fontsize"])
        ax.set_ylabel("查询延迟 (ms)", fontsize=common_opts["label_fontsize"])
        ax.set_title(
            f"{model_name}\n各知识库上的延迟分布（含所有 Query 及多次运行）",
            fontsize=common_opts["title_fontsize"]
        )
        ax.set_xticks(positions)
        ax.set_xticklabels(valid_sources, rotation=plot_config["rotate_xticks"])
        ax.grid(True, alpha=0.3, axis="y") # 箱线图通常只用 Y 轴网格

        plt.tight_layout()

        # 保存图像
        safe_model_name = model_name.replace("/", "_").replace(":", "_")
        output_path = Path(OUTPUT_DIR) / f"latency_distribution_{safe_model_name}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(
            output_path,
            dpi=plot_config["dpi"], # 使用配置中的 DPI
            bbox_inches="tight",
            facecolor="white"
        )
        plt.close(fig)
        print(f"✅ 延迟箱线图已保存: {output_path.absolute()}")

def plot_model_latency_line_with_error(data: List[Dict]) -> None:
    """
    为每个模型生成延迟折线图（含误差线与数据标注）
    
    - X轴：知识库类型
    - Y轴：查询延迟 (ms)
    - 每个点：显示多次运行的均值 ± 标准差
    - 背景点：显示所有单次运行延迟（抖动散点）
    
    图表样式由 REPORT_CONFIG["latency_line_plot"] 控制。
    """
    if not data:
        print("⚠️ 无数据可绘制折线图")
        return

    df = pd.DataFrame(data)
    models = df["model"].unique()
    # 使用 latency_line_plot 配置 - 更新键名
    plot_config_base = REPORT_CONFIG["latency_line_plot"]["default"] # 使用新的键名
    model_overrides = REPORT_CONFIG["latency_line_plot"].get("overrides", {}) # 使用新的键名

    for model_name in models:
        model_df = df[df["model"] == model_name]
        sources = sorted(model_df["knowledge"].unique())

        # 获取当前模型的配置
        model_override = model_overrides.get(model_name, {})
        plot_config = _deep_merge_dicts(plot_config_base, model_override)

        # 在创建图形前设置字体
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
        plt.rcParams['font.family'] = 'sans-serif'
        
        fig, ax = plt.subplots(figsize=plot_config["figsize"])
        x_positions = np.arange(len(sources))
        
        avg_latencies: List[float] = []
        std_devs: List[float] = []

        for i, source in enumerate(sources):
            # 筛选当前模型+知识库的所有记录
            subset = model_df[model_df["knowledge"] == source]
            if subset.empty:
                avg_latencies.append(0.0)
                std_devs.append(0.0)
                continue

            # 合并所有 query 的 latency_runs_ms
            all_runs: List[float] = []
            for _, row in subset.iterrows():
                per_query_results = row.get("per_query_results", [])
                for pq in per_query_results:
                    runs = pq.get("latency_runs_ms", [])
                    if isinstance(runs, (list, tuple)):
                        all_runs.extend(runs)

            if not all_runs:
                avg_latencies.append(0.0)
                std_devs.append(0.0)
                continue

            avg_val = float(np.mean(all_runs))
            std_val = float(np.std(all_runs))
            avg_latencies.append(avg_val)
            std_devs.append(std_val)

            # 绘制单次运行散点（轻微横向抖动，避免重叠）
            scatter_cfg = plot_config["scatter"]
            jitter = np.random.normal(0, scatter_cfg["jitter_sigma"], len(all_runs)) # 使用配置中的 jitter_sigma
            ax.scatter(
                x_positions[i] + jitter,
                all_runs,
                color=scatter_cfg["color"],
                alpha=scatter_cfg["alpha"],
                s=scatter_cfg["s"],
                zorder=2
            )

        # 绘制平均值折线 + 误差线
        line_cfg = plot_config["line"]
        ax.errorbar(
            x_positions,
            avg_latencies,
            yerr=std_devs,
            fmt=line_cfg["marker"], # 使用配置中的标记点形状
            capsize=line_cfg["capsize"], # 使用配置中的 capsize
            capthick=line_cfg["capthick"], # 使用配置中的 capthick
            elinewidth=line_cfg["elinewidth"], # 使用配置中的 elinewidth
            markersize=line_cfg["markersize"], # 使用配置中的 markersize
            color=line_cfg["color"], # 使用配置中的主线颜色
            ecolor=line_cfg["ecolor"], # 使用配置中的误差线颜色
            label=f"{model_name}（均值 ± 标准差）",
            zorder=3
        )

        # 在每个数据点上方标注 "均值 ± 标准差"
        annotate_cfg = plot_config["annotate"]
        for i, (avg, std) in enumerate(zip(avg_latencies, std_devs)):
            if avg == 0 and std == 0:
                continue  # 跳过无数据点
            text = f"{avg:.0f} ± {std:.0f}"
            ax.annotate(
                text,
                xy=(x_positions[i], avg),
                xytext=annotate_cfg["offset"], # 使用配置中的偏移
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=annotate_cfg["fontsize"], # 使用配置中的字体大小
                color="black",
                weight="bold",
                bbox=annotate_cfg["bbox"], # 使用配置中的背景框样式
                zorder=4
            )

        # 设置坐标轴与标题
        common_opts = REPORT_CONFIG["plot_options"]
        ax.set_xlabel("知识库类型", fontsize=common_opts["label_fontsize"])
        ax.set_ylabel("查询延迟 (ms)", fontsize=common_opts["label_fontsize"])
        ax.set_title(
            f"{model_name}\n各知识库上的延迟分布（含多次运行）",
            fontsize=common_opts["title_fontsize"]
        )
        ax.set_xticks(x_positions)
        ax.set_xticklabels(sources, rotation=plot_config["rotate_xticks"]) # 使用配置中的旋转角度
        ax.legend()
        ax.grid(True, alpha=plot_config["grid_alpha"]) # 使用配置中的网格透明度

        # 保存图像
        safe_model_name = model_name.replace("/", "_").replace(":", "_")
        output_path = Path(OUTPUT_DIR) / f"latency_line_{safe_model_name}.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(
            output_path,
            dpi=plot_config["dpi"], # 使用配置中的 DPI
            bbox_inches="tight",
            facecolor="white"
        )
        plt.close(fig)
        print(f"✅ 折线图已保存: {output_path.absolute()}")

def generate_summary_report(data: List[Dict]) -> None:
    """
    生成摘要报告
    """
    if not data:
        print("⚠️ 没有数据生成摘要报告")
        return
    
    # 创建 DataFrame 以便于分析
    df = pd.DataFrame(data)
    
    # 计算各模型在各项指标上的平均值
    summary = df.groupby('model').agg({
        'latency_ms': ['mean', 'std', 'min', 'max'],
        'cosine_similarity': ['mean', 'std', 'min', 'max']
    }).round(3)
    
    # 重命名列
    summary.columns = ['_'.join(col).strip() for col in summary.columns.values]
    
    # 保存为 CSV - 使用与 config.py 中相同的路径逻辑
    csv_path = Path(OUTPUT_DIR) / REPORT_CONFIG["output_files"]["summary_csv"]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(csv_path, encoding='utf-8-sig')
    print(f"📊 摘要报告已保存: {csv_path.absolute()}")
    
    # 打印摘要信息
    print("\n📈 模型性能摘要:")
    print(summary)

def generate_performance_rankings(data: List[Dict]) -> None:
    """
    生成性能排名
    """
    if not data:
        print("⚠️ 没有数据生成性能排名")
        return
    
    df = pd.DataFrame(data)
    
    print("\n🏆 模型性能排名:")
    
    # 按相似度排序（越高越好）
    similarity_ranking = df.groupby('model')['cosine_similarity'].mean().sort_values(ascending=False)
    print("\n🎯 相似度排名:")
    for i, (model, score) in enumerate(similarity_ranking.items(), 1):
        print(f"  {i}. {model}: {score:.3f}")
    
    # 按延迟排序（越低越好）
    latency_ranking = df.groupby('model')['latency_ms'].mean().sort_values(ascending=True)
    print("\n⚡ 延迟排名:")
    for i, (model, latency) in enumerate(latency_ranking.items(), 1):
        print(f"  {i}. {model}: {latency:.2f}ms")

def generate_detailed_report(data: List[Dict]) -> None:
    """
    生成详细报告
    """
    if not data:
        print("⚠️ 没有数据生成详细报告")
        return
    
    df = pd.DataFrame(data)
    
    print("\n📋 详细性能报告:")
    
    for model in df['model'].unique():
        print(f"\n🔹 {model}:")
        model_data = df[df['model'] == model]
        
        for knowledge in model_data['knowledge'].unique():
            knowledge_data = model_data[model_data['knowledge'] == knowledge]
            avg_similarity = knowledge_data['cosine_similarity'].mean()
            avg_latency = knowledge_data['latency_ms'].mean()
            
            print(f"  📚 {knowledge}: 相似度={avg_similarity:.3f}, 延迟={avg_latency:.2f}ms")
            
            # 如果有分块信息，也显示出来
            if 'chunk_count' in knowledge_data.columns:
                avg_chunks = knowledge_data['chunk_count'].mean()
                avg_chunk_len = knowledge_data['avg_chunk_length'].mean()
                print(f"    📄 分块: {int(avg_chunks)} 个, 平均长度: {int(avg_chunk_len)} 字符")

import argparse
def main():
    # 设置绘图风格
    sns.set_style("whitegrid")
    setup_chinese_font(verbose=False)  # 避免重复提示

    # 支持命令行参数
    parser = argparse.ArgumentParser(
        description="生成嵌入模型在多语言、多长度知识库上的基准测试可视化报告",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source_filter",
        type=str,
        default=None,
        help="仅生成指定知识源（如 'short_zh'）的报告"
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="跳过所有图表生成，只生成摘要报告"
    )
    parser.add_argument(
        "--chunking-only",
        action="store_true",
        help="仅生成分块分析图（覆盖其他生成选项）"
    )
    # --- 新增各类图表的独立命令行选项 ---
    parser.add_argument(
        "--latency-comparison-plots", # 延迟对比柱状图
        action="store_true",
        help="生成延迟对比柱状图"
    )
    parser.add_argument(
        "--similarity-comparison-plots", # 相似度对比图
        action="store_true",
        help="生成相似度对比图（支持多种算法）"
    )
    parser.add_argument(
        "--chunking-analysis-plots", # 分块分析图
        action="store_true",
        help="生成分块数量和长度统计图"
    )
    parser.add_argument(
        "--chunking-length-comparison-plots", # 分块长度对比图
        action="store_true",
        help="生成分块长度详细对比图"
    )
    parser.add_argument(
        "--line-plots", # 延迟折线图
        action="store_true",
        help="生成每个模型的延迟折线图（含多次运行和误差线）"
    )
    parser.add_argument(
        "--box-plots", # 延迟箱线图
        action="store_true",
        help="生成每个模型的延迟分布箱线图（含散点与统计标注）"
    )
    # --- end 新增 ---

    args = parser.parse_args()

    # 加载数据（可选过滤）
    data = load_and_process_results(source_filter=args.source_filter)
    if not data:
        print("⚠️ 没有有效数据，无法生成图表。")
        return

    # --- 🔍 记录初始文件列表 ---
    initial_files = set()
    if OUTPUT_DIR.exists():
        initial_files = {f.name for f in OUTPUT_DIR.iterdir() if f.is_file()}
    # --- end 记录 ---

    # --- 逻辑判断 ---
    # 1. 如果指定了 --chunking-only，只生成分块图
    if args.chunking_only:
        print("📊 仅生成分块分析图...")
        plot_chunking_analysis(data)
        plot_chunking_detailed_comparison(data)
    # 2. 如果指定了 --no-plots，只生成摘要报告
    elif args.no_plots:
        print("📊 仅生成摘要报告...")
        generate_summary_report(data)
        generate_performance_rankings(data)
        generate_detailed_report(data)
    # 3. 如果指定了特定图表参数，则只生成对应图表
    elif any([
        args.latency_comparison_plots,
        args.similarity_comparison_plots,
        args.chunking_analysis_plots,
        args.chunking_length_comparison_plots,
        args.line_plots,
        args.box_plots
    ]):
        print("📊 根据参数生成指定图表...")
        if args.latency_comparison_plots:
            plot_comparison(
                data,
                metric_key="latency_ms",
                ylabel="平均查询延迟 (ms)",
                title="不同模型在各类知识库上的查询延迟对比",
                filename=REPORT_CONFIG["output_files"]["latency_plot"]
            )
        if args.similarity_comparison_plots:
            generate_comparison_plots(data)
        if args.chunking_analysis_plots:
            plot_chunking_analysis(data)
        if args.chunking_length_comparison_plots:
            plot_chunking_detailed_comparison(data)
        if args.line_plots:
            plot_model_latency_line_with_error(data)  # 折线图 + 误差线
        if args.box_plots:
            plot_model_latency_distribution(data)     # 箱线图 + 散点分布
    # 4. 如果没有指定任何图表相关参数（默认情况），则生成所有图表和报告
    else:
        print("📊 生成所有图表和报告...")
        # 生成默认对比图
        plot_comparison(
            data,
            metric_key="latency_ms",
            ylabel="平均查询延迟 (ms)",
            title="不同模型在各类知识库上的查询延迟对比",
            filename=REPORT_CONFIG["output_files"]["latency_plot"]
        )
        generate_comparison_plots(data) # 相似度对比图

        # 生成分块分析图
        plot_chunking_analysis(data)
        plot_chunking_detailed_comparison(data)

        # 生成延迟分布图
        plot_model_latency_line_with_error(data)
        plot_model_latency_distribution(data)

        # 生成摘要报告
        generate_summary_report(data)
        generate_performance_rankings(data)
        generate_detailed_report(data)

    # --- 🔍 记录并对比最终文件列表 ---
    final_files = set()
    current_files_list = [] # 用于最终打印
    if OUTPUT_DIR.exists():
        final_files = {f.name for f in OUTPUT_DIR.iterdir() if f.is_file()}
        current_files_list = sorted([f.name for f in OUTPUT_DIR.iterdir() if f.is_file()])
    
    new_files = final_files - initial_files
    # --- end 记录和对比 ---

    print(f"\n🎉 报告生成完毕！所有输出位于: {Path(OUTPUT_DIR).resolve()}")
    
    # 显示本次运行新生成的文件
    if new_files:
        print(f"\n✨ 本次新生成的文件 ({len(new_files)} 个):")
        for file in sorted(list(new_files)):
            print(f"  🆕 {file}")
    else:
        print(f"\n🔍 本次运行未生成具有新名称的文件")
    
    # 显示当前目录下的所有文件
    print(f"\n📋 当前 '{OUTPUT_DIR.name}' 目录下的文件 ({len(current_files_list)} 个):")
    for file in current_files_list:
        status_icon = "🆕" if file in new_files else "📋" # 用图标区分新旧文件
        print(f"  {status_icon} {file}")


if __name__ == "__main__":
    import os
    # 确保从任何位置运行都能找到 config
    script_dir = Path(__file__).parent.resolve()
    if str(script_dir.parent) not in sys.path:
        sys.path.insert(0, str(script_dir.parent))
    main()