"""
伯乐 — Final Filter: 标记低质量岗位，不删行，全部保留
Usage:
  python scripts/enrich/final_filter.py --config config.yaml [--input position_enriched.csv] [--output position_final.csv]

在 enrich + enrich-fill 完成后执行，基于企业画像数据标记：
  - 个体工商户（公司名含特定后缀）
  - 无企业数据的微小企业（company_size 极小/空, enterprise_categories 空）
  - 兼职/时薪类低质量岗位（salary_range 含"元/时""日薪"）

所有行保留在输出中，被标记的行带 filter_reason 字段说明原因。
"""
import argparse
import csv
import json
import os
import re
import sys
from typing import Dict, List


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_csv(filepath: str, encoding: str = "utf-8-sig") -> List[Dict]:
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv(filepath: str, rows: List[Dict], fieldnames: List[str],
              encoding: str = "utf-8"):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            out = {k: row.get(k, "") or "" for k in fieldnames}
            w.writerow(out)


def chinese_chars(s: str) -> int:
    """Count Chinese characters in string."""
    return len(re.findall(r'[一-鿿]', s or ""))


def is_individual_business_name(company_name: str) -> str:
    """Check if company name matches individual business patterns.
    Returns the matched reason string, or None if not matched.
    """
    name = (company_name or "").strip()
    if not name:
        return ""

    # Ends with specific shop/individual business suffixes
    shop_suffixes = [
        "店", "馆", "行", "坊", "庄", "栈",
    ]
    for suffix in shop_suffixes:
        if name.endswith(suffix):
            # "店" suffix is very strong indicator (商贸店, 理疗馆, 饭店 etc.)
            return f"个体工商户：公司名以'{suffix}'结尾"

    # Other strong indicators
    if "经营部" in name:
        return "个体工商户：公司名含'经营部'"
    if "服务部" in name:
        return "个体工商户：公司名含'服务部'"
    if "批发部" in name:
        return "个体工商户：公司名含'批发部'"
    if "经销处" in name:
        return "个体工商户：公司名含'经销处'"

    # Truncated names (containing "..." at end) — almost always small shops
    if name.endswith("..."):
        return "个体工商户：公司名截断（疑似个体户）"

    return ""


def is_hourly_or_daily_wage(salary_range: str) -> str:
    """Check if salary is hourly or daily wage (兼职/低质量).
    Returns the matched reason string, or None.
    """
    if not salary_range:
        return ""
    if "元/时" in salary_range or "元/小时" in salary_range:
        return "兼职岗位：时薪制薪资"
    if "日薪" in salary_range:
        return "兼职岗位：日薪制薪资"
    return ""


def tag_rows(rows: List[Dict], config: dict) -> List[Dict]:
    """Tag low-quality positions with filter_reason instead of deleting them.

    All rows are preserved in the output. Each row gets a `filter_reason` field
    if it matches any low-quality pattern, allowing users to decide what to
    investigate further.
    """
    company_cfg = config.get("scoring", {}).get("company_filter", {})
    ef_cfg = config.get("scoring", {}).get("enterprise_filter", {})

    reasons = {}

    for row in rows:
        filter_reason = ""

        # 1) 个体工商户后缀检测
        name = row.get("company_name", "").strip()
        if not filter_reason:
            reason = is_individual_business_name(name)
            if reason:
                filter_reason = reason

        # 2) 短名过滤（补漏）
        if not filter_reason:
            min_cn = company_cfg.get("min_chinese_chars", 0)
            if min_cn > 0 and chinese_chars(name) < min_cn:
                filter_reason = f"个体户/低质企业：公司名中文字符数({chinese_chars(name)})低于阈值({min_cn})"

        # 3) 时薪日薪检查
        if not filter_reason and ef_cfg.get("exclude_hourly_wage", True):
            sal = row.get("salary_range", "").strip()
            reason = is_hourly_or_daily_wage(sal)
            if reason:
                filter_reason = reason

        if filter_reason:
            row["filter_reason"] = filter_reason
            reasons[filter_reason] = reasons.get(filter_reason, 0) + 1

    # Print audit report
    total = len(rows)
    tagged = sum(1 for r in rows if r.get("filter_reason"))
    print("=" * 50)
    print(f"  企业质量标记: {tagged}/{total} 条被标记（全部保留在输出中）")
    print("=" * 50)
    if reasons:
        print("\n  标记原因分布:")
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count} 条")
        print("\n  被标记企业样本（每种原因展示前 3 家）:")
        shown_reasons = {}
        for r in rows:
            reason = r.get("filter_reason", "")
            if not reason:
                continue
            if shown_reasons.get(reason, 0) >= 3:
                continue
            if reason not in shown_reasons:
                print(f"\n    [{reason}]")
            print(f"      · {r.get('company_name', '')} | {r.get('job_title', '')[:20]}")
            shown_reasons[reason] = shown_reasons.get(reason, 0) + 1
    print()

    return rows


def main():
    parser = argparse.ArgumentParser(description="伯乐 Final Filter")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--input", help="输入 CSV (默认 data/position/output/position_enriched.csv)")
    parser.add_argument("--output", help="输出 CSV (默认 data/position/output/position_final.csv)")
    args = parser.parse_args()

    config = load_config(args.config)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "output"))

    input_path = args.input or os.path.join(output_dir, "position_enriched.csv")
    if not os.path.exists(input_path):
        print(f"错误: 未找到 {input_path}")
        sys.exit(1)

    rows = load_csv(input_path)
    if not rows:
        print("错误: CSV 为空")
        sys.exit(1)

    print(f"加载: {len(rows)} 条岗位")
    fieldnames = list(rows[0].keys())

    # Ensure filter_reason field exists
    if "filter_reason" not in fieldnames:
        fieldnames.append("filter_reason")

    kept = tag_rows(rows, config)

    # 软降级：输出全部行（含被标记的），用户可追问被标记企业的详情
    # 小微企业查不到信息只是"暂无数据"而非"低质"，filter_reason 仅标记
    # 明确的非目标岗位（时薪/个体户），不标记查不到信息的小微企业
    output_path = args.output or os.path.join(output_dir, "position_final.csv")
    write_csv(output_path, kept, fieldnames)
    tagged = sum(1 for r in kept if r.get("filter_reason"))
    print(f"已保存: {output_path} ({len(kept)} 条, 其中 {tagged} 条被标记为低质)")



if __name__ == "__main__":
    main()
