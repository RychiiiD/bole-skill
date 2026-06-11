"""
伯乐 — Scoring Script
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/score.py --config config.yaml
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


# ── Salary Normalizer ──

class SalaryNormalizer:
    @staticmethod
    def normalize(sal: str) -> str:
        sal = (sal or "").strip()
        if not sal:
            return ""

        month_suffix = ""
        m_month = re.search(r"(·\d+薪)", sal)
        if m_month:
            month_suffix = m_month.group(1)
            sal = sal.replace(month_suffix, "")

        m = re.match(r"([0-9]+)\s*[-~]\s*([0-9]+)万/年", sal)
        if m:
            return "%dk-%dk(月均)" % (
                int(m.group(1)) * 10 // 12, int(m.group(2)) * 10 // 12) + month_suffix

        m = re.match(r"([0-9.]+)\s*[-~]\s*([0-9.]+)万", sal)
        if m:
            return "%dk-%dk" % (float(m.group(1)) * 10, float(m.group(2)) * 10) + month_suffix

        m = re.match(r"([0-9]+)千\s*[-~]\s*([0-9]+)万", sal)
        if m:
            return "%sk-%dk" % (m.group(1), int(m.group(2)) * 10) + month_suffix

        m = re.match(r"([0-9]+)千\s*[-~]\s*([0-9]+)千", sal)
        if m:
            return "%sk-%sk" % (m.group(1), m.group(2)) + month_suffix

        m = re.match(r"([0-9]+)\s*[-~]\s*([0-9]+)元", sal)
        if m and int(m.group(1)) >= 1000:
            return "%dk-%dk" % (int(m.group(1)) // 1000, int(m.group(2)) // 1000) + month_suffix

        m = re.match(r"([0-9]+)\s*[-~]\s*([0-9]+)元/月", sal)
        if m:
            return "%dk-%dk" % (int(m.group(1)) // 1000, int(m.group(2)) // 1000) + month_suffix

        m = re.match(r"([0-9]+)\s*[-~]\s*([0-9]+)元/天", sal)
        if m:
            return "%dk-%dk(日薪)" % (
                int(m.group(1)) * 22 // 1000, int(m.group(2)) * 22 // 1000) + month_suffix

        if re.match(r"[0-9.]+k", sal, re.I):
            result = re.sub(r"/月$", "", sal.strip())
            return result + month_suffix

        sal = re.sub(r"/月$", "", sal.strip())
        return sal + month_suffix

    @staticmethod
    def max_k(sal: str) -> float:
        m = re.findall(r"([0-9]+\.?[0-9]*)k", (sal or ""), re.I)
        return max([float(x) for x in m]) if m else 0


# ── 评分默认值（config 中未配置时使用）──

DEFAULT_SALARY_TIERS = [
    {"max_k": 4, "score": 1},
    {"max_k": 6, "score": 2},
    {"max_k": 8, "score": 3},
    {"max_k": 10, "score": 4},
    {"max_k": 999, "score": 5},
]
DEFAULT_SALARY_SCORE = 3

DEFAULT_EXPERIENCE = {
    "3-5年": 5, "5-10年": 4, "1-3年": 4, "2年以上": 4, "2年": 4,
    "不限": 3, "实习": 2, "应届": 2, "10年以上": 3,
    "default": 3,
}

DEFAULT_EDUCATION = {
    "博士": 5, "硕士": 5, "本科": 5, "大专": 4,
    "default": 3,
}

DEFAULT_NEED_DEEP_THRESHOLD = 60


def _scoring_cfg(cfg: dict, key: str, default):
    """从 scoring 段取值，不存在则返回默认值。"""
    return cfg.get(key) if cfg else default


def score_rows(rows: List[Dict], config: dict) -> List[Dict]:
    cfg = config.get("scoring", {})
    weights = cfg.get("weights", {"salary": 10, "experience": 4, "education": 3, "relevance": 5})
    sal_tiers = _scoring_cfg(cfg, "salary_tiers", DEFAULT_SALARY_TIERS)
    exp_map = _scoring_cfg(cfg, "experience", DEFAULT_EXPERIENCE)
    edu_map = _scoring_cfg(cfg, "education", DEFAULT_EDUCATION)
    # 用户偏好覆盖（从 .bole_context.json 读取，覆盖 config.yaml 默认值）
    user_prefs = _load_user_preferences()
    user_weights = user_prefs.get("weights", {})
    if user_weights:
        weights = {**weights, **user_weights}
    user_tiers = user_prefs.get("salary_tiers", [])
    if user_tiers:
        sal_tiers = user_tiers
    user_exp = user_prefs.get("experience", {})
    if user_exp:
        exp_map = {**exp_map, **user_exp}
    user_edu = user_prefs.get("education", {})
    if user_edu:
        edu_map = {**edu_map, **user_edu}

    tags_cfg = cfg.get("tags", {})
    need_deep_threshold = tags_cfg.get("need_deep_threshold", DEFAULT_NEED_DEEP_THRESHOLD)

    # 岗位相关度关键词：临时文件 > config > 自动推导
    relevance_kw = _load_relevance_kw(config)

    for row in rows:
        row["salary_range"] = SalaryNormalizer.normalize(row.get("salary_range", ""))

        row["salary_score"] = _score_salary(row.get("salary_range", ""), sal_tiers, cfg.get("salary_default_score", DEFAULT_SALARY_SCORE))
        row["exp_score"] = _score_experience(row.get("experience", ""), exp_map)
        row["edu_score"] = _score_education(row.get("education", ""), edu_map)
        row["relevance_score"] = _score_relevance(row.get("job_title", ""), relevance_kw)

        row["total_score"] = (
            row["salary_score"] * weights["salary"]
            + row["exp_score"] * weights["experience"]
            + row["edu_score"] * weights["education"]
            + row["relevance_score"] * weights["relevance"]
        )

        row["tag_relevance"] = "Y" if row["relevance_score"] >= 4 else "N"
        row["tag_target_company"] = "Y" if any(
            t in row.get("company_name", "") for t in tags_cfg.get("target_companies", [])
        ) else "N"
        row["tag_need_deep"] = "Y" if row["total_score"] >= need_deep_threshold else "N"

    rows.sort(key=lambda r: -r["total_score"])

    # 相关度过滤：软标记（不删行，tag_relevance 已标记低相关度）
    min_rel = cfg.get("relevance_filter", {}).get("min_score", 0)
    if min_rel > 0:
        below = [r for r in rows if r["relevance_score"] < min_rel]
        print(f"  相关度过滤: min_score={min_rel}, 已标记 {len(below)} 条为低相关（tag_relevance=N，仍保留在输出中）")

    # 企业名称过滤：硬删除（排除词匹配的岗位没有保留价值）
    exclude = cfg.get("company_filter", {}).get("exclude_patterns", [])
    if exclude:
        before = len(rows)
        kept = []
        removed = []
        for r in rows:
            cn = r.get("company_name", "")
            matched = [p for p in exclude if p in cn]
            if matched:
                removed.append((cn, matched))
            else:
                kept.append(r)
        rows = kept
        after = len(rows)
        print(f"  企业名称过滤: 排除词={exclude}, {before} → {after} 条 (筛除 {before - after} 条)")
        if removed:
            print(f"  被剔除企业名单 ({len(removed)} 家):")
            for name, patterns in removed[:30]:
                print(f"    - 匹配 [{', '.join(patterns)}] → {name}")
            if len(removed) > 30:
                print(f"    ... 及另 {len(removed) - 30} 家")

    # 最少中文字符数过滤：硬删除（短名公司几乎全是个体户/低质）
    import re as _re
    min_cn = cfg.get("company_filter", {}).get("min_chinese_chars", 0)
    if min_cn > 0:
        before = len(rows)
        _cn_re = _re.compile(r'[一-鿿]')
        rows = [r for r in rows if len(_cn_re.findall(r.get("company_name", ""))) >= min_cn]
        after = len(rows)
        print(f"  企业名称中文字数过滤: min_chinese_chars={min_cn}, {before} → {after} 条 (筛除 {before - after} 条)")
    return rows


def _load_user_preferences() -> dict:
    """Load user preference overrides from .bole_context.json.

    Returns dict with optional keys: weights, salary_tiers, experience, education.
    These override config.yaml defaults when present. Written by AI in Step 0
    based on natural language interaction with the user.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ctx_path = os.path.normpath(os.path.join(script_dir, "..", "data", ".bole_context.json"))
    try:
        with open(ctx_path, "r", encoding="utf-8") as f:
            ctx = json.load(f)
        prefs = ctx.get("preferences", {})
        if prefs and any(prefs.values()):
            active = {k: v for k, v in prefs.items() if v}
            if active.get("weights"):
                print(f"  用户偏好权重: {active['weights']}")
            return active
    except Exception:
        pass
    return {}


