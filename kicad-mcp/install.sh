#!/bin/bash
# ─────────────────────────────────────────────────────
# KiCad MCP Server 설치 스크립트
# 사용법: bash install.sh
# ─────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_PY="$SCRIPT_DIR/server.py"
CONFIG_DIR="$HOME/Library/Application Support/Claude"
CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"
INSTALL_DIR="$HOME/kicad-mcp"

echo "╔══════════════════════════════════════════╗"
echo "║      KiCad MCP Server 설치 시작          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── 1. kicad-mcp 폴더를 홈 디렉토리로 복사 ──────────
echo "📁 [1/4] kicad-mcp를 ~/kicad-mcp로 복사..."
if [ -d "$INSTALL_DIR" ]; then
  echo "  ⚠️  $INSTALL_DIR 이미 존재 → 덮어쓰기"
fi
cp -r "$SCRIPT_DIR" "$INSTALL_DIR"
echo "  ✅ 완료: $INSTALL_DIR"
echo ""

# ── 2. mcp 패키지 설치 ────────────────────────────
echo "📦 [2/4] Python mcp 패키지 설치..."
if python3 -c "import mcp" 2>/dev/null; then
  echo "  ✅ mcp 이미 설치됨"
else
  pip3 install mcp --quiet
  echo "  ✅ mcp 설치 완료"
fi
echo ""

# ── 3. Claude Desktop 설정 파일 수정 ──────────────
echo "⚙️  [3/4] Claude Desktop 설정 파일 업데이트..."
mkdir -p "$CONFIG_DIR"

PYTHON_PATH="$(which python3)"
KICAD_SERVER="$INSTALL_DIR/server.py"

if [ -f "$CONFIG_FILE" ]; then
  # 기존 설정 백업
  cp "$CONFIG_FILE" "${CONFIG_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
  echo "  ✅ 기존 설정 백업 완료"

  # Python으로 JSON 수정 (기존 mcpServers에 추가)
  python3 << PYEOF
import json, sys

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

print("  ✅ kicad-mcp 항목 추가 완료")
PYEOF

else
  # 새 설정 파일 생성
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
echo ""

# ── 4. 구문 검증 ──────────────────────────────────
echo "🔍 [4/4] 서버 구문 검증..."
if python3 -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from tools.schematic import SchematicManager
from tools.pcb_board import PCBManager
from tools.router import Router
from tools.kicad_cli import KiCadCLI
print('  ✅ 모든 모듈 임포트 성공')
"; then
  :
else
  echo "  ❌ 모듈 임포트 실패. 위 오류를 확인하세요."
  exit 1
fi
echo ""

# ── 완료 ──────────────────────────────────────────
echo "╔══════════════════════════════════════════╗"
echo "║           설치 완료! ✅                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "📌 다음 단계:"
echo "   1. Claude Desktop을 완전히 종료"
echo "   2. Claude Desktop 다시 시작"
echo "   3. 채팅창에서 'kicad-mcp PCB 만들어줘' 입력"
echo ""
echo "📂 설치 위치: $INSTALL_DIR"
echo "⚙️  설정 파일: $CONFIG_FILE"
echo ""
echo "🔧 kicad-cli도 설치하면 DRC/Gerber 기능이 완전히 활성화됩니다:"
echo "   https://www.kicad.org/download/"
