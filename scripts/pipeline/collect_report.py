"""
采集客观报告 — 基于实际数据文件的客观摘要，AI 不可篡改。

用法:
  python scripts/pipeline/collect_report.py --source <name> --config config.yaml
  python scripts/pipeline/collect_report.py --config config.yaml        # 全部来源

输出为固定格式文本，AI 只能原文展示，不得修改内容。
"""
import json
import os
import re
import sys
import yaml

# Windows GBK console fix
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_DIR = os.path.join(BASE_DIR, "data", "position", "raw")

# 文件名模式: {source}_{keyword}_page{N}.json
FILE_PATTERN = re.compile(r"^([^_]+)_(.+?)_page(\d+)\.json$")


def load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg


def scan_raw() -> dict:
    """扫描 raw/ 目录，返回 {source: {keyword: [{file, page, jobs_count}], ...}, ...}"""
    if not os.path.isdir(RAW_DIR):
        return {}

    result = {}
    for fname in os.listdir(RAW_DIR):
        if not fname.endswith(".json"):
            continue
        m = FILE_PATTERN.match(fname)
        if not m:
            continue
        source, keyword, page = m.group(1), m.group(2), int(m.group(3))
        fpath = os.path.join(RAW_DIR, fname)

        jobs_count = 0
        valid = True
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "jobs" in data:
                jobs_count = len(data["jobs"])
            elif isinstance(data, list):
                jobs_count = len(data)
        except (json.JSONDecodeError, Exception):
            valid = False

        entry = {
            "file": fname,
            "page": page,
            "jobs_count": jobs_count,
            "valid": valid,
        }

        result.setdefault(source, {}).setdefault(keyword, []).append(entry)

    return result


def get_expected_keywords(config: dict) -> list:
    """从 .bole_context.json 获取期望的搜索关键词列表"""
    ctx_path = os.path.join(BASE_DIR, "data", ".bole_context.json")
    if os.path.exists(ctx_path):
        with open(ctx_path, "r", encoding="utf-8") as f:
            ctx = json.load(f)
        return ctx.get("search_keywords", [])
    return config.get("job", {}).get("search_keywords", [])


def get_source_names_from_dir() -> list:
    """从文件名反向推导出现的来源名称"""
    if not os.path.isdir(RAW_DIR):
        return []
    seen = set()
    for fname in os.listdir(RAW_DIR):
        m = FILE_PATTERN.match(fname)
        if m:
            seen.add(m.group(1))
    return sorted(seen)


def _status_char(count: int, has_file: bool) -> str:
    if not has_file:
        return "[NO FILE]"  # 缺失
    if count > 0:
        return "[OK]"       # 有数据
    return "[EMPTY]"        # 空结果


def report_source(source: str, data: dict, expected_keywords: list) -> str:
    """生成单来源报告"""
    lines = []
    kw_data = data.get(source, {})
    # 找到该来源所有 keywords
    actual_kws = set(kw_data.keys())
    all_kws = list(actual_kws) + [kw for kw in expected_keywords if kw not in actual_kws]
    # 去重并保持预期顺序
    seen = set()
    ordered_kws = []
    for kw in expected_keywords:
        if kw not in seen:
            ordered_kws.append(kw)
            seen.add(kw)
    for kw in all_kws:
        if kw not in seen:
            ordered_kws.append(kw)
            seen.add(kw)

    total_pages = 0
    total_jobs = 0
    kw_lines = []

    for kw in ordered_kws:
        entries = kw_data.get(kw, [])
        has_file = len(entries) > 0
        pages = len(entries)
        jobs = sum(e["jobs_count"] for e in entries)
        status = _status_char(jobs, has_file)
        kw_lines.append(f"  {kw:20s}  {status}   {pages} 页   {jobs} 条")

        if has_file:
            total_pages += pages
            total_jobs += jobs

    # 统计完成度
    done = sum(1 for kw in expected_keywords if kw in kw_data)
    total_expected = len(expected_keywords)

    lines.append(f"╔══════════════════════════════════════════╗")
    lines.append(f"║  来源: {source:32s}║")
    lines.append(f"║  关键词: {done}/{total_expected} 完成                            ║")
    lines.append(f"╠══════════════════════════════════════════╣")
    lines.append(f"║  关键词              状态  页数  岗位数  ║")
    lines.append(f"║  ─────────────────────────────────────  ║")
    for kl in kw_lines:
        # 内容加左右边框
        content = f"  {kl}  "
        lines.append(f"║{content:44s}║")
    lines.append(f"╠══════════════════════════════════════════╣")
    lines.append(f"║  总计: {total_pages} 页, {total_jobs} 条                           ║")


    if done < total_expected:
        missing_kws = [kw for kw in expected_keywords if kw not in kw_data]
        lines.append(f"║  !! 缺失关键词: {', '.join(missing_kws):24s}║")

    lines.append(f"╚══════════════════════════════════════════╝")
    return "\n".join(lines)






def report_all_sources(source_data: dict, expected_keywords: list) -> str:
    """生成全来源汇总报告"""
    sources = sorted(source_data.keys())
    lines = []
    lines.append("=" * 50)
    lines.append("  采集覆盖报告")
    lines.append("=" * 50)
    lines.append("")

    for src in sources:
        lines.append(report_source(src, source_data, expected_keywords))
        lines.append("")

    # 整体统计
    total_keyword_combos = 0
    covered_combos = 0
    for src in sources:
        for src_name, kw_dict in source_data.items():
            if src_name == src:
                for kw in expected_keywords:
                    total_keyword_combos += 1
                    if kw in kw_dict:
                        covered_combos += 1
                break

    lines.append(f"整体覆盖率: {covered_combos}/{total_keyword_combos} (来源×关键词)")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="生成基于实际文件的采集客观报告")
    parser.add_argument("--source", help="指定来源名称（可选），仅输出该来源报告")
    parser.add_argument("--config", default=os.path.join(BASE_DIR, "config.yaml"),
                        help="config.yaml 路径")
    args = parser.parse_args()

    config = load_config(args.config)
    expected_kws = get_expected_keywords(config)
    source_data = scan_raw()

    if args.source:
        # 单来源报告
        if args.source not in source_data:
            # 来源无数据文件 → 显示空报告
            source_data[args.source] = {}
        print(report_source(args.source, source_data, expected_kws))
    else:
        if not source_data:
            print("!! data/position/raw/ 目录中没有找到数据文件。")
            sys.exit(0)
        print(report_all_sources(source_data, expected_kws))

    # 返回机器可读的覆盖率数据给调用方（pipeline verify 用）
    if args.source:
        done = sum(1 for kw in expected_kws if kw in source_data.get(args.source, {}))
        total = len(expected_kws)
        sys.exit(0 if done == total else 2)


if __name__ == "__main__":
    main()
