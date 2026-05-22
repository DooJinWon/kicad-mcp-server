"""
kicad_cli.py — KiCad CLI 래퍼

kicad-cli 명령줄 도구를 사용해 DRC, Gerber export 등을 수행합니다.
KiCad 7+ 에서 제공하는 공식 CLI를 활용합니다.
"""

from __future__ import annotations
import subprocess
import json
import re
import shutil
from pathlib import Path
from typing import Optional


class KiCadCLI:
    """kicad-cli 명령어 래퍼 클래스"""

    def __init__(self):
        self.cli_path = self._find_kicad_cli()

    def _find_kicad_cli(self) -> Optional[str]:
        """kicad-cli 실행 파일을 탐색합니다."""
        # 환경변수 PATH에서 탐색
        found = shutil.which("kicad-cli")
        if found:
            return found

        # macOS 기본 경로
        candidates = [
            "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/usr/bin/kicad-cli",
            "/usr/local/bin/kicad-cli",
        ]
        for c in candidates:
            if Path(c).exists():
                return c

        return None  # CLI 없음 → Python fallback 사용

    def is_available(self) -> bool:
        return self.cli_path is not None

    # ─────────────────────────────────────────
    # DRC 실행
    # ─────────────────────────────────────────
    def run_drc(self, pcb_path: Path) -> dict:
        """
        PCB DRC를 실행합니다.

        kicad-cli pcb drc --output {report} --format json {pcb_path}
        """
        pcb_path = Path(pcb_path)
        report_path = pcb_path.parent / "drc_report.json"

        if self.cli_path:
            cmd = [
                self.cli_path, "pcb", "drc",
                "--output", str(report_path),
                "--format", "json",
                "--units", "mm",
                "--severity-all",
                str(pcb_path),
            ]
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60
                )
                if report_path.exists():
                    return self._parse_drc_json(report_path)
                else:
                    return self._parse_drc_text(result.stdout + result.stderr)
            except subprocess.TimeoutExpired:
                return {"error": "DRC 타임아웃 (60초)", "violations": []}
            except Exception as e:
                return self._manual_drc(pcb_path)
        else:
            # CLI 없으면 파일 기반 분석
            return self._manual_drc(pcb_path)

    def _parse_drc_json(self, report_path: Path) -> dict:
        """DRC JSON 결과를 파싱합니다."""
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            violations = data.get("violations", [])
            unconnected = [v for v in violations
                          if v.get("type", "") == "unconnected_items"]
            errors = [v for v in violations
                     if v.get("severity", "") == "error"]
            return {
                "total": len(violations),
                "errors": len(errors),
                "unconnected": len(unconnected),
                "violations": [
                    {
                        "type": v.get("type", ""),
                        "severity": v.get("severity", ""),
                        "description": v.get("description", ""),
                    }
                    for v in violations[:20]  # 상위 20개만
                ],
                "report_path": str(report_path),
            }
        except Exception as e:
            return {"error": f"DRC 결과 파싱 실패: {e}"}

    def _parse_drc_text(self, text: str) -> dict:
        """텍스트 형식 DRC 결과를 파싱합니다."""
        violations = []
        for line in text.splitlines():
            if "[" in line and "]" in line:
                violations.append({"description": line.strip(), "severity": "error"})
        return {
            "total": len(violations),
            "violations": violations[:20],
            "raw": text[:1000],
        }

    def _manual_drc(self, pcb_path: Path) -> dict:
        """
        kicad-cli 없이 PCB 파일을 직접 분석해 기본적인 체크를 수행합니다.
        """
        if not pcb_path.exists():
            return {"error": "PCB 파일이 존재하지 않습니다.", "total": 0}

        content = pcb_path.read_text(encoding="utf-8", errors="replace")
        violations = []
        total = 0

        # 1. unconnected net 탐지 (net 0인 pad가 많은 경우)
        net_zero_pads = len(re.findall(r'\(net 0 ""\)', content))
        if net_zero_pads > 0:
            violations.append({
                "type": "unconnected_items",
                "severity": "error",
                "description": f"네트 미연결 패드가 {net_zero_pads}개 발견됨",
                "count": net_zero_pads
            })
            total += net_zero_pads

        # 2. via drill 크기 체크
        small_drills = re.findall(r'\(drill (0\.[01]\d+)\)', content)
        if small_drills:
            violations.append({
                "type": "drill_too_small",
                "severity": "warning",
                "description": f"드릴 크기가 작은 via {len(small_drills)}개 (권장: 0.3mm 이상)"
            })
            total += len(small_drills)

        # 3. 보드 외형 체크
        has_edge_cuts = "Edge.Cuts" in content
        if not has_edge_cuts:
            violations.append({
                "type": "board_edge_missing",
                "severity": "error",
                "description": "보드 외형(Edge.Cuts)이 없습니다."
            })
            total += 1

        # 4. 트레이스 수 확인
        track_count = content.count("(segment")
        via_count = content.count("(via ")
        fp_count = content.count("(footprint")

        return {
            "method": "manual_analysis",
            "total": total,
            "errors": sum(1 for v in violations if v.get("severity") == "error"),
            "warnings": sum(1 for v in violations if v.get("severity") == "warning"),
            "unconnected": net_zero_pads,
            "stats": {
                "footprints": fp_count,
                "tracks": track_count,
                "vias": via_count,
            },
            "violations": violations,
            "note": "kicad-cli를 설치하면 더 정확한 DRC 결과를 얻을 수 있습니다.",
        }

    # ─────────────────────────────────────────
    # Gerber Export
    # ─────────────────────────────────────────
    def export_gerber(self, pcb_path: Path, output_dir: Path) -> dict:
        """
        PCB를 Gerber 파일로 내보냅니다.

        kicad-cli pcb export gerbers --output {dir} {pcb_path}
        """
        pcb_path = Path(pcb_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.cli_path:
            # Gerber
            cmd_gerber = [
                self.cli_path, "pcb", "export", "gerbers",
                "--output", str(output_dir),
                "--layers", "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts",
                str(pcb_path),
            ]
            # Drill
            cmd_drill = [
                self.cli_path, "pcb", "export", "drill",
                "--output", str(output_dir),
                "--format", "excellon",
                str(pcb_path),
            ]
            try:
                subprocess.run(cmd_gerber, capture_output=True, timeout=60)
                subprocess.run(cmd_drill, capture_output=True, timeout=60)
                files = list(output_dir.glob("*"))
                return {
                    "output_dir": str(output_dir),
                    "files": [f.name for f in files],
                    "count": len(files),
                }
            except Exception as e:
                return {"error": str(e), "output_dir": str(output_dir)}
        else:
            # CLI 없이 더미 Gerber 파일 생성 (레이어 이름만)
            layers = {
                "F.Cu": "-F_Cu.gbr",
                "B.Cu": "-B_Cu.gbr",
                "F.SilkS": "-F_Silkscreen.gbr",
                "B.SilkS": "-B_Silkscreen.gbr",
                "F.Mask": "-F_Mask.gbr",
                "B.Mask": "-B_Mask.gbr",
                "Edge.Cuts": "-Edge_Cuts.gbr",
            }
            stem = pcb_path.stem
            created = []
            for layer, suffix in layers.items():
                fname = output_dir / (stem + suffix)
                fname.write_text(
                    f"%FSLAX25Y25*%\n%MOMM*%\n%LPD*%\nD02*\nM02*\n",
                    encoding="utf-8"
                )
                created.append(fname.name)

            return {
                "output_dir": str(output_dir),
                "files": created,
                "count": len(created),
                "note": "kicad-cli가 없어 플레이스홀더 Gerber를 생성했습니다.",
            }

    # ─────────────────────────────────────────
    # SVG Export (미리보기)
    # ─────────────────────────────────────────
    def export_svg(self, pcb_path: Path, output_dir: Path, layer: str = "F.Cu") -> dict:
        """PCB를 SVG로 내보냅니다 (미리보기용)."""
        pcb_path = Path(pcb_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.cli_path:
            svg_path = output_dir / f"{pcb_path.stem}_{layer.replace('.', '_')}.svg"
            cmd = [
                self.cli_path, "pcb", "export", "svg",
                "--output", str(svg_path),
                "--layers", layer,
                str(pcb_path),
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                return {"file": str(svg_path), "layer": layer}
            except Exception as e:
                return {"error": str(e)}
        else:
            return {"error": "kicad-cli가 필요합니다.", "layer": layer}
