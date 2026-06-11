"""
伯乐 — Enterprise Scoring Script (Phase 40)
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/enterprise_score.py --config config.yaml

Three-tier classification + industry_fit scoring.
  Level A (both):  qual*4 + job_quality*4 + industry_fit*2
  Level B (job only): job_quality*7 + industry_fit*3  (pre-filter + verify first)
  Level C (qual only): qual*6 + industry_fit*4

All tiers normalized to 0-50, sorted by (level_priority, total_score desc).
Priority: high>=30, medium>=15, low<15.
"""

import argparse
import csv
import json
import os
import re
import sys
from typing import Dict, List, Tuple

# ── Config / I/O helpers ──

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

def normalize(name: str) -> str:
    if not name:
        return ""
    n = name.strip().lower()
    for ch in "，。、：；！？（）【】":
        n = n.replace(ch, "")
    return n.replace(" ", "")

# ── Qualification tier mapping ──

QUAL_TIERS = {
    "专精特新小巨人": 5,
    "单项冠军": 5,
    "独角兽": 4,
    "专精特新": 3,
    "高新技术企业": 3,
    "瞪羚企业": 3,
    "雏鹰企业": 2,
    "科技型中小企业": 1,
}
QUAL_TIER_LABELS = {
    5: "专精特新小巨人/单项冠军",
    4: "独角兽",
    3: "专精特新/高新技术企业/瞪羚",
    2: "雏鹰企业",
    1: "科技型中小企业",
    0: "无资质",
}

# ── Industry inference (name-based heuristics) ──

INDUSTRY_PATTERNS = [
    (["软件", "计算机", "信息技术", "IT"], "软件/信息技术"),
    (["互联网", "网络科技", "网络技术"], "互联网/网络"),
    (["人工智能", "AI", "智能科技", "机器人", "大模型"], "人工智能"),
    (["数据", "大数据", "云"], "数据/云计算"),
    (["汽车", "汽配", "车辆", "整车", "零部件", "一汽"], "汽车制造"),
    (["光电", "光学", "光电子", "激光", "精密仪器"], "光电/精密仪器"),
    (["医药", "生物", "医疗", "制药"], "医药生物"),
    (["银行", "保险", "金融", "证券", "基金", "投资"], "金融服务"),
    (["教育", "培训", "学校", "学院", "大学"], "教育培训"),
    (["通信", "5G", "电信", "移动", "联通"], "通信技术"),
    (["电子", "半导体", "芯片", "集成电路"], "电子/半导体"),
    (["航天", "航空", "军工"], "航空航天/军工"),
    (["能源", "电力", "新能源", "光伏", "风电"], "能源/新能源"),
    (["环保", "环境", "节能", "绿色"], "环保/节能"),
    (["设计", "广告", "传媒", "营销"], "设计/传媒"),
    (["物流", "供应链", "快递", "运输"], "物流/供应链"),
    (["食品", "农业", "农产品", "牧业"], "食品/农业"),
    (["建筑", "工程", "建设", "施工"], "建筑/工程"),
    (["房地产", "置业", "物业"], "房地产/物业"),
]

def infer_industry(company_name: str) -> str:
    """Infer industry from company name using keyword patterns."""
    if not company_name:
        return ""
    name_lower = company_name.lower()
    for keywords, industry in INDUSTRY_PATTERNS:
        for kw in keywords:
            if kw.lower() in name_lower:
                return industry
    return ""

# ── Industry fit scoring via .industry_keywords.json ──

def load_industry_keywords(enterprise_dir: str) -> dict:
    kw_path = os.path.join(enterprise_dir, ".industry_keywords.json")
    if os.path.exists(kw_path):
        with open(kw_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"target_kw": [], "exclude_kw": [], "reasoning": ""}

