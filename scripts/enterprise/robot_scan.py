"""
Download-link detector for enterprise/government source URLs.

Checks whether a government source page provides visible download links
to data files (.xlsx, .xls, .pdf, .doc, .docx).  If the page is reachable
AND contains at least one download link, the source is marked collectable.

The rationale: a government website that publishes data via a visible
download link is actively providing that data.  No terms-scraping, no
pattern matching, no AI judgment.

Usage:
  python scripts/enterprise/robot_scan.py --url <PAGE_URL> \
      --output <OUTPUT_JSON> \
      --source-name "<SOURCE_NAME>"

Exit codes:
  0 = scan completed (check collectable in output JSON)
  1 = HTTP error or unreachable
  2 = invalid arguments
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


DOWNLOAD_EXTS = r'\.(xlsx|xls|pdf|doc|docx)(?:["\?#]|$)'


def _fetch(url: str, timeout: int = 15) -> tuple[str | None, str | None]:
    """Fetch page content. Returns (html_text, error_message)."""
    if not HAS_REQUESTS:
        return None, "requests 库不可用"
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        r = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        r.raise_for_status()
        # Detect encoding: prefer apparent_encoding when it detects CJK
        detected = r.apparent_encoding or ""
        reported = (r.encoding or "").lower()
        if detected.lower() in ("gbk", "gb2312", "gb18030", "utf-8", "utf-8-sig"):
            r.encoding = detected
        elif reported in ("iso-8859-1", "windows-1252") and detected:
            r.encoding = detected
        return r.text, None
    except requests.exceptions.Timeout:
        return None, f"请求超时 (>{timeout}s)"
    except requests.exceptions.ConnectionError as e:
        return None, f"连接失败: {e}"
    except requests.exceptions.HTTPError as e:
        return None, f"HTTP 错误: {e}"
    except Exception as e:
        return None, f"请求异常: {e}"


def _find_download_links(html: str, base_url: str) -> list[dict]:
    """Find <a href> links pointing to downloadable data files.

    Returns a list of {url, label} dicts, empty if none found.
    """
    pattern = re.compile(DOWNLOAD_EXTS, re.IGNORECASE)
    downloads = []
    for m in re.finditer(r'<a\s[^>]*href="([^"]*)"[^>]*>(.*?)</a>', html, re.DOTALL):
        href = m.group(1).strip()
        label = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if pattern.search(href):
            full_url = urljoin(base_url, href)
            downloads.append({"url": full_url, "label": label[:80]})
    return downloads


def main():
    parser = argparse.ArgumentParser(
        description="Download-link detector for enterprise/government source URLs",
    )
    parser.add_argument("--url", required=True, help="目标来源 URL")
    parser.add_argument("--output", required=True, help="输出 JSON 文件路径")
    parser.add_argument("--source-name", required=True, help="来源名称")
    parser.add_argument("--timeout", type=int, default=15, help="请求超时秒数")

    args = parser.parse_args()

    if not HAS_REQUESTS:
        print("错误: 需要 requests 库，请执行 pip install requests")
        sys.exit(2)

    # ── Fetch ──
    print(f"正在检测: {args.url}")
    html, error = _fetch(args.url, args.timeout)

    if error or html is None:
        print(f"  不可达: {error}")
        output = {
            "source": args.source_name,
            "url": args.url,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "reachable": False,
            "error": error,
            "download_links": [],
            "collectable": False,
            "reason": error,
        }
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"  输出: {args.output}")
        sys.exit(1)

    # ── Detect download links ──
    links = _find_download_links(html, args.url)
    has_links = len(links) > 0

    if has_links:
        collectable = True
        reason = f"页面提供 {len(links)} 个可下载文件链接（xlsx/pdf/doc），视为主动公开数据"
        print(f"  发现 {len(links)} 个下载链接，可采集")
    else:
        collectable = False
        reason = "页面无可下载文件链接（xlsx/xls/pdf/doc/docx），伯乐仅采集提供下载链接的政府公示来源"
        print(f"  未发现下载链接，不可采集")

    # ── Output ──
    output = {
        "source": args.source_name,
        "url": args.url,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "scan_method": "code",
        "scanner_version": "2.0.0",
        "reachable": True,
        "error": None,
        "download_links": links[:20],
        "download_link_count": len(links),
        "collectable": collectable,
        "reason": reason,
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 50)
    print(f"  来源: {args.source_name}")
    print(f"  URL: {args.url}")
    print(f"  可访问: [OK]")
    print(f"  下载链接: {len(links)} 个")
    if links:
        for l in links[:3]:
            print(f"    - {l['label'] or l['url']}")
        if len(links) > 3:
            print(f"    ... 及另外 {len(links) - 3} 个")
    print(f"  结果: {'[OK] 可采集' if collectable else '[SKIP] 跳过'}")
    print(f"  原因: {reason}")
    print(f"  输出: {args.output}")
    print("=" * 50)

    sys.exit(0)


if __name__ == "__main__":
    main()
