"""Merge raw JSON files from multiple platforms into dedup-ready CSV."""
import json, csv, os, glob, sys

# ── Pipeline step guard ──
def self_check():
    _base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _lock = os.path.join(_base, "data", ".verify_blocked")
    if os.path.exists(_lock):
        print("!! 错误: 上一步骤校验未通过，无法继续。")
        print("!! 排查问题后运行: rm data/.verify_blocked")
        print("!! 或使用 pipeline.py complete --skip-verify --skip-verify-ack 授权跳过")
        sys.exit(1)
    _raw = os.path.join(_base, "data", "position", "raw")
    if not os.path.isdir(_raw) or not os.listdir(_raw):
        print("!! 错误: data/position/raw/ 目录不存在或为空，请先完成采集步骤")
        sys.exit(1)
self_check()
# ──

# Derive project root from this script's location
_script_dir = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.normpath(os.path.join(_script_dir, "..", ".."))

RAW_DIR = os.path.join(BASE_DIR, "data", "position", "raw")
OUTPUT = os.path.join(BASE_DIR, "data", "position", "raw", "merged_raw.csv")
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")

# Read city from .bole_context.json (set by Step 0 NL extraction)
_city = ""
_ctx_path = os.path.join(BASE_DIR, "data", ".bole_context.json")
if os.path.exists(_ctx_path):
    try:
        import json
        with open(_ctx_path, "r", encoding="utf-8") as f:
            _ctx = json.load(f)
        _city = _ctx.get("city", _city)
    except Exception:
        pass

os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)

rows = []

# Try JSON files first (real collection)
json_files = sorted(glob.glob(os.path.join(RAW_DIR, "*.json")))
if json_files:
    for fpath in json_files:
        with open(fpath, encoding="utf-8") as f:
            data = json.load(f)
        source = data.get("source", "")
        if not source:
            fname = os.path.basename(fpath)
            source = fname.split("_")[0] if fname.split("_")[0] else "unknown"
        keyword = data.get("keyword", "")
        collect_time = data.get("collect_time", "")
        for job in data.get("jobs", []):
            row = {
                "job_title": job.get("title", ""),
                "company_name": job.get("company", ""),
                "salary_range": job.get("salary", ""),
                "city": _city,
                "education": job.get("education", ""),
                "experience": job.get("experience", ""),
                "benefits": job.get("benefits", ""),
                "source": source,
                "search_keyword": keyword,
                "collect_time": collect_time,
                "company_industry": job.get("industry", ""),
                "company_size": job.get("company_size", ""),
                "financing_stage": job.get("company_type", ""),
            }
            rows.append(row)
else:
    csv_files = sorted(glob.glob(os.path.join(RAW_DIR, "*.csv")))
    for fpath in csv_files:
        if fpath.endswith("merged_raw.csv"):
            continue
        with open(fpath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for job in reader:
                rows.append({
                    "job_title": job.get("job_title", ""),
                    "company_name": job.get("company_name", ""),
                    "salary_range": job.get("salary_range", ""),
                    "city": job.get("city", _city),
                    "education": job.get("education", ""),
                    "experience": job.get("experience", ""),
                    "benefits": job.get("benefits", ""),
                    "source": job.get("source", "unknown"),
                    "search_keyword": job.get("search_keyword", ""),
                    "collect_time": job.get("collect_time", ""),
                })

with open(OUTPUT, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "job_title", "company_name", "salary_range", "city",
        "education", "experience",
        "benefits", "source",
        "search_keyword", "collect_time",
        "company_industry", "company_size", "financing_stage",
    ])
    writer.writeheader()
    writer.writerows(rows)

print(f"Merged {len(rows)} jobs into {OUTPUT}")
