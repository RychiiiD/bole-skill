"""
伯乐 — Enrich Final Output Formatter
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/enrich_format.py --config config.yaml

Reads position_final.csv, filters to KB-relevant fields,
outputs UTF-8 (no BOM) / UTF-8 BOM versions + data report.

Also importable from enrich_fill.py to re-run format after save.
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


# 知识库导入字段：用户检索最关心的信息，过滤技术参数
KB_FIELDS = [
    "job_title", "company_name", "salary_range", "city",
    "education", "experience", "benefits",
    "company_industry", "company_size", "financing_stage",
    "enterprise_categories", "source", "source_list",
    "final_score", "tag_relevance", "tag_need_deep",
    "filter_reason",
    "legal_disputes", "business_anomaly",
]


def check_stale(output_dir: str) -> bool:
    """检测 kb/preview 是否落后于 position_final.csv。

    通过比较 benefits 填充数作为代理指标（因为 benefits 是 enrich-fill 最后补充的字段）。
    如果 kb 落后，返回 True 触发自动同步。
    """
    final_path = os.path.join(output_dir, "position_final.csv")
    kb_path = os.path.join(output_dir, "position_final_kb.csv")

    if not os.path.exists(kb_path):
        return True  # 不存在即视为落后

    final_rows = load_csv(final_path)
    kb_rows = load_csv(kb_path)

    if len(final_rows) != len(kb_rows):
        return True

    final_filled = sum(1 for r in final_rows if r.get("benefits", "").strip())
    kb_filled = sum(1 for r in kb_rows if r.get("benefits", "").strip())

    return final_filled != kb_filled


def write_kb_versions(rows: List[Dict], output_dir: str):
    """写入知识库导入版 CSV（无 BOM + 有 BOM），仅保留 KB_FIELDS。"""
    saved = [{k: r.get(k, "") or "" for k in KB_FIELDS} for r in rows]
    base = os.path.join(output_dir, "position_final_kb.csv")
    write_csv(base, saved, KB_FIELDS, encoding="utf-8")
    bom = os.path.join(output_dir, "position_final_preview.csv")
    write_csv(bom, saved, KB_FIELDS, encoding="utf-8-sig")
    print(f"[OK] {base} ({len(saved)} 条, UTF-8 无 BOM, 知识库导入)")
    print(f"[OK] {bom} ({len(saved)} 条, UTF-8 有 BOM, 预览用)")


def generate_report(rows: List[Dict], path: str):
    total = len(rows)
    today = date.today().isoformat()

    # final_score 统计
    scores = []
    for r in rows:
        try:
            s = float(r.get("final_score", 0) or 0)
            scores.append(s)
        except (ValueError, TypeError):
            pass
    avg = sum(scores) / len(scores) if scores else 0

    # 资质分布
    cat_dist = {}
    for r in rows:
        for cat in r.get("enterprise_categories", "").split(";"):
            cat = cat.strip()
            if cat:
                cat_dist[cat] = cat_dist.get(cat, 0) + 1

    # 是否需要深挖
    deep_count = sum(1 for r in rows if r.get("tag_need_deep") == "Y")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 富化最终数据报告\n\n")
        f.write(f"生成时间: {today}\n\n")
        f.write("| 指标 | 数值 |\n")
        f.write("|------|:----:|\n")
        f.write(f"| 岗位总数 | {total} |\n")
        f.write(f"| 平均最终分 | {avg:.1f} |\n")
        f.write(f"| 需深挖岗位 | {deep_count} |\n\n")

        if cat_dist:
            f.write("### 企业资质分布\n\n")
            f.write("| 资质类型 | 岗位数 |\n")
            f.write("|----------|:-----:|\n")
            for cat, cnt in sorted(cat_dist.items(), key=lambda x: -x[1]):
                f.write(f"| {cat} | {cnt} |\n")


def main():
    parser = argparse.ArgumentParser(description="伯乐 Enrich Final Output Formatter")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "output"))

    final_path = os.path.join(output_dir, "position_final.csv")
    if not os.path.exists(final_path):
        print(f"错误: 未找到 {final_path}")
        print("请先运行: python scripts/final_filter.py --config config.yaml")
        sys.exit(1)

    rows = load_csv(final_path)
    print(f"加载: {len(rows)} 条最终数据")

    # ── 自愈约束：检测 kb/preview 是否落后于 final，落后则自动同步（并提示） ──
    if check_stale(output_dir):
        print("[AUTO-SYNC] position_final_kb.csv/preview 落后于 position_final.csv，自动同步中...")

    write_kb_versions(rows, output_dir)

    report_path = os.path.join(output_dir, "enrich_final_report.md")
    generate_report(rows, report_path)
    print(f"[OK] {report_path}")


if __name__ == "__main__":
    main()
