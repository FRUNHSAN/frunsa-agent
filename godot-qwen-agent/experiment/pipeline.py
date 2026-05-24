"""
RAG 评估分析管道
- 自动加载 results/raw_outputs/ 下最新 run_*.json
- 分析指标
- 保存摘要到 results/metrics/
- 打印报告
"""

import os
import json
import glob
from pathlib import Path
from datetime import datetime
import pandas as pd

# 👇 获取脚本所在目录（experiment/）
SCRIPT_DIR = Path(__file__).parent

def find_latest_raw_result(raw_dir: str = "results/raw_outputs") -> str:
    """查找 raw_outputs/ 下最新的 run_*.json"""
    raw_path = SCRIPT_DIR / raw_dir
    files = list(raw_path.glob("run_*.json"))
    if not files:
        raise FileNotFoundError(f"No run_*.json found in {raw_path}")
    return str(max(files, key=os.path.getctime))

def analyze_results(result_file: str):
    with open(result_file, 'r', encoding='utf-8') as f:
        results = json.load(f)
    
    total = len(results)
    successful = [r for r in results if "error" not in r]
    failed = [r for r in results if "error" in r]
    
    stats = {
        "total_queries": total,
        "successful": len(successful),
        "failed": len(failed),
        "success_rate": len(successful) / total if total > 0 else 0,
        "avg_retrieved": sum(r["retrieved_count"] for r in successful) / len(successful) if successful else 0,
        "min_retrieved": min((r["retrieved_count"] for r in successful), default=0),
        "max_retrieved": max((r["retrieved_count"] for r in successful), default=0),
    }
    
    if successful and "retrieved_scores" in successful[0]:
        all_scores = [score for r in successful for score in r["retrieved_scores"]]
        stats["avg_similarity_score"] = sum(all_scores) / len(all_scores) if all_scores else None
    else:
        stats["avg_similarity_score"] = None
    
    return stats, results, successful, failed

def print_report(stats: dict, result_file: str, successful: list, failed: list):
    print("=" * 60)
    print("📊 RAG 评估报告")
    print("=" * 60)
    print(f"📁 原始结果: {result_file}")
    print(f"🕒 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    print("📈 核心指标:")
    print(f"  • 总查询数:      {stats['total_queries']}")
    print(f"  • 成功率:        {stats['success_rate']:.1%} ({stats['successful']}/{stats['total_queries']})")
    print(f"  • 平均检索数:    {stats['avg_retrieved']:.2f} (范围: {stats['min_retrieved']}-{stats['max_retrieved']})")
    if stats["avg_similarity_score"] is not None:
        print(f"  • 平均相似度:    {stats['avg_similarity_score']:.3f}")
    print()
    
    if successful:
        print("✅ 示例成功回答 (前2条):")
        for i, r in enumerate(successful[:2]):
            print(f"  [{i+1}] Q: {r['original_query'][:80]}...")
            print(f"      A: {r['answer'][:150]}...")
            print()
    
    if failed:
        print("❌ 失败示例 (前2条):")
        for i, r in enumerate(failed[:2]):
            print(f"  [{i+1}] Q: {r['original_query'][:80]}...")
            print(f"      Error: {r['error']}")
            print()

def save_metrics_json(stats: dict, result_file: str, metrics_dir: str = "results/metrics"):
    """保存指标为 JSON（便于程序读取）"""
    metrics_path = SCRIPT_DIR / metrics_dir  # ✅ 关键：基于 SCRIPT_DIR
    metrics_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = Path(result_file).stem.replace("run_", "")
    metrics_file = metrics_path / f"metrics_{timestamp}.json"
    
    output = {
        "analysis_time": datetime.now().isoformat(),
        "source_raw_file": os.path.basename(result_file),
        "metrics": stats
    }
    
    with open(metrics_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"💾 指标已保存至: {metrics_file}")

def save_metrics_csv(stats: dict, result_file: str, summary_csv: str = "results/metrics/summary.csv"):
    """追加到汇总 CSV（用于多轮对比）"""
    summary_path = SCRIPT_DIR / summary_csv  # ✅ 关键：基于 SCRIPT_DIR
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    
    row = {
        "run_id": Path(result_file).stem,
        "analysis_time": datetime.now().isoformat(),
        "total_queries": stats["total_queries"],
        "success_rate": f"{stats['success_rate']:.1%}",
        "avg_retrieved": round(stats["avg_retrieved"], 2),
        "avg_similarity": round(stats["avg_similarity_score"], 3) if stats["avg_similarity_score"] else "",
    }
    
    df = pd.DataFrame([row])
    if summary_path.exists():
        df.to_csv(summary_path, mode='a', header=False, index=False, encoding='utf-8-sig')
    else:
        df.to_csv(summary_path, index=False, encoding='utf-8-sig')
    
    print(f"📊 汇总记录追加至: {summary_path}")

def main():
    try:
        latest_raw = find_latest_raw_result()
        stats, all_results, successful, failed = analyze_results(latest_raw)
        
        print_report(stats, latest_raw, successful, failed)
        save_metrics_json(stats, latest_raw)
        save_metrics_csv(stats, latest_raw)
        
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        raise

if __name__ == "__main__":
    main()