"""
生成 RAG 回答与标准答案的对比报告（含自动评分 + 高亮差异）
输出：
  - CSV: experiment/results/report/report_*.csv
  - HTML: experiment/results/report/report_*.html
"""

import json
import glob
import os
import re
from pathlib import Path
from datetime import datetime
import pandas as pd

# 脚本所在目录（experiment/）
SCRIPT_DIR = Path(__file__).parent

def find_latest_raw_result():
    raw_dir = SCRIPT_DIR / "results" / "raw_outputs"
    files = list(raw_dir.glob("run_*.json"))
    if not files:
        raise FileNotFoundError(f"No run_*.json found in {raw_dir}")
    return max(files, key=os.path.getctime)

def load_ground_truth():
    gt_path = SCRIPT_DIR / "ground_truth.json"
    with open(gt_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # 构建 {question: {answer, keywords}} 映射
    return {
        item["question"]: {
            "answer": item["answer"],
            "keywords": [kw.lower() for kw in item.get("expected_chunks_keywords", [])]
        }
        for item in data["questions"]
    }

def compute_keyword_score(generated: str, keywords: list) -> tuple[float, list, list]:
    """
    计算关键词覆盖率
    返回: (score, matched, missed)
    """
    if not keywords:
        return 1.0, [], []
    
    text_lower = generated.lower()
    matched = []
    missed = []
    
    for kw in keywords:
        # 支持子串匹配（如 "export_range" 匹配 "@export_range(...)"）
        if kw in text_lower:
            matched.append(kw)
        else:
            missed.append(kw)
    
    score = len(matched) / len(keywords)
    return score, matched, missed

def highlight_keywords(text: str, keywords: list) -> str:
    """在 HTML 中高亮关键词（绿色），缺失关键词用红色列出"""
    if not keywords:
        return text.replace("\n", "<br>")
    
    text_html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
    highlighted = text_html
    
    # 高亮已命中的关键词（绿色）
    for kw in keywords:
        if kw in text.lower():
            # 使用正则忽略大小写替换
            pattern = re.compile(re.escape(kw), re.IGNORECASE)
            highlighted = pattern.sub(f'<span style="background-color: #d4edda; color: #155724; font-weight: bold;">{kw.upper()}</span>', highlighted)
    
    return highlighted

def main():
    # 1. 加载数据
    raw_file = find_latest_raw_result()
    with open(raw_file, 'r', encoding='utf-8') as f:
        model_results = json.load(f)

    ground_truth = load_ground_truth()

    # 2. 构建报告数据
    csv_data = []
    html_rows = []

    for item in model_results:
        query = item["original_query"]
        gt_info = ground_truth.get(query, {"answer": "[未找到标准答案]", "keywords": []})
        
        generated = item.get("answer", "[无回答]")
        keywords = gt_info["keywords"]
        
        # 自动评分
        score, matched, missed = compute_keyword_score(generated, keywords)
        
        # CSV 数据
        csv_data.append({
            "original_query": query,
            "processed_query": item.get("processed_query", ""),
            "generated_answer": generated,
            "ground_truth_answer": gt_info["answer"],
            "keyword_score": round(score, 3),
            "matched_keywords": ", ".join(matched),
            "missed_keywords": ", ".join(missed)
        })

        # HTML 高亮
        gen_highlighted = highlight_keywords(generated, keywords)
        gt_highlighted = highlight_keywords(gt_info["answer"], keywords)
        
        html_rows.append(f"""
        <tr>
            <td style="vertical-align: top; width: 20%;"><strong>{query}</strong></td>
            <td style="vertical-align: top; width: 30%;">
                <div style="background: #f8f9fa; padding: 8px; border-radius: 4px;">
                    {gen_highlighted}
                </div>
                <div style="margin-top: 6px; font-size: 0.9em; color: #6c757d;">
                    <strong>关键词得分:</strong> {score:.1%} |
                    <span style="color: green;">命中: {', '.join(matched) or '—'}</span> |
                    <span style="color: red;">缺失: {', '.join(missed) or '—'}</span>
                </div>
            </td>
            <td style="vertical-align: top; width: 30%;">
                <div style="background: #e9ecef; padding: 8px; border-radius: 4px;">
                    {gt_highlighted}
                </div>
            </td>
        </tr>
        """)

    # 3. 保存 CSV
    report_dir = SCRIPT_DIR / "results" / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    csv_file = report_dir / f"report_{timestamp}.csv"
    df = pd.DataFrame(csv_data)
    df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    
    # 4. 保存 HTML
    html_content = f"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <title>RAG 评估对比报告</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 20px; background: #fff; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ border: 1px solid #dee2e6; padding: 12px; text-align: left; vertical-align: top; }}
            th {{ background-color: #f1f3f5; font-weight: bold; }}
            tr:nth-child(even) {{ background-color: #fafafa; }}
            .header {{ text-align: center; margin-bottom: 20px; }}
            .summary {{ background: #e2e3e5; padding: 10px; border-radius: 6px; margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 RAG 评估对比报告</h1>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>原始结果: {raw_file.name}</p>
        </div>
        
        <div class="summary">
            <strong>整体关键词平均分: {df['keyword_score'].mean():.1%}</strong>
        </div>

        <table>
            <thead>
                <tr>
                    <th>问题 (Query)</th>
                    <th>模型回答（🟢 高亮命中关键词）</th>
                    <th>标准答案（参考）</th>
                </tr>
            </thead>
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
    </body>
    </html>
    """
    
    html_file = report_dir / f"report_{timestamp}.html"
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    print(f"✅ 对比报告已生成:")
    print(f"   📊 CSV: {csv_file}")
    print(f"   🌐 HTML: {html_file}")
    print(f"   📈 平均关键词得分: {df['keyword_score'].mean():.1%}")

if __name__ == "__main__":
    main()