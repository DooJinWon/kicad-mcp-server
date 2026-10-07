#!/bin/bash
# ─────────────────────────────────────────────────────
# kicad-mcp-server GitHub 업로드 스크립트
# 사용법: bash github_upload.sh <GitHub_사용자명>
# 예시:   bash github_upload.sh labremote2025
# ─────────────────────────────────────────────────────

set -e

GITHUB_USER="${1:-}"
REPO_NAME="kicad-mcp-server"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════╗"
echo "║    kicad-mcp-server → GitHub 업로드      ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── GitHub 사용자명 확인 ───────────────────────
if [ -z "$GITHUB_USER" ]; then
  # git config에서 자동 탐색
  GITHUB_USER=$(git config --global github.user 2>/dev/null || echo "")
  if [ -z "$GITHUB_USER" ]; then
    echo "❌ GitHub 사용자명을 입력해주세요:"
    echo "   bash github_upload.sh <사용자명>"
    echo ""
    echo "   예시: bash github_upload.sh labremote2025"
    exit 1
  fi
fi

echo "👤 GitHub 사용자: $GITHUB_USER"
echo "📦 저장소 이름: $REPO_NAME"
echo ""

# ── 1. 최신 파일을 ~/kicad-mcp에서 복사 ──────────
INSTALL_DIR="$HOME/kicad-mcp"
WORK_DIR="$HOME/kicad-mcp-server-git"

echo "📁 [1/5] 작업 디렉토리 준비..."
if [ -d "$WORK_DIR" ]; then
  echo "  기존 $WORK_DIR 삭제 후 재생성"
  rm -rf "$WORK_DIR"
fi
mkdir -p "$WORK_DIR"

# 소스 파일 복사 (kicad-projects/, __pycache__ 제외)
rsync -a --exclude='__pycache__' \
         --exclude='*.pyc' \
         --exclude='kicad-projects/' \
         --exclude='*.jar' \
         --exclude='*.bak*' \
         --exclude='.git' \
         "$SCRIPT_DIR/" "$WORK_DIR/"

echo "  ✅ 파일 준비 완료: $WORK_DIR"
echo ""

# ── 2. git 초기화 ─────────────────────────────
echo "🔧 [2/5] Git 초기화..."
cd "$WORK_DIR"
git init
git config user.name "$(git config --global user.name 2>/dev/null || echo $GITHUB_USER)"
git config user.email "$(git config --global user.email 2>/dev/null || echo "${GITHUB_USER}@users.noreply.github.com")"
echo "  ✅ Git 초기화 완료"
echo ""

# ── 3. 첫 커밋 ────────────────────────────────
echo "📝 [3/5] 첫 커밋 생성..."
git add .
git status --short
git commit -m "feat: initial release — KiCad MCP Server v1.0.0

- 19개 MCP 도구: 프로젝트 생성, 회로도, PCB 배치, 라우팅, DRC, Gerber
- Zero-dependency: pip install 불필요, Python 표준 라이브러리만 사용
- BOM → 회로도 자동 생성
- 3가지 자동 배치 전략: cluster, hierarchical, grid
- Freerouting 연동 자동 라우팅 (Manhattan 폴백)
- KiCad 7/8 호환 (.kicad_sch, .kicad_pcb 포맷)"
echo "  ✅ 커밋 완료"
echo ""

# ── 4. GitHub 저장소 생성 (API) ───────────────
echo "🌐 [4/5] GitHub 저장소 생성..."
echo ""
echo "  ⚠️  GitHub에서 저장소를 먼저 만들어야 합니다:"
echo ""
echo "  1. 브라우저에서 열기:"
echo "     https://github.com/new"
echo ""
echo "  2. 아래 설정으로 생성:"
echo "     • Repository name: $REPO_NAME"
echo "     • Description: Claude MCP server for automated KiCad PCB design"
echo "     • Visibility: Public ✅"
echo "     • README, .gitignore, License: 체크 해제 (이미 있음)"
echo ""
echo "  3. 생성 후 Enter를 눌러 계속..."
read -p "  GitHub 저장소 생성 완료 후 Enter: "
echo ""

# ── 5. Push ───────────────────────────────────
echo "🚀 [5/5] GitHub에 Push..."
REMOTE_URL="https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
echo "  원격 주소: $REMOTE_URL"
echo ""

git remote add origin "$REMOTE_URL"
git branch -M main
git push -u origin main

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║               업로드 완료! 🎉                        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "🔗 저장소 주소:"
echo "   https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo ""
echo "📋 다른 사람이 설치하는 방법:"
echo "   git clone https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
echo "   cd ${REPO_NAME} && bash install.sh"
echo ""
echo "💡 README에서 설치 URL 업데이트:"
echo "   git clone https://github.com/${GITHUB_USER}/${REPO_NAME}.git"