def _load_relevance_kw(config: dict) -> dict:
    """加载岗位相关度关键词：临时文件 > config > 自动推导"""
    # 1) 检查临时文件（交互步骤生成）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    temp_path = os.path.normpath(os.path.join(script_dir, "..", "data", "position", ".relevance_keywords.json"))
    if os.path.exists(temp_path):
        try:
            with open(temp_path, "r", encoding="utf-8") as f:
                kw = json.load(f)
            # Handle SKILL format: {"keywords": [{"keyword": "X", "level": "high"}, ...]}
            if kw.get("keywords") and not kw.get("high"):
                high = [k["keyword"] for k in kw["keywords"] if k.get("level") == "high"]
                mid = [k["keyword"] for k in kw["keywords"] if k.get("level") == "mid"]
                kw["high"] = high
                kw["mid"] = mid
            if kw.get("high") or kw.get("mid"):
                print(f"  相关度关键词: 取自交互配置 (high={len(kw.get('high',[]))}, mid={len(kw.get('mid',[]))})")
                return kw
        except Exception:
            pass

    # 2) config 中手动配置
    kw = config.get("scoring", {}).get("relevance_keywords")
    if kw and (kw.get("high") or kw.get("mid")):
        print(f"  相关度关键词: 取自配置文件 (high={len(kw.get('high',[]))}, mid={len(kw.get('mid',[]))})")
        return kw

    # 3) 自动推导（从 .bole_context.json 获取岗位关键词）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ctx_path = os.path.normpath(os.path.join(script_dir, "..", "data", ".bole_context.json"))
    job_cfg = {}
    if os.path.exists(ctx_path):
        try:
            with open(ctx_path, "r", encoding="utf-8") as f:
                ctx = json.load(f)
            job_cfg = {
                "title_keywords": ctx.get("title_keywords", []),
                "search_keywords": ctx.get("search_keywords", []),
            }
        except Exception:
            pass
    kw = _derive_relevance_keywords(job_cfg)
    print(f"  相关度关键词: 自动推导 (high={kw['high']}, mid={kw['mid']})")
    return kw


