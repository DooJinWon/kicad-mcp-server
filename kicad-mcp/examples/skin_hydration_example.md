# KiCad MCP 사용 예시 — SHS v2.0 (Skin Hydration Sensor)

이 예시는 Claude와 KiCad MCP를 사용해 피부 수분 측정 PCB를 자동으로 설계하는 대화 흐름입니다.

---

## 1단계: 프로젝트 생성

```
사용자: 피부 수분 측정 센서 PCB 프로젝트를 만들어줘. 보드 크기는 30x30mm야.
```

**Claude가 호출하는 MCP 도구:**
```json
{
  "tool": "create_project",
  "args": {
    "name": "skin_hydration_v2",
    "board_width_mm": 30,
    "board_height_mm": 30
  }
}
```

---

## 2단계: BOM으로 회로도 자동 생성

```
사용자: BOM을 바탕으로 회로도를 만들어줘.
```

**Claude가 호출하는 MCP 도구:**
```json
{
  "tool": "create_schematic_from_bom",
  "args": {
    "project_name": "skin_hydration_v2",
    "components": [
      {"reference": "U1", "lib_id": "MCU_Nordic:nRF52832-QFAA", "value": "nRF52832-QFAA-R7", "footprint": "NRF52832:NRF52832-QFAA-R7"},
      {"reference": "U2", "lib_id": "Device:VREG", "value": "TPS70933QDRVRQ1", "footprint": "SON65P200X200X80-7N"},
      {"reference": "U3", "lib_id": "Device:BatteryCharger", "value": "BQ25100YFPR", "footprint": "BGA6N40P3X2_157X88X50N"},
      {"reference": "AN1", "lib_id": "Device:Antenna", "value": "2450AT42A100E", "footprint": "library:2450AT42A100E"},
      {"reference": "X1", "lib_id": "Device:Crystal", "value": "32MHz", "footprint": "Crystal_SMD_2016-4Pin_2.0x1.6mm"},
      {"reference": "X2", "lib_id": "Device:Crystal", "value": "32.768kHz", "footprint": "Crystal_SMD_3215-2Pin_3.2x1.5mm"},
      {"reference": "RH1", "lib_id": "Device:R", "value": "221", "footprint": "Resistor_SMD:R_0201_0603Metric"},
      {"reference": "RH2", "lib_id": "Device:R", "value": "221", "footprint": "Resistor_SMD:R_0201_0603Metric"},
      {"reference": "NTC+1", "lib_id": "Device:Thermistor_NTC", "value": "NTC", "footprint": "library:THRMC0603X33N"},
      {"reference": "NTC-1", "lib_id": "Device:Thermistor_NTC", "value": "NTC", "footprint": "library:THRMC0603X33N"},
      {"reference": "R1", "lib_id": "Device:R", "value": "10k", "footprint": "Resistor_SMD:R_0603_1608Metric"},
      {"reference": "C1", "lib_id": "Device:C", "value": "100nF", "footprint": "Capacitor_SMD:C_0402_1005Metric"},
      {"reference": "L1", "lib_id": "Device:L", "value": "3.9nH", "footprint": "Inductor_SMD:L_0402_1005Metric"},
      {"reference": "BAT1", "lib_id": "Device:Battery", "value": "LiPo 3.7V", "footprint": "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal"}
    ]
  }
}
```

---

## 3단계: 전원 심볼 추가

```
사용자: VDD와 GND 심볼을 추가해줘.
```

```json
{"tool": "add_power_symbol", "args": {"project_name": "skin_hydration_v2", "power_name": "VDD", "x": 100, "y": 50}}
{"tool": "add_power_symbol", "args": {"project_name": "skin_hydration_v2", "power_name": "GND", "x": 100, "y": 200}}
```

---

## 4단계: PCB 자동 배치

```
사용자: 컴포넌트를 PCB에 자동으로 배치해줘. MCU 중심으로 기능별로 묶어서.
```

```json
{
  "tool": "auto_place_components",
  "args": {
    "project_name": "skin_hydration_v2",
    "strategy": "hierarchical",
    "margin_mm": 0.5
  }
}
```

**예상 배치 결과:**
- **중앙**: U1 (nRF52832) — 보드 중심
- **우측**: U2 (TPS70933), U3 (BQ25100) — 전원 블록
- **하단**: NTC+1/2, NTC-1/2, RH1/2 — 센서 블록  
- **상단**: AN1 (안테나) — RF 블록
- **주변**: 패시브 소자들 (R, C, L)

---

## 5단계: 자동 라우팅

```
사용자: 배선을 자동으로 연결해줘.
```

```json
{
  "tool": "auto_route",
  "args": {
    "project_name": "skin_hydration_v2",
    "passes": 5
  }
}
```

→ Freerouting 있으면 고품질 라우팅, 없으면 Manhattan 폴백

---

## 6단계: DRC 검증

```
사용자: DRC 돌려줘.
```

```json
{"tool": "run_drc", "args": {"project_name": "skin_hydration_v2"}}
```

---

## 7단계: Gerber 내보내기

```
사용자: Gerber 파일 만들어줘. JLCPCB에 보낼 거야.
```

```json
{"tool": "export_gerber", "args": {"project_name": "skin_hydration_v2"}}
```

생성 파일:
- `skin_hydration_v2-F_Cu.gbr` — 앞면 구리
- `skin_hydration_v2-B_Cu.gbr` — 뒷면 구리  
- `skin_hydration_v2-F_Silkscreen.gbr` — 실크스크린
- `skin_hydration_v2-Edge_Cuts.gbr` — 보드 외형
- `skin_hydration_v2.drl` — 드릴 파일
