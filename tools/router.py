"""
router.py — 자동 라우팅 모듈

Freerouting(오픈소스 자동 라우터)과 연동하여 PCB 트레이스를 자동으로 생성합니다.
Freerouting이 없을 경우 간단한 Manhattan 라우팅 알고리즘을 사용합니다.
"""

from __future__ import annotations
import asyncio
import subprocess
import json
import urllib.request
import shutil
from pathlib import Path
from typing import Optional

from .pcb_board import PCBManager

# Freerouting 최신 릴리즈 URL
FREEROUTING_RELEASE_URL = (
    "https://github.com/freerouting/freerouting/releases/download/"
    "v1.9.0/freerouting-1.9.0.jar"
)


class Router:
    """KiCad PCB 자동 라우터"""

    # ─────────────────────────────────────────
    # Freerouting 연동
    # ─────────────────────────────────────────
    async def freeroute(self, pcb: PCBManager,
                         freerouting_jar: Optional[str] = None,
                         passes: int = 3) -> dict:
        """
        Freerouting을 사용해 자동 라우팅을 수행합니다.

        흐름:
          1. PCB → DSN(Specctra) 파일 export
          2. Freerouting.jar 실행
          3. SES 파일을 .kicad_pcb에 import
        """
        pcb.save()
        pcb_path = pcb.file_path
        project_dir = pcb_path.parent
        dsn_path = project_dir / (pcb_path.stem + ".dsn")
        ses_path = project_dir / (pcb_path.stem + ".ses")

        # DSN export
        dsn_ok = self._export_dsn(pcb, dsn_path)
        if not dsn_ok:
            return {"success": False, "message": "DSN export 실패"}

        # Freerouting jar 확인/다운로드
        jar_path = self._ensure_freerouting(freerouting_jar, project_dir)
        if jar_path is None:
            # Fallback: 간단한 Manhattan 라우팅 적용
            result = self._manhattan_route(pcb)
            return {"success": True, "method": "manhattan_fallback", **result}

        # Freerouting 실행
        cmd = [
            "java", "-jar", str(jar_path),
            "-de", str(dsn_path),
            "-do", str(ses_path),
            "-mp", str(passes),
            "-dr", str(project_dir / "design_rules.rul"),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_dir),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode != 0:
                return {
                    "success": False,
                    "method": "freerouting",
                    "error": stderr.decode("utf-8", errors="replace")[:500],
                }

            # SES import
            if ses_path.exists():
                imported = self._import_ses(pcb, ses_path)
                pcb.save()
                return {
                    "success": True,
                    "method": "freerouting",
                    "passes": passes,
                    "tracks_added": imported,
                    "dsn_path": str(dsn_path),
                    "ses_path": str(ses_path),
                }
            else:
                return {"success": False, "method": "freerouting",
                        "error": "SES 파일이 생성되지 않았습니다."}

        except asyncio.TimeoutError:
            return {"success": False, "method": "freerouting",
                    "error": f"Freerouting 타임아웃 ({300}초)"}
        except FileNotFoundError:
            # Java가 없는 경우
            result = self._manhattan_route(pcb)
            pcb.save()
            return {"success": True, "method": "manhattan_fallback",
                    "note": "Java를 찾을 수 없어 Manhattan 라우팅을 사용했습니다.", **result}

    # ─────────────────────────────────────────
    # DSN (Specctra) Export
    # ─────────────────────────────────────────
    def _export_dsn(self, pcb: PCBManager, dsn_path: Path) -> bool:
        """PCB를 DSN(Specctra) 포맷으로 내보냅니다."""
        ox, oy = pcb._board_origin
        w, h = pcb.width_mm, pcb.height_mm

        lines = [
            f'(pcb "{pcb.file_path.stem}"',
            f'  (parser',
            f'    (string_quote ")',
            f'    (space_in_quoted_tokens on)',
            f'    (host_cad "KiCad-MCP")',
            f'    (host_version "7.0")',
            f'  )',
            f'  (resolution um 10)',
            f'  (unit um)',
            f'',
            f'  (structure',
            f'    (layer F.Cu (type signal) (property (pcb_layer_number 0)))',
            f'    (layer B.Cu (type signal) (property (pcb_layer_number 31)))',
            f'    (boundary',
            f'      (rect pcb {ox*1000:.0f} {oy*1000:.0f} '
            f'{(ox+w)*1000:.0f} {(oy+h)*1000:.0f})',
            f'    )',
            f'    (via "Via[0-1]_800:400_um" "F.Cu" "B.Cu")',
            f'    (rule',
            f'      (width 250)',
            f'      (clearance 200)',
            f'    )',
            f'  )',
            f'',
            f'  (placement',
        ]

        # Footprint → component
        for fp in pcb.footprints:
            lines += [
                f'    (component "{fp.lib_id}"',
                f'      (place "{fp.reference}" {fp.x*1000:.0f} {fp.y*1000:.0f} '
                f'{"front" if fp.layer == "F.Cu" else "back"} {fp.rotation})',
                f'    )',
            ]

        lines += [
            f'  )',
            f'',
            f'  (library',
        ]

        # 기본 footprint 정의 (단순화)
        defined = set()
        for fp in pcb.footprints:
            if fp.lib_id not in defined:
                lines += [
                    f'    (image "{fp.lib_id}"',
                    f'      (outline (path Signal 100',
                    f'        -500 -500  500 -500  500 500  -500 500  -500 -500))',
                    f'      (pin Pad_1 1 -500 0)',
                    f'      (pin Pad_2 2 500 0)',
                    f'    )',
                ]
                defined.add(fp.lib_id)

        lines += [
            f'  )',
            f'',
            f'  (network',
        ]

        # Net 정의
        for net_name, net_id in pcb._nets.items():
            if net_id > 0:
                # 해당 네트에 연결된 핀 찾기
                pins = []
                for fp in pcb.footprints:
                    for pad_num, pad_net, _, _ in fp.pads:
                        if pad_net == net_name:
                            pins.append(f'      (pin "{fp.reference}"-"{pad_num}")')
                if pins:
                    lines.append(f'    (net "{net_name}"')
                    lines.extend(pins)
                    lines.append(f'    )')

        lines += [
            f'  )',
            f'',
            f'  (wiring',
            f'  )',
            f')',
        ]

        dsn_path.write_text('\n'.join(lines), encoding='utf-8')
        return True

    # ─────────────────────────────────────────
    # SES Import
    # ─────────────────────────────────────────
    def _import_ses(self, pcb: PCBManager, ses_path: Path) -> int:
        """SES(Specctra Session) 파일을 파싱해 트레이스를 PCB에 추가합니다."""
        content = ses_path.read_text(encoding='utf-8', errors='replace')
        count = 0

        # 간단한 wire 파싱
        import re
        wire_pattern = re.compile(
            r'\(wire\s+\(path\s+(\S+)\s+(\d+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)\s+([\d.\-]+)',
            re.IGNORECASE
        )
        for m in wire_pattern.finditer(content):
            layer_name = m.group(1)
            width_um = float(m.group(2))
            x1 = float(m.group(3)) / 1000  # um → mm
            y1 = float(m.group(4)) / 1000
            x2 = float(m.group(5)) / 1000
            y2 = float(m.group(6)) / 1000

            layer = "F.Cu" if "F" in layer_name.upper() else "B.Cu"
            from .pcb_board import Track
            import uuid as _uuid
            track = Track(
                x1=x1, y1=y1, x2=x2, y2=y2,
                width_mm=width_um / 1000,
                layer=layer,
            )
            pcb.tracks.append(track)
            count += 1

        return count

    # ─────────────────────────────────────────
    # Manhattan Fallback 라우터
    # ─────────────────────────────────────────
    def _manhattan_route(self, pcb: PCBManager) -> dict:
        """
        간단한 Manhattan(직각) 라우팅을 수행합니다.
        Freerouting 없이도 기본적인 배선을 생성합니다.

        알고리즘: 각 네트의 centroid를 구해 L자형 트레이스로 연결.
        """
        from .pcb_board import Track

        # 네트별 footprint 수집
        net_fps: dict[str, list] = {}
        for fp in pcb.footprints:
            for pad_num, net_name, dx, dy in fp.pads:
                if net_name:
                    net_fps.setdefault(net_name, []).append({
                        "ref": fp.reference,
                        "x": fp.x + dx,
                        "y": fp.y + dy,
                        "pad": pad_num
                    })

        routed = 0
        DEFAULT_WIDTH = 0.25

        for net_name, pads in net_fps.items():
            if len(pads) < 2:
                continue

            net_id = pcb._get_or_create_net(net_name)
            # Daisy-chain: 첫 번째 패드부터 순서대로 L자 연결
            for i in range(len(pads) - 1):
                p1 = pads[i]
                p2 = pads[i + 1]
                x1, y1 = p1["x"], p1["y"]
                x2, y2 = p2["x"], p2["y"]

                # L자 트레이스: 수평 → 수직
                if abs(x2 - x1) > 0.001:
                    t = Track(x1=x1, y1=y1, x2=x2, y2=y1,
                              width_mm=DEFAULT_WIDTH, layer="F.Cu",
                              net_name=net_name, net_id=net_id)
                    pcb.tracks.append(t)
                    routed += 1

                if abs(y2 - y1) > 0.001:
                    t = Track(x1=x2, y1=y1, x2=x2, y2=y2,
                              width_mm=DEFAULT_WIDTH, layer="F.Cu",
                              net_name=net_name, net_id=net_id)
                    pcb.tracks.append(t)
                    routed += 1

        return {
            "tracks_added": routed,
            "nets_routed": len(net_fps),
            "note": "Manhattan L자 라우팅. 더 나은 결과를 위해 Freerouting을 설치하세요."
        }

    # ─────────────────────────────────────────
    # Freerouting 다운로드
    # ─────────────────────────────────────────
    def _ensure_freerouting(self, jar_path: Optional[str],
                              project_dir: Path) -> Optional[Path]:
        """Freerouting.jar를 확인하거나 다운로드합니다."""
        if jar_path and Path(jar_path).exists():
            return Path(jar_path)

        # 일반적인 위치 탐색
        candidates = [
            Path.home() / "freerouting" / "freerouting.jar",
            Path("/usr/local/lib/freerouting.jar"),
            project_dir / "freerouting.jar",
        ]
        for c in candidates:
            if c.exists():
                return c

        # 자동 다운로드 시도
        download_path = project_dir / "freerouting.jar"
        try:
            print(f"Freerouting 다운로드 중: {FREEROUTING_RELEASE_URL}")
            urllib.request.urlretrieve(FREEROUTING_RELEASE_URL, str(download_path))
            if download_path.exists() and download_path.stat().st_size > 1000:
                return download_path
        except Exception as e:
            print(f"Freerouting 다운로드 실패: {e}")

        return None
