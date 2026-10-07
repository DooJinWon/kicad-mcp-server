"""
schematic.py — .kicad_sch 파일 생성 및 조작 모듈

KiCad 7+ S-expression 포맷(.kicad_sch)을 직접 생성/수정합니다.
"""

from __future__ import annotations
import uuid
import time
import csv
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────
@dataclass
class SymbolPin:
    number: str
    name: str
    x: float
    y: float
    angle: float = 0


@dataclass
class SchSymbol:
    lib_id: str
    reference: str
    value: str
    footprint: str
    x: float
    y: float
    angle: float = 0
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Wire:
    x1: float
    y1: float
    x2: float
    y2: float
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PowerSymbol:
    name: str
    x: float
    y: float
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class NetLabel:
    label: str
    x: float
    y: float
    angle: float = 0
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


# ─────────────────────────────────────────────
# 기본 심볼 라이브러리 (내장)
# KiCad 심볼 S-expression 정의
# ─────────────────────────────────────────────
BUILTIN_SYMBOLS = {
    "Device:R": {
        "pins": [("1", "~", 0, 1.016), ("2", "~", 0, -1.016)],
        "body": "rect",
    },
    "Device:C": {
        "pins": [("1", "+", 0, 1.016), ("2", "~", 0, -1.016)],
        "body": "cap",
    },
    "Device:L": {
        "pins": [("1", "~", 0, 1.016), ("2", "~", 0, -1.016)],
        "body": "inductor",
    },
    "Device:LED": {
        "pins": [("K", "K", -1.016, 0), ("A", "A", 1.016, 0)],
        "body": "diode",
    },
    "Device:Battery": {
        "pins": [("+", "+", 0, 1.016), ("-", "-", 0, -1.016)],
        "body": "battery",
    },
    "Connector:Conn_01x02_Pin": {
        "pins": [("1", "Pin_1", 0, 1.27), ("2", "Pin_2", 0, -1.27)],
        "body": "conn",
    },
    "Switch:SW_SPDT": {
        "pins": [("1", "A", -2.54, 0), ("2", "B", 2.54, 1.27), ("3", "C", 2.54, -1.27)],
        "body": "switch",
    },
}

# mil 단위 (1 mil = 0.0254 mm), KiCad 내부 단위
MIL = 50  # 기본 그리드 스텝


