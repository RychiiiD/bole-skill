"""
伯乐 — Output Formatter Script
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/format.py --config config.yaml
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


def get_all_fieldnames(rows: List[Dict]) -> List[str]:
    seen_fields = []
    for r in rows:
        for k in r:
            if k not in seen_fields:
                seen_fields.append(k)
    return seen_fields


SCORED_FIELDS = [
    "job_title", "company_name", "salary_range", "city",
    "education", "experience",
    "benefits", "company_industry",
    "company_size", "financing_stage", "source", "source_list",
    "total_score", "tag_relevance", "tag_target_company", "tag_need_deep",
]


def self_check():
    """Pipeline step guard — prevents execution if prerequisites are missing."""
    _base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _lock = os.path.join(_base, "data", ".verify_blocked")
    if os.path.exists(_lock):
        print("!! 错误: 上一步骤校验未通过，无法继续。")
        print("!! 排查问题后运行: rm data/.verify_blocked")
        print("!! 或使用 pipeline.py complete --skip-verify --skip-verify-ack 授权跳过")
        sys.exit(1)


def main():
    self_check()
    parser = argparse.ArgumentParser(description="伯乐 Output Formatter")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "processed"))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "output"))

    scored_path = os.path.join(processed_dir, "position_scored.csv")
    if not os.path.exists(scored_path):
        print(f"错误: 未找到评分数据 {scored_path}")
        print("请先运行: python scripts/score.py --config config.yaml")
        sys.exit(1)

    scored = load_csv(scored_path)
    print(f"加载: {len(scored)} 条评分数据")

    # 无 BOM 版 — 供 Dify/FastGPT 等知识库导入
    final_path = os.path.join(output_dir, "position_basic.csv")
    write_csv(final_path, scored, SCORED_FIELDS, encoding="utf-8")
    print(f"[OK] {final_path} ({len(scored)} 条, UTF-8 无 BOM — 知识库导入)")

    # 有 BOM 版 — 供 Excel 直接双击打开
    bom_path = os.path.join(output_dir, "position_basic_bom.csv")
    write_csv(bom_path, scored, SCORED_FIELDS, encoding="utf-8-sig")
    print(f"[OK] {bom_path} ({len(scored)} 条, UTF-8 有 BOM — 预览用)")

    # 生成数据报告
    report_path = os.path.join(output_dir, "position_report.md")
    generate_report(scored, report_path)
    print(f"[OK] {report_path}")


def generate_report(rows: List[Dict], path: str):
    total = len(rows)
    if total == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 岗位数据报告\n\n无数据。\n")
        return

    # 来源分布
    sources = {}
    for r in rows:
        src = (r.get("source_list") or r.get("source") or "").strip()
        if src:
            sources[src] = sources.get(src, 0) + 1

    # 评分分布
    score_tiers = {"≥ 80": 0, "60-79": 0, "40-59": 0, "< 40": 0}
    scores = []
    for r in rows:
        try:
            s = float(r.get("total_score", 0) or 0)
            scores.append(s)
            if s >= 80:
                score_tiers["≥ 80"] += 1
            elif s >= 60:
                score_tiers["60-79"] += 1
            elif s >= 40:
                score_tiers["40-59"] += 1
            else:
                score_tiers["< 40"] += 1
        except (ValueError, TypeError):
            pass
    avg_score = sum(scores) / len(scores) if scores else 0

    # 标签统计
    tag_relevance_y = sum(1 for r in rows if r.get("tag_relevance") == "Y")
    tag_need_deep_y = sum(1 for r in rows if r.get("tag_need_deep") == "Y")

    today = date.today().isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 岗位数据报告\n\n")
        f.write(f"生成时间: {today}\n\n")
        f.write("| 指标 | 数值 |\n")
        f.write("|------|:----:|\n")
        f.write(f"| 岗位总数 | {total} |\n")
        f.write(f"| 数据来源数 | {len(sources)} |\n")
        f.write(f"| 平均总分 | {avg_score:.1f} |\n\n")

        f.write("### 来源分布\n\n")
        f.write("| 来源 | 数量 |\n")
        f.write("|------|:----:|\n")
        for src, cnt in sorted(sources.items(), key=lambda x: -x[1]):
            f.write(f"| {src} | {cnt} |\n")
        f.write("\n")

        f.write("### 评分分布\n\n")
        f.write("| 区间 | 数量 |\n")
        f.write("|------|:----:|\n")
        for tier, cnt in score_tiers.items():
            f.write(f"| {tier} | {cnt} |\n")
        f.write("\n")

        f.write("### 标签统计\n\n")
        f.write("| 标签 | 是 | 否 |\n")
        f.write("|------|:--:|:--:|\n")
        f.write(f"| 岗位相关 (tag_relevance) | {tag_relevance_y} | {total - tag_relevance_y} |\n")
        f.write(f"| 需深挖 (tag_need_deep) | {tag_need_deep_y} | {total - tag_need_deep_y} |\n")


if __name__ == "__main__":
    main()
