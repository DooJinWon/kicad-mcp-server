# kicad-mcp-server

> **Claude와 대화하면서 KiCad PCB를 자동으로 설계하는 MCP 서버**

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://python.org)
[![KiCad](https://img.shields.io/badge/KiCad-7.x%20%7C%208.x-brightgreen.svg)](https://kicad.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Zero Dependencies](https://img.shields.io/badge/dependencies-zero-green.svg)](#설치)

BOM을 입력하면 회로도 생성 → PCB 자동 배치 → 자동 라우팅 → Gerber 출력까지 Claude와의 대화만으로 완성할 수 있습니다. `pip install` 없이 Python 표준 라이브러리만으로 동작합니다.

---

Claude와 대화하면서 PCB 회로도(Schematic)와 레이아웃을 자동 생성하는 MCP 서버입니다.

## 지원 기능

| 기능 | 도구 이름 | 설명 |
|------|-----------|------|
| 프로젝트 생성 | `create_project` | 새 KiCad 프로젝트 (.kicad_pro/sch/pcb) |
| 프로젝트 열기 | `open_project` | 기존 KiCad 프로젝트 로드 |
| 심볼 추가 | `add_symbol` | 회로도에 컴포넌트 추가 |
| 와이어 연결 | `add_wire` | 핀 간 와이어 연결 |
| 전원 심볼 | `add_power_symbol` | VDD/GND 심볼 추가 |
| BOM 자동 생성 | `create_schematic_from_bom` | BOM 리스트 → 회로도 자동 생성 |
| Netlist 추출 | `generate_netlist` | 회로도에서 Netlist 추출 |
| PCB 자동 배치 | `auto_place_components` | 기능 블록 단위 자동 배치 |
| 컴포넌트 배치 | `place_component` | 특정 위치에 수동 배치 |
| 자동 라우팅 | `auto_route` | Freerouting 연동 자동 배선 |
| 트레이스 추가 | `add_trace` | 수동 트레이스 추가 |
| DRC 실행 | `run_drc` | Design Rule Check |
| Gerber 내보내기 | `export_gerber` | 제조용 Gerber 파일 생성 |
| BOM 내보내기 | `export_bom` | CSV/JSON BOM 파일 생성 |

## 설치

```bash
# 1. 저장소 클론
git clone https://github.com/<your-username>/kicad-mcp-server.git
cd kicad-mcp-server

# 2. 설치 스크립트 실행 (pip install 불필요 — 표준 라이브러리만 사용)
bash install.sh
```

> **install.sh가 자동으로 처리하는 것:**
> - `~/kicad-mcp/`로 파일 복사
> - Python 3.8+ 경로 자동 탐지
> - `claude_desktop_config.json` 설정 자동 등록

### 수동 설치

```bash
# claude_desktop_config.json 에 직접 추가
# macOS: ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "kicad-mcp": {
      "command": "python3",
      "args": ["/절대경로/kicad-mcp-server/server.py"]
    }
  }
}
```

Claude Desktop을 재시작하면 KiCad 도구들이 활성화됩니다.

### 선택 사항 (자동 라우팅)

```bash
# Java 설치 시 Freerouting 고품질 라우팅 사용 가능
brew install openjdk  # macOS
# freerouting.jar는 첫 auto_route 실행 시 자동 다운로드됩니다.
```

## 배치 전략

`auto_place_components` 의 `strategy` 옵션:

- **`cluster`** (기본): 기능 블록별 분리 배치
  - MCU/IC → 중앙
  - 전원 회로 → 우측
  - 센서 → 하단
  - 커넥터 → 상단 가장자리
- **`hierarchical`**: MCU 중심 방사형 배치
- **`grid`**: 단순 격자 배치

## 라우팅

1. **Freerouting** (추천): Java 기반 고품질 자동 라우터
   - Java 설치 필요
   - 첫 실행 시 `freerouting.jar` 자동 다운로드
   - DSN export → 라우팅 → SES import 자동 처리

2. **Manhattan Fallback**: Freerouting/Java 없을 때 사용
   - L자형 직각 배선
   - 기본적인 연결 보장

## 파일 구조

```
kicad-mcp/
├── server.py              # MCP 서버 메인 (18개 도구 정의)
├── tools/
│   ├── schematic.py       # .kicad_sch 생성/수정
│   ├── pcb_board.py       # .kicad_pcb 생성/수정, 자동 배치
│   ├── router.py          # Freerouting 연동, Manhattan 라우팅
│   └── kicad_cli.py       # kicad-cli 래퍼 (DRC, Gerber)
├── examples/
│   └── skin_hydration_example.md
├── requirements.txt
└── README.md
```

## KiCad 버전 호환성

| 버전 | 호환성 |
|------|--------|
| KiCad 7.x | ✅ 완전 호환 (kicad_sch/pcb 포맷) |
| KiCad 8.x | ✅ 호환 |
| KiCad 6.x | ⚠️ 일부 포맷 차이 가능 |
| KiCad 4/5 (Legacy .sch) | ❌ 미지원 → 먼저 KiCad에서 마이그레이션 필요 |

## 예시 대화

```
사용자: nRF52832 기반 센서 보드 PCB 만들어줘. 30x30mm 사이즈로.

Claude: 
  [create_project] → skin_hydration_v2 프로젝트 생성
  [create_schematic_from_bom] → BOM 입력하면 자동으로 회로도 생성
  [auto_place_components] → 기능 블록별 자동 배치
  [auto_route] → Freerouting으로 자동 배선
  [run_drc] → 설계 규칙 검증
  [export_gerber] → JLCPCB 제출용 Gerber 생성
```
