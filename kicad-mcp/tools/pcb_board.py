"""
pcb_board.py — .kicad_pcb 파일 생성 및 조작 모듈

KiCad 7+ PCB S-expression 포맷을 직접 생성/수정합니다.
자동 배치 알고리즘과 트레이스 추가를 지원합니다.
"""

from __future__ import annotations
import uuid
import math
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────
# 데이터 클래스
# ─────────────────────────────────────────────
@dataclass
class Footprint:
    reference: str
    lib_id: str
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    layer: str = "F.Cu"
    value: str = ""
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    pads: list = field(default_factory=list)  # [(pad_num, net_name, x_rel, y_rel)]


@dataclass
class Track:
    x1: float
    y1: float
    x2: float
    y2: float
    width_mm: float = 0.25
    layer: str = "F.Cu"
    net_name: str = ""
    net_id: int = 0
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Via:
    x: float
    y: float
    size: float = 0.8
    drill: float = 0.4
    net_name: str = ""
    net_id: int = 0
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Zone:
    net_name: str
    layer: str = "B.Cu"
    clearance_mm: float = 0.2
    pts: list = field(default_factory=list)
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))


# ─────────────────────────────────────────────
# 표준 Footprint 크기 데이터베이스
# ─────────────────────────────────────────────
FOOTPRINT_SIZES = {
    "Resistor_SMD:R_0201_0603Metric": (0.6, 0.3),
    "Resistor_SMD:R_0402_1005Metric": (1.0, 0.5),
    "Resistor_SMD:R_0603_1608Metric": (1.6, 0.8),
    "Resistor_SMD:R_0805_2012Metric": (2.0, 1.2),
    "Capacitor_SMD:C_0201_0603Metric": (0.6, 0.3),
    "Capacitor_SMD:C_0402_1005Metric": (1.0, 0.5),
    "Capacitor_SMD:C_0603_1608Metric": (1.6, 0.8),
    "Capacitor_SMD:C_0805_2012Metric": (2.0, 1.2),
    "Inductor_SMD:L_0402_1005Metric": (1.0, 0.5),
    "Inductor_SMD:L_0603_1608Metric": (1.6, 0.8),
    "NRF52832:NRF52832-QFAA-R7": (6.0, 6.0),
    "default_ic": (5.0, 5.0),
    "default_passive": (1.6, 0.8),
}


def _footprint_size(lib_id: str) -> tuple[float, float]:
    """footprint 크기를 반환합니다 (w, h mm)."""
    if lib_id in FOOTPRINT_SIZES:
        return FOOTPRINT_SIZES[lib_id]
    if "QFN" in lib_id or "BGA" in lib_id or "IC" in lib_id or "MCU" in lib_id:
        return FOOTPRINT_SIZES["default_ic"]
    return FOOTPRINT_SIZES["default_passive"]


