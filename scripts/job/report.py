"""
伯乐 — 数据报告生成器

从评分/最终数据生成全面的 Markdown 数据报告。
Usage: python scripts/job/report.py --config config.yaml
"""

import argparse
import csv
import os
import re
import sys
from datetime import date
from collections import Counter, defaultdict
from typing import Dict, List


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_csv(filepath: str) -> List[Dict]:
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _parse_salary(sal: str) -> tuple:
    """Parse salary range to (low, high) in thousands."""
    if not sal:
        return (0, 0)
    sal = sal.replace(",", "").replace("·", ".").strip()
    nums = re.findall(r'[\d.]+', sal.replace("k", "").replace("K", ""))
    if "k" in sal.lower() or "K" in sal:
        if len(nums) >= 2:
            return (float(nums[0]), float(nums[1]))
        elif len(nums) == 1:
            return (float(nums[0]), float(nums[0]))
    nums2 = re.findall(r'[\d.]+', sal)
    if len(nums2) >= 2:
        lo, hi = float(nums2[0]), float(nums2[1])
        if hi > 100:  # yuan → k
            lo, hi = lo / 1000, hi / 1000
        return (lo, hi)
    elif len(nums2) == 1:
        v = float(nums2[0])
        if v > 100:
            v /= 1000
        return (v, v)
    return (0, 0)


def _salary_mid(sal: str) -> float:
    lo, hi = _parse_salary(sal)
    return (lo + hi) / 2 if hi > 0 else lo


SALARY_BANDS = [
    ("< 5k", 0, 5),
    ("5-8k", 5, 8),
    ("8-12k", 8, 12),
    ("12-20k", 12, 20),
    ("20-30k", 20, 30),
    ("30-50k", 30, 50),
    ("> 50k", 50, 999),
]


def _salary_band(sal: str) -> str:
    mid = _salary_mid(sal)
    for label, lo, hi in SALARY_BANDS:
        if lo <= mid < hi:
            return label
    return "未知"


def _tag_yes(rows: List[Dict], field: str) -> int:
    return sum(1 for r in rows if r.get(field, "").strip().upper() in ("Y", "YES", "TRUE", "1"))


def _field_exists(rows: List[Dict], field: str) -> bool:
    return any(r.get(field, "").strip() for r in rows)


def _fmt_pct(n: int, total: int) -> str:
    if total == 0:
        return " - "
    return f"{n / total * 100:.1f}%"


