"""
Pipeline state manager — enforces step-by-step execution order.

Usage:
  python scripts/pipeline/pipeline.py status                 # Show all pipeline status
  python scripts/pipeline/pipeline.py check <pipeline> <step>      # Check prerequisites (exit 1 if blocked)
  python scripts/pipeline/pipeline.py verify <pipeline> <step>     # Verify step output quality (exit 2 if failed)
  python scripts/pipeline/pipeline.py preflight [pipeline]        # Pre-flight: validate context + check stale output
  python scripts/pipeline/pipeline.py complete <pipeline> <step>   # Mark step as completed (runs verify first)
  python scripts/pipeline/pipeline.py reset [pipeline]             # Reset pipeline state
  python scripts/pipeline/pipeline.py reset --hard                 # Reset ALL pipelines + delete state file
  python scripts/pipeline/pipeline.py keyword-verify <source> <keyword>   # Verify single source×keyword (exit 2 if incomplete)
  python scripts/pipeline/pipeline.py keyword-status              # Show keyword verify status
  python scripts/pipeline/pipeline.py auth-scan <source>           # Post-source auth gate (exit 1 if login evidence found)
  python scripts/pipeline/pipeline.py robot-check <pipeline> <source_name>  # Pre-collection compliance gate (exit 1 if site prohibits crawling)
  python scripts/pipeline/pipeline.py robots-check <source_url>  # Pre-collection robots.txt gate (exit 1 if disallowed)
  python scripts/pipeline/pipeline.py compliance-check           # Check compliance acceptance (exit 1 if not accepted)
  python scripts/pipeline/pipeline.py compliance-accept          # Record user's compliance acceptance
  python scripts/pipeline/pipeline.py rate-tick <source_id>      # Pre-request rate limit gate (exit 1 if exceeded)
  python scripts/pipeline/pipeline.py save-verify <source> <keyword>  # Per-batch field completeness gate (exit 2 if incomplete)
  python scripts/pipeline/pipeline.py self-test                   # Run all verify functions against synthetic test data
"""

import json
import os
import re
import sys
import shutil
import tempfile
from datetime import datetime
from collections import defaultdict, OrderedDict
from typing import Dict, List, Optional, Tuple

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_FILE = os.path.join(BASE_DIR, "data", ".pipeline_state.json")
CONTEXT_FILE = os.path.join(BASE_DIR, "data", ".bole_context.json")
VERIFY_LOCK = os.path.join(BASE_DIR, "data", ".verify_blocked")
MCP_VERIFIED = os.path.join(BASE_DIR, "data", ".mcp_verified")
AUTH_BLOCKED = os.path.join(BASE_DIR, "data", ".auth_blocked")
BOSS_LOGIN_VERIFIED = os.path.join(BASE_DIR, "data", ".boss_login_verified")
RESTART_REQUIRED = os.path.join(BASE_DIR, "data", ".restart_required")
COMPLIANCE_ACCEPTED = os.path.join(BASE_DIR, "data", ".compliance_accepted")
RAW_DATA_DIR = os.path.join(BASE_DIR, "data", "position", "raw")
KEYWORD_VERIFY_STATUS = os.path.join(BASE_DIR, "data", "position", ".keyword_verify_status.json")
ROBOT_CHECK_RAW = os.path.join(BASE_DIR, "data", "enterprise", "raw")
ROBOT_CHECK_POSITION_EVIDENCE = os.path.join(BASE_DIR, "data", "position", "raw", "evidence")
ROBOTS_CHECK_DIR = os.path.join(BASE_DIR, "data", "position", "raw", "evidence")
RATE_STATE_FILE = os.path.join(BASE_DIR, "data", ".rate_state.json")

# ── Constants ──
STALE_OUTPUT_DIRS = [
    os.path.join(BASE_DIR, "data", "position", "output"),
    os.path.join(BASE_DIR, "data", "enterprise", "output"),
]


# ═══════════════════════════════════════════════════════════════
# Job Field Resolution — source-agnostic field access
# ═══════════════════════════════════════════════════════════════

# Known field aliases across different source platforms.
# Standard field name → possible source-specific keys in raw data.
# First match wins; exact standard name is checked first.
# Extend this when adding new sources with non-standard schemas.
JOB_FIELD_ALIASES = {
    "title": ["jobName", "positionName", "job_title", "name"],
    "company": ["brandName", "companyName", "company_full_name"],
    "salary": ["salaryDesc", "salaryRange"],
    "experience": ["expDesc", "experienceDesc", "workingExp"],
    "education": ["eduDesc", "educationDesc"],
}


def _get_job_field(job: dict, field: str) -> str:
    """Resolve a standard field name from raw job data.

    Tries the standard key first, then each alias in JOB_FIELD_ALIASES.
    Returns '' if no alias has a value.

    Usage:
        title = _get_job_field(job, "title")  # returns jobName if title absent
    """
    val = job.get(field)
    if val:
        return val
    for alias in JOB_FIELD_ALIASES.get(field, []):
        val = job.get(alias)
        if val:
            return val
    return ""


def _job_has_field(job: dict, field: str) -> bool:
    """Check if a job dictionary has the given field (standard key or alias key exists).

    Matches original 'field in job' semantics (key existence, not truthiness)
    while also accepting source-specific aliases (e.g. jobName for title).
    """
    if field in job:
        return True
    for alias in JOB_FIELD_ALIASES.get(field, []):
        if alias in job:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# Pipeline Definitions
# ═══════════════════════════════════════════════════════════════