# ─────────────────────────────────────────────
# PCBManager
# ─────────────────────────────────────────────
class PCBManager:
    """KiCad 7+ .kicad_pcb 파일 생성/수정/저장"""

    def __init__(self, file_path: Path, width_mm: float = 30.0, height_mm: float = 30.0):
        self.file_path = Path(file_path)
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.footprints: list[Footprint] = []
        self.tracks: list[Track] = []
        self.vias: list[Via] = []
        self.zones: list[Zone] = []
        self._nets: dict[str, int] = {"": 0}  # net_name → net_id
        self._net_counter = 1
        self._board_origin = (100.0, 100.0)  # KiCad 기본 원점

    def create_new(self):
        """새 PCB를 초기화합니다."""
        self.footprints = []
        self.tracks = []
        self.vias = []
        self.zones = []
        self._nets = {"": 0}
        self._net_counter = 1

    def load(self):
        """기존 .kicad_pcb 파일을 로드합니다 (footprint 목록 파싱)."""
        if not self.file_path.exists():
            self.create_new()
            return
        content = self.file_path.read_text(encoding="utf-8")
        # 간단한 footprint 파싱
        self.footprints = []
        refs = re.findall(r'\(property "Reference" "([^"]+)"', content)
        fps = re.findall(r'\(footprint "([^"]+)"', content)
        xys = re.findall(r'\(at ([\d.]+) ([\d.]+)', content)

        for i, ref in enumerate(refs):
            fp = Footprint(
                reference=ref,
                lib_id=fps[i] if i < len(fps) else "Unknown:Unknown",
                x=float(xys[i][0]) if i < len(xys) else 100.0,
                y=float(xys[i][1]) if i < len(xys) else 100.0,
            )
            self.footprints.append(fp)

    def save(self):
        """현재 PCB를 .kicad_pcb 파일로 저장합니다."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        content = self._generate_kicad_pcb()
        self.file_path.write_text(content, encoding="utf-8")

    # ── Footprint 관리 ────────────────────────
    def add_footprint(self, reference: str, lib_id: str, value: str = "",
                      x: float = 100.0, y: float = 100.0,
                      rotation: float = 0, layer: str = "F.Cu") -> Footprint:
        """Footprint을 PCB에 추가합니다."""
        fp = Footprint(
            reference=reference, lib_id=lib_id, value=value,
            x=x, y=y, rotation=rotation, layer=layer
        )
        self.footprints.append(fp)
        return fp

    def place_component(self, reference: str, x_mm: float, y_mm: float,
                        rotation: float = 0, layer: str = "F.Cu") -> dict:
        """특정 레퍼런스의 footprint 위치를 설정합니다."""
        ox, oy = self._board_origin
        abs_x = ox + x_mm
        abs_y = oy + y_mm

        for fp in self.footprints:
            if fp.reference == reference:
                fp.x = abs_x
                fp.y = abs_y
                fp.rotation = rotation
                fp.layer = layer
                return {"reference": reference, "x_mm": x_mm, "y_mm": y_mm,
                        "rotation": rotation, "layer": layer}

        # 없으면 새로 추가
        fp = Footprint(reference=reference, lib_id="Unknown:Unknown",
                       x=abs_x, y=abs_y, rotation=rotation, layer=layer)
        self.footprints.append(fp)
        return {"reference": reference, "x_mm": x_mm, "y_mm": y_mm,
                "rotation": rotation, "layer": layer, "note": "새로 추가됨"}

    # ── 자동 배치 알고리즘 ──────────────────────
    def auto_place(self, netlist: dict, strategy: str = "cluster",
                   margin_mm: float = 1.0) -> dict:
        """
        BOM/Netlist를 기반으로 컴포넌트를 자동 배치합니다.

        strategy:
          - 'grid': 단순 격자 배치
          - 'cluster': 기능 블록(MCU/전원/패시브) 분리 배치
          - 'hierarchical': 계층 배치 (중앙 MCU → 주변부)
        """
        components = netlist.get("components", [])
        if not components:
            return {"placed": 0, "message": "배치할 컴포넌트가 없습니다."}

        # 기존 footprint를 업데이트
        fp_map = {fp.reference: fp for fp in self.footprints}

        # 컴포넌트 없으면 netlist에서 추가
        for comp in components:
            ref = comp["reference"]
            if ref not in fp_map:
                fp = Footprint(
                    reference=ref,
                    lib_id=comp.get("footprint", "Unknown:Unknown"),
                    value=comp.get("value", ""),
                )
                self.footprints.append(fp)
                fp_map[ref] = fp

        if strategy == "grid":
            positions = self._grid_placement(components, margin_mm)
        elif strategy == "cluster":
            positions = self._cluster_placement(components, margin_mm)
        else:  # hierarchical
            positions = self._hierarchical_placement(components, margin_mm)

        # 위치 적용
        ox, oy = self._board_origin
        for ref, (rx, ry) in positions.items():
            if ref in fp_map:
                fp_map[ref].x = ox + rx
                fp_map[ref].y = oy + ry

        return {"placed": len(positions), "strategy": strategy,
                "components": [{"ref": k, "x_mm": v[0], "y_mm": v[1]}
                                for k, v in positions.items()]}

    def _grid_placement(self, components: list[dict], margin: float) -> dict[str, tuple]:
        """단순 격자 배치 (왼쪽 위부터 순서대로)."""
        positions = {}
        cols = max(1, int(math.sqrt(len(components))))
        for i, comp in enumerate(components):
            col = i % cols
            row = i // cols
            fp_w, fp_h = _footprint_size(comp.get("footprint", ""))
            x = 2.0 + col * (fp_w + margin + 2.0)
            y = 2.0 + row * (fp_h + margin + 2.0)
            positions[comp["reference"]] = (x, y)
        return positions

    def _cluster_placement(self, components: list[dict], margin: float) -> dict[str, tuple]:
        """
        기능 블록별 클러스터 배치:
        - MCU / IC → 중앙
        - 전원 회로(U2, C_bypass) → 우측
        - 저항/커패시터 → MCU 주변
        - 커넥터 → 보드 가장자리
        """
        positions = {}
        mcu, power, passive, connector, sensor, other = [], [], [], [], [], []

        for comp in components:
            ref = comp["reference"]
            lib_id = comp.get("lib_id", "")
            fp = comp.get("footprint", "")

            if any(k in lib_id.upper() for k in ["NRF", "MCU", "MICRO"]):
                mcu.append(comp)
            elif ref.startswith("U") and "POWER" not in lib_id.upper():
                if any(k in lib_id.upper() for k in ["TPS", "BQ", "LDO", "REG"]):
                    power.append(comp)
                else:
                    mcu.append(comp)
            elif any(k in ref for k in ["NTC", "RH", "SENSOR"]):
                sensor.append(comp)
            elif ref.startswith(("J", "CN", "P")):
                connector.append(comp)
            elif ref.startswith(("R", "C", "L", "D")):
                passive.append(comp)
            else:
                other.append(comp)

        # MCU/IC → 보드 중앙 영역
        cx, cy = self.width_mm / 2, self.height_mm / 2
        self._place_group(mcu, cx - 8, cy - 5, 8.0, margin, positions)

        # 전원 → 우측
        self._place_group(power, self.width_mm - 12, 2, 5.0, margin, positions)

        # 센서 → 하단
        self._place_group(sensor, 2, self.height_mm - 10, 6.0, margin, positions)

        # 커넥터 → 보드 상단 가장자리
        self._place_group(connector, 2, 1, 10.0, margin, positions)

        # 패시브 → MCU 주변 빈 공간
        self._place_group(passive, 2, cy - 5, 5.0, margin, positions)

        # 나머지
        self._place_group(other, cx - 3, 2, 5.0, margin, positions)

        return positions

    def _hierarchical_placement(self, components: list[dict], margin: float) -> dict[str, tuple]:
        """MCU 중심, 주변부에 서브 블록을 방사형으로 배치."""
        positions = {}
        cx, cy = self.width_mm / 2 - 5, self.height_mm / 2 - 5

        mcu_comps = [c for c in components if any(k in c.get("lib_id", "").upper()
                     for k in ["NRF", "MCU", "MICRO"]) or
                     (c["reference"].startswith("U") and c["reference"] in ["U1"])]
        others = [c for c in components if c not in mcu_comps]

        # MCU 중앙
        if mcu_comps:
            positions[mcu_comps[0]["reference"]] = (cx, cy)
            for i, comp in enumerate(mcu_comps[1:], 1):
                positions[comp["reference"]] = (cx + i * 8, cy)

        # 나머지는 주변부에 방사형으로
        n = len(others)
        radius = min(self.width_mm, self.height_mm) * 0.35
        for i, comp in enumerate(others):
            angle = (2 * math.pi * i / max(n, 1)) - math.pi / 2
            rx = cx + radius * math.cos(angle)
            ry = cy + radius * math.sin(angle)
            rx = max(2.0, min(self.width_mm - 4, rx))
            ry = max(2.0, min(self.height_mm - 4, ry))
            positions[comp["reference"]] = (rx, ry)

        return positions

    def _place_group(self, comps: list[dict], start_x: float, start_y: float,
                     row_w: float, margin: float, positions: dict):
        """그룹 내 컴포넌트를 격자로 배치합니다."""
        x, y = start_x, start_y
        max_h = 0.0
        for comp in comps:
            fw, fh = _footprint_size(comp.get("footprint", ""))
            positions[comp["reference"]] = (x, y)
            x += fw + margin
            max_h = max(max_h, fh)
            if x > start_x + row_w:
                x = start_x
                y += max_h + margin
                max_h = 0.0

    # ── 트레이스 / Via ────────────────────────
    def add_trace(self, x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float,
                  width_mm: float = 0.25, layer: str = "F.Cu", net_name: str = "") -> Track:
        """트레이스를 추가합니다."""
        ox, oy = self._board_origin
        net_id = self._get_or_create_net(net_name)
        track = Track(
            x1=ox + x1_mm, y1=oy + y1_mm,
            x2=ox + x2_mm, y2=oy + y2_mm,
            width_mm=width_mm, layer=layer,
            net_name=net_name, net_id=net_id
        )
        self.tracks.append(track)
        return track

    def add_via(self, x_mm: float, y_mm: float,
                size: float = 0.8, drill: float = 0.4, net_name: str = "") -> Via:
        """Via를 추가합니다."""
        ox, oy = self._board_origin
        net_id = self._get_or_create_net(net_name)
        via = Via(x=ox + x_mm, y=oy + y_mm,
                  size=size, drill=drill, net_name=net_name, net_id=net_id)
        self.vias.append(via)
        return via

    # ── 보드 외형 ─────────────────────────────
    def set_board_outline(self, shape: str = "rect",
                           width_mm: float = 30.0, height_mm: float = 30.0,
                           corner_radius_mm: float = 1.0):
        """보드 외형을 설정합니다 (Edge.Cuts 레이어)."""
        self.width_mm = width_mm
        self.height_mm = height_mm
        self._board_shape = shape
        self._corner_radius = corner_radius_mm

    # ── 구리 채우기 ───────────────────────────
    def add_copper_pour(self, net_name: str, layer: str = "B.Cu",
                         clearance_mm: float = 0.2):
        """보드 전체를 덮는 구리 채우기를 추가합니다."""
        ox, oy = self._board_origin
        net_id = self._get_or_create_net(net_name)
        zone = Zone(
            net_name=net_name, layer=layer, clearance_mm=clearance_mm,
            pts=[
                [ox, oy],
                [ox + self.width_mm, oy],
                [ox + self.width_mm, oy + self.height_mm],
                [ox, oy + self.height_mm],
            ]
        )
        self.zones.append(zone)

    # ── 정보 ──────────────────────────────────
    def get_footprint_count(self) -> int:
        return len(self.footprints)

    def get_track_count(self) -> int:
        return len(self.tracks)

    def get_board_size(self) -> list[float]:
        return [self.width_mm, self.height_mm]

    # ── 내부 메서드 ──────────────────────────
    def _get_or_create_net(self, net_name: str) -> int:
        if not net_name:
            return 0
        if net_name not in self._nets:
            self._nets[net_name] = self._net_counter
            self._net_counter += 1
        return self._nets[net_name]

    def _generate_kicad_pcb(self) -> str:
        """KiCad 7 .kicad_pcb S-expression을 생성합니다."""
        ox, oy = self._board_origin
        lines = [
            '(kicad_pcb (version 20230121) (generator kicad-mcp)',
            '',
            '  (general',
            f'    (thickness 1.6)',
            f'    (legacy_teardrops no)',
            '  )',
            '',
            '  (paper "A4")',
            '',
            '  (layers',
            '    (0 "F.Cu" signal)',
            '    (31 "B.Cu" signal)',
            '    (32 "B.Adhes" user "B.Adhesive")',
            '    (33 "F.Adhes" user "F.Adhesive")',
            '    (34 "B.Paste" user)',
            '    (35 "F.Paste" user)',
            '    (36 "B.SilkS" user "B.Silkscreen")',
            '    (37 "F.SilkS" user "F.Silkscreen")',
            '    (38 "B.Mask" user)',
            '    (39 "F.Mask" user)',
            '    (40 "Dwgs.User" user "User.Drawings")',
            '    (44 "Edge.Cuts" user)',
            '    (45 "Margin" user)',
            '  )',
            '',
            '  (setup',
            '    (pad_to_mask_clearance 0)',
            '    (pcbplotparams',
            '      (layerselection 0x00010fc_ffffffff)',
            '      (plot_on_all_layers_selection 0x0000000_00000000)',
            '      (disableapertmacros no)',
            '      (usegerberextensions no)',
            '      (usegerberattributes yes)',
            '      (usegerberadvancedattributes yes)',
            '      (creategerberjobfile yes)',
            '      (dashed_line_dash_ratio 12.000000)',
            '      (dashed_line_gap_ratio 3.000000)',
            '      (svgprecision 4)',
            '      (plotframeref no)',
            '      (viasonmask no)',
            '      (mode 1)',
            '      (useauxorigin no)',
            '      (hpglpennumber 1)',
            '      (hpglpenspeed 20)',
            '      (hpglpendiameter 15.000000)',
            '      (dxfpolygonmode yes)',
            '      (dxfimperialunits yes)',
            '      (dxfusepcbnewfont yes)',
            '      (psnegative no)',
            '      (psa4output no)',
            '      (plotreference yes)',
            '      (plotvalue yes)',
            '      (plotfptext yes)',
            '      (plotinvisibletext no)',
            '      (sketchpadsonfab no)',
            '      (subtractmaskfromsilk no)',
            '      (outputformat 1)',
            '      (mirror no)',
            '      (drillshape 1)',
            '      (scaleselection 1)',
            '      (outputdirectory "gerber/")',
            '    )',
            '  )',
            '',
        ]

        # 네트 목록
        lines.append('  (net 0 "")')
        for net_name, net_id in self._nets.items():
            if net_id > 0:
                lines.append(f'  (net {net_id} "{net_name}")')
        lines.append('')

        # 보드 외형 (Edge.Cuts)
        lines.extend(self._board_outline_sexpr())
        lines.append('')

        # Footprint
        for fp in self.footprints:
            lines.extend(self._footprint_sexpr(fp))

        # 트레이스
        for track in self.tracks:
            lines.append(
                f'  (segment (start {track.x1:.3f} {track.y1:.3f}) '
                f'(end {track.x2:.3f} {track.y2:.3f}) '
                f'(width {track.width_mm:.3f}) '
                f'(layer "{track.layer}") '
                f'(net {track.net_id}) '
                f'(uuid "{track.uuid}"))'
            )

        # Via
        for via in self.vias:
            lines.append(
                f'  (via (at {via.x:.3f} {via.y:.3f}) '
                f'(size {via.size:.3f}) (drill {via.drill:.3f}) '
                f'(layers "F.Cu" "B.Cu") '
                f'(net {via.net_id}) '
                f'(uuid "{via.uuid}"))'
            )

        # Zone (구리 채우기)
        for zone in self.zones:
            lines.extend(self._zone_sexpr(zone))

        lines.append(')')
        return '\n'.join(lines)

    def _board_outline_sexpr(self) -> list[str]:
        """보드 외형 S-expression."""
        ox, oy = self._board_origin
        w, h = self.width_mm, self.height_mm
        shape = getattr(self, "_board_shape", "rect")
        cr = getattr(self, "_corner_radius", 1.0)
        lines = []

        if shape in ("rect", "rounded_rect"):
            # 4변 직선 (rounded_rect는 추후 arc 추가 가능)
            edges = [
                (ox, oy, ox + w, oy),
                (ox + w, oy, ox + w, oy + h),
                (ox + w, oy + h, ox, oy + h),
                (ox, oy + h, ox, oy),
            ]
            for x1, y1, x2, y2 in edges:
                lines.append(
                    f'  (gr_line (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) '
                    f'(layer "Edge.Cuts") (width 0.05) (uuid "{uuid.uuid4()}"))'
                )
        elif shape == "circle":
            r = min(w, h) / 2
            cx, cy = ox + w / 2, oy + h / 2
            lines.append(
                f'  (gr_circle (center {cx:.3f} {cy:.3f}) (end {cx + r:.3f} {cy:.3f}) '
                f'(layer "Edge.Cuts") (width 0.05) (uuid "{uuid.uuid4()}"))'
            )
        return lines

    def _footprint_sexpr(self, fp: Footprint) -> list[str]:
        """Footprint S-expression."""
        fw, fh = _footprint_size(fp.lib_id)
        hw, hh = fw / 2, fh / 2

        lines = [
            f'  (footprint "{fp.lib_id}"',
            f'    (layer "{fp.layer}")',
            f'    (uuid "{fp.uuid}")',
            f'    (at {fp.x:.3f} {fp.y:.3f}' + (f' {fp.rotation}' if fp.rotation else '') + ')',
            f'    (property "Reference" "{fp.reference}"',
            f'      (at 0 {-hh - 0.8:.3f} 0)',
            f'      (layer "F.SilkS")',
            f'      (uuid "{uuid.uuid4()}")',
            f'      (effects (font (size 1 1) (thickness 0.15))))',
            f'    (property "Value" "{fp.value}"',
            f'      (at 0 {hh + 0.8:.3f} 0)',
            f'      (layer "F.Fab")',
            f'      (uuid "{uuid.uuid4()}")',
            f'      (effects (font (size 1 1) (thickness 0.15))))',
            # Courtyard
            f'    (fp_rect (start {-hw - 0.25:.3f} {-hh - 0.25:.3f}) (end {hw + 0.25:.3f} {hh + 0.25:.3f})',
            f'      (layer "F.CrtYd") (width 0.05) (uuid "{uuid.uuid4()}"))',
            # Fab 외형
            f'    (fp_rect (start {-hw:.3f} {-hh:.3f}) (end {hw:.3f} {hh:.3f})',
            f'      (layer "F.Fab") (width 0.1) (uuid "{uuid.uuid4()}"))',
        ]

        # 기본 패드 (2-pin 패시브 또는 IC)
        if fw <= 2.0:  # 패시브 SMD
            pad_w, pad_h = min(hw * 0.8, 0.9), fh * 0.9
            lines += [
                f'    (pad "1" smd roundrect (at {-hw + pad_w / 2:.3f} 0) (size {pad_w:.3f} {pad_h:.3f})',
                f'      (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25)',
                f'      (net 0 "") (uuid "{uuid.uuid4()}"))',
                f'    (pad "2" smd roundrect (at {hw - pad_w / 2:.3f} 0) (size {pad_w:.3f} {pad_h:.3f})',
                f'      (layers "F.Cu" "F.Paste" "F.Mask") (roundrect_rratio 0.25)',
                f'      (net 0 "") (uuid "{uuid.uuid4()}"))',
            ]
        else:  # IC - 4면에 핀 배치
            pin_pitch = 0.5
            pins_per_side = max(2, int(min(fw, fh) / pin_pitch))
            pad_w, pad_h = 0.3, pin_pitch * 0.8

            for side in range(4):
                for i in range(pins_per_side):
                    t = (i - (pins_per_side - 1) / 2) * pin_pitch
                    if side == 0:  # 하단
                        px, py = t, hh + 0.5
                    elif side == 1:  # 우측
                        px, py = hw + 0.5, t
                    elif side == 2:  # 상단
                        px, py = -t, -hh - 0.5
                    else:  # 좌측
                        px, py = -hw - 0.5, -t

                    pin_num = side * pins_per_side + i + 1
                    rot = 90 if side in (1, 3) else 0
                    lines += [
                        f'    (pad "{pin_num}" smd rect (at {px:.3f} {py:.3f} {rot})',
                        f'      (size {pad_w:.3f} {pad_h:.3f})',
                        f'      (layers "F.Cu" "F.Paste" "F.Mask")',
                        f'      (net 0 "") (uuid "{uuid.uuid4()}"))',
                    ]

        lines.append('  )')
        lines.append('')
        return lines

    def _zone_sexpr(self, zone: Zone) -> list[str]:
        """Zone(구리 채우기) S-expression."""
        net_id = self._nets.get(zone.net_name, 0)
        pts_str = " ".join(f"(xy {p[0]:.3f} {p[1]:.3f})" for p in zone.pts)
        return [
            f'  (zone (net {net_id}) (net_name "{zone.net_name}") (layer "{zone.layer}")',
            f'    (uuid "{zone.uuid}")',
            f'    (hatch edge 0.508)',
            f'    (connect_pads (clearance {zone.clearance_mm:.3f}))',
            f'    (min_thickness 0.25)',
            f'    (filled_areas_thickness no)',
            f'    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))',
            f'    (polygon (pts {pts_str}))',
            f'  )',
            '',
        ]