# ─────────────────────────────────────────────
# SchematicManager
# ─────────────────────────────────────────────
class SchematicManager:
    """KiCad 7+ .kicad_sch 파일을 생성/수정/저장"""

    def __init__(self, file_path: Path):
        self.file_path = Path(file_path)
        self.symbols: list[SchSymbol] = []
        self.wires: list[Wire] = []
        self.power_symbols: list[PowerSymbol] = []
        self.labels: list[NetLabel] = []
        self._auto_x = 50.0
        self._auto_y = 50.0
        self._col_count = 0
        self._page_width = 297.0   # A4 mm
        self._page_height = 210.0

    def create_new(self):
        """새 빈 회로도를 초기화합니다."""
        self.symbols = []
        self.wires = []
        self.power_symbols = []
        self.labels = []
        self._auto_x = 50.0
        self._auto_y = 50.0

    def load(self):
        """기존 .kicad_sch 파일을 파싱합니다 (간단한 파서)."""
        if not self.file_path.exists():
            self.create_new()
            return
        content = self.file_path.read_text(encoding="utf-8")
        # 심볼 개수만 파악 (상세 파싱은 추후 확장)
        self.symbols = []  # 실제 파일 로드 시 파서 확장 가능

    def save(self):
        """현재 회로도를 .kicad_sch S-expression 형식으로 저장합니다."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._generate_kicad_sch()
        self.file_path.write_text(content, encoding="utf-8")

    # ── 심볼 추가 ────────────────────────────
    def add_symbol(self, lib_id: str, reference: str, value: str,
                   footprint: str = "", x: float = 0, y: float = 0) -> dict:
        """회로도에 컴포넌트 심볼을 추가합니다."""
        if x == 0 and y == 0:
            x, y = self._next_auto_pos()

        sym = SchSymbol(
            lib_id=lib_id,
            reference=reference,
            value=value,
            footprint=footprint,
            x=x, y=y
        )
        self.symbols.append(sym)
        return {"reference": reference, "lib_id": lib_id, "position": [x, y]}

    def add_wire(self, x1: float, y1: float, x2: float, y2: float):
        """와이어를 추가합니다."""
        self.wires.append(Wire(x1, y1, x2, y2))

    def add_power_symbol(self, power_name: str, x: float, y: float) -> dict:
        """전원 심볼을 추가합니다 (VDD, GND, +3.3V 등)."""
        ps = PowerSymbol(name=power_name, x=x, y=y)
        self.power_symbols.append(ps)
        return {"power": power_name, "position": [x, y]}

    def add_label(self, label: str, x: float, y: float, angle: float = 0):
        """네트 레이블을 추가합니다."""
        self.labels.append(NetLabel(label=label, x=x, y=y, angle=angle))

    # ── BOM으로부터 자동 배치 ──────────────────
    def auto_place_bom(self, components: list[dict]) -> int:
        """BOM 목록으로부터 심볼을 자동으로 배치합니다."""
        placed = 0
        cols = max(1, int(self._page_width / 30))

        for i, comp in enumerate(components):
            col = i % cols
            row = i // cols
            x = 20.0 + col * 30.0
            y = 20.0 + row * 20.0

            sym = SchSymbol(
                lib_id=comp["lib_id"],
                reference=comp["reference"],
                value=comp["value"],
                footprint=comp.get("footprint", ""),
                x=x, y=y
            )
            self.symbols.append(sym)
            placed += 1

        return placed

    # ── Netlist 생성 ─────────────────────────
    def generate_netlist(self) -> dict:
        """현재 회로도에서 netlist를 생성합니다."""
        components = []
        for sym in self.symbols:
            components.append({
                "reference": sym.reference,
                "lib_id": sym.lib_id,
                "value": sym.value,
                "footprint": sym.footprint,
                "x": sym.x,
                "y": sym.y,
            })

        # 와이어 네트 분석 (Union-Find 방식)
        nets = self._analyze_nets()

        return {"components": components, "nets": nets}

    def _analyze_nets(self) -> list[dict]:
        """와이어 연결로부터 네트를 분석합니다."""
        # 포인트 → 네트 매핑
        point_to_net: dict[tuple, str] = {}
        net_counter = 1

        for wire in self.wires:
            p1 = (round(wire.x1, 3), round(wire.y1, 3))
            p2 = (round(wire.x2, 3), round(wire.y2, 3))

            net1 = point_to_net.get(p1)
            net2 = point_to_net.get(p2)

            if net1 is None and net2 is None:
                net_name = f"Net_{net_counter:03d}"
                net_counter += 1
                point_to_net[p1] = net_name
                point_to_net[p2] = net_name
            elif net1 is not None and net2 is None:
                point_to_net[p2] = net1
            elif net1 is None and net2 is not None:
                point_to_net[p1] = net2
            elif net1 != net2:
                # 두 네트 병합
                old_net = net2
                for k, v in point_to_net.items():
                    if v == old_net:
                        point_to_net[k] = net1

        # 레이블 반영
        for label in self.labels:
            p = (round(label.x, 3), round(label.y, 3))
            if p in point_to_net:
                old = point_to_net[p]
                for k, v in point_to_net.items():
                    if v == old:
                        point_to_net[k] = label.label
            else:
                point_to_net[p] = label.label

        # 네트 그룹화
        nets_dict: dict[str, list] = {}
        for pt, net in point_to_net.items():
            nets_dict.setdefault(net, []).append(list(pt))

        return [{"name": k, "points": v} for k, v in nets_dict.items()]

    # ── BOM 내보내기 ─────────────────────────
    def export_bom(self, fmt: str, output_dir: Path) -> dict:
        """BOM을 CSV 또는 JSON으로 내보냅니다."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        rows = [{"Reference": s.reference, "Value": s.value,
                 "Library": s.lib_id, "Footprint": s.footprint}
                for s in self.symbols]

        if fmt == "csv":
            out_path = output_dir / "bom.csv"
            with open(out_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["Reference", "Value", "Library", "Footprint"])
                writer.writeheader()
                writer.writerows(rows)
            return {"file": str(out_path), "rows": len(rows)}
        else:
            out_path = output_dir / "bom.json"
            out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
            return {"file": str(out_path), "rows": len(rows)}

    # ── 카운터 ───────────────────────────────
    def get_symbol_count(self) -> int:
        return len(self.symbols)

    def get_wire_count(self) -> int:
        return len(self.wires)

    # ── 내부 메서드 ──────────────────────────
    def _next_auto_pos(self) -> tuple[float, float]:
        """다음 자동 배치 좌표를 반환합니다."""
        x = self._auto_x
        y = self._auto_y
        self._auto_x += 25.4  # 1인치 간격
        self._col_count += 1
        if self._col_count >= 8:
            self._col_count = 0
            self._auto_x = 50.0
            self._auto_y += 25.4
        return x, y

    def _generate_kicad_sch(self) -> str:
        """KiCad 7 .kicad_sch S-expression을 생성합니다."""
        ts = int(time.time())
        lines = [
            f'(kicad_sch (version 20230121) (generator kicad-mcp)',
            f'',
            f'  (paper "A4")',
            f'',
            f'  (lib_symbols',
        ]

        # 사용된 심볼 라이브러리 정의 (기본 심볼만 인라인 정의)
        defined = set()
        for sym in self.symbols:
            if sym.lib_id not in defined:
                lines.extend(self._symbol_definition(sym.lib_id))
                defined.add(sym.lib_id)

        lines.append('  )')
        lines.append('')

        # 심볼 인스턴스
        for sym in self.symbols:
            lines.extend(self._symbol_instance(sym))

        # 전원 심볼
        for ps in self.power_symbols:
            lines.extend(self._power_instance(ps))

        # 와이어
        for wire in self.wires:
            lines.append(f'  (wire (pts (xy {wire.x1:.3f} {wire.y1:.3f}) (xy {wire.x2:.3f} {wire.y2:.3f}))')
            lines.append(f'    (stroke (width 0) (type default))')
            lines.append(f'    (uuid "{wire.uuid}")')
            lines.append(f'  )')

        # 레이블
        for lbl in self.labels:
            lines.append(f'  (label "{lbl.label}" (at {lbl.x:.3f} {lbl.y:.3f} {lbl.angle})')
            lines.append(f'    (effects (font (size 1.27 1.27)))')
            lines.append(f'    (uuid "{lbl.uuid}")')
            lines.append(f'  )')

        lines.append(')')
        return '\n'.join(lines)

    def _symbol_definition(self, lib_id: str) -> list[str]:
        """심볼 라이브러리 정의 S-expression 생성."""
        lib, name = lib_id.split(":", 1) if ":" in lib_id else ("Unknown", lib_id)
        lines = [
            f'    (symbol "{lib_id}"',
            f'      (pin_numbers (hide yes))',
            f'      (pin_names (offset 0))',
            f'      (in_bom yes) (on_board yes)',
        ]

        if lib_id in BUILTIN_SYMBOLS:
            info = BUILTIN_SYMBOLS[lib_id]
            # 바디 도형
            if info["body"] == "rect":
                lines += [
                    f'      (symbol "{name}_0_1"',
                    f'        (rectangle (start -1.016 -2.032) (end 1.016 2.032)',
                    f'          (stroke (width 0.1524) (type default))',
                    f'          (fill (type none)))',
                    f'      )',
                ]
            elif info["body"] == "cap":
                lines += [
                    f'      (symbol "{name}_0_1"',
                    f'        (polyline (pts (xy -1.524 -0.508) (xy 1.524 -0.508))',
                    f'          (stroke (width 0.3048) (type default)) (fill (type none)))',
                    f'        (polyline (pts (xy -1.524 0.508) (xy 1.524 0.508))',
                    f'          (stroke (width 0.3048) (type default)) (fill (type none)))',
                    f'      )',
                ]
            else:
                # 기본 사각형
                lines += [
                    f'      (symbol "{name}_0_1"',
                    f'        (rectangle (start -1.524 -1.524) (end 1.524 1.524)',
                    f'          (stroke (width 0.1524) (type default))',
                    f'          (fill (type background)))',
                    f'      )',
                ]

            # 핀 정의
            lines.append(f'      (symbol "{name}_1_1"')
            for pin_num, pin_name, px, py in info["pins"]:
                angle = 270 if py > 0 else 90
                lines += [
                    f'        (pin passive line (at {px:.3f} {py:.3f} {angle})',
                    f'          (length 1.016)',
                    f'          (name "{pin_name}" (effects (font (size 1.27 1.27))))',
                    f'          (number "{pin_num}" (effects (font (size 1.27 1.27))))',
                    f'        )',
                ]
            lines.append('      )')
        else:
            # 알 수 없는 심볼: 기본 박스
            lines += [
                f'      (symbol "{name}_0_1"',
                f'        (rectangle (start -2.54 -2.54) (end 2.54 2.54)',
                f'          (stroke (width 0.1524) (type default))',
                f'          (fill (type background)))',
                f'      )',
                f'      (symbol "{name}_1_1"',
                f'        (pin input line (at -2.54 0 0) (length 1.016)',
                f'          (name "~" (effects (font (size 1.27 1.27))))',
                f'          (number "1" (effects (font (size 1.27 1.27))))',
                f'        )',
                f'      )',
            ]

        lines.append('    )')
        return lines

    def _symbol_instance(self, sym: SchSymbol) -> list[str]:
        """심볼 인스턴스 S-expression 생성."""
        lib, name = sym.lib_id.split(":", 1) if ":" in sym.lib_id else ("Unknown", sym.lib_id)
        lines = [
            f'  (symbol (lib_id "{sym.lib_id}") (at {sym.x:.3f} {sym.y:.3f} {sym.angle})',
            f'    (unit 1)',
            f'    (in_bom yes) (on_board yes) (dnp no)',
            f'    (uuid "{sym.uuid}")',
            f'    (property "Reference" "{sym.reference}" (at {sym.x:.3f} {sym.y - 3.0:.3f} 0)',
            f'      (effects (font (size 1.27 1.27))))',
            f'    (property "Value" "{sym.value}" (at {sym.x:.3f} {sym.y + 3.0:.3f} 0)',
            f'      (effects (font (size 1.27 1.27))))',
        ]
        if sym.footprint:
            lines += [
                f'    (property "Footprint" "{sym.footprint}" (at {sym.x:.3f} {sym.y:.3f} 0)',
                f'      (effects (font (size 1.27 1.27)) (hide yes)))',
            ]
        lines += [
            f'    (instances (project "project"',
            f'      (path "/{sym.uuid}" (reference "{sym.reference}") (unit 1))))',
            f'  )',
            f'',
        ]
        return lines

    def _power_instance(self, ps: PowerSymbol) -> list[str]:
        """전원 심볼 인스턴스 S-expression 생성."""
        power_lib_map = {
            "GND": "power:GND",
            "VDD": "power:VDD",
            "+3.3V": "power:+3.3V",
            "+5V": "power:+5V",
            "VBAT": "power:VBAT",
        }
        lib_id = power_lib_map.get(ps.name, f"power:{ps.name}")
        angle = 270 if ps.name == "GND" else 0
        lines = [
            f'  (symbol (lib_id "{lib_id}") (at {ps.x:.3f} {ps.y:.3f} {angle})',
            f'    (unit 1) (in_bom yes) (on_board yes) (dnp no)',
            f'    (uuid "{ps.uuid}")',
            f'    (property "Reference" "#PWR" (at {ps.x:.3f} {ps.y:.3f} 0)',
            f'      (effects (font (size 1.27 1.27)) (hide yes)))',
            f'    (property "Value" "{ps.name}" (at {ps.x:.3f} {ps.y - 2.54:.3f} 0)',
            f'      (effects (font (size 1.27 1.27))))',
            f'    (instances (project "project"',
            f'      (path "/{ps.uuid}" (reference "#PWR01") (unit 1))))',
            f'  )',
            f'',
        ]
        return lines