def score_industry_fit(company_name: str, industry_kw: dict) -> Tuple[float, str]:
    """Score 0-5: baseline 3, +1 per target match, -1 per exclude match."""
    if not company_name or not industry_kw:
        return 3.0, ""

    name = company_name.lower()
    target = [kw.lower() for kw in industry_kw.get("target_kw", [])]
    exclude = [kw.lower() for kw in industry_kw.get("exclude_kw", [])]

    matched_target = [kw for kw in target if kw in name]
    matched_exclude = [kw for kw in exclude if kw in name]

    score = 3.0 + len(matched_target) - len(matched_exclude)
    score = max(0.0, min(5.0, score))

    parts = []
    if matched_target:
        parts.append(f"目标赛道:{','.join(matched_target)}")
    if matched_exclude:
        parts.append(f"排除赛道:{','.join(matched_exclude)}")
    detail = "; ".join(parts) if parts else ""

    return score, detail

# ── Job quality composite ──

def compute_job_quality(job_rows: List[Dict], company_norm: str) -> Tuple[float, float, int, float]:
    """Compute job quality metrics for a company.
    Returns (avg_total_score, max_salary_score, job_count, composite_0_5).
    """
    total_sum = 0.0
    max_sal = 0.0
    count = 0
    for j in job_rows:
        if normalize(j.get("company_name", "")) == company_norm:
            count += 1
            total_sum += float(j.get("total_score", 0) or 0)
            sal = float(j.get("salary_score", 0) or 0)
            if sal > max_sal:
                max_sal = sal

    if count == 0:
        return 0.0, 0.0, 0, 0.0

    avg = total_sum / count
    # Composite 0-5: avg_total/20 *0.5 + max_salary*0.3 + min(count,10)/2*0.2
    avg_part = (avg / 20.0) * 0.5       # avg 0-100 → 0-5, *0.5 → 0-2.5
    sal_part = max_sal * 0.3            # 1-5, *0.3 → 0.3-1.5
    cnt_part = (min(count, 10) / 2.0) * 0.2  # 1-10 → 0.5-5, *0.2 → 0.1-1.0
    composite = min(5.0, avg_part + sal_part + cnt_part)

    return avg, max_sal, count, round(composite, 2)

# ── Main scoring logic ──

