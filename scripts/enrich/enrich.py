"""
伯乐 — Enterprise Enrichment Script
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/enrich.py --config config.yaml

Reads position_scored.csv + enterprise_scored.csv, performs strict left join
on company_name, computes company_quality_bonus from enterprise tier/qualifications,
outputs position_enriched.csv with enriched enterprise categories and final_score.
"""

import argparse
import csv
import os
import re
import sys
from datetime import date
from typing import Dict, List, Optional


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
              encoding: str = "utf-8-sig"):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            out = {k: row.get(k, "") or "" for k in fieldnames}
            w.writerow(out)


def normalize_company_name(name: str) -> str:
    """Normalize company name for matching. Same logic as enterprise_clean.py."""
    if not name:
        return ""
    n = name.strip()

    # Fullwidth ASCII to halfwidth
    result = []
    for ch in n:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            result.append(chr(code - 0xFEE0))
        else:
            result.append(ch)
    n = "".join(result)

    # Normalize brackets
    n = n.replace("（", "(").replace("）", ")")
    n = n.replace("【", "[").replace("】", "]")

    # Normalize dashes
    n = n.replace("—", "-").replace("～", "-").replace("~", "-")

    # Normalize spaces
    n = n.replace("　", " ").strip()

    # Remove company suffix for matching
    n = re.sub(r"[（(]?有限[公合]?[司同][)）]?", "", n)
    n = re.sub(r"[（(]?股份?有限[公合]?[司同][)）]?", "", n)

    # Collapse
    n = re.sub(r"\s+", "", n)
    n = n.strip("，, \t")
    n = n.lower()

    return n


def build_enterprise_lookup(enterprise_rows: List[Dict]) -> Dict[str, Dict]:
    """Build lookup dict with both exact and normalized name keys."""
    lookup = {}
    norm_pairs = []
    seen_norms = set()
    for row in enterprise_rows:
        name = (row.get("company_name") or "").strip()
        if not name:
            continue
        lookup[name] = row
        norm = normalize_company_name(name)
        if norm and norm != name:
            if norm not in lookup:
                lookup[norm] = row
        if norm and len(norm) >= 2 and norm not in seen_norms:
            seen_norms.add(norm)
            norm_pairs.append((norm, name))
    return lookup, norm_pairs


# ── Company quality bonus tiers ──

QUAL_BONUS_TIERS = [
    ("专精特新小巨人", 10, "国家级专精特新小巨人"),
    ("单项冠军", 10, "制造业单项冠军"),
    ("独角兽", 8, "独角兽企业"),
    ("专精特新", 6, "专精特新企业"),
    ("高新技术企业", 6, "高新技术企业"),
    ("瞪羚企业", 6, "瞪羚企业"),
    ("雏鹰企业", 4, "雏鹰企业"),
    ("科技型中小企业", 2, "科技型中小企业"),
]

# Level-based discount: A=full, C=reduced, B=no qual bonus
LEVEL_DISCOUNT = {
    "A": 1.0,
    "C": 0.5,
}


def compute_quality_bonus(enterprise_categories: str, level: str = "",
                           job_quality: str = "", job_count: str = "") -> tuple:
    """Compute company quality bonus and reason using enterprise scoring data.

    Uses enterprise level (A/B/C) to modulate qualification-based bonus:
      - Level A (双在册):  full bonus (1.0x)
      - Level C (仅资质):  reduced bonus (0.5x) — active status unknown
      - Level B (仅岗位):  no qualification bonus; uses job_quality signal instead

    Returns (bonus_score: int, reason: str).
    """
    level = level or ""
    try:
        jq = float(job_quality or 0)
    except (ValueError, TypeError):
        jq = 0

    if level == "B":
        # Level B: no known qualification, use job quality signal
        if jq >= 3.5:
            return 2, "岗位质量高+2分"
        return 0, ""

    # Level A or C: compute from enterprise categories
    if not enterprise_categories or not enterprise_categories.strip():
        return 0, ""

    best_bonus = 0
    best_reason = ""
    for kw, bonus, label in QUAL_BONUS_TIERS:
        if kw in enterprise_categories:
            if bonus > best_bonus:
                best_bonus = bonus
                best_reason = f"{label}+{bonus}分"

    if best_bonus == 0:
        return 0, ""

    # Apply level discount
    discount = LEVEL_DISCOUNT.get(level, 1.0)
    if discount < 1.0:
        adjusted = max(1, int(best_bonus * discount))
        reason = f"{best_reason}({level}层折{adjusted}分)"
        return adjusted, reason

    return best_bonus, best_reason


