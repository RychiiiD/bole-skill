"""
伯乐 — Enterprise Output Formatter
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/enterprise_format.py --config config.yaml

Reads enterprise_scored.csv, filters to KB-relevant fields,
outputs UTF-8 (no BOM) / UTF-8 BOM versions + data report.
"""

import argparse
import csv
import os
import sys
from datetime import date
from typing import Dict, List


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_csv(filepath: str, encoding: str = "utf-8-sig") -> List[Dict]:
    with open(filepath, "r", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv(filepath: str, rows: List[Dict], fieldnames: List[str],
              encoding: str = "utf-8-sig"):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            out = {k: row.get(k, "") or "" for k in fieldnames}
            w.writerow(out)


# 知识库导入保留字段（过滤掉 company_name_raw 及各子维度分）
ENTERPRISE_KB_FIELDS = [
    "company_name", "enterprise_categories",
    "level", "inferred_industry",
    "qual_score", "job_quality", "industry_fit_score",
    "avg_job_score", "job_count", "total_score",
    "priority", "source_list",
]


def main():
    parser = argparse.ArgumentParser(description="伯乐 Enterprise Output Formatter")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "enterprise", "processed"))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "enterprise", "output"))

    scored_path = os.path.join(processed_dir, "enterprise_scored.csv")
    if not os.path.exists(scored_path):
        print(f"错误: 未找到企业评分数据 {scored_path}")
        print("请先运行: python scripts/enterprise_score.py --config config.yaml")
        sys.exit(1)

    rows = load_csv(scored_path)
    print(f"加载: {len(rows)} 条企业评分数据")

    # 无 BOM 版 — 供知识库导入
    final_path = os.path.join(output_dir, "enterprise_basic.csv")
    write_csv(final_path, rows, ENTERPRISE_KB_FIELDS, encoding="utf-8")
    print(f"[OK] {final_path} ({len(rows)} 条, UTF-8 无 BOM — 知识库导入)")

    # 有 BOM 版 — 供 Excel 预览
    bom_path = os.path.join(output_dir, "enterprise_basic_bom.csv")
    write_csv(bom_path, rows, ENTERPRISE_KB_FIELDS, encoding="utf-8-sig")
    print(f"[OK] {bom_path} ({len(rows)} 条, UTF-8 有 BOM — 预览用)")

    # 生成数据报告
    report_path = os.path.join(output_dir, "enterprise_report.md")
    generate_report(rows, report_path)
    print(f"[OK] {report_path}")


def generate_report(rows: List[Dict], path: str):
    total = len(rows)
    if total == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 企业数据报告\n\n无数据。\n")
        return

    # 层级分布
    level_dist = {"A": 0, "B": 0, "C": 0}
    for r in rows:
        lv = r.get("level", "")
        if lv in level_dist:
            level_dist[lv] += 1

    # 优先级分布
    priority_dist = {"high": 0, "medium": 0, "low": 0}
    for r in rows:
        p = r.get("priority", "")
        if p in priority_dist:
            priority_dist[p] += 1

    # 资质分布
    cat_dist = {}
    for r in rows:
        for cat in r.get("enterprise_categories", "").split(";"):
            cat = cat.strip()
            if cat:
                cat_dist[cat] = cat_dist.get(cat, 0) + 1

    # 分数统计
    scores = []
    for r in rows:
        try:
            s = float(r.get("total_score", 0) or 0)
            scores.append(s)
        except (ValueError, TypeError):
            pass
    avg_score = sum(scores) / len(scores) if scores else 0

    today = date.today().isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 企业数据报告\n\n")
        f.write(f"生成时间: {today}\n\n")
        f.write("| 指标 | 数值 |\n")
        f.write("|------|:----:|\n")
        f.write(f"| 企业总数 | {total} |\n")
        f.write(f"| 平均总分 | {avg_score:.1f} |\n\n")

        f.write("### 三层级分布\n\n")
        f.write("| 层级 | 数量 | 占比 |\n")
        f.write("|------|:----:|:----:|\n")
        for lv in ("A", "B", "C"):
            cnt = level_dist.get(lv, 0)
            f.write(f"| {lv} | {cnt} | {cnt/total*100:.1f}% |\n")
        f.write("\n")

        f.write("### 优先级分布\n\n")
        f.write("| 优先级 | 数量 | 占比 |\n")
        f.write("|--------|:----:|:----:|\n")
        for p in ("high", "medium", "low"):
            cnt = priority_dist.get(p, 0)
            f.write(f"| {p} | {cnt} | {cnt/total*100:.1f}% |\n")
        f.write("\n")

        f.write("### 资质分布\n\n")
        f.write("| 资质类型 | 企业数 |\n")
        f.write("|----------|:-----:|\n")
        for cat, cnt in sorted(cat_dist.items(), key=lambda x: -x[1]):
            f.write(f"| {cat} | {cnt} |\n")


if __name__ == "__main__":
    main()