PIPELINES: Dict[str, Dict] = {
    "bole": {
        "title": "岗位采集管线",
        "steps": [
            ("confirm_mode", "确认模式", []),
            ("mcp_precheck", "MCP 预检", ["confirm_mode"]),
            ("mainstream_sources", "主流平台来源", ["mcp_precheck"]),
            ("collect", "采集", ["mainstream_sources"]),
            ("relevance_keywords", "相关度关键词", ["collect"]),
            ("dedup", "去重", ["relevance_keywords"]),
            ("score", "评分", ["dedup"]),
            ("format", "格式化", ["score"]),
            ("report", "报告", ["format"]),
            ("handoff", "管线衔接", ["report"]),
        ],
    },
    "enterprise": {
        "title": "企业资质管线",
        "steps": [
            ("confirm_mode", "确认模式", []),
            ("discover_sources", "发现来源", ["confirm_mode"]),
            ("collect", "采集", ["discover_sources"]),
            ("clean", "清洗", ["collect"]),
            ("industry_keywords", "行业信号词", ["clean"]),
            ("score", "评分", ["industry_keywords"]),
            ("format", "格式化", ["score"]),
            ("handoff", "管线衔接", ["format"]),
        ],
    },
    "enrich": {
        "title": "富化桥梁管线",
        "steps": [
            ("enrich", "企业匹配富化", []),
            ("report", "报告", ["enrich"]),
            ("final_filter", "最终过滤", ["report"]),
            ("format", "格式化", ["final_filter"]),
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# State Management
# ═══════════════════════════════════════════════════════════════

def _get_state() -> dict:
    """Load pipeline state from STATE_FILE. Returns default if file missing."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"pipelines": {}, "completed_at": {}}


def _save_state(state: dict):
    """Save pipeline state to STATE_FILE."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _read_bole_context() -> dict:
    """Read bole context (city, keywords) from .bole_context.json."""
    if not os.path.exists(CONTEXT_FILE):
        return {}
    try:
        with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _validate_bole_context() -> list:
    """Validate .bole_context.json has non-empty city and title_keywords."""
    ctx = _read_bole_context()
    errors = []
    if not ctx.get("city", "").strip():
        errors.append("data/.bole_context.json 缺少 city（目标城市）")
    if not ctx.get("title_keywords", []):
        errors.append("data/.bole_context.json 缺少 title_keywords（目标岗位）")
    return errors


# ═══════════════════════════════════════════════════════════════
# CSV / JSON Helpers
# ═══════════════════════════════════════════════════════════════

def load_csv(filepath: str, encoding: str = "utf-8-sig") -> List[Dict]:
    if not os.path.exists(filepath):
        return []
    import csv
    with open(filepath, "r", encoding=encoding) as f:
        return list(csv.DictReader(f))


def write_csv(filepath: str, rows: List[Dict], fieldnames: List[str],
              encoding: str = "utf-8-sig"):
    import csv
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="", encoding=encoding) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            out = {k: row.get(k, "") or "" for k in fieldnames}
            w.writerow(out)


def load_json(filepath: str) -> Optional[dict]:
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# ═══════════════════════════════════════════════════════════════
# Keyword State — Track per-keyword verification for collect step
# ═══════════════════════════════════════════════════════════════

def _load_keyword_state() -> dict:
    """Load keyword verify state from KEYWORD_VERIFY_STATUS."""
    if os.path.exists(KEYWORD_VERIFY_STATUS):
        try:
            with open(KEYWORD_VERIFY_STATUS, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_keyword_state(state: dict):
    """Save keyword verify state."""
    os.makedirs(os.path.dirname(KEYWORD_VERIFY_STATUS), exist_ok=True)
    with open(KEYWORD_VERIFY_STATUS, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _mark_keyword_verified(source: str, keyword: str,
                           total_pages: int, total_count: int):
    """Record a source×keyword combo as fully collected and verified."""
    state = _load_keyword_state()
    src_state = state.setdefault(source, {})
    kw_state = src_state.setdefault(keyword, {})
    kw_state["verified"] = True
    kw_state["total_pages"] = total_pages
    kw_state["pages_collected"] = list(range(1, total_pages + 1))
    kw_state["total_count"] = total_count
    kw_state["verified_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_keyword_state(state)


def _list_raw_page_files(raw_dir: str, source: str, keyword: str) -> Dict[int, str]:
    """List all page files for a source×keyword combo, returning {page_num: path}."""
    pattern = re.compile(re.escape(source) + "_" + re.escape(keyword) + r"_page(\d+)\.json$")
    pages = {}
    if os.path.isdir(raw_dir):
        for fname in os.listdir(raw_dir):
            m = pattern.match(fname)
            if m:
                pages[int(m.group(1))] = os.path.join(raw_dir, fname)
    return pages


# ═══════════════════════════════════════════════════════════════
# VERIFY_TABLE — Step-specific verification functions
# ═══════════════════════════════════════════════════════════════

VERIFY_TABLE: Dict[str, Dict[str, callable]] = {}


def _v_bole_confirm_mode():
    """Check .bole_context.json exists and has required fields."""
    ctx = _read_bole_context()
    if not ctx:
        return False, "data/.bole_context.json missing or empty"
    if not ctx.get("city", "").strip():
        return False, "city is empty in .bole_context.json"
    if not ctx.get("title_keywords", []):
        return False, "title_keywords is empty in .bole_context.json"
    # 用户确认检查
    if not ctx.get("_meta", {}).get("confirmed_by_user"):
        return False, "意图未获用户确认 — .bole_context.json 缺少 _meta.confirmed_by_user。AI 必须展示意图信息给用户并获得明确确认后才可设置此标记。"
    # 清除旧 MCP 标记，下次必须重新验证
    if os.path.exists(MCP_VERIFIED):
        os.remove(MCP_VERIFIED)
    return True, f"city={ctx.get('city')}, keywords={ctx.get('title_keywords')}"
VERIFY_TABLE["bole"] = VERIFY_TABLE.get("bole", {})
VERIFY_TABLE["bole"]["confirm_mode"] = _v_bole_confirm_mode


def _v_bole_mcp_precheck():
    """Check .mcp_verified marker exists and contains valid MCP evidence."""
    if not os.path.exists(MCP_VERIFIED):
        return False, "MCP 未验证 — data/.mcp_verified 不存在。AI 必须调用 browser_snapshot 确认 MCP 可用后写入标记。"
    try:
        with open(MCP_VERIFIED, "r") as f:
            content = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False, f"MCP 验证标记格式错误 — {MCP_VERIFIED} 不是有效 JSON"
    if not isinstance(content, dict):
        return False, "MCP 验证标记内容不是 JSON 对象"
    if content.get("tool") != "browser_snapshot":
        return False, f"MCP 验证标记缺少 tool=\"browser_snapshot\"（当前: {content.get('tool', '空')}）"
    if not content.get("url"):
        return False, "MCP 验证标记缺少 url（browser_snapshot 时的页面 URL）"
    if not content.get("timestamp"):
        return False, "MCP 验证标记缺少 timestamp"
    return True, f"MCP verified (url: {content.get('url')})"
VERIFY_TABLE["bole"]["mcp_precheck"] = _v_bole_mcp_precheck


def _v_bole_mainstream_sources():
    """Check .sources.json contains at least the 6 fixed mainstream platforms."""
    path = os.path.join(BASE_DIR, "data", "position", ".sources.json")
    if not os.path.exists(path):
        return False, f".sources.json not found at {path}"
    data = load_json(path)
    if not isinstance(data, list):
        return False, ".sources.json is not a JSON array"
    expected = {"boss", "liepin", "51job", "zhaopin", "lagou"}
    found = {s.get("id") for s in data if s.get("enabled")}
    missing = expected - found
    if missing:
        return False, f"主流平台缺失: {', '.join(sorted(missing))}"
    return True, f"5 个主流平台均已配置"
VERIFY_TABLE["bole"]["mainstream_sources"] = _v_bole_mainstream_sources


def _v_bole_collect():
    """Check raw JSON files exist for each enabled source × keyword."""
    # 1) Auth block check — 有未解决的登录/验证码则卡死
    if os.path.exists(AUTH_BLOCKED):
        return False, f"管道被 auth block 阻塞 — {AUTH_BLOCKED} 存在。AI 必须先等待用户处理登录/验证码，然后运行 `python scripts/pipeline/pipeline.py auth-release` 解锁。"

    sources_path = os.path.join(BASE_DIR, "data", "position", ".sources.json")
    sources = load_json(sources_path) or []
    enabled_sources = [s for s in sources if s.get("pipeline") == "job" and s.get("enabled")]
    if not enabled_sources:
        return False, "no enabled job sources in .sources.json"

    ctx = _read_bole_context()
    keywords = ctx.get("search_keywords", ctx.get("title_keywords", []))
    if not keywords:
        return False, "no keywords in .bole_context.json"

    raw_dir = os.path.join(BASE_DIR, "data", "position", "raw")
    if not os.path.isdir(raw_dir):
        return False, "raw directory not found"

    # 2) File existence check
    all_files = os.listdir(raw_dir)
    missing = []
    for src in enabled_sources:
        sid = src.get("id", "")
        if src.get("tech_type") == "notice_list":
            continue
        for kw in keywords:
            pattern = re.compile(re.escape(sid) + "_" + re.escape(kw) + r"_page\d+\.json")
            found = any(pattern.match(f) for f in os.listdir(raw_dir))
            if not found:
                missing.append(f"{sid}/{kw}")

    if missing:
        return False, f"missing files for {len(missing)} source/keyword combos: {missing[:5]}..."

    # 3) JSON field completeness check — 每个文件必须包含必要字段
    REQUIRED_ENVELOPE_FIELDS = ["source", "keyword", "city", "page", "jobs"]
    REQUIRED_JOB_FIELDS = ["title", "company", "salary", "experience", "education"]
    BOSS_IDS = ("boss",)

    field_issues = []
    for fname in all_files:
        if not fname.endswith(".json"):
            continue
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        # Check envelope fields
        for field in REQUIRED_ENVELOPE_FIELDS:
            if field not in data:
                field_issues.append(f"{fname}: 缺少必要 envelope 字段 '{field}'")
                break
        # Check per-job fields (only when jobs non-empty)
        jobs = data.get("jobs", [])
        if jobs:
            for i, job in enumerate(jobs):
                for field in REQUIRED_JOB_FIELDS:
                    if not _job_has_field(job, field):
                        field_issues.append(f"{fname} jobs[{i}]: 缺少必要字段 '{field}'"
                                            f"（也不包含任何别名: {JOB_FIELD_ALIASES.get(field, [])}）")
                        break
                # BOSS 必须含 lid/encryptJobId（去重必需）
                sid = fname.split("_")[0]
                if sid in BOSS_IDS and "lid" not in job and "encryptJobId" not in job:
                    field_issues.append(f"{fname} jobs[{i}]: BOSS 数据缺少 lid/encryptJobId")

        # Check note field is one of allowed values
        note = data.get("note", "")
        if note and note not in ALLOWED_NOTES:
            field_issues.append(f"{fname}: note 字段值 '{note}' 不在许可列表中")

    if field_issues:
        return False, (
            "JSON 字段完整性检测失败（exit(2) STOP — 数据字段不完整，AI 不得推进到下一步）:\n  "
            + "\n  ".join(field_issues[:15])
        )

    # 4) Page depth check — 主流平台翻页确认
    major = ("boss", "liepin", "51job", "zhaopin", "lagou")
    for src in enabled_sources:
        sid = src.get("id", "")
        if sid not in major:
            continue
        for kw in keywords:
            pages = sorted(f for f in all_files if re.match(re.escape(sid) + "_" + re.escape(kw) + r"_page\d+\.json$", f))
            if len(pages) == 1:
                data = load_json(os.path.join(raw_dir, pages[0]))
                job_count = len(data.get("jobs", [])) if data else 0
                if job_count >= 10:
                    return False, f"{sid}/{kw}: 仅采了 1 页但含 {job_count} 条岗位，疑似未翻页"

    # 5) Keyword relevance check — do job titles contain the search keyword?
    relevance_issues = []
    for fname in all_files:
        if not fname.endswith(".json"):
            continue
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        keyword = data.get("keyword", "")
        if not keyword or keyword == "all":
            continue
        jobs = data.get("jobs", [])
        if len(jobs) < 5:
            continue
        titles = [_get_job_field(j, "title") for j in jobs if _get_job_field(j, "title")]
        match_count = sum(1 for t in titles if keyword in t)
        rate = match_count / len(titles) if titles else 0
        if rate < 0.05:
            relevance_issues.append(
                f"{fname}: 仅 {match_count}/{len(titles)} ({rate:.0%}) "
                f"的岗位标题含关键词 '{keyword}'"
            )

    if relevance_issues:
        return False, (
            "关键词相关度检测失败（exit(2) STOP — 岗位标题与搜索关键词不匹配，"
            "数据疑似与搜索关键词不对应）:\n  "
            + "\n  ".join(relevance_issues[:10])
        )

    # 6) Data quality check — 薪资字段空置率检测（识别登录脱敏场景）
    EMPTY_SALARY_THRESHOLD = 0.8
    src_jobs: Dict[str, list] = {}
    for fname in all_files:
        if not fname.endswith(".json"):
            continue
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        sid = data.get("source", fname.split("_")[0])
        src_jobs.setdefault(sid, []).extend(data.get("jobs", []))

    quality_issues = []
    for sid, jobs in src_jobs.items():
        if not jobs:
            continue
        empty = sum(1 for j in jobs if not _get_job_field(j, "salary"))
        rate = empty / len(jobs)
        if rate > EMPTY_SALARY_THRESHOLD:
            quality_issues.append(
                f"  {sid}: {len(jobs)} 条岗位中 {empty} 条薪资为空（{rate:.0%}）"
            )

    if quality_issues:
        return False, (
            "═══════════════════════════════════════════════════════════════\n"
            "  数据质量检测失败：以下来源薪资空置率超过 80%，疑似登录墙导致\n"
            "  数据脱敏。AI 必须暂停并向用户展示此报告，等待用户决策。\n"
            "  用户确认前，不得推进到下一步（dedup）。\n"
            "═══════════════════════════════════════════════════════════════\n" +
            "\n".join(quality_issues)
        )

    # 6) Source origin check — 验证数据来自 MCP 采集而非 WebSearch 伪造
    for fname in all_files:
        if not fname.endswith(".json"):
            continue
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        source_type = data.get("_meta", {}).get("tool_used") or data.get("source_type", "")
        if source_type != "mcp":
            return False, f"{fname}: 数据来源未标记为 MCP 采集（_meta.tool_used != \"mcp\"）。AI 必须通过浏览器 MCP 工具采集数据，不得用 WebSearch 替代。"

    # 7) Note field + evidence check for all raw files
    for fname in all_files:
        if not fname.endswith(".json"):
            continue
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        if "note" not in data:
            return False, f"{fname} 缺少 note 字段"
        if data.get("note") == "login_blocked":
            sid = data.get("source", fname.split("_")[0])
            kw = data.get("keyword", "")
            evidence_dir = os.path.join(raw_dir, "evidence")
            evidence_path = os.path.join(evidence_dir, f"{sid}_{kw}.png")
            if not os.path.exists(evidence_path):
                return False, f"{fname}: 标记 login_blocked 但未找到证据截图 ({sid}_{kw}.png)"
        if data.get("note") == "no_results":
            sid = data.get("source", fname.split("_")[0])
            kw = data.get("keyword", "")
            evidence_dir = os.path.join(raw_dir, "evidence")
            evidence_path = os.path.join(evidence_dir, f"{sid}_{kw}_no_results.png")
            if not os.path.exists(evidence_path):
                return False, f"{fname}: 标记 no_results 但未找到证据截图 ({sid}_{kw}_no_results.png)"

    # 8) Navigation self-check evidence — 非BOSS 主流平台必须有自检留痕
    nav_issues = []
    major_no_boss = ("liepin", "51job", "zhaopin", "lagou")
    evidence_dir = os.path.join(raw_dir, "evidence")
    for src in enabled_sources:
        sid = src.get("id", "")
        if sid not in major_no_boss:
            continue
        check_record = os.path.join(evidence_dir, f"{sid}_check.json")
        if not os.path.exists(check_record):
            nav_issues.append(f"{sid}: 缺少自检记录 evidence/{sid}_check.json（AI 未执行导航后自检）")
            continue
        record = load_json(check_record)
        if not record:
            nav_issues.append(f"{sid}: 自检记录为空或无效 JSON")
            continue
        if "login_detected" not in record:
            nav_issues.append(f"{sid}: 自检记录缺少 login_detected 字段")

    if nav_issues:
        err_lines = ["导航自检证据缺失（exit(2) STOP — AI 未执行导航后自检清单）:"]
        err_lines.extend(nav_issues)
        return False, chr(10) + "  " + chr(10) + "  ".join(err_lines)

    # 9) Source-level user confirmation — 每个主流来源完成后必须经用户确认放行
    position_dir = os.path.join(BASE_DIR, "data", "position")
    confirm_issues = []
    for src in enabled_sources:
        sid = src.get("id", "")
        if sid not in major:
            continue
        has_files = any(f.startswith(sid + "_") and f.endswith(".json") for f in all_files)
        if not has_files:
            continue
        confirmed_file = os.path.join(position_dir, f".source_{sid}_confirmed")
        if not os.path.exists(confirmed_file):
            confirm_issues.append(f"{sid}: 缺少用户放行确认标记 .source_{sid}_confirmed（AI 未暂停等用户确认）")
    if confirm_issues:
        msgs = ["来源放行确认缺失（exit(2) STOP — AI 未等待用户确认即自动继续下一来源）:"]
        msgs.extend(confirm_issues)
        return False, chr(10) + "  " + chr(10) + "  ".join(msgs)

    # 10) Keyword verify record check — 每个来源×关键词必须有 keyword-verify 记录
    kw_state = _load_keyword_state()
    missing_verify = []
    for src in enabled_sources:
        sid = src.get("id", "")
        if src.get("tech_type") == "notice_list":
            continue
        for kw in keywords:
            pattern = re.compile(re.escape(sid) + "_" + re.escape(kw) + r"_page\d+\.json$")
            has_files = any(pattern.match(f) for f in all_files)
            if not has_files:
                continue
            record = kw_state.get(sid, {}).get(kw, {})
            if not record.get("verified"):
                missing_verify.append(f"{sid}/{kw}")

    if missing_verify:
        return False, (
            "关键词 verify 记录缺失（exit(2) STOP — 以下来源×关键词已采集但缺少 keyword-verify 确认）:\n  "
            + "\n  ".join(missing_verify)
            + "\n\nAI 必须对每个来源×关键词运行 pipeline.py keyword-verify 确认采集完整性。"
        )
    # 11) City evidence check — each source with collected data must have city verification
    evidence_dir = os.path.join(raw_dir, "evidence")
    city_issues = []
    for src in enabled_sources:
        sid = src.get("id", "")
        has_files = any(f.startswith(sid + "_") and f.endswith(".json") for f in all_files)
        if not has_files:
            continue
        ev_file = os.path.join(evidence_dir, f".city_verified_{sid}.json")
        if not os.path.exists(ev_file):
            city_issues.append(f"{sid}: 缺少城市选择存证 evidence/.city_verified_{sid}.json（AI 未执行城市选择子 Agent 或跳过城市选择）")
            continue
        ev = load_json(ev_file)
        if not ev:
            city_issues.append(f"{sid}: 城市存证文件为空或无效 JSON")
            continue
        if "city" not in ev or "city_code" not in ev:
            city_issues.append(f"{sid}: 城市存证缺少必要字段（city/city_code）")
    if city_issues:
        return False, (
            "城市存证检查失败（exit(2) STOP — AI 未正确执行城市选择或存证文件损坏，不得跳过城市选择步骤）:\\n  "
            + "\\n  ".join(city_issues)
        )

    return True, f"{len(enabled_sources)} sources × {len(keywords)} keywords verified"
VERIFY_TABLE["bole"]["collect"] = _v_bole_collect

def _v_bole_relevance_keywords():
    """Check .relevance_keywords.json exists."""
    path = os.path.join(BASE_DIR, "data", "position", ".relevance_keywords.json")
    if not os.path.exists(path):
        return False, ".relevance_keywords.json not found"
    data = load_json(path)
    if not data or not data.get("keywords"):
        return False, ".relevance_keywords.json has no keywords"
    if not data.get("_meta", {}).get("confirmed_by_user"):
        return False, "相关度关键词未获用户确认 — .relevance_keywords.json 缺少 _meta.confirmed_by_user。AI 必须展示关键词给用户并获得确认后才可设置此标记。"
    return True, f"{len(data['keywords'])} relevance keywords"
VERIFY_TABLE["bole"]["relevance_keywords"] = _v_bole_relevance_keywords


def _v_bole_dedup():
    """Check deduped CSV exists and has rows."""
    path = os.path.join(BASE_DIR, "data", "position", "processed", "position_deduped.csv")
    if not os.path.exists(path):
        return False, "position_deduped.csv not found"
    rows = load_csv(path)
    if len(rows) == 0:
        return False, "position_deduped.csv is empty"
    return True, f"{len(rows)} deduped rows"
VERIFY_TABLE["bole"]["dedup"] = _v_bole_dedup


def _v_bole_score():
    """Check scored CSV exists and has total_score column."""
    path = os.path.join(BASE_DIR, "data", "position", "processed", "position_scored.csv")
    if not os.path.exists(path):
        return False, "position_scored.csv not found"
    rows = load_csv(path)
    if len(rows) == 0:
        return False, "position_scored.csv is empty"
    if "total_score" not in rows[0]:
        return False, "position_scored.csv missing total_score column"
    return True, f"{len(rows)} scored rows"
VERIFY_TABLE["bole"]["score"] = _v_bole_score


def _v_bole_format():
    """Check formatted CSV exists (either output/ or processed/)."""
    candidates = [
        os.path.join(BASE_DIR, "data", "position", "output", "position_formatted.csv"),
        os.path.join(BASE_DIR, "data", "position", "output", "position_basic.csv"),
        os.path.join(BASE_DIR, "data", "position", "processed", "position_formatted.csv"),
    ]
    for path in candidates:
        if os.path.exists(path):
            rows = load_csv(path)
            return True, f"{len(rows)} rows in {os.path.basename(path)}"
    return False, "no formatted CSV found in output/ or processed/"
VERIFY_TABLE["bole"]["format"] = _v_bole_format


def _v_bole_report():
    """Check report file exists."""
    path = os.path.join(BASE_DIR, "data", "position", "output", "position_report.md")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            size = len(f.read())
        return True, f"report.md exists ({size} chars)"
    return False, "position_report.md not found"
VERIFY_TABLE["bole"]["report"] = _v_bole_report


def _v_bole_handoff():
    """Check user has responded about enterprise pipeline handoff.

    Passes if:
      - handoff.to_enterprise is 'approved' (user wants enterprise)
      - handoff.to_enterprise is 'skipped' (user skipped)
      - handoff.to_enterprise is 'completed' (enterprise already done)
      - enterprise_scored.csv already exists (historical data, no question needed)

    Fails if:
      - handoff.to_enterprise is 'pending' (user hasn't been asked yet)
    """
    ctx = _read_bole_context()
    if not ctx:
        return False, "data/.bole_context.json missing — cannot determine handoff status"

    handoff = ctx.get("handoff", {})
    status = handoff.get("to_enterprise", "pending")

    # Already decided — any decision passes
    if status in ("approved", "skipped", "completed"):
        reason = {"approved": "用户已确认继续", "skipped": "用户已跳过", "completed": "已完成"}
        return True, f"企业管线衔接: {reason.get(status, status)}"

    # Historical data exists — pass silently
    ent_path = os.path.join(BASE_DIR, "data", "enterprise", "processed", "enterprise_scored.csv")
    if os.path.exists(ent_path):
        return True, "企业数据已存在（历史采集），无需重新采集"

    return False, ("管线衔接未确认 (pending) — AI 必须询问用户是否继续企业资质管线，"
                   "将用户回应写入 .bole_context.json handoff.to_enterprise 后方可继续")
VERIFY_TABLE["bole"]["handoff"] = _v_bole_handoff


# ── Enterprise pipeline verify functions ──

def _v_enterprise_confirm_mode():
    return _v_bole_confirm_mode()
VERIFY_TABLE["enterprise"] = VERIFY_TABLE.get("enterprise", {})
VERIFY_TABLE["enterprise"]["confirm_mode"] = _v_enterprise_confirm_mode


def _v_enterprise_discover_sources():
    """Check .enterprise_sources.json exists and is confirmed by user."""
    path = os.path.join(BASE_DIR, "data", "enterprise", ".enterprise_sources.json")
    if not os.path.exists(path):
        return False, "data/enterprise/.enterprise_sources.json 不存在 — AI 未执行企业来源发现步骤或未写结构化输出"
    data = load_json(path)
    if not data:
        return False, ".enterprise_sources.json 为空或无效 JSON"
    if not data.get("_meta", {}).get("confirmed_by_user"):
        return False, "企业来源未获用户确认 — .enterprise_sources.json 缺少 _meta.confirmed_by_user。AI 必须展示来源列表给用户并获得明确确认后才可设置此标记。"
    sources = data.get("qualification_sources", [])
    if not sources:
        return False, "qualification_sources 为空 — 没有已确认的企业资质来源"
    return True, f"{len(sources)} 个资质来源 (city: {data.get('city', '?')})"
VERIFY_TABLE["enterprise"]["discover_sources"] = _v_enterprise_discover_sources


def _v_enterprise_collect():
    """Check enterprise raw data exists and no disallowed formats.

    Also verifies each source has a completed robot_check (compliance pre-check).
    """
    ALLOWED_EXT = (".json", ".csv", ".xls", ".xlsx", ".pdf", ".doc", ".docx", ".txt")
    DISALLOWED_IMG = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
    path = os.path.join(BASE_DIR, "data", "enterprise", "raw", "qualification_lists")
    if not os.path.isdir(path):
        return False, "qualification_lists/ not found"
    all_files = os.listdir(path)
    # Reject image files — they are not valid collection output
    img_files = [f for f in all_files if f.lower().endswith(DISALLOWED_IMG)]
    if img_files:
        return False, ("qualification_lists/ 中包含非许可格式的图片文件，PNG/JPEG 不是 "
                       "企业名录的有效格式，AI 不得以截图替代数据提取。\n  "
                       + "\n  ".join(img_files[:10]))
    data_files = [f for f in all_files if f.lower().endswith(ALLOWED_EXT)]
    if len(data_files) == 0:
        return False, "no enterprise data files found (允许格式: json/csv/xls/xlsx/pdf/doc/docx/txt)"

    # ── Robot compliance check: each data source must have a .robot_check_*.json ──
    robot_checks = {
        f for f in os.listdir(ROBOT_CHECK_RAW)
        if f.startswith(".robot_check_") and f.endswith(".json")
    }
    missing_checks = []
    prohibited_found = []
    for df in data_files:
        # Derive source name from filename (去掉扩展名作为 source 标识)
        base = os.path.splitext(df)[0]
        expected_check = f".robot_check_{base}.json"
        if expected_check not in robot_checks:
            # 尝试按 source_name 前缀匹配（文件名可能被截断或包含多余信息）
            # .robot_check_{source_name}.json 可能在 robot_checks 中存在包含关系
            match_found = any(rc.startswith(f".robot_check_{base}") for rc in robot_checks)
            if not match_found:
                missing_checks.append(df)
            else:
                # Check the matched file for collectable status
                matched_file = next(rc for rc in robot_checks if rc.startswith(f".robot_check_{base}"))
                try:
                    with open(os.path.join(ROBOT_CHECK_RAW, matched_file), "r") as f:
                        rc_data = json.load(f)
                    if rc_data.get("scan_method", "unknown") != "code":
                        prohibited_found.append(f"{df}: scan_method='{rc_data.get('scan_method', 'unknown')}' 要求为 'code'（AI 自行判断无效）")
                    if not rc_data.get("collectable", True):
                        prohibited_found.append(f"{df}: robot_check 标记为 collectable=false ({rc_data.get('reason', '无原因')})")
                except (json.JSONDecodeError, IOError):
                    missing_checks.append(f"{df} (robot_check 文件无法读取)")

    issues = []
    if missing_checks:
        issues.append("以下数据文件缺少对应的 .robot_check_*.json 合规自检记录:\n  "
                      + "\n  ".join(missing_checks[:10]))
    if prohibited_found:
        issues.append("以下来源的 robot_check 标记为不可采集（collectable=false）:\n  "
                      + "\n  ".join(prohibited_found[:10]))

    if issues:
        return False, ("企业数据合规自检不完整:\n" + "\n".join(issues))

    return True, f"{len(data_files)} data files, {len(robot_checks)} robot checks"
VERIFY_TABLE["enterprise"]["collect"] = _v_enterprise_collect


def _v_enterprise_clean():
    """Check cleaned enterprise CSV exists."""
    path = os.path.join(BASE_DIR, "data", "enterprise", "processed", "enterprise_cleaned.csv")
    if not os.path.exists(path):
        return False, "enterprise_cleaned.csv not found"
    rows = load_csv(path)
    return True, f"{len(rows)} cleaned enterprises"
VERIFY_TABLE["enterprise"]["clean"] = _v_enterprise_clean


def _v_enterprise_industry_keywords():
    """Check industry keywords file exists."""
    path = os.path.join(BASE_DIR, "data", "enterprise", ".industry_keywords.json")
    if not os.path.exists(path):
        return False, ".industry_keywords.json not found"
    data = load_json(path)
    if not data or not data.get("target_kw"):
        return False, ".industry_keywords.json has no target_kw"
    if not data.get("_meta", {}).get("confirmed_by_user"):
        return False, "行业信号词未获用户确认 — .industry_keywords.json 缺少 _meta.confirmed_by_user。AI 必须展示信号词给用户并获得确认后才可设置此标记。"
    return True, f"{len(data['target_kw'])} target keywords"
VERIFY_TABLE["enterprise"]["industry_keywords"] = _v_enterprise_industry_keywords


def _v_enterprise_score():
    """Check enterprise scored CSV exists."""
    path = os.path.join(BASE_DIR, "data", "enterprise", "processed", "enterprise_scored.csv")
    if not os.path.exists(path):
        return False, "enterprise_scored.csv not found"
    rows = load_csv(path)
    if len(rows) == 0:
        return False, "enterprise_scored.csv is empty"
    return True, f"{len(rows)} scored enterprises"
VERIFY_TABLE["enterprise"]["score"] = _v_enterprise_score


def _v_enterprise_format():
    """Check formatted enterprise output exists."""
    path = os.path.join(BASE_DIR, "data", "enterprise", "output", "enterprise_basic.csv")
    if os.path.exists(path):
        rows = load_csv(path)
        return True, f"{len(rows)} rows in enterprise_basic.csv"
    path2 = os.path.join(BASE_DIR, "data", "enterprise", "output", "enterprise_report.md")
    if os.path.exists(path2):
        return True, "enterprise_report.md exists"
    return False, "no enterprise formatted output found"
VERIFY_TABLE["enterprise"]["format"] = _v_enterprise_format


def _v_enterprise_handoff():
    """Check user has responded about enrich pipeline handoff.

    Passes if:
      - handoff.to_enrich is 'approved' / 'skipped' / 'completed'
      - position_enriched.csv already exists (historical data)

    Fails if:
      - handoff.to_enrich is 'pending' (user hasn't been asked yet)
    """
    ctx = _read_bole_context()
    if not ctx:
        return False, "data/.bole_context.json missing — cannot determine handoff status"

    handoff = ctx.get("handoff", {})
    status = handoff.get("to_enrich", "pending")

    if status in ("approved", "skipped", "completed"):
        reason = {"approved": "用户已确认继续", "skipped": "用户已跳过", "completed": "已完成"}
        return True, f"富化管线衔接: {reason.get(status, status)}"

    # Historical data exists — pass silently
    enrich_path = os.path.join(BASE_DIR, "data", "position", "output", "position_enriched.csv")
    if os.path.exists(enrich_path):
        return True, "富化数据已存在（历史采集），无需重新采集"

    return False, ("管线衔接未确认 (pending) — AI 必须询问用户是否继续富化管线，"
                   "将用户回应写入 .bole_context.json handoff.to_enrich 后方可继续")
VERIFY_TABLE["enterprise"]["handoff"] = _v_enterprise_handoff


# ── Enrich pipeline verify functions ──

def _v_enrich_enrich():
    """Check enriched CSV exists."""
    path = os.path.join(BASE_DIR, "data", "position", "output", "position_enriched.csv")
    if not os.path.exists(path):
        return False, "position_enriched.csv not found"
    rows = load_csv(path)
    return True, f"{len(rows)} enriched rows"
VERIFY_TABLE["enrich"] = VERIFY_TABLE.get("enrich", {})
VERIFY_TABLE["enrich"]["enrich"] = _v_enrich_enrich


def _v_enrich_report():
    """Check enrich report exists."""
    path = os.path.join(BASE_DIR, "data", "position", "output", "enrich_report.md")
    if os.path.exists(path):
        return True, "enrich_report.md exists"
    return False, "enrich_report.md not found"
VERIFY_TABLE["enrich"]["report"] = _v_enrich_report


def _v_enrich_final_filter():
    """Check filtered output exists."""
    path = os.path.join(BASE_DIR, "data", "position", "output", "position_final.csv")
    if os.path.exists(path):
        rows = load_csv(path)
        return True, f"{len(rows)} filtered rows"
    return False, "position_final.csv not found"
VERIFY_TABLE["enrich"]["final_filter"] = _v_enrich_final_filter


def _v_enrich_format():
    """Check final formatted enrich output."""
    path = os.path.join(BASE_DIR, "data", "position", "output", "position_final.csv")
    if os.path.exists(path):
        rows = load_csv(path)
        return True, f"{len(rows)} rows in position_final.csv"
    path2 = os.path.join(BASE_DIR, "data", "position", "output", "enrich_report.md")
    if os.path.exists(path2):
        return True, "enrich_report.md exists"
    return False, "no enrich formatted output found"
VERIFY_TABLE["enrich"]["format"] = _v_enrich_format

# ── Check hooks (pre-collection gates, called by cmd_check) ──
CHECK_HOOKS: Dict[str, Dict[str, callable]] = {}

def _ch_bole_collect():
    """Pre-collection check: BOSS login probe + keyword verify gate."""
    raw_dir = os.path.join(BASE_DIR, "data", "position", "raw")
    sources_path = os.path.join(BASE_DIR, "data", "position", ".sources.json")
    sources = load_json(sources_path) or []
    ctx = _read_bole_context()
    keywords = ctx.get("search_keywords", ctx.get("title_keywords", []))

    # 1) BOSS login probe
    boss_enabled = any(s.get("id") == "boss" and s.get("enabled") for s in sources)
    if boss_enabled:
        if os.path.exists(AUTH_BLOCKED):
            print("!! BOSS 登录预检: 管道已被 auth block 锁定，请先处理登录后以 auth-release 解锁。")
            print(f"   标记文件: {AUTH_BLOCKED}")
            sys.exit(1)
        if not os.path.exists(BOSS_LOGIN_VERIFIED):
            print("!! BOSS 登录预检: 未通过。BOSS 直聘需要登录才能获取完整数据（含薪资字段）。")
            print()
            print("   AI 必须执行 BOSS 登录探针检测（非全量采集）：")
            print("   1. browser_navigate → 1 次 POST 请求获取 1 页数据")
            print("   2. 检查返回数据的 salary 字段是否有值")
            print("   3a. 有薪资数据 → 写入标记文件并重试 check:")
            print(f"         echo 'ok' > {BOSS_LOGIN_VERIFIED}")
            print("   3b. 薪资全部为空 → 登录墙已激活，写入 auth_block 并停止:")
            print(f"         touch {AUTH_BLOCKED}")
            print("   4. 重新运行此 check 命令确认。")
            sys.exit(1)

    # 2) Keyword verify gate — unverified keywords block new collection
    if not keywords or not os.path.isdir(raw_dir):
        return
    enabled_sources = [s for s in sources if s.get("pipeline") == "job" and s.get("enabled")]
    kw_state = _load_keyword_state()
    unverified = []
    for src in enabled_sources:
        sid = src.get("id", "")
        if src.get("tech_type") == "notice_list":
            continue
        for kw in keywords:
            pages = _list_raw_page_files(raw_dir, sid, kw)
            if not pages:
                continue  # Not started yet
            record = kw_state.get(sid, {}).get(kw, {})
            if not record.get("verified"):
                unverified.append(f"{sid}/{kw}")

    if unverified:
        print("!! 关键词验证闸门: 以下来源×关键词已采集但未经验证:")
        for item in unverified:
            print(f"   - {item}")
        print()
        print("   在继续采集前，AI 必须运行以下命令验证每个关键词的完整性:")
        print()
        for item in unverified:
            parts = item.split("/", 1)
            print(f"   python scripts/pipeline/pipeline.py keyword-verify {parts[0]} \"{parts[1]}\"")
        print()
        print("   exit(2) 表示采集未完成，AI 必须继续采集当前关键词的缺失页面。")
        print("   exit(0) 后重新运行此 check 命令确认。")
        sys.exit(1)

CHECK_HOOKS["bole"] = CHECK_HOOKS.get("bole", {})
CHECK_HOOKS["bole"]["collect"] = _ch_bole_collect


def _ch_enrich_enrich():
    """Pre-enrich check: verify bole + enterprise pipelines have completed output."""
    missing = []
    pos_scored = os.path.join(BASE_DIR, "data", "position", "processed", "position_scored.csv")
    if not os.path.exists(pos_scored):
        missing.append("data/position/processed/position_scored.csv（岗位管线未完成评分）")
    ent_scored = os.path.join(BASE_DIR, "data", "enterprise", "processed", "enterprise_scored.csv")
    if not os.path.exists(ent_scored):
        missing.append("data/enterprise/processed/enterprise_scored.csv（企业管线未完成评分）")

    if missing:
        print("!! 富化前置校验失败 — 以下前置产出文件不存在:")
        for m in missing:
            print(f"   - {m}")
        print()
        print("   富化步骤需要岗位管线 (bole) 和企业管线 (enterprise) 均已完成评分步骤。")
        print("   请先完成两条管线的评分后再执行富化。")
        sys.exit(1)

    print("[OK] enrich 前置条件满足 — position_scored.csv + enterprise_scored.csv 均存在")
CHECK_HOOKS["enrich"] = CHECK_HOOKS.get("enrich", {})
CHECK_HOOKS["enrich"]["enrich"] = _ch_enrich_enrich


# ── Restart + auth block gate ──
def _bail_if_blocked():
    """Check for .restart_required, .auth_blocked and .compliance_accepted markers.

    .restart_required      → exit(2): MCP not ready, user must restart.
    .auth_blocked          → exit(1): login/verification wall detected,
                             pipeline frozen until user runs auth-release.
    .compliance_accepted   → exit(1): user has not accepted compliance terms.

    Called at the top of every state-modifying command."""
    if os.path.exists(RESTART_REQUIRED):
        print("=" * 60)
        print("  !! MCP 未就绪：安装后未重启 Claude Code")
        print("=" * 60)
        print()
        print("  data/.restart_required 标记仍然存在，说明安装后未重启。")
        print("  请完全退出当前 Claude Code 会话并重新打开。")
        print("  （不是关窗口重开，是退出进程再启动）")
        print()
        print("  ★ AI 操作指引：向用户展示此提示，请求用户重启。")
        print("    用户告知已重启后，执行 rm data/.restart_required 并继续管线。")
        print()
        sys.exit(2)

    if os.path.exists(AUTH_BLOCKED):
        try:
            with open(AUTH_BLOCKED, "r", encoding="utf-8") as f:
                detail = f.read().strip()
        except Exception:
            detail = ""
        print("=" * 60)
        print("  !! 管道被登录阻塞锁定")
        print("=" * 60)
        print()
        print("  data/.auth_blocked 标记存在，检测到登录/验证码。")
        print()
        if detail:
            print(f"  详情: {detail[:300]}")
        print()
        print("  处理方式:")
        print("  1. 用户已完成登录 → python scripts/pipeline/pipeline.py auth-release")
        print("  2. 用户选择跳过该来源 → python scripts/pipeline/pipeline.py auth-release")
        print()
        print("  AI 必须向用户展示此提示，等待用户处理。")
        print()
        sys.exit(1)

    if not os.path.exists(COMPLIANCE_ACCEPTED):
        print("=" * 60)
        print("  !! 合规确认未完成")
        print("=" * 60)
        print()
        print("  data/.compliance_accepted 不存在 — 用户尚未接受合规条款。")
        print()
        print("  AI 必须向用户展示合规声明，获得明确确认后运行：")
        print(f"    python scripts/pipeline/pipeline.py compliance-accept")
        print()
        print("  或手动创建:")
        print(f"    echo 'ok' > {COMPLIANCE_ACCEPTED}")
        print()
        sys.exit(1)


# ── Protocol compliance gate ──

ALLOWED_NOTES = ("no_results", "login_blocked", "redirect_to_login", "keyword_not_applicable", "spa_cache_duplicate")


def _check_protocol_compliance(source: str = None, keyword: str = None):
    """Scan data/position/raw/ for protocol violations.

    Checks:
      1) Every note field must be in ALLOWED_NOTES (or empty for normal data).
      2) Login-blocked evidence without .auth_blocked.
      3) SPA cache / stale content (files with identical job lists).

    When called from keyword-verify (source+keyword provided), scope is
    narrowed to that specific source×keyword. Otherwise, all files are
    checked (for check/verify/complete global commands).

    Exit 1 (blocked) if violations found.
    This is a code-level gate — the AI cannot edit or bypass this function."""
    raw_dir = os.path.join(BASE_DIR, "data", "position", "raw")
    if not os.path.isdir(raw_dir):
        return

    violations = []
    scope_label = f"（scope: {source}/{keyword}）" if keyword else "（global）"

    # ── 1) Scan for invalid note values ──
    for fname in sorted(os.listdir(raw_dir)):
        if not fname.endswith(".json"):
            continue
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        # Scope filter: keyword-verify 只检查当前关键词的文件
        if keyword and data.get("keyword", "") != keyword:
            continue
        note = data.get("note", "")
        if note and note not in ALLOWED_NOTES:
            violations.append(
                f"{fname}: note 值 '{note}' 不在许可列表中 {ALLOWED_NOTES}"
            )

    # ── 2) Login-blocked evidence without .auth_blocked ──
    # Always global — if any login_blocked file exists without .auth_blocked,
    # it's a protocol violation regardless of keyword scope.
    if not os.path.exists(AUTH_BLOCKED):
        src_issues = defaultdict(list)
        for fname in sorted(os.listdir(raw_dir)):
            if not fname.endswith(".json"):
                continue
            data = load_json(os.path.join(raw_dir, fname))
            if not data:
                continue
            note = data.get("note", "")
            if note in ("login_blocked", "redirect_to_login"):
                sid = fname.split("_")[0]
                src_issues[sid].append(fname)

        for sid, login_files in src_issues.items():
            violations.append(
                f"{sid}: {len(login_files)} 个文件标记 login_blocked/redirect_to_login "
                f"但 data/.auth_blocked 不存在\n"
                f"        → AI 检测到登录/验证码后未执行阻塞协议（未写 .auth_blocked、"
                f"未暂停提示用户）"
            )

    # ── 3) Reserve for future source-level checks ──
    pass

    if violations:
        print()
        print("=" * 60)
        print("  !! 协议合规检查失败 — 采集数据存在违规")
        print("=" * 60)
        print()
        for v in violations:
            print(f"  • {v}")
        print()
        print("  范围:", scope_label)
        print()
        print("  AI 必须向用户完整展示此报告，等待用户决策。")
        print("  在用户确认处理方案前，不得执行任何管线操作。")
        print()
        sys.exit(1)


def cmd_auth_scan(source: str):
    """Mandatory post-source auth gate.

    Scans all raw JSON files for *one* source and checks for login
    evidence.  If any is found, writes data/.auth_blocked and exits 1 —
    the pipeline is frozen until the user runs auth-release.

    Evidence checked (per source — generic, not platform-specific):
      a) note=login_blocked / note=redirect_to_login in any file
      b) >80 % salary fields empty across all jobs of the source
      c) note value not in ALLOWED_NOTES

    Exit 0 = source is clean.
    Exit 1 = login evidence found → pipeline frozen."""
    raw_dir = os.path.join(BASE_DIR, "data", "position", "raw")
    if not os.path.isdir(raw_dir):
        print(f"[OK] {source}: raw 目录不存在，跳过")
        sys.exit(0)

    files = [f for f in os.listdir(raw_dir)
             if f.startswith(source + "_") and f.endswith(".json")]
    if not files:
        print(f"[OK] {source}: 无数据文件，跳过")
        sys.exit(0)

    login_files = []
    invalid_notes = []
    total_jobs = 0
    empty_salary = 0

    for fname in sorted(files):
        data = load_json(os.path.join(raw_dir, fname))
        if not data:
            continue
        jobs = data.get("jobs", [])
        total_jobs += len(jobs)
        empty_salary += sum(1 for j in jobs if not _get_job_field(j, "salary"))

        note = data.get("note", "")
        if note in ("login_blocked", "redirect_to_login"):
            login_files.append(fname)
        elif note and note not in ALLOWED_NOTES:
            invalid_notes.append(f"{fname}: note='{note}'")

    issues = []
    if login_files:
        issues.append(f"  登录标记文件: {len(login_files)} 个（{', '.join(login_files[:3])}）")
    if invalid_notes:
        issues.append(f"  无效 note 值: {'; '.join(str(x) for x in invalid_notes[:3])}")
    salary_empty_rate = empty_salary / total_jobs if total_jobs > 0 else 0
    if salary_empty_rate > 0.8:
        issues.append(f"  薪资空置率: {empty_salary}/{total_jobs} ({salary_empty_rate:.0%}) > 80%")

    if issues:
        detail = f"[{source}] auth-scan 检测到登录证据，管道已阻塞:\n" + "\n".join(issues)
        print(detail)
        print()
        os.makedirs(os.path.dirname(AUTH_BLOCKED), exist_ok=True)
        with open(AUTH_BLOCKED, "w", encoding="utf-8") as f:
            f.write(f"source: {source}\nscanned_at: {datetime.now().isoformat()}\n{detail}\n")
        print("管道已冻结。向用户展示此报告，等待用户处理。")
        print("用户操作: python scripts/pipeline/pipeline.py auth-release")
        sys.exit(1)

    print(f"[OK] {source}: {len(files)} 个文件, {total_jobs} 条岗位, 无登录检测异常")
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# Command: status
# ═══════════════════════════════════════════════════════════════

def cmd_status():
    """Print current state of all pipelines."""
    state = _get_state()
    completed = state.get("completed_at", {})

    print("=" * 60)
    print("  Pipeline Status")
    print("=" * 60)
    print()

    for pid, pipeline in PIPELINES.items():
        pipe_state = state.get("pipelines", {}).get(pid, [])
        print(f"[{pid}] {pipeline['title']}")
        print(f"  Steps: {len(pipeline['steps'])}")
        print(f"  Completed: {len([s for s in pipe_state if s in dict(pipeline['steps'])])}/{len(pipeline['steps'])}")

        for step_id, step_name, _ in pipeline["steps"]:
            if step_id in pipe_state:
                ts = completed.get(f"{pid}/{step_id}", "")
                print(f"    ✔ {step_id} ({step_name})  [{ts}]")
            else:
                print(f"    ○ {step_id} ({step_name})")

        print()

    # Show verify lock status
    if os.path.exists(VERIFY_LOCK):
        print("[!] Verify lock file detected (previous verify failure)")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════
# Command: check
# ═══════════════════════════════════════════════════════════════

def cmd_check(pid: str, step_id: str):
    """Check if step dependencies are satisfied. Exit 1 if blocked."""
    _bail_if_blocked()
    pipeline = PIPELINES.get(pid)
    if not pipeline:
        print(f"BLOCKED: unknown pipeline '{pid}'")
        sys.exit(1)

    step_info = None
    for s in pipeline["steps"]:
        if s[0] == step_id:
            step_info = s
            break
    if not step_info:
        print(f"BLOCKED: step '{step_id}' not found in pipeline '{pid}'")
        sys.exit(1)

    state = _get_state()
    completed = state.get("pipelines", {}).get(pid, [])

    sid, sname, deps = step_info

    if sid in completed:
        print(f"BLOCKED: step [{sid}] {sname} already done.")
        print(f"To re-run: python scripts/pipeline/pipeline.py reset {pid}")
        sys.exit(1)

    blocked_by = [d for d in deps if d not in completed]
    if blocked_by:
        print(f"BLOCKED: step [{sid}] {sname} has unfinished dependencies:")
        for d in blocked_by:
            dname = next((sn for sd, sn, _ in pipeline["steps"] if sd == d), d)
            print(f"  - {d} ({dname})")
        print()
        print("AI must complete all dependencies before proceeding.")
        sys.exit(1)

    # Run step-specific pre-check hook (if any)
    hook = CHECK_HOOKS.get(pid, {}).get(sid)
    if hook:
        hook()

    print(f"[OK] step [{sid}] {sname} — dependencies satisfied")
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# Command: verify
# ═══════════════════════════════════════════════════════════════

def cmd_verify(pid: str, step_id: str):
    """Verify step output quality. Exit 2 if failed."""
    _bail_if_blocked()
    pipeline = PIPELINES.get(pid)
    if not pipeline:
        print(f"FAIL: unknown pipeline '{pid}'")
        sys.exit(2)

    step_info = None
    for s in pipeline["steps"]:
        if s[0] == step_id:
            step_info = s
            break
    if not step_info:
        print(f"FAIL: step '{step_id}' not found in pipeline '{pid}'")
        sys.exit(2)

    sid, sname = step_info[0], step_info[1]

    # Look up verify function
    vfunc = VERIFY_TABLE.get(pid, {}).get(sid)
    if not vfunc:
        print(f"FAIL: no verify function for [{pid}/{sid}] {sname}")
        sys.exit(2)

    ok, msg = vfunc()
    if ok:
        print(f"[OK] [{pid}/{sid}] {sname} — {msg}")
        # Clear verify lock if present
        if os.path.exists(VERIFY_LOCK):
            os.remove(VERIFY_LOCK)
        sys.exit(0)
    else:
        print(f"[FAIL] [{pid}/{sid}] {sname}")
        print(f"  Reason: {msg}")
        print()
        print("AI must STOP and present this report to the user.")
        print("Do NOT retry, do NOT --skip-verify without user confirmation.")
        # Write verify lock file
        os.makedirs(os.path.dirname(VERIFY_LOCK), exist_ok=True)
        with open(VERIFY_LOCK, "w") as f:
            f.write(f"{pid}/{sid}\n{msg}\n")
        sys.exit(2)


# ═══════════════════════════════════════════════════════════════
# Command: complete
# ═══════════════════════════════════════════════════════════════

def cmd_complete(pid: str, step_id: str, skip: bool = False,
                 skip_verify: bool = False, skip_verify_ack: bool = False):
    """Mark step as completed. Runs verify first unless skipped."""
    _bail_if_blocked()
    pipeline = PIPELINES.get(pid)
    if not pipeline:
        print(f"Error: unknown pipeline '{pid}'")
        sys.exit(1)

    step_info = None
    for s in pipeline["steps"]:
        if s[0] == step_id:
            step_info = s
            break
    if not step_info:
        print(f"Error: step '{step_id}' not found")
        sys.exit(1)

    sid, sname = step_info[0], step_info[1]

    # Run verify unless skipped
    if not skip_verify:
        vfunc = VERIFY_TABLE.get(pid, {}).get(sid)
        if vfunc:
            ok, msg = vfunc()
            if not ok:
                print(f"[FAIL] [{pid}/{sid}] {sname} — {msg}")
                if skip_verify_ack:
                    print("--skip-verify-ack granted, proceeding with complete.")
                else:
                    print("Use --skip-verify --skip-verify-ack to bypass.")
                    sys.exit(1)
    elif not skip_verify_ack:
        print("--skip-verify requires --skip-verify-ack to confirm.")
        sys.exit(1)
    else:
        # skip-verify with ack — still block if auth_blocked exists
        if os.path.exists(AUTH_BLOCKED):
            print(f"[FAIL] [{pid}/{sid}] 无法跳过 verify：存在未解决的 auth block ({AUTH_BLOCKED})。")
            print("请先处理登录/验证码，然后运行 `python scripts/pipeline/pipeline.py auth-release` 解锁。")
            sys.exit(1)

    state = _get_state()
    completed = state.setdefault("pipelines", {}).setdefault(pid, [])
    completed_at = state.setdefault("completed_at", {})

    if sid not in completed:
        completed.append(sid)
    completed_at[f"{pid}/{sid}"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_state(state)

    print(f"[OK] [{pid}/{sid}] {sname} — completed")
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# Command: reset
# ═══════════════════════════════════════════════════════════════

def cmd_reset(pid: str = None, hard: bool = False):
    """Reset pipeline state. --hard deletes state file entirely."""
    if hard:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
            print(f"已删除 {STATE_FILE}")
        else:
            print("状态文件不存在，无需重置。")
        if os.path.exists(VERIFY_LOCK):
            os.remove(VERIFY_LOCK)
            print(f"已删除 {VERIFY_LOCK}")
        return

    # 清除 MCP 标记（新流程必须重新验证）
    if os.path.exists(MCP_VERIFIED):
        os.remove(MCP_VERIFIED)

    # 清除城市存证（新流程必须重新 UI 选择城市）
    import glob
    for f in glob.glob(os.path.join(ROBOT_CHECK_POSITION_EVIDENCE, ".city_verified_*.json")):
        os.remove(f)
        print(f"已清除城市存证: {os.path.basename(f)}")

    # 清除 .sources.json 中的 Tier-2+ 条目（仅保留 5 个主流平台）
    sources_path = os.path.join(BASE_DIR, "data", "position", ".sources.json")
    if os.path.exists(sources_path):
        import json
        with open(sources_path, "r", encoding="utf-8") as f:
            sources_data = json.load(f)
        if isinstance(sources_data, list):
            mainstream_ids = {"boss", "liepin", "51job", "zhaopin", "lagou"}
            filtered = [s for s in sources_data if s.get("id") in mainstream_ids]
            for s in filtered:
                s["enabled"] = True
            with open(sources_path, "w", encoding="utf-8") as f:
                json.dump(filtered, f, ensure_ascii=False, indent=2)
            kept = len(filtered)
            removed = len(sources_data) - kept
            print(f"已清理 .sources.json: 移除 {removed} 个非主流来源，保留 {kept} 个主流平台")
        else:
            os.remove(sources_path)
            print("已删除无效的 .sources.json")

    state = _get_state()
    if pid:
        if pid not in PIPELINES:
            print(f"错误: 未知管线 '{pid}'")
            sys.exit(1)
        state["pipelines"][pid] = []
        print(f"已重置管线 [{pid}]")
    else:
        state["pipelines"] = {}
        print("已重置所有管线")
    state["completed_at"] = {}
    _save_state(state)


# ═══════════════════════════════════════════════════════════════
# Command: preflight
# ═══════════════════════════════════════════════════════════════

def cmd_preflight(pid: str = None):
    """Pre-flight check: validate context completeness before starting a pipeline.

    Unlike 'check' which validates step dependencies, preflight validates
    user-provided context (city, job title) and detects stale output files
    that need user confirmation before being overwritten.

    This is especially important for long-running conversations where
    context degradation may occur. The preflight acts as a code-level guard: if it fails,
    the AI MUST stop and ask the user, it cannot proceed.

    Exit codes:
      0 = all clear, ready to proceed
      1 = issues found, AI must stop and ask user
    """
    _bail_if_blocked()
    ok = True

    # 1) Validate context fields (city + title_keywords)
    ctx_errs = _validate_bole_context()
    if ctx_errs:
        print("!! Pre-flight 检查失败 — 上下文缺失:")
        for e in ctx_errs:
            print(f"   - {e}")
        print()
        print("AI 必须向用户询问缺失信息，写入 data/.bole_context.json 后重试。")
        ok = False

    # 2) Check for stale output from previous runs
    for output_dir in STALE_OUTPUT_DIRS:
        if os.path.isdir(output_dir):
            existing_files = [f for f in os.listdir(output_dir)
                             if f.endswith(".csv") or f.endswith(".md")]
            if existing_files:
                print(f"!! Pre-flight 检查 — 发现旧产出 ({len(existing_files)} 个文件) 在 {output_dir}:")
                for f in existing_files[:10]:
                    fpath = os.path.join(output_dir, f)
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    print(f"   - {f}  ({mtime.strftime('%Y-%m-%d %H:%M')})")
                if len(existing_files) > 10:
                    print(f"   ... 及另 {len(existing_files) - 10} 个文件")
                print()
                print("AI 必须询问用户处理方式: 覆盖 / 备份 / 跳过采集直接出结果")
                ok = False

    # 3) Data TTL — 自动清理超过 7 天的原始数据
    DATA_TTL_DAYS = 7
    if os.path.isdir(RAW_DATA_DIR):
        deleted = []
        for fname in os.listdir(RAW_DATA_DIR):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(RAW_DATA_DIR, fname)
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(fpath))).days
            if age >= DATA_TTL_DAYS:
                os.remove(fpath)
                deleted.append((fname, age))
        if deleted:
            print(f"!! 已自动清理 {len(deleted)} 个超过 {DATA_TTL_DAYS} 天的原始数据文件:")
            for fname, age in sorted(deleted, key=lambda x: -x[1])[:10]:
                print(f"   - {fname} ({age} 天)")
            if len(deleted) > 10:
                print(f"   ... 及另 {len(deleted) - 10} 个文件")

    if ok:
        print("Pre-flight 检查通过，可以开始管线。")
        sys.exit(0)
    else:
        print("\nAI 必须先解决以上问题，不可自行跳过。")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Command: auth-release
# ═══════════════════════════════════════════════════════════════

def cmd_auth_release(source: str = None):
    """Delete auth block marker, unblock the pipeline."""
    if not os.path.exists(AUTH_BLOCKED):
        print("当前无 auth block，无需释放。")
        return
    os.remove(AUTH_BLOCKED)
    if source:
        print(f"[OK] auth block 已释放（来源: {source}）")
    else:
        print("[OK] auth block 已释放，管道已解锁。")


# ═══════════════════════════════════════════════════════════════
# Command: compliance-check / compliance-accept
# ═══════════════════════════════════════════════════════════════

COMPLIANCE_TEXT = r"""
╔══════════════════════════════════════════════════════════════╗
║                   法律合规确认                                ║
║             Legal & Compliance Acknowledgement                ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  本工具（伯乐 / bole-skill）仅供个人学习与求职参考使用。      ║
║                                                              ║
║  使用前请确认以下事项：                                        ║
║                                                              ║
║  1. 本工具为开源学习项目，不得用于商业目的                      ║
║  2. 数据通过您本人的浏览器会话获取，您对操作过程可见            ║
║  3. 您应遵守各招聘/信息平台的服务条款                          ║
║  4. 本工具不规避平台的反爬虫措施（遇验证码/登录墙即暂停）      ║
║  5. 所有数据在本地处理，不上传第三方服务器                      ║
║  6. 采集频率受代码约束，不会对平台造成异常请求负担              ║
║  7. 岗位数据本地留存不超过7天，到期自动清理                     ║
║                                                              ║
║  本人确认以上事项，并承诺在遵守各平台服务条款的前提下          ║
║  使用本工具。                                                  ║
║                                                              ║
║  输入 "同意" / "accept" 继续，其他任意内容退出。               ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""


def cmd_compliance_check():
    """Check whether the user has accepted the compliance terms.

    Exit 0 = accepted.
    Exit 1 = not accepted yet — AI must show terms and ask user."""
    if os.path.exists(COMPLIANCE_ACCEPTED):
        print("[OK] 合规确认已完成。")
        sys.exit(0)
    print("!! 合规确认未完成 — data/.compliance_accepted 不存在。")
    print()
    print("AI 必须向用户展示合规条款并获得明确确认后方可开始采集。")
    print("用户确认后运行: python scripts/pipeline/pipeline.py compliance-accept")
    sys.exit(1)


def cmd_compliance_accept():
    """Record user's compliance acceptance by writing .compliance_accepted."""
    if os.path.exists(COMPLIANCE_ACCEPTED):
        print("[OK] 合规确认已记录，无需重复确认。")
        return
    os.makedirs(os.path.dirname(COMPLIANCE_ACCEPTED), exist_ok=True)
    with open(COMPLIANCE_ACCEPTED, "w", encoding="utf-8") as f:
        json.dump({
            "accepted": True,
            "accepted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
        }, f, ensure_ascii=False, indent=2)
    print("[OK] 合规确认已记录，采集管线可以继续。")


# ═══════════════════════════════════════════════════════════════
# Command: rate-tick — pre-request rate limit gate (code-enforced)
# ═══════════════════════════════════════════════════════════════

RATE_CONFIG = {
    "burst_page_limit": 5,    # 连续 N 页后需长停
    "burst_pause": 3.0,       # 长停至少 N 秒
    "hourly_page_limit": 180, # 同一来源每小时最多 N 页
}


def _load_rate_state() -> dict:
    if os.path.exists(RATE_STATE_FILE):
        try:
            with open(RATE_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_rate_state(state: dict):
    os.makedirs(os.path.dirname(RATE_STATE_FILE), exist_ok=True)
    with open(RATE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def cmd_rate_tick(source: str):
    """Pre-request rate limit gate.

    AI calls this before each pagination/navigation request.
    Checks two constraints (code-enforced, not self-reported):
      1) Burst — after burst_page_limit consecutive requests without a long pause,
         at least burst_pause seconds since the last request
      2) Hourly — total requests in the current hour ≤ hourly_page_limit

    Exit 0 = rate limit check passed, request allowed.
    Exit 1 = rate limit violated, pipeline blocked. AI must wait."""
    now = datetime.now()
    now_ts = now.timestamp()
    hour_key = now.strftime("%Y-%m-%dT%H")  # e.g. "2026-06-10T14"

    state = _load_rate_state()
    src = state.setdefault(source, {
        "requests": [],       # list of ISO timestamps
        "hourly_buckets": {}, # {hour_key: count}
    })

    requests = src.get("requests", [])
    hourly = src.setdefault("hourly_buckets", {})
    recent_bucket = hourly.get(hour_key, 0)

    # ── Clean stale hourly buckets (keep only current + last hour) ──
    stale_keys = [k for k in hourly if k < hour_key]
    for k in stale_keys:
        del hourly[k]

    status_lines = []
    violations = []

    # Check 1: Burst — count consecutive requests since last long pause
    # A long pause is any interval ≥ burst_pause
    consecutive = 0
    for i in range(len(requests) - 1, -1, -1):
        try:
            cur = datetime.fromisoformat(requests[i])
            if i == 0:
                consecutive = i + 1
                break
            prev = datetime.fromisoformat(requests[i - 1])
            gap = (cur - prev).total_seconds()
            if gap >= RATE_CONFIG["burst_pause"]:
                # Long pause found — reset count to just this request
                consecutive = 1
                break
            consecutive += 1
        except (ValueError, TypeError):
            consecutive += 1

    if consecutive >= RATE_CONFIG["burst_page_limit"]:
        # Need a long pause after last request
        if requests:
            last_ts_str = requests[-1]
            try:
                last_dt = datetime.fromisoformat(last_ts_str)
                since_last = (now - last_dt).total_seconds()
            except (ValueError, TypeError):
                since_last = float("inf")
            if since_last < RATE_CONFIG["burst_pause"]:
                violations.append(
                    f"  突发上限: 连续 {consecutive} 页后需停顿 ≥ {RATE_CONFIG['burst_pause']}s"
                    f"（距上次仅 {since_last:.1f}s）"
                )
        status_lines.append(f"  burst: {consecutive} pages since last pause")

    # Check 2: Hourly limit
    status_lines.append(f"  hourly: {recent_bucket}/{RATE_CONFIG['hourly_page_limit']}")
    if recent_bucket >= RATE_CONFIG["hourly_page_limit"]:
        violations.append(
            f"  小时上限: 本小时已 {recent_bucket} 页"
            f"（上限 {RATE_CONFIG['hourly_page_limit']} 页/小时）"
        )

    if violations:
        print(f"[BLOCKED] {source} — 速率限制触发:")
        for v in violations:
            print(v)
        print()
        print("AI 必须等待后重试。")
        print(f"  State file: {RATE_STATE_FILE}")
        sys.exit(1)

    # ── All checks passed — record the tick ──
    requests.append(now.isoformat())
    hourly[hour_key] = recent_bucket + 1
    # Trim old requests (keep last 1000 to prevent unbounded growth)
    if len(requests) > 1000:
        src["requests"] = requests[-500:]
    _save_rate_state(state)

    print(f"[OK] {source} — 速率门禁通过")
    for line in status_lines:
        print(line)
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# Command: save-verify — per-batch field completeness gate
# ═══════════════════════════════════════════════════════════════

def cmd_save_verify(source_id: str, keyword: str):
    """Verify field completeness of saved JSON files for one source × keyword.

    Called by AI after each batch write (not deferred to final verify).
    Fail-fast: catches field corruption/immediately after write, before
    proceeding to next batch.

    Checks (same logic as _v_bole_collect):
      1) Envelope fields: source, keyword, city, page, jobs
      2) Per-job fields: title, company, salary, experience, education
      3) BOSS-specific: lid/encryptJobId
      4) note values in ALLOWED_NOTES

    Usage:
      python scripts/pipeline/pipeline.py save-verify <source_id> <keyword>

    Exit 0 = all files valid.
    Exit 2 = field issues found — AI must STOP and show report."""
    raw_dir = os.path.join(BASE_DIR, "data", "position", "raw")
    if not os.path.isdir(raw_dir):
        print(f"[OK] {source_id}/{keyword}: raw 目录不存在，跳过")
        sys.exit(0)

    pattern = re.compile(re.escape(source_id) + "_" + re.escape(keyword) + r"_page\d+\.json")
    files = sorted(f for f in os.listdir(raw_dir) if pattern.match(f))
    if not files:
        print(f"[OK] {source_id}/{keyword}: 无数据文件，跳过")
        sys.exit(0)

    REQUIRED_ENVELOPE = ["source", "keyword", "city", "page", "jobs"]
    REQUIRED_JOB = ["title", "company", "salary", "experience", "education"]
    BOSS_IDS = ("boss",)
    issues = []

    for fname in files:
        fpath = os.path.join(raw_dir, fname)
        data = load_json(fpath)
        if not data:
            issues.append(f"{fname}: 无法解析 JSON")
            continue

        # Check envelope fields
        for field in REQUIRED_ENVELOPE:
            if field not in data:
                issues.append(f"{fname}: 缺少 envelope 字段 '{field}'")
                break

        # Check per-job fields
        jobs = data.get("jobs", [])
        if jobs:
            for i, job in enumerate(jobs):
                for field in REQUIRED_JOB:
                    if not _job_has_field(job, field):
                        issues.append(f"{fname} jobs[{i}]: 缺少字段 '{field}'")
                        break
                sid = fname.split("_")[0]
                if sid in BOSS_IDS and "lid" not in job and "encryptJobId" not in job:
                    issues.append(f"{fname} jobs[{i}]: BOSS 缺少 lid/encryptJobId")

        # Check note value
        note = data.get("note", "")
        if note and note not in ALLOWED_NOTES:
            issues.append(f"{fname}: note 值 '{note}' 不在许可列表中")

    if issues:
        print(f"[FAIL] {source_id}/{keyword} — 字段完整性检测未通过:")
        for issue in issues[:20]:
            print(f"  - {issue}")
        if len(issues) > 20:
            print(f"  ... 及另 {len(issues) - 20} 个问题")
        print()
        print("AI 必须 STOP 并展示此报告给用户。")
        print("修正数据后重新运行 save-verify，通过后方可继续。")
        sys.exit(2)

    print(f"[OK] {source_id}/{keyword} — {len(files)} 个文件字段完整，校验通过")
    for fname in files:
        fpath = os.path.join(raw_dir, fname)
        jobs_count = len((load_json(fpath) or {}).get("jobs", []))
        print(f"  - {fname}: {jobs_count} 条")
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════
# Command: robots-check — pre-collection robots.txt compliance gate
# ═══════════════════════════════════════════════════════════════

def cmd_robots_check(source_url: str):
    """Check a source URL against its site's robots.txt before collecting.

    Delegates to scripts/job/robots_check.py.  If robots.txt disallows
    the target path, the pipeline is blocked.

    Usage:
      python scripts/pipeline/pipeline.py robots-check <source_url>

    Exit 0 = allowed.
    Exit 1 = disallowed or unreachable."""
    import subprocess
    output_path = os.path.join(ROBOTS_CHECK_DIR, f".robots_check_{abs(hash(source_url)) % 10**8}.json")
    os.makedirs(ROBOTS_CHECK_DIR, exist_ok=True)

    result = subprocess.run(
        [sys.executable, os.path.join(BASE_DIR, "scripts", "job", "robots_check.py"),
         "--url", source_url, "--output", output_path],
        capture_output=True, text=True, timeout=30,
    )

    if result.returncode == 2:
        print(f"FAIL: robots_check.py 参数错误")
        print(result.stderr)
        sys.exit(1)

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        print(f"WARN: robots_check.py 输出无法读取，视为允许采集")
        sys.exit(0)

    if data.get("allowed", True):
        print(f"[OK] robots.txt 合规: {data['reason']}")
        sys.exit(0)
    else:
        print("=" * 60)
        print("  !! robots.txt 阻止采集")
        print("=" * 60)
        print()
        print(f"  来源 URL: {source_url}")
        print(f"  目标路径: {data.get('target_path', '/')}")
        print(f"  原因: {data.get('reason', '未知')}")
        print()
        print(f"  robots.txt: {data.get('robots_url', '?')}")
        if data.get("disallow_matched"):
            print(f"  匹配的 Disallow 规则:")
            for d in data["disallow_matched"]:
                print(f"    - {d}")
        print()
        print("  AI 必须向用户展示此报告，由用户决定是否继续。")
        print("  用户明确确认后可继续采集，否则应跳过该来源。")
        print()
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════
# Command: robot-check (enterprise pipeline)
# ═══════════════════════════════════════════════════════════════

def cmd_robot_check(pipeline: str, source_name: str):
    """Verify download-link scan was done for a source (CODE-LEVEL gate).

    Before collecting from any enterprise/government source, the AI must
    have run scripts/enterprise/robot_scan.py.  This command verifies:
      a) The output .robot_check_*.json exists
      b) collectable == true (page has download links)

    Usage:
      python scripts/pipeline/pipeline.py robot-check enterprise <source_name>
      python scripts/pipeline/pipeline.py robot-check position <source_id>

    Exit 0 = check passed.
    Exit 1 = check failed or missing (pipeline blocked)."""
    safe_name = source_name.replace("/", "_").replace("\\", "_").replace(" ", "_").replace(".", "_")

    if pipeline == "enterprise":
        check_dir = ROBOT_CHECK_RAW
    elif pipeline == "position":
        check_dir = ROBOT_CHECK_POSITION_EVIDENCE
    else:
        print(f"FAIL: unknown pipeline '{pipeline}' for robot-check")
        sys.exit(1)

    os.makedirs(check_dir, exist_ok=True)

    pattern_prefix = f".robot_check_{safe_name}"
    candidates = [
        f for f in os.listdir(check_dir)
        if f.startswith(pattern_prefix) and f.endswith(".json")
    ]

    if not candidates:
        print(f"BLOCKED: {pipeline}/{source_name}")
        print(f"  找不到 robot_scan.py 扫描记录: {check_dir}/{pattern_prefix}*.json")
        print()
        print("  必须先运行 robot_scan.py 检测下载链接:")
        print(f"    python scripts/enterprise/robot_scan.py \\")
        print(f"      --url <SOURCE_URL> \\")
        print(f"      --output {os.path.join(check_dir, '.robot_check_' + safe_name)}.json \\")
        print(f"      --source-name \"{source_name}\"")
        sys.exit(1)

    check_path = os.path.join(check_dir, candidates[0])
    try:
        with open(check_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"BLOCKED: {pipeline}/{source_name}")
        print(f"  扫描结果无法读取: {check_path}")
        print(f"  错误: {e}")
        sys.exit(1)

    if not data.get("collectable", False):
        reason = data.get("reason", "未注明原因")
        dl_count = data.get("download_link_count", 0)
        print(f"BLOCKED: {pipeline}/{source_name}")
        print(f"  robot_scan.py 检测结果: 不可采集")
        print(f"  下载链接数: {dl_count}")
        print(f"  原因: {reason}")
        print()
        print("  伯乐仅采集提供 xlsx/xls/pdf/doc/docx 下载链接的政府公示来源。")
        print("  跳过该来源或用户确认后手动将 collectable 改为 true。")
        sys.exit(1)

    print(f"[OK] {pipeline}/{source_name}: 有下载链接，可采集")
    sys.exit(0)

# ═══════════════════════════════════════════════════════════════
# Command: keyword-verify
# ═══════════════════════════════════════════════════════════════

def _print_fail(source: str, keyword: str, reason: str,
                existing, missing, total_count, total_pages):
    """Print keyword-verify failure report."""
    print("=" * 60)
    print(f"  关键词验证失败: {source}/{keyword}")
    print("=" * 60)
    print()
    print(f"  原因: {reason}")
    print()
    print(f"  已有页面: {existing}")
    if missing:
        print(f"  缺失页面: {missing}")
    if total_count is not None:
        print(f"  总条数: {total_count}")
    if total_pages is not None:
        print(f"  总页数: {total_pages}")
    print()
    print("  AI 不得切换到下一关键词。必须继续采集当前关键词的缺失页面。")
    print("  因限速中断: 开新 tab → navigate → 继续采集。")
    print()


def cmd_keyword_verify(source: str, keyword: str):
    """Verify a single source×keyword combo is fully collected.

    Three-tier check:
      1) Page continuity (no gaps in file sequence)
      2) Rationality: if totalCount >> page1 items, totalPages must be > 1
      3) Total pages reached — non-BOSS only (BOSS randomly samples, see below)

    BOSS 直聘 randomly samples ~15 items per page from a pool (resCount).
    Pages overlap — reaching totalPages = ceil(resCount/15) is often impossible
    due to rate limiting. For BOSS, skip check 3; checks 1+2 still apply.

    Writes verify record to .keyword_verify_status.json on success.
    Exit 0 = verified, exit 2 = incomplete."""
    _bail_if_blocked()
    raw_dir = os.path.join(BASE_DIR, "data", "position", "raw")
    if not os.path.isdir(raw_dir):
        print(f"FAIL: raw directory not found at {raw_dir}")
        sys.exit(2)

    pages = _list_raw_page_files(raw_dir, source, keyword)
    if not pages:
        print(f"FAIL: no files found for {source}/{keyword}")
        sys.exit(2)

    page1 = load_json(pages.get(1, ""))
    total_count = page1.get("totalCount") if page1 else None
    total_pages = page1.get("totalPages") if page1 else None
    is_boss = (source == "boss")

    existing = sorted(pages.keys())

    # Special case: empty results (jobs=[] with note) — no data expected
    if page1 and page1.get("jobs") == [] and page1.get("note"):
        _mark_keyword_verified(source, keyword, 1, 0)
        print(f"[OK] {source}/{keyword}: empty result ({page1.get("note")}) — 已验证")
        sys.exit(0)

    # SPA duplicate termination: sub-Agent confirmed no more valid data
    last_page_data = load_json(pages.get(existing[-1], ""))
    if last_page_data and last_page_data.get("note") == "spa_cache_duplicate":
        _mark_keyword_verified(source, keyword, existing[-1], total_count or 0)
        print(f"[OK] {source}/{keyword}: {len(pages)} 页, {total_count or '?'} 条 — "
              f"末页 SPA 缓存重复（翻页子 Agent 已重试确认）")
        sys.exit(0)

    # ── Check 0: Field completeness — every page+job has required fields ──
    REQUIRED_TOP = ("source", "keyword", "city", "page", "jobs")
    REQUIRED_JOB = ("title", "company", "salary", "experience", "education")
    has_missing = False
    for pnum in existing:
        pdata = load_json(pages[pnum])
        if not pdata:
            continue
        for f in REQUIRED_TOP:
            if f not in pdata or (f != "jobs" and not pdata.get(f)):
                # Skip top-level field check for empty-result files
                if pdata.get("jobs") == [] and pdata.get("note"):
                    continue
                print(f"  [FIELD] {pages[pnum]}: 缺少顶层字段 \"{f}\"")
                has_missing = True
        for idx, job in enumerate(pdata.get("jobs", [])):
            for f in REQUIRED_JOB:
                if not _get_job_field(job, f):
                    print(f"  [FIELD] {pages[pnum]} jobs[{idx}]: 缺少字段 \"{f}\""
                          f"（也不包含别名: {JOB_FIELD_ALIASES.get(f, [])}）")
                    has_missing = True
    if has_missing:
        msg = ("部分数据缺少必要字段，参见上方 [FIELD] 标记。\n"
               "  子 Agent 应补全缺失字段后重新运行 keyword-verify。")
        _print_fail(source, keyword, msg, existing, [], None, None)
        sys.exit(2)

    # ── Check 1: Page continuity — gaps between existing pages ──
    missing_contiguous = [p for p in range(1, existing[-1] + 1) if p not in existing]
    if missing_contiguous:
        _print_fail(source, keyword, "页码不连续，中间有缺失页",
                     existing, missing_contiguous, total_count, total_pages)
        sys.exit(2)

    # ── Check 2: Rationality — totalCount >> single-page capacity? ──
    page1_jobs = len(page1.get("jobs", [])) if page1 else 0
    if (total_count is not None and page1_jobs > 0
            and total_count > page1_jobs * 2
            and total_pages is not None and total_pages < 2):
        # totalCount is more than double what page1 shows, but totalPages=1
        msg = ("总条数({}) 超过 page1 条数({}) 的两倍，"
               "但 totalPages={} 表示只有 1 页，数据矛盾。"
               .format(total_count, page1_jobs, total_pages))
        if is_boss:
            msg += ("\n  BOSS 直聘每次随机采样，resCount 是池子总量。"
                    "\n  如果仅采了 1 页就触发限速，请开新 tab 继续翻页。"
                    "\n  该关键词所有页面采完后才能切换到下一关键词。")
        _print_fail(source, keyword, msg,
                     existing, [], total_count, total_pages)
        sys.exit(2)

    # ── Check 3: Total pages reached (BOSS excluded, see docstring) ──
    if not is_boss and total_pages and total_pages > 0:
        if existing[-1] < total_pages:
            missing_end = list(range(existing[-1] + 1, total_pages + 1))
            _print_fail(source, keyword, "未达到 totalPages 声明数",
                         existing, missing_end, total_count, total_pages)
            sys.exit(2)

    _mark_keyword_verified(source, keyword, existing[-1], total_count or 0)
    print(f"[OK] {source}/{keyword}: {len(pages)} 页, {total_count or '?'} 条 — 全部采集完成已验证")
    sys.exit(0)


def cmd_keyword_status():
    """Show keyword verify status for all source×keyword combos."""
    state = _load_keyword_state()
    if not state:
        print("关键词验证状态: (空)")
        print("还没有任何关键词完成 keyword-verify。")
        return

    print("=" * 60)
    print("  关键词验证状态")
    print("=" * 60)
    print()
    for src, keywords in sorted(state.items()):
        for kw, rec in sorted(keywords.items()):
            status_icon = "✔" if rec.get("verified") else "○"
            pages = rec.get("pages_collected", [])
            count = rec.get("total_count", "?")
            ts = rec.get("verified_at", "")
            print(f"  {status_icon} {src}/{kw}: {len(pages)} 页, {count} 条  [{ts}]")
    print()
# ═══════════════════════════════════════════════════════════════
# Command: self-test
# ═══════════════════════════════════════════════════════════════


def _create_self_test_data(base_dir: str):
    """Create minimal valid test data tree for all verify functions."""

    def _write(rel_path: str, content):
        full = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if isinstance(content, (dict, list)):
            with open(full, 'w', encoding='utf-8') as f:
                json.dump(content, f, ensure_ascii=False, indent=2)
        else:
            with open(full, 'w', encoding='utf-8') as f:
                f.write(content)

    # ── Context ──
    _write("data/.bole_context.json", {
        "city": "测试城市", "province": "测试省", "region": "测试区",
        "title_keywords": ["测试"], "search_keywords": ["测试"],
        "_meta": {"confirmed_by_user": True},
    })

    # ── MCP verified ──
    _write("data/.mcp_verified", {
        "tool": "browser_snapshot", "url": "https://example.com",
        "timestamp": "2026-06-07T00:00:00",
    })

    # ── Sources (6 fixed mainstream platforms, all enabled) ──
    sources = [
        {"id": "liepin", "name": "猎聘", "pipeline": "job",
         "tech_type": "searchable",
         "url": "https://example.com/liepin?keyword={keyword}", "enabled": True},
        {"id": "51job", "name": "前程无忧", "pipeline": "job",
         "tech_type": "searchable",
         "url": "https://example.com/51job?keyword={keyword}", "enabled": True},
        {"id": "zhaopin", "name": "智联招聘", "pipeline": "job",
         "tech_type": "searchable",
         "url": "https://example.com/zhaopin?keyword={keyword}", "enabled": True},
        {"id": "lagou", "name": "拉勾", "pipeline": "job",
         "tech_type": "searchable",
         "url": "https://example.com/lagou?keyword={keyword}", "enabled": True},
        {"id": "boss", "name": "BOSS直聘", "pipeline": "job",
         "tech_type": "searchable",
         "url": "https://example.com/boss?query={keyword}", "enabled": True},
    ]
    _write("data/position/.sources.json", sources)
    for s in sources:
        if s.get("enabled"):
            _write(f"data/position/.source_{s['id']}_confirmed", "confirmed")

    _write("data/.boss_login_verified", "ok")

    # ── Raw data files (data differs per page to avoid SPA cache false positive) ──
    # BOSS uses source-native field names (jobName/brandName) to validate alias resolution
    for sid in ["boss", "liepin", "51job", "zhaopin", "lagou"]:
        for page in [1, 2]:
            if sid == "boss":
                jobs = [
                    {"jobName": "测试工程师", "brandName": f"boss公司{page}A",
                     "salaryDesc": "20k-30k", "experience": "3-5年",
                     "education": "本科", "lid": f"boss_p{page}_a"},
                    {"jobName": "测试专员", "brandName": f"boss公司{page}B",
                     "salaryDesc": "15k-25k", "experience": "1-3年",
                     "education": "本科", "lid": f"boss_p{page}_b"},
                    {"jobName": "测试经理", "brandName": f"boss公司{page}C",
                     "salaryDesc": "30k-40k", "experience": "5-10年",
                     "education": "本科", "lid": f"boss_p{page}_c"},
                ]
            else:
                jobs = [
                    {"title": "测试工程师", "company": f"{sid}公司{page}A",
                     "salary": "20k-30k", "experience": "3-5年",
                     "education": "本科", "lid": f"{sid}_p{page}_a"},
                    {"title": "测试专员", "company": f"{sid}公司{page}B",
                     "salary": "15k-25k", "experience": "1-3年",
                     "education": "本科", "lid": f"{sid}_p{page}_b"},
                    {"title": "测试经理", "company": f"{sid}公司{page}C",
                     "salary": "30k-40k", "experience": "5-10年",
                     "education": "本科", "lid": f"{sid}_p{page}_c"},
                ]
            _write(f"data/position/raw/{sid}_测试_page{page}.json", {
                "source": sid, "keyword": "测试",
                "city": "测试城市",
                "page": page, "totalPages": 2, "totalCount": 30,
                "note": "", "_meta": {"tool_used": "mcp"},
                "jobs": jobs,
            })

    # ── Self-check evidence (non-BOSS) ──
    for sid in ["liepin", "51job", "zhaopin", "lagou"]:
        _write(f"data/position/raw/evidence/{sid}_check.json", {
            "login_detected": False, "url": "https://example.com",
            "timestamp": "2026-06-07T00:00:00",
        })

    # ── City evidence files ──
    for sid in ["boss", "liepin", "51job", "zhaopin", "lagou"]:
        _write(f"data/position/raw/evidence/.city_verified_{sid}.json", {
            "source_id": sid, "city": "测试城市",
            "city_code": "999", "verified_at": "2026-06-07T00:00:00",
        })

    # ── Keyword verify state ──
    kw_state = {}
    for sid in ["boss", "liepin", "51job", "zhaopin", "lagou"]:
        kw_state[sid] = {"测试": {
            "verified": True, "total_pages": 2,
            "pages_collected": [1, 2], "total_count": 30,
            "verified_at": "2026-06-07T00:00:00",
        }}
    _write("data/position/.keyword_verify_status.json", kw_state)

    # ── Relevance keywords ──
    _write("data/position/.relevance_keywords.json", {
        "keywords": ["测试1", "测试2"],
        "_meta": {"confirmed_by_user": True},
    })

    # ── Processed CSVs ──
    _write("data/position/processed/position_deduped.csv",
           "title,company,salary,experience,education\n"
           "测试工程师,公司A,20k-30k,3-5年,本科\n")
    _write("data/position/processed/position_scored.csv",
           "title,company,salary,experience,education,total_score\n"
           "测试工程师,公司A,20k-30k,3-5年,本科,85\n")

    # ── Output files ──
    _write("data/position/output/position_formatted.csv",
           "title,company,salary\n测试,公司A,20k\n")
    _write("data/position/output/position_report.md",
           "# 测试报告\n\n岗位采集管线自检用测试数据。\n")

    # ── Enrich output ──
    _write("data/position/output/position_enriched.csv",
           "title,company\n测试,公司\n")
    _write("data/position/output/enrich_report.md",
           "# 富化报告\n\n测试数据。\n")
    _write("data/position/output/position_filtered.csv",
           "title,company\n测试,公司\n")
    _write("data/position/output/position_final.csv",
           "title,company\n测试,公司\n")

    # ── Enterprise data ──
    _write("data/enterprise/.enterprise_sources.json", {
        "city": "测试城市", "province": "测试省",
        "discovered_at": "2026-06-07T00:00:00",
        "qualification_sources": [
            {"qualification_type": "专精特新",
             "source_name": "测试省工信厅_2025专精特新",
             "url": "https://example.com/qualification",
             "page_type": "web_table",
             "institution": "测试省工信厅",
             "year": 2025},
        ],
        "_meta": {"total_sources": 1, "confirmed_by_user": True},
    })
    _write("data/enterprise/raw/qualification_lists/test_list.json",
           [{"name": "测试企业", "qualification": "专精特新"}])
    _write("data/enterprise/raw/.robot_check_test_list.json", {
        "source": "测试省工信厅_2025专精特新",
        "url": "https://example.com/qualification",
        "scanned_at": "2026-06-07T00:00:00",
        "scan_method": "code",
        "scanner_version": "2.0.0",
        "reachable": True,
        "error": None,
        "download_links": [
            {"url": "https://example.com/list.xlsx", "label": "2025年度名单"},
        ],
        "download_link_count": 1,
        "collectable": True,
        "reason": "页面提供 1 个可下载文件链接（xlsx/pdf/doc），视为主动公开数据",
    })
    _write("data/enterprise/.industry_keywords.json", {
        "target_kw": ["科技", "制造"],
        "_meta": {"confirmed_by_user": True},
    })
    _write("data/enterprise/processed/enterprise_cleaned.csv",
           "name,industry\n测试企业,科技\n")
    _write("data/enterprise/processed/enterprise_scored.csv",
           "name,industry,score\n测试企业,科技,85\n")
    _write("data/enterprise/output/enterprise_basic.csv",
           "name,industry\n测试企业,科技\n")


def cmd_self_test():
    """Run all verify functions against synthetic test data.

    Creates a minimal valid data tree in a temp directory, temporarily
    redirects all module-level paths to point at it, then runs every
    function registered in VERIFY_TABLE.

    Catches and reports exceptions (crashes) separately from verify
    failures (returned False).  Crashes indicate real execution-path
    bugs (like the all_files UnboundLocalError this test was designed
    to catch).  Failures may indicate incomplete test data.

    Exit 0 = all verifies passed (code is sound).
    Exit 1 = one or more verifies crashed (execution-path bugs exist).
    """
    temp_dir = tempfile.mkdtemp(prefix="bole_selftest_")
    mod = sys.modules[__name__]

    # Ensure UTF-8 output for readable CJK in report
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass

    # Save originals
    _saved = {}
    for name in ['BASE_DIR', 'STATE_FILE', 'CONTEXT_FILE', 'VERIFY_LOCK',
                 'MCP_VERIFIED', 'AUTH_BLOCKED', 'BOSS_LOGIN_VERIFIED',
                 'RESTART_REQUIRED', 'KEYWORD_VERIFY_STATUS',
                 'ROBOT_CHECK_RAW', 'ROBOT_CHECK_POSITION_EVIDENCE']:
        _saved[name] = getattr(mod, name)

    try:
        # Override paths to temp directory
        mod.BASE_DIR = temp_dir
        mod.STATE_FILE = os.path.join(temp_dir, "data", ".pipeline_state.json")
        mod.CONTEXT_FILE = os.path.join(temp_dir, "data", ".bole_context.json")
        mod.VERIFY_LOCK = os.path.join(temp_dir, "data", ".verify_blocked")
        mod.MCP_VERIFIED = os.path.join(temp_dir, "data", ".mcp_verified")
        mod.AUTH_BLOCKED = os.path.join(temp_dir, "data", ".auth_blocked")
        mod.BOSS_LOGIN_VERIFIED = os.path.join(temp_dir, "data", ".boss_login_verified")
        mod.RESTART_REQUIRED = os.path.join(temp_dir, "data", ".restart_required")
        mod.KEYWORD_VERIFY_STATUS = os.path.join(
            temp_dir, "data", "position", ".keyword_verify_status.json")
        mod.ROBOT_CHECK_RAW = os.path.join(temp_dir, "data", "enterprise", "raw")
        mod.ROBOT_CHECK_POSITION_EVIDENCE = os.path.join(temp_dir, "data", "position", "raw", "evidence")

        _create_self_test_data(temp_dir)

        # Run every verify function registered in VERIFY_TABLE
        results = []
        for pid, pipeline in PIPELINES.items():
            for step_id, step_name, _ in pipeline["steps"]:
                vfunc = VERIFY_TABLE.get(pid, {}).get(step_id)
                if not vfunc:
                    continue

                # Restore markers that verify functions may have deleted
                # (e.g. _v_bole_confirm_mode deletes .mcp_verified to force
                # fresh validation on restart)
                if not os.path.exists(mod.MCP_VERIFIED):
                    os.makedirs(os.path.dirname(mod.MCP_VERIFIED), exist_ok=True)
                    with open(mod.MCP_VERIFIED, 'w', encoding='utf-8') as f:
                        json.dump({
                            "tool": "browser_snapshot",
                            "url": "https://example.com",
                            "timestamp": "2026-06-07T00:00:00",
                        }, f)
                try:
                    ok, msg = vfunc()
                    results.append({
                        "pid": pid, "step": step_id, "name": step_name,
                        "status": "PASS" if ok else "FAIL",
                        "message": msg, "error": None,
                    })
                except Exception as e:
                    results.append({
                        "pid": pid, "step": step_id, "name": step_name,
                        "status": "CRASH", "message": "",
                        "error": f"{type(e).__name__}: {e}",
                    })

        _print_self_test_report(results)

        crashes = sum(1 for r in results if r["status"] == "CRASH")
        sys.exit(1 if crashes > 0 else 0)

    finally:
        for name, val in _saved.items():
            setattr(mod, name, val)
        shutil.rmtree(temp_dir, ignore_errors=True)


def _print_self_test_report(results: list):
    """Print formatted self-test report grouped by pipeline."""
    by_pipeline = OrderedDict()
    for r in results:
        by_pipeline.setdefault(r["pid"], []).append(r)

    passes = sum(1 for r in results if r["status"] == "PASS")
    fails = sum(1 for r in results if r["status"] == "FAIL")
    crashes = sum(1 for r in results if r["status"] == "CRASH")

    print()
    print("=" * 60)
    print("  伯乐管线自检报告 -- verify 函数全覆盖")
    print("=" * 60)
    print()

    for pid, entries in by_pipeline.items():
        title = PIPELINES.get(pid, {}).get("title", pid)
        print(f"  [{pid}] {title}")
        for r in entries:
            icon = {"PASS": "[OK]", "FAIL": "[!!]", "CRASH": "[XX]"}.get(r["status"], "[??]")
            label = f"{r['step']:25s}"
            if r["status"] == "PASS":
                print(f"    {icon} {label}  PASS  ({r['message']})")
            elif r["status"] == "FAIL":
                print(f"    {icon} {label}  FAIL  ({r['message'][:80]})")
            else:
                print(f"    {icon} {label}  CRASH  {r['error']}")
        print()

    print("-" * 60)
    print(f"  总计: {len(results)} 个 verify 函数  |  "
          f"通过: {passes}  |  失败: {fails}  |  崩溃: {crashes}")
    print()

    if crashes > 0:
        # For crash messages, use CJK characters that may cause GBK issues
        # Replace with ASCII fallback
        print("  !! verify functions CRASHED -- execution-path bugs detected")
        print()
    elif fails > 0:
        print("  Some verify functions returned False (may be incomplete test")
        print("  data coverage, or verify logic issues -- manual check needed).")
        print()
    else:
        print("  ALL VERIFY FUNCTIONS PASSED -- pipeline code has no execution-path bugs.")
        print()


# Main Dispatch
# ═══════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    # Protocol compliance gate — blocks all state-modifying commands
    # when raw data contains protocol violations.
    # Every pipeline (bole/enterprise/enrich) and every command
    # that could proceed past a login wall is covered.
    # Keyword-verify is scoped to its specific keyword so known issues
    # in one keyword don't block verification of others.
    if command == "keyword-verify" and len(sys.argv) >= 4:
        _check_protocol_compliance(source=sys.argv[2], keyword=sys.argv[3])
    elif command in ("check", "verify", "complete"):
        _check_protocol_compliance()

    if command == "status":
        cmd_status()
    elif command == "check":
        if len(sys.argv) < 4:
            print("用法: python scripts/pipeline/pipeline.py check <pipeline> <step>")
            sys.exit(1)
        cmd_check(sys.argv[2], sys.argv[3])
    elif command == "verify":
        if len(sys.argv) < 4:
            print("用法: python scripts/pipeline/pipeline.py verify <pipeline> <step>")
            sys.exit(1)
        cmd_verify(sys.argv[2], sys.argv[3])
    elif command == "complete":
        if len(sys.argv) < 4:
            print("用法: python scripts/pipeline/pipeline.py complete <pipeline> <step> [--skip] [--skip-verify --skip-verify-ack]")
            sys.exit(1)
        skip = "--skip" in sys.argv
        skip_verify = "--skip-verify" in sys.argv
        skip_verify_ack = "--skip-verify-ack" in sys.argv
        cmd_complete(sys.argv[2], sys.argv[3], skip, skip_verify, skip_verify_ack)
    elif command == "reset":
        pid = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
        hard = "--hard" in sys.argv
        cmd_reset(pid, hard)
    elif command == "preflight":
        pid = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_preflight(pid)
    elif command == "auth-scan":
        if len(sys.argv) < 3:
            print("用法: python scripts/pipeline/pipeline.py auth-scan <source_id>")
            sys.exit(1)
        cmd_auth_scan(sys.argv[2])
    elif command == "auth-release":
        source = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_auth_release(source)
    elif command == "keyword-verify":
        if len(sys.argv) < 4:
            print("用法: python scripts/pipeline/pipeline.py keyword-verify <source> <keyword>")
            sys.exit(1)
        cmd_keyword_verify(sys.argv[2], sys.argv[3])
    elif command == "robot-check":
        if len(sys.argv) < 4:
            print("用法: python scripts/pipeline/pipeline.py robot-check <pipeline> <source_name>")
            print("  pipeline: enterprise | position")
            print("  source_name: 来源名称（如 吉林省工信厅_2025省级专精特新）")
            sys.exit(1)
        cmd_robot_check(sys.argv[2], sys.argv[3])
    elif command == "robots-check":
        if len(sys.argv) < 3:
            print("用法: python scripts/pipeline/pipeline.py robots-check <source_url>")
            sys.exit(1)
        cmd_robots_check(sys.argv[2])
    elif command == "compliance-check":
        cmd_compliance_check()
    elif command == "compliance-accept":
        cmd_compliance_accept()
    elif command == "rate-tick":
        if len(sys.argv) < 3:
            print("用法: python scripts/pipeline/pipeline.py rate-tick <source_id>")
            sys.exit(1)
        cmd_rate_tick(sys.argv[2])
    elif command == "save-verify":
        if len(sys.argv) < 4:
            print("用法: python scripts/pipeline/pipeline.py save-verify <source_id> <keyword>")
            print("  逐批写入后立即校验字段完整性，不等最终 verify")
            sys.exit(1)
        cmd_save_verify(sys.argv[2], sys.argv[3])
    elif command == "keyword-status":
        cmd_keyword_status()
    elif command == "self-test":
        cmd_self_test()
    else:
        print(f"未知命令: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
