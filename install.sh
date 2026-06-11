#!/bin/bash
# ============================================================
# 伯乐 (bole-skill) — 一键安装
# ============================================================
# 用法:
#   bash install.sh
# ============================================================
set -e

echo "=========================================="
echo "  Bole-skill — One-Click Install"
echo "=========================================="
echo ""

# Step 1: Python deps
echo "[1/5] Installing Python dependencies..."
pip install -r requirements.txt -q
echo "  Done."
echo ""

# Step 2: MCP config — npx 安装时 .mcp.json 不在项目根目录，需补到根目录
echo "[2/5] Checking MCP config..."
if [ ! -f ".mcp.json" ]; then
  for dir in .agents .claude; do
    if [ -f "$dir/skills/bole-skill/.mcp.json" ]; then
      cp "$dir/skills/bole-skill/.mcp.json" .mcp.json
      echo "  .mcp.json copied to project root."
      break
    fi
  done
fi
echo "  MCP OK."
echo ""

# Step 3: Skills — 技能在子目录时（npx/git clone 嵌套），复制到根目录
echo "[3/4] Linking skills to project root..."
if [ ! -d ".claude/skills" ]; then
  for src in bole-skill .agents .agents/skills/bole-skill; do
    if [ -d "$src/.claude/skills" ]; then
      mkdir -p .claude
      cp -r "$src/.claude/skills" .claude/skills
      echo "  Skills linked from $src/.claude/skills"
      break
    fi
  done
  if [ ! -d ".claude/skills" ]; then
    echo "  ⚠️  未找到技能目录，请确保在项目根目录运行 install.sh"
  fi
else
  echo "  Skills OK."
fi
echo ""

# Step 4: Environment
echo "[4/4] Checking environment..."
python scripts/install/configure_mcp.py
echo "  Environment OK."
echo ""

# Step 5: 重启锁定 — 未重启时 pipeline.py 入口强制 exit(2)
touch data/.restart_required

echo "=========================================="
echo "  Install complete!"
echo ""
echo "  ========================================"
echo "  ⚠️  重要：重启后需在项目根目录启动  ⚠️"
echo "  ========================================"
echo ""
echo "  💡 建议在 Claude Code CLI（终端）中运行伯乐，"
echo "     长流程体验更稳定。"
echo ""
echo "  1. 完全退出当前 Claude Code 会话"
echo "  2. cd 到项目根目录（包含 .claude/skills/ 的目录）"
echo "  3. 重新打开 Claude Code"
echo "  4. 告诉 Claude：「已重启，帮我在 XX 城市看看 XX 岗位」"
echo ""
echo "=========================================="