def score_enterprises(enterprise_rows: List[Dict], job_rows: List[Dict],
                      industry_kw: dict) -> Tuple[List[Dict], Dict, Dict, Dict]:
    """Three-tier scoring. Returns (scored_list, tier_stats, b_stats, c_dist)."""

    # Build set of job company names (normalized)
    job_norms = set()
    job_company_names = {}
    for j in job_rows:
        name = (j.get("company_name") or "").strip()
        if name:
            norm = normalize(name)
            job_norms.add(norm)
            job_company_names[norm] = name

    # Build set of qual company names (normalized)
    qual_norms = set()
    for e in enterprise_rows:
        name = (e.get("company_name") or "").strip()
        if name:
            qual_norms.add(normalize(name))

    # Precompute job quality for each enterprise
    qual_map = {}
    for e in enterprise_rows:
        name = (e.get("company_name") or "").strip()
        if not name:
            continue
        norm = normalize(name)
        qual_map[norm] = e

    # Three-tier classification
    a_list, b_list, c_list = [], [], []
    b_prefilter_stats = {
        "total": 0, "low_salary": 0, "single_job_low": 0, "stale": 0
    }

    # Process all enterprises from qual lists
    for norm, e in qual_map.items():
        name = e.get("company_name", "")
        in_job = norm in job_norms
        qual_cats = (e.get("enterprise_categories") or "")
        qual_score = 0
        for cat in qual_cats.split(";"):
            cat = cat.strip()
            for kw, val in QUAL_TIERS.items():
                if kw in cat:
                    qual_score = max(qual_score, val)

        avg_ts, max_sal, jcount, jq = compute_job_quality(job_rows, norm)
        ind_fit, ind_detail = score_industry_fit(name, industry_kw)
        inferred = infer_industry(name)

        if in_job:
            # Level A: both qual + job
            total = qual_score * 4 + jq * 4 + ind_fit * 2
            entry = {
                "company_name": name,
                "company_name_raw": e.get("company_name_raw", name),
                "enterprise_categories": qual_cats,
                "level": "A",
                "inferred_industry": inferred,
                "qual_score": str(qual_score),
                "job_quality": str(jq),
                "industry_fit_score": str(ind_fit),
                "industry_fit_detail": ind_detail,
                "avg_job_score": str(round(avg_ts, 1)),
                "job_count": str(jcount),
                "total_score": str(round(total, 1)),
                "source_list": e.get("source_list", ""),
            }
            entry["priority"] = "high" if total >= 30 else ("medium" if total >= 15 else "low")
            a_list.append(entry)
        else:
            # Level C: qual only
            total = qual_score * 6 + ind_fit * 4
            entry = {
                "company_name": name,
                "company_name_raw": e.get("company_name_raw", name),
                "enterprise_categories": qual_cats,
                "level": "C",
                "inferred_industry": inferred,
                "qual_score": str(qual_score),
                "job_quality": "0",
                "industry_fit_score": str(ind_fit),
                "industry_fit_detail": ind_detail,
                "avg_job_score": "0",
                "job_count": "0",
                "total_score": str(round(total, 1)),
                "source_list": e.get("source_list", ""),
            }
            entry["priority"] = "high" if total >= 30 else ("medium" if total >= 15 else "low")
            c_list.append(entry)

    # Process job-only companies (Level B)
    for norm in job_norms:
        if norm in qual_map:
            continue  # already in A
        name = job_company_names.get(norm, "")
        avg_ts, max_sal, jcount, jq = compute_job_quality(job_rows, norm)
        ind_fit, ind_detail = score_industry_fit(name, industry_kw)
        inferred = infer_industry(name)

        # Collect pre-filter stats
        b_prefilter_stats["total"] += 1
        if max_sal < 2:  # salary_score < 2 means < 6k
            b_prefilter_stats["low_salary"] += 1
        if jcount == 0:
            b_prefilter_stats["single_job_low"] += 1
        # (Freshness-based pre-filter removed — posting_date no longer collected)

        total = jq * 7 + ind_fit * 3
        entry = {
            "company_name": name,
            "company_name_raw": name,
            "enterprise_categories": "",
            "level": "B",
            "inferred_industry": inferred,
            "qual_score": "0",
            "job_quality": str(jq),
            "industry_fit_score": str(ind_fit),
            "industry_fit_detail": ind_detail,
            "avg_job_score": str(round(avg_ts, 1)),
            "job_count": str(jcount),
            "total_score": str(round(total, 1)),
            "source_list": "",
        }
        entry["priority"] = "high" if total >= 30 else ("medium" if total >= 15 else "low")
        b_list.append(entry)

    # Sort within tiers by total_score desc, then name
    a_list.sort(key=lambda r: (-float(r["total_score"]), r["company_name"]))
    b_list.sort(key=lambda r: (-float(r["total_score"]), r["company_name"]))
    c_list.sort(key=lambda r: (-float(r["total_score"]), r["company_name"]))

    # Combine: A first, then B, then C
    scored = a_list + b_list + c_list

    # Tier stats
    tier_stats = {
        "A": {"count": len(a_list),
              "high": sum(1 for r in a_list if r["priority"] == "high"),
              "medium": sum(1 for r in a_list if r["priority"] == "medium")},
        "B": {"count": len(b_list),
              "high": sum(1 for r in b_list if r["priority"] == "high"),
              "medium": sum(1 for r in b_list if r["priority"] == "medium")},
        "C": {"count": len(c_list),
              "high": sum(1 for r in c_list if r["priority"] == "high"),
              "medium": sum(1 for r in c_list if r["priority"] == "medium")},
    }

    # Level C qual distribution
    c_qual_dist = {}
    for r in c_list:
        qs = int(float(r["qual_score"]))
        label = QUAL_TIER_LABELS.get(qs, f"资质{qs}级")
        c_qual_dist[label] = c_qual_dist.get(label, 0) + 1

    return scored, tier_stats, b_prefilter_stats, c_qual_dist


