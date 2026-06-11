"""
Pre-collection robots.txt compliance detection.

Fetches robots.txt from the source URL's origin, parses User-agent: * rules,
and checks whether the target path is disallowed.  If robots.txt is unreachable
(the site does not serve one), the source is treated as "no explicit restriction"
and allowed (with a warning logged).

Usage:
  python scripts/job/robots_check.py --url <SOURCE_URL> --output <OUTPUT_JSON>

Exit codes:
  0 = allowed (no disallow match, or no robots.txt)
  1 = disallowed by robots.txt
  2 = invalid arguments
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _fetch_robots(url: str, timeout: int = 10) -> tuple[str | None, str | None]:
    """Fetch robots.txt from the URL origin. Returns (body, error)."""
    if not HAS_REQUESTS:
        return None, "requests 库不可用"
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = requests.get(robots_url, timeout=timeout, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; bole-skill/1.0; +https://github.com/RychiiiD/bole-skill)"})
        if resp.status_code < 400:
            return resp.text, None
        if resp.status_code == 404:
            return None, None  # No robots.txt = no restriction
        return None, f"HTTP {resp.status_code}"
    except requests.RequestException as e:
        return None, str(e)


def _parse_disallow_paths(body: str) -> list[str]:
    """Extract Disallow paths under User-agent: * from a robots.txt body.

    Supports:
      - User-agent: * block (collects Disallow lines until next User-agent)
      - Wildcard * in paths
      - Comments (#)
    """
    disallow_paths = []
    in_star_block = False

    for line in body.splitlines():
        line = line.strip()
        # Strip comments (not inside a value)
        if "#" in line:
            line = line[:line.index("#")].strip()
        if not line:
            continue

        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            in_star_block = (agent == "*")
            continue

        if in_star_block and line.lower().startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:  # Empty Disallow means allow all
                disallow_paths.append(path)

    return disallow_paths


def _path_matches(path: str, disallow: str) -> bool:
    """Check if a URL path matches a Disallow pattern (with wildcard support)."""
    # Convert robots.txt pattern to regex
    if "*" in disallow:
        pattern = "^" + re.escape(disallow).replace(r"\*", ".*") + ""
        return bool(re.match(pattern, path))
    return path.startswith(disallow)


def check_url(url: str) -> dict:
    """Check a URL against its origin's robots.txt.

    Returns dict with:
      - allowed: bool — whether collection is permitted
      - reason: str — explanation
      - robots_url: str | None
      - has_robots: bool
      - disallow_matched: list[str] — matched disallow rules (empty if none)
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return {
            "allowed": False,
            "reason": f"无效 URL: {url}",
            "robots_url": None,
            "has_robots": False,
            "disallow_matched": [],
        }

    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    body, error = _fetch_robots(url)

    result = {
        "check_time": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "target_path": parsed.path or "/",
        "robots_url": robots_url,
    }

    if error:
        # Unreachable or error — treat as no restriction, log warning
        result["allowed"] = True
        result["has_robots"] = False
        result["reason"] = f"robots.txt 不可达（{error}），视为无明确限制"
        result["disallow_matched"] = []
        return result

    if body is None:
        # 404 — explicitly no robots.txt
        result["allowed"] = True
        result["has_robots"] = False
        result["reason"] = "站点无 robots.txt（HTTP 404），视为无限制"
        result["disallow_matched"] = []
        return result

    # Parse and check
    result["has_robots"] = True
    disallow_paths = _parse_disallow_paths(body)
    matched = [d for d in disallow_paths if _path_matches(parsed.path or "/", d)]

    if matched:
        result["allowed"] = False
        result["reason"] = f"robots.txt User-agent: * 禁止采集路径: {', '.join(matched)}"
        result["disallow_matched"] = matched
    else:
        result["allowed"] = True
        result["reason"] = f"robots.txt 无匹配 Disallow 规则（共 {len(disallow_paths)} 条规则）"
        result["disallow_matched"] = []

    return result


def main():
    parser = argparse.ArgumentParser(description="Robots.txt compliance check for collection target")
    parser.add_argument("--url", required=True, help="Target collection URL")
    parser.add_argument("--output", help="Output JSON path (default: print to stdout)")
    args = parser.parse_args()

    result = check_url(args.url)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["allowed"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
