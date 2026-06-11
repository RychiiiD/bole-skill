"""
伯乐 — 企业 PDF 提取工具

文本层提取 + Playwright text-layer 辅助，全程无图片无 OCR。

Usage:
  # 自动提取（pdfplumber → PyMuPDF → pdftotext 三层递进）
  python scripts/enterprise/pdf_extract.py <pdf_path> -o <csv_path> \\
    --source-name "来源名" --category "资质类型"

  # 所有 Python 后端失败时 → 生成 Playwright 浏览器提取指令
  python scripts/enterprise/pdf_extract.py --playwright-code <PDF_URL>

  # Playwright 提取的文本 → 解析为企业名称 CSV
  python scripts/enterprise/pdf_extract.py --import-text <txt_path> -o <csv_path> \\
    --source-name "来源名" --category "资质类型"

Exit codes:
  0 — CSV 写入成功
  1 — 所有后端均失败（含 --playwright-code 或 --import-text 无法解析时）
"""

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys

CHINESE_THRESHOLD = 0.02

# ── Playwright text-layer 提取用的 JavaScript ─────────────────────

PLAYWRIGHT_JS = r"""() => {
  // Chrome PDF viewer 的 text layer 选择器（多版本兼容）
  const selectors = [
    '.textLayer span',
    'iframe#viewer + div .textLayer span',
    '#viewer .textLayer span',
    'embed + div .textLayer span',
  ];
  let spans = [];
  for (const sel of selectors) {
    const found = document.querySelectorAll(sel);
    if (found.length > 0) { spans = found; break; }
  }
  if (spans.length === 0) {
    // 尝试从 PDF.js canvas 获取（部分版本无 textLayer）
    const canvases = document.querySelectorAll('canvas');
    return JSON.stringify({status: 'no_text_layer', canvasCount: canvases.length,
      hint: '尝试 browser_run_code_unsafe: await page.evaluate(() => document.body.innerText)'});
  }
  const text = Array.from(spans).map(s => s.textContent).join('\n').trim();
  const hasChinese = /[一-鿿]/.test(text);
  // 返回前 10000 字符以防 JSON 溢出（企业名单足够）
  return JSON.stringify({
    status: hasChinese ? 'ok' : 'garbled',
    text: text.slice(0, 30000),
    totalLength: text.length,
    chineseRatio: (text.match(/[一-鿿]/g) || []).length / Math.max(text.length, 1)
  });
}"""


def _has_chinese(text: str) -> bool:
    if not text or not text.strip():
        return False
    total = len(text)
    if total == 0:
        return False
    chinese = sum(1 for c in text if '一' <= c <= '鿿')
    return (chinese / total) >= CHINESE_THRESHOLD


# ── Python 文本层提取后端 ─────────────────────────────────────────

def _extract_pdfplumber(pdf_path: str) -> str | None:
    try:
        import pdfplumber
    except ImportError:
        return None
    try:
        with pdfplumber.open(pdf_path) as pdf:
            chunks = []
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row and any(c for c in row if c):
                            chunks.append(" | ".join(
                                c.strip() if c else "" for c in row
                            ))
                text = page.extract_text()
                if text:
                    chunks.append(text)
            result = "\n".join(chunks)
            return result if _has_chinese(result) else None
    except Exception:
        return None


def _extract_fitz(pdf_path: str) -> str | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        doc = fitz.open(pdf_path)
        chunks = []
        for page in doc:
            text = page.get_text()
            if text:
                chunks.append(text)
        doc.close()
        result = "\n".join(chunks)
        return result if _has_chinese(result) else None
    except Exception:
        return None


def _extract_pdftotext(pdf_path: str) -> str | None:
    if not shutil.which("pdftotext"):
        return None
    try:
        r = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            return r.stdout if _has_chinese(r.stdout) else None
    except (subprocess.TimeoutExpired, OSError):
        return None
    return None