def main():
    parser = argparse.ArgumentParser(description="伯乐 Enterprise Scorer (Phase 40)")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    enterprise_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "enterprise"))
    processed_dir = os.path.join(enterprise_dir, "processed")
    position_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "processed"))

    # ── Load data ──
    enterprise_rows = load_csv(os.path.join(processed_dir, "enterprise_cleaned.csv"))
    if not enterprise_rows:
        print("错误: 未找到企业数据，请先运行 enterprise_clean.py")
        sys.exit(1)
    print(f"加载资质企业: {len(enterprise_rows)} 家")

    job_rows = load_csv(os.path.join(position_dir, "position_scored.csv"))
    print(f"加载岗位数据: {len(job_rows)} 条" if job_rows else "未找到岗位数据")

    industry_kw = load_industry_keywords(enterprise_dir)
    has_industry_kw = bool(industry_kw.get("target_kw") or industry_kw.get("exclude_kw"))
    if has_industry_kw:
        print(f"行业信号词: target={len(industry_kw.get('target_kw',[]))}, exclude={len(industry_kw.get('exclude_kw',[]))}")
    else:
        print("行业信号词: 未配置（industry_fit 默认 3.0）")

    # ── Score ──
    scored, tier_stats, b_prefilter, c_qual_dist = score_enterprises(
        enterprise_rows, job_rows, industry_kw if has_industry_kw else {})

    print(f"\n=== 三层级分类 ===")
    for level in ["A", "B", "C"]:
        s = tier_stats[level]
        print(f"  Level {level}: {s['count']} 家 (high={s['high']}, medium={s['medium']})")

    # ── Level B pre-filter suggestions ──
    if b_prefilter["total"] > 0:
        print(f"\n=== Level B 前筛建议 ===")
        print(f"  Level B 总数: {b_prefilter['total']}")
        print(f"  薪资偏低(≤6k)可能排除: {b_prefilter['low_salary']}")
        print(f"  仅 1 条岗位: {b_prefilter['single_job_low']}")
        print(f"  (freshness pre-filter removed — posting_date no longer collected)")

    # ── Level C qual distribution ──
    if c_qual_dist:
        print(f"\n=== Level C 资质分布 ===")
        for label in ["专精特新小巨人/单项冠军", "独角兽", "专精特新/高新技术企业/瞪羚",
                       "雏鹰企业", "科技型中小企业", "无资质"]:
            cnt = c_qual_dist.get(label, 0)
            if cnt:
                print(f"  {label}: {cnt} 家")

    # ── Top per tier ──
    print(f"\n=== Level A Top 5 ===")
    for r in scored[:5]:
        if r["level"] != "A":
            continue
        print(f"  [{r['priority'][0].upper()}] {r['company_name'][:24]:24s} score={r['total_score']:>4s} qual={r['qual_score']} jq={r['job_quality']} ind={r['industry_fit_score']}")

    b_start = sum(1 for r in scored if r["level"] == "A")
    print(f"\n=== Level B Top 5 ===")
    for r in scored[b_start:b_start+5]:
        if r["level"] != "B":
            continue
        print(f"  [{r['priority'][0].upper()}] {r['company_name'][:24]:24s} score={r['total_score']:>4s} jq={r['job_quality']} ind={r['industry_fit_score']}")

    c_start = sum(1 for r in scored if r["level"] in ("A", "B"))
    print(f"\n=== Level C Top 5 ===")
    for r in scored[c_start:c_start+5]:
        if r["level"] != "C":
            continue
        print(f"  [{r['priority'][0].upper()}] {r['company_name'][:24]:24s} score={r['total_score']:>4s} qual={r['qual_score']} ind={r['industry_fit_score']}")

    # ── Write output ──
    fields = [
        "company_name", "company_name_raw", "enterprise_categories",
        "level", "inferred_industry",
        "qual_score", "job_quality", "industry_fit_score", "industry_fit_detail",
        "avg_job_score", "job_count", "total_score", "priority", "source_list",
    ]
    out_path = os.path.join(processed_dir, "enterprise_scored.csv")
    write_csv(out_path, scored, fields)
    print(f"\n已保存: {out_path} ({len(scored)} 家)")

    # Distribution summary
    dist = {"high": 0, "medium": 0, "low": 0}
    for r in scored:
        dist[r["priority"]] = dist.get(r["priority"], 0) + 1
    print(f"优先级分布: high={dist['high']}  medium={dist['medium']}  low={dist['low']}")


if __name__ == "__main__":
    main()
