#!/bin/bash
# ─────────────────────────────────────────────────────
# KiCad MCP — 패치 스크립트 (pip 불필요 버전으로 업데이트)
# 사용법: bash patch.sh
# ─────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/kicad-mcp"
CONFIG_DIR="$HOME/Library/Application Support/Claude"
CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

echo "╔══════════════════════════════════════════╗"
echo "║   KiCad MCP 패치 적용 (pip 불필요 버전) ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. server.py 업데이트 ─────────────────────
echo "🔄 [1/3] server.py 업데이트..."
cp "$SCRIPT_DIR/server.py" "$INSTALL_DIR/server.py"
cp "$SCRIPT_DIR/tools/schematic.py" "$INSTALL_DIR/tools/schematic.py"
cp "$SCRIPT_DIR/tools/pcb_board.py" "$INSTALL_DIR/tools/pcb_board.py"
cp "$SCRIPT_DIR/tools/router.py"    "$INSTALL_DIR/tools/router.py"
cp "$SCRIPT_DIR/tools/kicad_cli.py" "$INSTALL_DIR/tools/kicad_cli.py"
echo "  ✅ 파일 업데이트 완료"
echo ""

# ── 2. Python 버전 확인 ───────────────────────
echo "🐍 [2/3] Python 버전 확인..."
PYTHON_PATH=""

# Python 3.8+ 탐색 (우선순위 순)
for cmd in python3.12 python3.11 python3.10 python3.9 python3.8 python3; do
  if command -v "$cmd" &>/dev/null; then
    VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    MAJOR=$(echo $VER | cut -d. -f1)
    MINOR=$(echo $VER | cut -d. -f2)
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 8 ]; then
      PYTHON_PATH=$(which "$cmd")
      echo "  ✅ 사용할 Python: $PYTHON_PATH ($VER)"
      break
    fi
  fi
done

if [ -z "$PYTHON_PATH" ]; then
  echo "  ❌ Python 3.8+를 찾을 수 없습니다."
  echo "  👉 Homebrew로 설치: brew install python3"
  exit 1
fi
echo ""

# ── 3. claude_desktop_config.json 업데이트 ────
echo "⚙️  [3/3] Claude Desktop 설정 업데이트..."
mkdir -p "$CONFIG_DIR"

KICAD_SERVER="$INSTALL_DIR/server.py"

if [ -f "$CONFIG_FILE" ]; then
  # 기존 백업
  cp "$CONFIG_FILE" "${CONFIG_FILE}.bak_$(date +%Y%m%d_%H%M%S)"

  python3 << PYEOF
import json

config_path = "$CONFIG_FILE"
with open(config_path, 'r', encoding='utf-8') as f:
    config = json.load(f)

if 'mcpServers' not in config:
    config['mcpServers'] = {}

config['mcpServers']['kicad-mcp'] = {
    "command": "$PYTHON_PATH",
    "args": ["$KICAD_SERVER"],
    "env": {}
}

with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print("  ✅ kicad-mcp 설정 업데이트 완료")
PYEOF

else
  # 새로 생성
  cat > "$CONFIG_FILE" << JSONEOF
{
  "mcpServers": {
    "kicad-mcp": {
      "command": "$PYTHON_PATH",
      "args": ["$KICAD_SERVER"],
      "env": {}
    }
  }
}
JSONEOF
  echo "  ✅ 새 설정 파일 생성 완료"
fi

# ── 구문 검증 ─────────────────────────────────
echo ""
echo "🔍 모듈 검증..."
"$PYTHON_PATH" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from tools.schematic import SchematicManager
from tools.pcb_board import PCBManager
from tools.router import Router
from tools.kicad_cli import KiCadCLI
print('  ✅ 모든 모듈 정상')
"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║          패치 완료! ✅                   ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "👉 Claude Desktop을 완전히 종료 후 재시작하세요."
echo ""

# 현재 설정 파일 내용 확인
echo "📋 현재 설정:"
cat "$CONFIG_FILE"
