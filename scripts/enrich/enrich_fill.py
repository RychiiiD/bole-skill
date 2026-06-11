"""
伯乐 — Enrich Fill: 全网检索补充岗位中的企业信息
Usage:
  python scripts/enrich_fill.py status --config config.yaml   # 查看填充进度
  python scripts/enrich_fill.py batch --config config.yaml    # 输出下一批待处理岗位（<=20 条）
  python scripts/enrich_fill.py save --config config.yaml --input batch_result.json  # 保存填充结果
"""
import argparse
import csv
import json
import os
import sys


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_csv(filepath: str, encoding: str = "utf-8-sig") -> list:
    with open(filepath, "r", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv(filepath: str, rows: list, fieldnames: list, encoding: str = "utf-8-sig"):
    with open(filepath, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


FILL_FIELDS = [
    "benefits",
    "company_size",
    "official_website",
    "enterprise_categories",
    "legal_disputes",
    "business_anomaly",
]

# 企业质量加分等级（与 enrich.py 一致，但 enrich-fill 无 level 信息，始终全量）
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



def recalc_bonus(enterprise_categories: str) -> tuple:
    """根据企业资质关键词重新计算加分（无 level 折扣，WebSearch 补充数据用）。"""
    if not enterprise_categories or not enterprise_categories.strip():
        return 0, ""
    best_bonus = 0
    best_reason = ""
    for kw, bonus, label in QUAL_BONUS_TIERS:
        if kw in enterprise_categories:
            if bonus > best_bonus:
                best_bonus = bonus
                best_reason = f"{label}+{bonus}分"
    return best_bonus, best_reason


def get_final_paths(config: dict) -> dict:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position", "output"))
    return {
        "final": os.path.join(output_dir, "position_final.csv"),
    }


def needs_fill(row: dict) -> bool:
    """判断岗位是否需要补充企业信息。以下任一条件满足即需补充。"""
    # 无企业资质且无福利 → 需要全量补充
    if not row.get("enterprise_categories", "").strip() and not row.get("benefits", "").strip():
        return True
    return False


def get_empty_fields(row: dict) -> list:
    """获取该岗位哪些字段为空（含基础岗位字段和企业字段）。"""
    empty = []
    for f in FILL_FIELDS:
        if not row.get(f, "").strip():
            empty.append(f)
    return empty


def cmd_status(config: dict):
    """显示填充进度。"""
    paths = get_final_paths(config)
    if not os.path.exists(paths["final"]):
        print("错误: 未找到 position_final.csv，请先运行 /bole-enrich")
        sys.exit(1)

    rows = load_csv(paths["final"])
    total = len(rows)

    need = [r for r in rows if needs_fill(r)]
    filled = total - len(need)

    # 统计每家企业的岗位数
    company_positions = {}
    for r in need:
        c = r.get("company_name", "").strip()
        if c:
            company_positions.setdefault(c, []).append(r)

    # 各类字段空缺统计
    empty_counts = {}
    for r in need:
        for f in FILL_FIELDS:
            if not r.get(f, "").strip():
                empty_counts[f] = empty_counts.get(f, 0) + 1

    print("=" * 55)
    print(f"  填充进度: {filled}/{total} 已完成")
    print(f"  待填充:   {len(need)} 条岗位 ({len(company_positions)} 家独立企业)")
    print(f"  字段空缺分布:")
    for f, c in sorted(empty_counts.items(), key=lambda x: -x[1]):
        print(f"    - {f:25s}: {c:3d}/{total} 条空")
    print("=" * 55)

    return need, company_positions


def cmd_batch(config: dict):
    """输出下一批待填充的岗位（<=20 条）。"""
    need, _ = cmd_status(config)
    if not need:
        print("所有岗位企业信息已填充完毕！")
        return

    batch = need[:50]

    # 去重提取本批涉及的企业
    companies = []
    seen = set()
    for r in batch:
        c = r.get("company_name", "").strip()
        if c and c not in seen:
            seen.add(c)
            companies.append(c)

    print(f"\n批次大小: {len(batch)} 条岗位, {len(companies)} 家独立企业\n")

    out = []
    for i, r in enumerate(batch, 1):
        empty = get_empty_fields(r)
        entry = {
            "batch_index": i,
            "company_name": r.get("company_name", "").strip(),
            "job_title": r.get("job_title", "").strip(),
            "salary_range": r.get("salary_range", "").strip(),
            "total_score": r.get("total_score", "").strip(),
            "empty_fields": empty,
            "existing_info": {
                "benefits": r.get("benefits", "").strip(),
                "company_size": r.get("company_size", "").strip(),
                "official_website": r.get("official_website", "").strip(),
                "enterprise_categories": r.get("enterprise_categories", "").strip(),
            },
            # 从 enterprise_categories 反推已知资质（可能来自原始企业管线匹配但分类为空）
            "enterprise_categories": r.get("enterprise_categories", "").strip(),
        }
        out.append(entry)
        print(f"  [{i}] {entry['company_name']} — {entry['job_title'][:30]}")
        print(f"      空字段: {', '.join(empty)}")
        print()

    # 写批次 JSON
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position"))
    batch_file = os.path.join(output_dir, ".enrich_fill_batch.json")
    with open(batch_file, "w", encoding="utf-8") as f:
        json.dump({"batch_size": len(batch), "companies": companies, "positions": out}, f, ensure_ascii=False, indent=2)
    print(f"批次文件已保存: {batch_file}")


def cmd_save(config: dict, input_path: str):
    """保存填充结果回 position_final.csv（带字段校验和回滚保护）。"""
    if not input_path or not os.path.exists(input_path):
        print("错误: --input 文件不存在或未指定")
        sys.exit(1)

    with open(input_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    filled = result.get("filled", [])
    if not filled:
        print("错误: JSON 中无 filled 数据")
        sys.exit(1)

    paths = get_final_paths(config)
    rows = load_csv(paths["final"])
    if not rows:
        print("错误: position_final.csv 为空或读取失败")
        sys.exit(1)

    fieldnames = list(rows[0].keys())

    # ── 字段校验：输入 JSON 中的字段必须在 CSV 表头中存在 ──
    input_fields = set()
    for item in filled:
        input_fields.update(item.keys())
    # company_name 和 job_title 是匹配键，不写回
    input_fields.discard("company_name")
    input_fields.discard("job_title")
    csv_fields = set(fieldnames)

    illegal = input_fields - csv_fields
    if illegal:
        print(f"错误: JSON 中以下字段在 position_final.csv 中不存在: {sorted(illegal)}")
        print(f"可写入字段: {sorted(csv_fields)}")
        sys.exit(1)

    # ── 数据匹配 ──
    updated = 0
    for item in filled:
        company = item.get("company_name", "").strip()
        job_title = item.get("job_title", "").strip()
        for r in rows:
            if r.get("company_name", "").strip() == company and r.get("job_title", "").strip() == job_title:
                # 记录更新前的 enterprise_categories，用于判断是否需要重算加分
                old_cats = r.get("enterprise_categories", "").strip()
                for f in input_fields:
                    if item.get(f):
                        r[f] = item[f]
                # 如果 enterprise_categories 被补充，重算加分和 final_score
                new_cats = r.get("enterprise_categories", "").strip()
                if new_cats and new_cats != old_cats:
                    bonus, reason = recalc_bonus(new_cats)
                    r["company_quality_bonus"] = str(bonus)
                    r["company_quality_reason"] = reason
                    try:
                        ts = float(r.get("total_score", 0) or 0)
                        r["final_score"] = str(round(ts + bonus, 1))
                    except (ValueError, TypeError):
                        pass
                updated += 1
                break

    # ── 匹配数检查 ──
    if updated == 0:
        print("错误: 匹配到 0 条岗位，拒绝写入。请确认 batch 文件是否来自当前 position_final.csv")
        print("提示: 先运行 python scripts/enrich_fill.py batch --config config.yaml 重新生成批次")
        sys.exit(1)

    # ── 按 final_score 降序重排 ──
    rows.sort(key=lambda r: -float(r.get("final_score", 0) or 0))

    # ── 安全写入：先备份（保留 .bak 不删除，供回滚用）──
    import shutil
    import glob
    backup = paths["final"] + ".bak"
    shutil.copy2(paths["final"], backup)
    # 最多保留 3 个历史备份版本
    bak_dir = os.path.dirname(backup)
    bak_base = os.path.basename(backup)
    old_baks = sorted(glob.glob(os.path.join(bak_dir, ".position_final.csv.bak.*")))
    while len(old_baks) >= 3:
        os.remove(old_baks.pop(0))
    import datetime
    versioned_bak = backup + "." + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(paths["final"], versioned_bak)
    try:
        write_csv(paths["final"], rows, fieldnames, encoding="utf-8")
        print(f"[OK] 已更新 {updated} 条岗位 → position_final.csv")

        # 重新运行 format：输出知识库导入版
        output_dir = os.path.dirname(paths["final"])
        from enrich_format import write_kb_versions
        write_kb_versions(rows, output_dir)
    except Exception as e:
        # 写入失败，回滚
        shutil.copy2(backup, paths["final"])
        os.remove(backup)
        print(f"错误: 写入失败 ({e})，已自动回滚")
        sys.exit(1)


def _verify_value_in_snippets(value: str, snippets_text: str) -> bool:
    """验证提取的值是否在搜索结果片段中有依据。

    将值拆分为内容词（中文词+英文单词），检查至少 30% 出现在片段中。
    """
    if not snippets_text:
        return False
    import re
    content_words = re.findall(r'[一-鿿\w]+', value)
    if not content_words:
        return False
    unique_words = set(content_words)
    matched = sum(1 for w in unique_words if w in snippets_text)
    ratio = matched / len(unique_words) if unique_words else 0
    return ratio >= 0.3


def _has_suspicious_patterns(value: str) -> bool:
    """检查值是否包含可疑模式（重复、无意义内容等）。"""
    import re

    # 常见合法短值白名单
    SHORT_VALUE_WHITELIST = {"面议", "未公开", "未透露", "不详", "暂无", "无"}
    if value.strip() in SHORT_VALUE_WHITELIST:
        return False

    # 纯数字/纯标点
    if re.match(r'^[\d\s\.\,\;\:\!\?\(\)\[\]\{\}]+$', value):
        return True
    # 同一字符重复 5 次以上（如 "aaaaaaaa"）
    if re.search(r'(.)\1{4,}', value):
        return True
    # 少于 2 个中文字符且非 URL
    zh_chars = re.findall(r'[一-鿿]', value)
    if len(zh_chars) < 2 and not value.startswith('http') and len(value) > 5:
        return True
    return False


def cmd_extract(config: dict, evidence_path: str):
    """从搜索证据文件提取结构化数据，代码验证后生成填充结果。

    输入 JSON 格式：
    {
      "searched": [
        {
          "company_name": "xxx",
          "job_title": "xxx",
          "snippets": ["原始搜索结果文本1", "原始搜索结果文本2"],
          "extracted": {   ← AI 从搜索结果中提取的结构化字段
            "benefits": "五险一金、年终奖",
            "company_size": "100-499人",
            ...
          }
        }
      ]
    }
    """
    if not evidence_path or not os.path.exists(evidence_path):
        print("错误: --evidence 文件不存在")
        sys.exit(1)

    with open(evidence_path, "r", encoding="utf-8") as f:
        evidence = json.load(f)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    pos_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position"))
    batch_path = os.path.join(pos_dir, ".enrich_fill_batch.json")

    if not os.path.exists(batch_path):
        print("错误: 未找到 .enrich_fill_batch.json，请先运行 batch 命令")
        sys.exit(1)

    with open(batch_path, "r", encoding="utf-8") as f:
        batch = json.load(f)

    filled = []
    total = len(evidence.get("searched", []))
    verified_count = 0
    suspicious_count = 0

    for idx, item in enumerate(evidence.get("searched", []), 1):
        company = item.get("company_name", "").strip()
        job_title = item.get("job_title", "").strip()
        if not company or not job_title:
            print(f"  [{idx}] 跳过: 缺少 company_name 或 job_title")
            continue

        snippets_text = " ".join(item.get("snippets", []))
        extracted = item.get("extracted", {})

        entry = {"company_name": company, "job_title": job_title}
        verified_fields = []
        failed_fields = []

        for field in FILL_FIELDS:
            value = extracted.get(field, "").strip()

            if not value or "目前未检索" in value:
                entry[field] = f"目前未检索到该企业{field}详细信息"
                continue

            # Step 1: 检查可疑模式
            if _has_suspicious_patterns(value):
                suspicious_count += 1
                failed_fields.append(field)
                entry[field] = f"目前未检索到该企业{field}详细信息"
                continue

            # Step 2: 验证字段值是否在搜索片段中有依据
            if _verify_value_in_snippets(value, snippets_text):
                entry[field] = value
                verified_fields.append(field)
            else:
                failed_fields.append(field)
                entry[field] = f"目前未检索到该企业{field}详细信息"

        filled.append(entry)
        if failed_fields:
            print(f"  [{idx}] {company}/{job_title[:20]:20s} 验证失败: {', '.join(failed_fields)}")
        if verified_fields:
            verified_count += 1

    result = {"filled": filled}
    output_path = os.path.join(pos_dir, ".enrich_fill_result.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 提取验证完成: {len(filled)} 条结果")
    print(f"     通过验证: {verified_count}/{total} 条")
    print(f"     输出文件: {output_path}")


def cmd_clean():
    """删除 enrich_fill 所有临时文件和备份。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pos_dir = os.path.normpath(os.path.join(script_dir, "..", "data", "position"))
    files = [
        os.path.join(pos_dir, ".enrich_fill_batch.json"),
        os.path.join(pos_dir, ".enrich_fill_result.json"),
        os.path.join(pos_dir, ".enrich_fill_evidence.json"),
    ]
    for f in files:
        if os.path.exists(f):
            os.remove(f)
            print(f"  已删除: {f}")

    # 清理备份文件（含版本历史）
    output_dir = os.path.join(pos_dir, "output")
    bak = os.path.join(output_dir, "position_final.csv.bak")
    if os.path.exists(bak):
        os.remove(bak)
        print(f"  已删除: {bak}")
    import glob
    for vb in glob.glob(os.path.join(output_dir, "position_final.csv.bak.*")):
        os.remove(vb)
        print(f"  已删除: {vb}")
    print("[OK] enrich_fill 临时文件已清理")


def main():
    parser = argparse.ArgumentParser(description="伯乐 Enrich Fill")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--input", help="填充结果 JSON 文件路径")
    subparsers = parser.add_subparsers(dest="command", help="子命令: status / batch / extract / save / clean")

    subparsers.add_parser("status", help="查看填充进度")
    subparsers.add_parser("batch", help="输出下一批待填充岗位（<=50 条）")
    subparsers.add_parser("clean", help="删除 enrich_fill 所有临时文件（batch/result/备份）")
    extract_parser = subparsers.add_parser("extract", help="从搜索证据提取+验证结构化字段")
    extract_parser.add_argument("--evidence", required=True, help="搜索证据 JSON 文件路径")
    save_parser = subparsers.add_parser("save", help="保存填充结果")
    save_parser.add_argument("--input", required=True, help="填充结果 JSON 文件")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "status":
        cmd_status(config)
    elif args.command == "batch":
        cmd_batch(config)
    elif args.command == "clean":
        cmd_clean()
    elif args.command == "extract":
        cmd_extract(config, args.evidence)
    elif args.command == "save":
        cmd_save(config, args.input)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