_BACKENDS: list[tuple[str, callable]] = [
    ("pdfplumber", _extract_pdfplumber),
    ("PyMuPDF",    _extract_fitz),
    ("pdftotext",  _extract_pdftotext),
]


# ── 企业名称解析 ────────────────────────────────────────────────────


def _parse_company_lines(text: str) -> list[str]:
    companies: list[str] = []
    for line in text.split("\n"):
        line = line.strip().rstrip(".")
        if len(line) < 4:
            continue
        if re.match(r'^[\d\s\-—–|/\\:：,，;；、()（）.．]+$', line):
            continue
        if not re.search(r'[一-鿿]', line):
            continue
        if re.match(r'^第\s*\d+\s*[页頁]', line):
            continue
        if re.match(r'^-\s*\d+\s*-$', line):
            continue
        companies.append(line)
    seen: set[str] = set()
    return [c for c in companies if not (c in seen or seen.add(c))]


def _write_csv(companies: list[str],
               output: str,
               source_name: str,
               category: str) -> None:
    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company_name", "enterprise_category", "source_name"])
        for c in companies:
            w.writerow([c, category, source_name])


# ── 子命令：Playwright 代码生成 ────────────────────────────────────


def cmd_playwright_code(pdf_url: str) -> None:
    print("=" * 60)
    print("  Playwright text-layer 提取指引")
    print("=" * 60)
    print()
    print(f"  PDF URL: {pdf_url}")
    print()
    print("  步骤 1: browser_navigate")
    print(f"    URL: {pdf_url}")
    print()
    print("  步骤 2: browser_snapshot 确认页面已渲染")
    print()
    print("  步骤 3: browser_evaluate 执行以下 JS 代码提取 text-layer：")
    print()
    print("─" * 60)
    print(PLAYWRIGHT_JS)
    print("─" * 60)
    print()
    print("  步骤 4: 检查返回的 JSON.status:")
    print('    "ok"             → 提取成功，保存文本到临时文件')
    print('    "garbled"        → Chrome 也无法解码，记录 parse_failed')
    print('    "no_text_layer"  → PDF 查看器无 text-layer，记录 parse_failed')
    print()
    print("  步骤 5: 如果提取成功：")
    print("    将 text 内容保存到临时 txt 文件后运行：")
    print("    python scripts/enterprise/pdf_extract.py --import-text <txt_path> \\")
    print("      -o data/enterprise/raw/qualification_lists/<filename>.csv \\")
    print("      --source-name \"来源_年份资质\" --category \"专精特新\"")
    print()
    print("  步骤 6（全部失败）:")
    print("    回到页面检查有无其他格式的备用文件")
    print("    有 → 下载备用格式重新解析")
    print("    无 → 记录 parse_failed，保存 .txt 说明文件")
    sys.exit(1)


# ── 子命令：导入 Playwright 提取的文本 ────────────────────────────


def cmd_import_text(txt_path: str,
                    output: str,
                    source_name: str,
                    category: str,
                    verbose: bool) -> None:
    if not os.path.isfile(txt_path):
        print(f"错误: 文件不存在 — {txt_path}", file=sys.stderr)
        sys.exit(1)

    with open(txt_path, "r", encoding="utf-8") as f:
        text = f.read()

    if not _has_chinese(text):
        print("警告: 导入文本中未检测到有效中文内容", file=sys.stderr)
        if verbose:
            print("--- 前 500 字符 ---", file=sys.stderr)
            print(text[:500], file=sys.stderr)
            print("---", file=sys.stderr)
        sys.exit(1)

    companies = _parse_company_lines(text)
    if not companies:
        print("警告: 导入文本中未解析出企业名称", file=sys.stderr)
        sys.exit(1)

    _write_csv(companies, output, source_name, category)
    print(f"✓ [playwright text-layer] {len(companies)} 家企业 → {output}")
    sys.exit(0)


# ── CLI ─────────────────────────────────────────────────────────────


