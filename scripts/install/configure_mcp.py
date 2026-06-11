"""
Playwright MCP 自动安装/配置检测。

检测系统环境，输出 MCP 配置 JSON，支持写入 ~/.claude.json 或项目 .mcp.json。

Usage:
  python scripts/install/configure_mcp.py              # 检测并打印配置
  python scripts/install/configure_mcp.py --apply       # 写入项目 .mcp.json
"""
import json
import os
import shutil
import subprocess
import sys

CONFIG = {
    "mcpServers": {
        "playwright": {
            "command": "npx",
            "args": [
                "-y", "@playwright/mcp@latest",
                "--user-data-dir", ".claude/browser_profile",
                "--viewport-size", "1280x720",
                "--shared-browser-context",
                "--browser", "chrome"
            ]
        }
    }
}


def check_python() -> dict:
    return {"ok": True, "version": sys.version.split()[0]}


def check_node() -> dict:
    if not shutil.which("node"):
        return {"ok": False, "msg": "Node.js 未安装，请先安装 Node.js (https://nodejs.org)"}
    try:
        ver = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        return {"ok": True, "version": ver.stdout.strip()}
    except Exception as e:
        return {"ok": False, "msg": str(e)}


def check_chrome() -> dict:
    candidates = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        os.path.expanduser("~/AppData/Local/Google/Chrome/Application/chrome.exe"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return {"ok": True, "path": path}
    # Linux which
    which_chrome = shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
    if which_chrome:
        return {"ok": True, "path": which_chrome}
    return {"ok": False, "msg": "Chrome 未找到。伯乐使用系统 Chrome 浏览器采集以降低兼容性风险"}


def check_npx() -> dict:
    if not shutil.which("npx"):
        return {"ok": False, "msg": "npx 未找到，请确保 Node.js 安装正确"}
    return {"ok": True}


def _status_char(ok: bool) -> str:
    """Return status character safe for Windows GBK console."""
    return "[OK]" if ok else "[!!]"


def main():
    print("=== Bole-skill Environment Check ===\n")

    results = {
        "Python": check_python(),
        "Node.js": check_node(),
        "npx": check_npx(),
        "Chrome": check_chrome(),
    }

    all_ok = True
    for name, result in results.items():
        status = _status_char(result["ok"])
        detail = result.get("version") or result.get("path", "")
        print(f"  {status} {name}  {detail}")
        if not result["ok"]:
            print(f"       {result.get('msg', '')}")
            all_ok = False

    print()
    if not all_ok:
        print("Some dependencies are missing. Install them following the hints above.")
        print()

    print("=== Playwright MCP Config ===\n")
    print(json.dumps(CONFIG, ensure_ascii=False, indent=2))
    print()

    if "--apply" in sys.argv:
        mcp_path = os.path.join(os.path.dirname(__file__), "..", "..", ".mcp.json")
        with open(mcp_path, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        print(f"Written to {os.path.normpath(mcp_path)}")

    print("Done! Run /bole in Claude Code to start.")


if __name__ == "__main__":
    main()