def _derive_relevance_keywords(job_cfg: dict) -> dict:
    """从岗位关键词自动推导相关度关键词。"""
    title_kws = job_cfg.get("title_keywords", [])
    search_kws = job_cfg.get("search_keywords", [])

    high = []
    seen = set()
    for kw in title_kws + search_kws:
        k = kw.strip().lower()
        if k and k not in seen:
            seen.add(k)
            high.append(k)

    mid = []
    for kw in title_kws + search_kws:
        for part in re.split(r'[\(\)（）,，\s/]+', kw):
            p = part.strip().lower()
            if p and len(p) >= 2 and p not in seen:
                seen.add(p)
                mid.append(p)

    return {"high": high, "mid": mid}


def _score_salary(sal: str, tiers: list, default: int) -> int:
    m = re.search(r"([0-9]+\.?[0-9]*)k", sal, re.I)
    if not m:
        return default
    sk = float(m.group(1))
    for tier in tiers:
        if sk <= tier["max_k"]:
            return tier["score"]
    return default


def _score_experience(exp: str, mapping: dict) -> int:
    for pattern, score in mapping.items():
        if pattern in exp:
            return score
    return mapping.get("default", 3)


def _score_education(edu: str, mapping: dict) -> int:
    for pattern, score in mapping.items():
        if pattern == edu or pattern in edu:
            return score
    return mapping.get("default", 3)


def _score_relevance(title: str, kw: dict) -> int:
    combined = title.lower()
    if any(k in combined for k in kw["high"]):
        return 5
    if any(k in combined for k in kw["mid"]):
        return 4
    return 3


# (freshness dimension removed — posting_date no longer collected)


def get_all_fieldnames(rows: List[Dict]) -> List[str]:
    seen_fields = []
    for r in rows:
        for k in r:
            if k not in seen_fields:
                seen_fields.append(k)
    return seen_fields


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
    parser = argparse.ArgumentParser(description="伯乐 Scorer")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    processed_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "processed"))

    deduped_path = os.path.join(processed_dir, "deduped.csv")
    if not os.path.exists(deduped_path):
        print(f"错误: 未找到去重数据 {deduped_path}")
        print("请先运行: python scripts/dedup.py --config config.yaml")
        sys.exit(1)

    rows = load_csv(deduped_path)
    print(f"加载: {len(rows)} 条")

    scored = score_rows(rows, config)
    print(f"评分完成: {len(scored)} 条")

    ai_pm = sum(1 for r in scored if r.get("tag_relevance") == "Y")
    target = sum(1 for r in scored if r.get("tag_target_company") == "Y")
    deep = sum(1 for r in scored if r.get("tag_need_deep") == "Y")
    print(f"高相关: {ai_pm} | 目标公司: {target} | 需深挖: {deep}")

    fieldnames = get_all_fieldnames(scored)
    out_path = os.path.join(processed_dir, "position_scored.csv")
    write_csv(out_path, scored, fieldnames)
    print(f"已保存: {out_path}")

    print("\nTop 10:")
    for r in scored[:10]:
        print(f"  [{r['total_score']}] {r['job_title'][:30]} | {r['company_name'][:20]} | {r.get('salary_range', '')[:15]}")


if __name__ == "__main__":
    main()