def generate_report(rows: List[Dict], path: str, city: str = ""):
    total = len(rows)
    if total == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 岗位数据报告\n\n无数据。\n")
        return

    today = date.today().isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # ── Data preparation ──
    scores = [_safe_float(r.get("total_score") or r.get("final_score")) for r in rows]
    avg_score = sum(scores) / len(scores) if scores else 0
    median_score = sorted(scores)[len(scores) // 2] if scores else 0

    # ── Write ──
    with open(path, "w", encoding="utf-8") as f:
        # ═══════════════════ HEADER ═══════════════════
        f.write("# 岗位数据报告\n\n")
        title = city or ""
        f.write(f"**生成时间**: {today}")
        if title:
            f.write(f"  |  **目标城市**: {title}")
        f.write("\n\n")

        # ═══════════════════ 1. Executive Summary ═══════════════════
        f.write("---\n\n## 1. 总览\n\n")
        unique_companies = len(set(r.get("company_name", "").strip() for r in rows if r.get("company_name")))
        sources = set()
        for r in rows:
            src = (r.get("source_list") or r.get("source") or "").strip()
            if src:
                for s in src.split(";"):
                    s = s.strip()
                    if s:
                        sources.add(s)

        f.write("| 指标 | 数值 |\n")
        f.write("|------|:----:|\n")
        f.write(f"| 岗位总数 | {total} |\n")
        f.write(f"| 企业总数 | {unique_companies} |\n")
        f.write(f"| 数据来源 | {len(sources)} 个平台/渠道 |\n")
        f.write(f"| 平均分 | {avg_score:.1f} |\n")
        f.write(f"| 中位数分 | {median_score:.1f} |\n")
        f.write(f"| 最高分 | {max(scores):.0f} |\n")
        f.write(f"| 最低分 | {min(scores):.0f} |\n\n")

        # ═══════════════════ 2. Score Distribution ═══════════════════
        f.write("---\n\n## 2. 评分分布\n\n")
        tiers = [("≥ 80", 80, 999), ("60-79", 60, 80),
                 ("40-59", 40, 60), ("20-39", 20, 40), ("< 20", 0, 20)]
        f.write("| 区间 | 数量 | 占比 |\n")
        f.write("|------|:----:|:----:|\n")
        for label, lo, hi in tiers:
            cnt = sum(1 for s in scores if lo <= s < hi)
            f.write(f"| {label} | {cnt} | {_fmt_pct(cnt, total)} |\n")
        f.write("\n")

        # Top 10
        enriched = [{**r, "_score": _safe_float(r.get("total_score") or r.get("final_score"))} for r in rows]
        top10 = sorted(enriched, key=lambda x: -x["_score"])[:10]
        f.write("### Top 10 岗位\n\n")
        f.write("| # | 岗位 | 公司 | 薪资 | 评分 |\n")
        f.write("|---|------|------|:----:|:----:|\n")
        for i, r in enumerate(top10, 1):
            title = r.get("job_title", "?")[:20]
            company = r.get("company_name", "?")[:16]
            salary = r.get("salary_range", "?")
            score = f"{r['_score']:.0f}"
            f.write(f"| {i} | {title} | {company} | {salary} | {score} |\n")
        f.write("\n")

        # ═══════════════════ 3. Source Distribution ═══════════════════
        f.write("---\n\n## 3. 来源分布\n\n")
        src_counter = Counter()
        for r in rows:
            src = (r.get("source_list") or r.get("source") or "").strip()
            if src:
                for s in src.split(";"):
                    s = s.strip()
                    if s:
                        src_counter[s] += 1

        if src_counter:
            f.write("| 来源 | 数量 | 占比 |\n")
            f.write("|------|:----:|:----:|\n")
            for src, cnt in src_counter.most_common():
                f.write(f"| {src} | {cnt} | {_fmt_pct(cnt, total)} |\n")
            f.write("\n")

        # ═══════════════════ 4. Salary Analysis ═══════════════════
        if _field_exists(rows, "salary_range"):
            f.write("---\n\n## 4. 薪资分析\n\n")
            band_counter = Counter()
            for r in rows:
                band_counter[_salary_band(r.get("salary_range", ""))] += 1
            f.write("| 薪资区间 | 数量 | 占比 |\n")
            f.write("|----------|:----:|:----:|\n")
            for label, _, _ in SALARY_BANDS:
                cnt = band_counter.get(label, 0)
                f.write(f"| {label} | {cnt} | {_fmt_pct(cnt, total)} |\n")

            mids = [_salary_mid(r.get("salary_range", "")) for r in rows if r.get("salary_range")]
            if mids:
                avg_sal = sum(mids) / len(mids)
                f.write(f"\n| 指标 | 数值 |\n")
                f.write(f"|------|:----:|\n")
                f.write(f"| 薪资中位数 (k) | {sorted(mids)[len(mids)//2]:.1f} |\n")
                f.write(f"| 薪资均值 (k) | {avg_sal:.1f} |\n")
                f.write(f"| 最高薪资 (k) | {max(mids):.1f} |\n\n")

        # ═══════════════════ 5. Company Analysis ═══════════════════
        f.write("---\n\n## 5. 企业分析\n\n")

        # Top companies by job count
        company_jobs = Counter(r.get("company_name", "").strip() for r in rows if r.get("company_name"))
        if company_jobs:
            f.write("### 招聘量 Top 10 企业\n\n")
            f.write("| # | 企业 | 岗位数 |\n")
            f.write("|---|------|:----:|\n")
            for i, (company, cnt) in enumerate(company_jobs.most_common(10), 1):
                f.write(f"| {i} | {company} | {cnt} |\n")
            f.write("\n")

        # Industry distribution
        if _field_exists(rows, "company_industry"):
            ind_counter = Counter()
            for r in rows:
                ind = r.get("company_industry", "").strip()
                if ind:
                    for i in re.split(r'[/;；、]', ind):
                        i = i.strip()
                        if i:
                            ind_counter[i] += 1
            if ind_counter:
                f.write("### 行业分布\n\n")
                f.write("| 行业 | 出现次数 |\n")
                f.write("|------|:-------:|\n")
                for ind, cnt in ind_counter.most_common(10):
                    f.write(f"| {ind} | {cnt} |\n")
                f.write("\n")

        # Company size
        if _field_exists(rows, "company_size"):
            size_counter = Counter()
            for r in rows:
                sz = r.get("company_size", "").strip()
                if sz:
                    size_counter[sz] += 1
            if size_counter:
                f.write("### 企业规模分布\n\n")
                f.write("| 规模 | 数量 |\n")
                f.write("|------|:----:|\n")
                for sz, cnt in size_counter.most_common():
                    f.write(f"| {sz} | {cnt} |\n")
                f.write("\n")

        # Enterprise qualification coverage (if enrich data exists)
        if _field_exists(rows, "enterprise_categories"):
            f.write("### 企业资质覆盖\n\n")
            qual_rows = [r for r in rows if r.get("enterprise_categories", "").strip()]
            f.write(f"| 指标 | 数值 |\n")
            f.write(f"|------|:----:|\n")
            f.write(f"| 有资质信息的企业 | {len(set(r.get('company_name','') for r in qual_rows if r.get('company_name')))} 家 |\n")
            f.write(f"| 有资质信息的岗位 | {len(qual_rows)} 条 |\n\n")

        if _field_exists(rows, "benefits"):
            benefits_cnt = sum(1 for r in rows if r.get("benefits", "").strip())
            f.write(f"| 有福利信息的岗位 | {benefits_cnt} | {_fmt_pct(benefits_cnt, total)} |\n")
            f.write("\n")

        # ═══════════════════ 6. Requirements ═══════════════════
        f.write("---\n\n## 6. 岗位要求\n\n")

        if _field_exists(rows, "education"):
            edu_counter = Counter()
            for r in rows:
                edu = r.get("education", "").strip()
                if edu:
                    edu_counter[edu] += 1
            if edu_counter:
                f.write("### 学历要求\n\n")
                f.write("| 学历 | 数量 | 占比 |\n")
                f.write("|------|:----:|:----:|\n")
                for edu, cnt in edu_counter.most_common():
                    f.write(f"| {edu} | {cnt} | {_fmt_pct(cnt, total)} |\n")
                f.write("\n")

        if _field_exists(rows, "experience"):
            exp_counter = Counter()
            for r in rows:
                exp = r.get("experience", "").strip()
                if exp:
                    exp_counter[exp] += 1
            if exp_counter:
                f.write("### 经验要求\n\n")
                f.write("| 经验 | 数量 | 占比 |\n")
                f.write("|------|:----:|:----:|\n")
                for exp, cnt in exp_counter.most_common():
                    f.write(f"| {exp} | {cnt} | {_fmt_pct(cnt, total)} |\n")
                f.write("\n")

        # ═══════════════════ 7. Quality Tags ═══════════════════
        f.write("---\n\n## 7. 质量标签\n\n")
        f.write("| 标签 | 是 | 否 | 通过率 |\n")
        f.write("|------|:--:|:--:|:------:|\n")

        relevance_y = _tag_yes(rows, "tag_relevance")
        f.write(f"| 岗位相关 | {relevance_y} | {total - relevance_y} | {_fmt_pct(relevance_y, total)} |\n")

        deep_y = _tag_yes(rows, "tag_need_deep")
        f.write(f"| 需深挖 | {deep_y} | {total - deep_y} | {_fmt_pct(deep_y, total)} |\n")

        if _field_exists(rows, "quality"):
            qual_y = _tag_yes(rows, "quality")
            f.write(f"| 企业质量加分 | {qual_y} | {total - qual_y} | {_fmt_pct(qual_y, total)} |\n")

        if _field_exists(rows, "enterprise_categories"):
            ec_y = sum(1 for r in rows if r.get("enterprise_categories", "").strip())
            f.write(f"| 企业资质匹配 | {ec_y} | {total - ec_y} | {_fmt_pct(ec_y, total)} |\n")

        f.write("\n")

        # ═══════════════════ FOOTER ═══════════════════
        f.write("---\n\n")
        f.write(f"*报告由伯乐自动生成 | {today} | {total} 条岗位*\n")

    print(f"[OK] {path}")


def main():
    parser = argparse.ArgumentParser(description="伯乐 — 数据报告生成器")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    base_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    output_dir = os.path.join(base_dir, "data", "position", "output")

    # Try enriched final data first, fall back to scored data
    candidates = [
        os.path.join(output_dir, "position_final.csv"),
        os.path.join(output_dir, "position_enriched.csv"),
        os.path.join(base_dir, "data", "position", "processed", "position_scored.csv"),
    ]

    rows = []
    source_path = ""
    for p in candidates:
        if os.path.exists(p):
            rows = load_csv(p)
            source_path = p
            break

    if not rows:
        print("错误: 未找到岗位数据文件（尝试了 position_final / position_enriched / position_scored）",
              file=sys.stderr)
        sys.exit(1)

    city = config.get("city", "")
    print(f"加载: {len(rows)} 条 ({os.path.basename(source_path)})")
    report_path = os.path.join(output_dir, "position_report.md")
    generate_report(rows, report_path, city=city)


if __name__ == "__main__":
    main()