def enrich_jobs(job_rows: List[Dict], enterprise_rows: List[Dict]) -> List[Dict]:
    """Perform strict left join: jobs ← enterprise on company_name."""
    lookup, norm_pairs = build_enterprise_lookup(enterprise_rows)
    matched = 0

    for job in job_rows:
        job_name = (job.get("company_name") or "").strip()
        if not job_name:
            job["enterprise_categories"] = ""
            job["has_enterprise_data"] = "false"
            job["company_quality_bonus"] = "0"
            job["company_quality_reason"] = ""
            job["final_score"] = job.get("total_score", "")
            continue

        # Phase 1: exact match
        ent = lookup.get(job_name)

        # Phase 2: normalized match
        if ent is None:
            norm = normalize_company_name(job_name)
            if norm:
                ent = lookup.get(norm)

        # Phase 3: substring containment
        if ent is None:
            job_norm = normalize_company_name(job_name)
            if job_norm and len(job_norm) >= 3:
                for ent_norm, ent_orig in norm_pairs:
                    if len(ent_norm) < 3:
                        continue
                    shorter, longer = (job_norm, ent_norm) if len(job_norm) <= len(ent_norm) else (ent_norm, job_norm)
                    if shorter in longer:
                        ent = lookup.get(ent_orig)
                        break

        if ent is not None:
            # Enterprise qualification categories
            job["enterprise_categories"] = ent.get("enterprise_categories", "")

            # Company quality bonus using enterprise scoring signals
            bonus, reason = compute_quality_bonus(
                job["enterprise_categories"],
                level=ent.get("level", ""),
                job_quality=ent.get("job_quality", ""),
                job_count=ent.get("job_count", ""),
            )
            job["company_quality_bonus"] = str(bonus)
            job["company_quality_reason"] = reason

            job["has_enterprise_data"] = "true"
            matched += 1
        else:
            job["enterprise_categories"] = ""
            job["has_enterprise_data"] = "false"
            job["company_quality_bonus"] = "0"
            job["company_quality_reason"] = ""

        # Phase 40: final score = total_score + company_quality_bonus
        try:
            ts = float(job.get("total_score", 0) or 0)
            cb = float(job.get("company_quality_bonus", 0) or 0)
            job["final_score"] = str(round(ts + cb, 1))
        except (ValueError, TypeError):
            job["final_score"] = job.get("total_score", "")

    print(f"  匹配企业数据: {matched}/{len(job_rows)} 条岗位")
    return job_rows


# Basic field order (matching format.py SCORED_FIELDS), enterprise fields appended after
BASIC_FIELDS = [
    "job_title", "company_name", "salary_range", "city",
    "education", "experience",
    "benefits", "company_industry",
    "company_size", "financing_stage", "source", "search_keyword",
    "collect_time", "source_list", "salary_score", "exp_score",
    "edu_score", "relevance_score", "total_score",
    "tag_relevance", "tag_target_company", "tag_need_deep",
]


def get_all_fieldnames(rows: List[Dict]) -> List[str]:
    seen = BASIC_FIELDS.copy()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.append(k)
    return seen


