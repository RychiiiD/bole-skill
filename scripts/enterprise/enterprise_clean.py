"""
伯乐 — Enterprise Data Cleaning Script
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/enterprise_clean.py --config config.yaml

Reads enterprise qualification lists and profiles from data/enterprise/raw/,
normalizes company names, deduplicates, merges multi-source data.
"""

import argparse
import csv
import glob
import os
import re
import sys
from datetime import date
from typing import Dict, List


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _detect_csv_encoding(filepath: str) -> str:
    """Detect CSV file encoding by trying common Chinese encodings.

    Tries utf-8-sig first (most common), then GBK, then GB18030.
    Returns the encoding whose decoded text has the highest Chinese char ratio.
    """
    with open(filepath, "rb") as f:
        raw = f.read(8192)  # Read enough to detect
    if not raw:
        return "utf-8-sig"

    candidates = ["utf-8-sig", "utf-8", "gbk", "gb18030"]
    best_enc = "utf-8-sig"
    best_ratio = 0

    for enc in candidates:
        try:
            text = raw.decode(enc)
            total = len(text)
            if total == 0:
                continue
            chinese = sum(1 for c in text if '一' <= c <= '鿿')
            ratio = chinese / total
            if ratio > best_ratio:
                best_ratio = ratio
                best_enc = enc
        except (UnicodeDecodeError, LookupError):
            continue

    return best_enc


def load_csvs(data_dir: str, encoding: str = None) -> List[Dict]:
    all_rows = []
    for f in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        enc = encoding or _detect_csv_encoding(f)
        with open(f, "r", encoding=enc) as fh:
            for row in csv.DictReader(fh):
                all_rows.append(row)
    return all_rows


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
    """Normalize company name for dedup matching.

    Handles: fullwidth→halfwidth, bracket variants, company suffix,
    dash variants, whitespace normalization.
    """
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

    # Normalize brackets: （）→ (),  【】→ []
    n = n.replace("（", "(").replace("）", ")")
    n = n.replace("【", "[").replace("】", "]")

    # Normalize dashes: — → -,  ～ → -
    n = n.replace("—", "-").replace("～", "-").replace("~", "-")

    # Normalize spaces: fullwidth space → regular, collapse multiple
    n = n.replace("　", " ").replace(" ", " ").strip()

    # Remove common suffix variations for matching purposes
    # Keep original for output, but normalize for dedup key
    n = re.sub(r"[（(]?有限[公合]?[司同][)）]?", "", n)
    n = re.sub(r"[（(]?股份?有限[公合]?[司同][)）]?", "", n)

    # Remove leading/trailing punctuation
    n = n.strip("，, \t")

    # Collapse multiple spaces
    n = re.sub(r"\s+", "", n)

    # Lowercase for matching
    n = n.lower()

    return n


def _classify_source(filepath: str) -> str:
    """Classify a raw CSV file as qualification_list or enterprise_profile
    based on its directory path."""
    path_normalized = filepath.replace("\\", "/")
    if "qualification_lists" in path_normalized:
        return "qualification"
    if "profiles" in path_normalized:
        return "profile"
    return "unknown"


def clean_and_merge() -> List[Dict]:
    """Main cleaning and merging logic.

    Returns:
        cleaned_list: enterprises with qualification categories (deduped, merged)
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    enterprise_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "enterprise"))

    raw_dir = os.path.join(enterprise_dir, "raw")
    qual_dir = os.path.join(raw_dir, "qualification_lists")

    # ── Load qualification lists ──
    qual_rows = []
    if os.path.isdir(qual_dir):
        for f in sorted(glob.glob(os.path.join(qual_dir, "*.csv"))):
            source_name = os.path.splitext(os.path.basename(f))[0]
            with open(f, "r", encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
            for r in rows:
                if r.get("company_name", "").strip():
                    r["_source_name"] = source_name
                    qual_rows.append(r)
            print(f"  [qualification] {source_name}: {len(rows)} 条")

    # ── Dedup and merge qualification data ──
    qual_map: Dict[str, dict] = {}
    for r in qual_rows:
        name = (r.get("company_name") or "").strip()
        key = normalize_company_name(name)
        if not key:
            continue
        cat = (r.get("enterprise_category") or "").strip()
        src = r.get("_source_name", "")
        raw_name = r.get("company_name_raw", "") or name

        if key not in qual_map:
            qual_map[key] = {
                "company_name": name,
                "company_name_raw": name,
                "enterprise_categories": cat,
                "source_list": src,
            }
        else:
            existing = qual_map[key]
            # Merge categories (dedup, semicolon-separated)
            cats = set(existing["enterprise_categories"].split(";"))
            if cat:
                cats.add(cat)
            existing["enterprise_categories"] = ";".join(sorted(c for c in cats if c))

            # Merge sources
            srcs = set(existing["source_list"].split(";"))
            if src:
                srcs.add(src)
            existing["source_list"] = ";".join(sorted(s for s in srcs if s))

            # Take longer raw name as canonical
            if len(raw_name) > len(existing["company_name"]):
                existing["company_name"] = raw_name
            if len(raw_name) > len(existing["company_name_raw"]):
                existing["company_name_raw"] = raw_name

    cleaned_list = list(qual_map.values())
    print(f"\n  清洗后企业名录: {len(cleaned_list)} 家 (来自 {len(qual_rows)} 条原始记录)")

    return cleaned_list


def main():
    parser = argparse.ArgumentParser(description="伯乐 Enterprise Data Cleaner")
    parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    enterprise_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "enterprise"))
    processed_dir = os.path.join(enterprise_dir, "processed")

    print("企业数据清洗去重...")
    cleaned_list = clean_and_merge()

    # Write cleaned (qualification only)
    cleaned_fields = ["company_name", "company_name_raw", "enterprise_categories", "source_list"]
    cleaned_path = os.path.join(processed_dir, "enterprise_cleaned.csv")
    write_csv(cleaned_path, cleaned_list, cleaned_fields)
    print(f"\n已保存: {cleaned_path}")

    # Summary
    cat_dist = {}
    for e in cleaned_list:
        for cat in e["enterprise_categories"].split(";"):
            cat = cat.strip()
            if cat:
                cat_dist[cat] = cat_dist.get(cat, 0) + 1
    print(f"\n资质分布:")
    for cat, count in sorted(cat_dist.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count} 家")

    # 生成企业数据报告
    report_path = os.path.join(processed_dir, "enterprise_report.md")
    generate_enterprise_report(cleaned_list, report_path)
    print(f"[OK] {report_path}")


def generate_enterprise_report(rows: List[Dict], path: str):
    total = len(rows)
    if total == 0:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# 企业数据报告\n\n无数据。\n")
        return

    # 资质分布
    cat_dist = {}
    for e in rows:
        for cat in e.get("enterprise_categories", "").split(";"):
            cat = cat.strip()
            if cat:
                cat_dist[cat] = cat_dist.get(cat, 0) + 1

    today = date.today().isoformat()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 企业数据报告\n\n")
        f.write(f"生成时间: {today}\n\n")
        f.write("| 指标 | 数值 |\n")
        f.write("|------|:----:|\n")
        f.write(f"| 企业总数 | {total} |\n\n")

        f.write("### 资质分布\n\n")
        f.write("| 资质类型 | 企业数 |\n")
        f.write("|----------|:-----:|\n")
        for cat, cnt in sorted(cat_dist.items(), key=lambda x: -x[1]):
            f.write(f"| {cat} | {cnt} |\n")


if __name__ == "__main__":
    main()
