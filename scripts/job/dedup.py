"""
伯乐 — Deduplication Script
Standalone CLI tool, no BaseSkill dependency.
Usage: python scripts/dedup.py --config config.yaml
"""

import argparse
import csv
import glob
import os
import re
import sys
from typing import Dict, List


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_csvs(data_dir: str, encoding: str = "utf-8-sig") -> List[Dict]:
    all_rows = []
    for f in sorted(glob.glob(os.path.join(data_dir, "*.csv"))):
        if "_progress" in f:
            continue
        with open(f, "r", encoding=encoding) as fh:
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


def dedup(rows: List[Dict], config: dict) -> List[Dict]:
    cfg = config.get("dedup", {})
    key_fields = cfg.get("key_fields", ["company_name", "job_title"])
    strip_brackets = cfg.get("strip_brackets", True)
    take_longest = cfg.get("merge_take_longest", ["salary_range", "benefits",
        "company_industry", "company_size", "financing_stage"])

    seen: Dict[str, Dict] = {}

    for row in rows:
        key_parts = []
        for kf in key_fields:
            val = (row.get(kf) or "").strip()
            if strip_brackets and kf == "job_title":
                val = re.sub(r'[\[（(）)\]]', '', val).strip()
            key_parts.append(val)

        c = key_parts[0]
        t = key_parts[-1]
        if not c and not t:
            continue

        composite_key = c + "|" + t

        if composite_key not in seen:
            seen[composite_key] = dict(row)
            seen[composite_key]["source_list"] = row.get("source", "")
        else:
            existing = seen[composite_key]
            src_set = set(existing["source_list"].split(";"))
            src_set.add(row.get("source", ""))
            existing["source_list"] = ";".join(sorted(s for s in src_set if s))
            existing["source"] = existing["source_list"]
            for field in take_longest:
                if len(row.get(field, "")) > len(existing.get(field, "")):
                    existing[field] = row[field]

    return list(seen.values())


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
    _merged = os.path.join(_base, "data", "position", "raw", "merged_raw.csv")
    if not os.path.exists(_merged):
        _raw_csvs = glob.glob(os.path.join(_base, "data", "position", "raw", "*.csv"))
        if not _raw_csvs:
            print("!! 错误: 缺少 merged_raw.csv 且 raw/ 下无 CSV 文件，请先运行 merge_raw.py")
            sys.exit(1)


def main():
    self_check()
    parser = argparse.ArgumentParser(description="伯乐 Deduplicator")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)
    sources_cfg = config.get("sources", {})

    raw_dir = sources_cfg.get("raw_dir", "data/position/raw")
    if raw_dir.startswith(".."):
        raw_dir = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "data", "position", "raw"))

    processed_dir = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "position", "processed"))

    encoding = sources_cfg.get("encoding", "utf-8-sig")

    print(f"加载数据: {raw_dir}")
    all_rows = load_csvs(raw_dir, encoding)
    print(f"  原始记录: {len(all_rows)} 条")

    unique_jobs = dedup(all_rows, config)
    print(f"  去重后: {len(unique_jobs)} 条独立岗位")

    fieldnames = get_all_fieldnames(unique_jobs)
    out_path = os.path.join(processed_dir, "deduped.csv")
    write_csv(out_path, unique_jobs, fieldnames, encoding)
    print(f"  已保存: {out_path}")

    # 来源分布
    sources_dist = {}
    for r in unique_jobs:
        s = r.get("source_list", r.get("source", "unknown"))
        for src in s.split(";"):
            src = src.strip()
            if src:
                sources_dist[src] = sources_dist.get(src, 0) + 1
    print(f"  来源分布: {sources_dist}")


if __name__ == "__main__":
    main()