def main():
    parser = argparse.ArgumentParser(description="伯乐 Enterprise Enrichment")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "processed"))
    enterprise_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "enterprise"))

    # Load job data
    scored_path = os.path.join(processed_dir, "position_scored.csv")
    if not os.path.exists(scored_path):
        print(f"错误: 未找到岗位数据 {scored_path}")
        print("请先运行: python scripts/score.py --config config.yaml")
        sys.exit(1)

    job_rows = load_csv(scored_path)
    print(f"加载岗位数据: {len(job_rows)} 条")

    # Load enterprise scored data (includes level, qual_score, job_quality, etc.)
    enterprise_path = os.path.join(enterprise_dir, "processed", "enterprise_scored.csv")
    enterprise_rows = load_csv(enterprise_path)
    print(f"加载企业数据: {len(enterprise_rows)} 条")

    if not enterprise_rows:
        print("警告: 未找到企业数据，跳过富化")
        for r in job_rows:
            r["enterprise_categories"] = ""
            r["has_enterprise_data"] = "false"

    # Enrich
    enriched = enrich_jobs(job_rows, enterprise_rows)

    # 按 final_score 降序排列（双侧评分后重新排序）
    enriched.sort(key=lambda r: -float(r.get("final_score", 0) or 0))

    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "output"))

    fieldnames = get_all_fieldnames(enriched)

    # 无 BOM 版 — 供 Dify/FastGPT 等知识库导入
    enrich_path = os.path.join(output_dir, "position_enriched.csv")
    write_csv(enrich_path, enriched, fieldnames, encoding="utf-8")
    print(f"已保存: {enrich_path} ({len(enriched)} 条, 含企业字段, UTF-8 无 BOM — 过程文件)")

    # Report
    eco_count = sum(1 for r in enriched if r.get("has_enterprise_data") == "true")
    qual_count = sum(1 for r in enriched if r.get("enterprise_categories", "").strip())
    bonus_count = sum(1 for r in enriched if int(r.get("company_quality_bonus", 0) or 0) > 0)
    avg_bonus = 0
    if bonus_count > 0:
        avg_bonus = sum(int(r.get("company_quality_bonus", 0) or 0) for r in enriched if int(r.get("company_quality_bonus", 0) or 0) > 0) / bonus_count
    print(f"\n  企业匹配: {eco_count} 条")
    print(f"  有资质标签: {qual_count} 条")
    print(f"  有资质加分: {bonus_count} 条 (平均 +{avg_bonus:.1f} 分)")

    if enriched:
        print("\nTop 5 (按 final_score 降序):")
        for r in enriched[:5]:
            eco = r.get("enterprise_categories", "")[:30]
            fs = r.get("final_score", "0")
            print(f"  [{fs:>4s}] {r.get('company_name', ''):20s} | {eco:30s}")

    # 生成富化报告
    report_path = os.path.join(output_dir, "enrich_report.md")
    generate_enrich_report(enriched, report_path)
    print(f"[OK] {report_path}")


def generate_enrich_report(rows: List[Dict], path: str):
    total = len(rows)
    eco_count = sum(1 for r in rows if r.get("has_enterprise_data") == "true")
    qual_count = sum(1 for r in rows if r.get("enterprise_categories", "").strip())
    bonus_count = sum(1 for r in rows if int(r.get("company_quality_bonus", 0) or 0) > 0)
    match_rate = eco_count / total * 100 if total > 0 else 0

    # 分类统计
    cat_dist = {}
    bonus_dist = {}
    for r in rows:
        cats = (r.get("enterprise_categories") or "").split(";")
        for c in cats:
            c = c.strip()
            if c:
                cat_dist[c] = cat_dist.get(c, 0) + 1
        b = r.get("company_quality_bonus", "0")
        if b and b != "0":
            bonus_dist[b] = bonus_dist.get(b, 0) + 1

    today = date.today().isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 富化报告\n\n")
        f.write(f"生成时间: {today}\n\n")
        f.write("| 指标 | 数值 |\n")
        f.write("|------|:----:|\n")
        f.write(f"| 岗位总数 | {total} |\n")
        f.write(f"| 匹配企业数据 | {eco_count} |\n")
        f.write(f"| 匹配率 | {match_rate:.1f}% |\n")
        f.write(f"| 有资质标签 | {qual_count} |\n")
        f.write(f"| 有资质加分 | {bonus_count} |\n\n")

        if bonus_dist:
            f.write("### 资质加分分布\n\n")
            f.write("| 加分 | 岗位数 |\n")
            f.write("|------|:-----:|\n")
            for b, cnt in sorted(bonus_dist.items(), key=lambda x: -int(x[0])):
                f.write(f"| +{b} | {cnt} |\n")
            f.write("\n")

        if cat_dist:
            f.write("### 资质标签分布\n\n")
            f.write("| 资质类型 | 覆盖岗位数 |\n")
            f.write("|----------|:----------:|\n")
            for cat, cnt in sorted(cat_dist.items(), key=lambda x: -x[1]):
                f.write(f"| {cat} | {cnt} |\n")


if __name__ == "__main__":
    main()