def _print_pdftotext_help() -> None:
    """Print pdftotext installation guidance for different platforms."""
    print("  pdftotext (poppler) 未安装。如需更强 PDF 提取能力：", file=sys.stderr)
    print("    Windows: 下载 poppler 并加入 PATH", file=sys.stderr)
    print("      https://github.com/oschwartz10612/poppler-windows/releases/", file=sys.stderr)
    print("    macOS:   brew install poppler", file=sys.stderr)
    print("    Linux:   apt install poppler-utils", file=sys.stderr)
    print()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="伯乐 — 企业 PDF 四层递进文本提取工具"
    )
    ap.add_argument("pdf_path", nargs="?", help="PDF 文件路径")
    ap.add_argument("--output", "-o", help="输出 CSV 路径")
    ap.add_argument("--source-name", help="来源名称")
    ap.add_argument("--category", help="资质类型")
    ap.add_argument("--verbose", "-v", action="store_true")

    # Playwright 辅助模式
    ap.add_argument("--playwright-code", metavar="PDF_URL",
                    help="生成 Playwright text-layer 提取代码（不执行提取）")
    ap.add_argument("--import-text", metavar="TXT_FILE",
                    help="导入 Playwright 提取的文本文件，解析为企业名称 CSV")

    args = ap.parse_args()

    # ── 子命令分发 ──
    if args.playwright_code:
        cmd_playwright_code(args.playwright_code)
        return  # never reached

    if args.import_text:
        if not args.output or not args.source_name or not args.category:
            print("错误: --import-text 需要 --output / --source-name / --category", file=sys.stderr)
            sys.exit(1)
        cmd_import_text(args.import_text, args.output,
                        args.source_name, args.category, args.verbose)
        return  # never reached

    # ── 主模式：自动提取 ──
    if not args.pdf_path:
        ap.print_help()
        sys.exit(1)

    if not args.output or not args.source_name or not args.category:
        print("错误: 需要 --output / --source-name / --category", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(args.pdf_path):
        print(f"错误: 文件不存在 — {args.pdf_path}", file=sys.stderr)
        sys.exit(1)

    # ── 四层递进 ──
    text: str | None = None
    used: str | None = None
    for name, fn in _BACKENDS:
        if args.verbose:
            print(f"尝试后端: {name}...", file=sys.stderr)
        text = fn(args.pdf_path)
        if text is not None:
            used = name
            if args.verbose:
                print(f"  ✓ {name} 提取成功", file=sys.stderr)
            break
        if args.verbose:
            print(f"  ✗ {name} 未提取到有效中文", file=sys.stderr)

    if text is None:
        print("所有 Python 后端均失败: PDF 字体编码损坏，文本提取无有效中文内容",
              file=sys.stderr)
        print(file=sys.stderr)
        _print_pdftotext_help()
        print("下一步（必须按顺序执行，不得跳过 Playwright）:", file=sys.stderr)
        print(file=sys.stderr)
        print("  第 1 步 — 用 Playwright 提取 Chrome PDF 查看器的 text-layer:", file=sys.stderr)
        print(f"    python scripts/enterprise/pdf_extract.py --playwright-code <PDF_URL>",
              file=sys.stderr)
        print(file=sys.stderr)
        print("  └─ 提取成功 → --import-text 解析为 CSV", file=sys.stderr)
        print("  └─ 仍无效 → 检查页面有无其他格式备用文件", file=sys.stderr)
        print("  └─ 无 → 记录 parse_failed", file=sys.stderr)
        sys.exit(1)

    # ── 解析企业名称 ──
    companies = _parse_company_lines(text)
    if not companies:
        print("警告: 提取到文本但未解析出企业名称", file=sys.stderr)
        print("--- 提取内容前 2000 字符 ---", file=sys.stderr)
        print(text[:2000], file=sys.stderr)
        print("---", file=sys.stderr)
        sys.exit(1)

    _write_csv(companies, args.output, args.source_name, args.category)
    print(f"✓ [{used}] {len(companies)} 家企业 → {args.output}")
    sys.exit(0)


if __name__ == "__main__":
    main()
