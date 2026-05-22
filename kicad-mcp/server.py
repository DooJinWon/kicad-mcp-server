#!/usr/bin/env python3
"""
KiCad MCP Server — zero-dependency implementation
MCP protocol (JSON-RPC 2.0 over stdio) implemented with standard library only.
No pip install required. Requires Python 3.8+
"""

import sys
import json
import asyncio
import traceback
from pathlib import Path

# 내부 모듈
sys.path.insert(0, str(Path(__file__).parent))
from tools.schematic import SchematicManager
from tools.pcb_board import PCBManager
from tools.router import Router
from tools.kicad_cli import KiCadCLI

# ─────────────────────────────────────────────
# 프로젝트 저장소
# ─────────────────────────────────────────────
_projects: dict = {}


def _get_project(name: str) -> dict:
    if name not in _projects:
        raise ValueError(f"프로젝트 '{name}'을 찾을 수 없습니다. create_project를 먼저 실행하세요.")
    return _projects[name]


# ─────────────────────────────────────────────
# 도구 정의 (JSON Schema)
# ─────────────────────────────────────────────
TOOLS = [
    {
        "name": "create_project",
        "description": "새 KiCad 프로젝트를 생성합니다. .kicad_pro, .kicad_sch, .kicad_pcb 파일을 만듭니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "프로젝트 이름"},
                "output_dir": {"type": "string", "description": "저장 디렉토리 (기본: ~/kicad-projects/)"},
                "board_width_mm": {"type": "number", "description": "보드 가로 (mm)", "default": 30},
                "board_height_mm": {"type": "number", "description": "보드 세로 (mm)", "default": 30},
            },
            "required": ["name"]
        }
    },
    {
        "name": "open_project",
        "description": "기존 KiCad 프로젝트를 열어 로드합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": ".kicad_pro 파일 경로 또는 디렉토리"},
            },
            "required": ["project_path"]
        }
    },
    {
        "name": "get_project_info",
        "description": "로드된 프로젝트 정보를 반환합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_name": {"type": "string"}},
            "required": ["project_name"]
        }
    },
    {
        "name": "add_symbol",
        "description": "회로도에 컴포넌트 심볼을 추가합니다 (예: Device:R, Device:C, Device:LED).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "lib_id": {"type": "string", "description": "심볼 ID (예: Device:R)"},
                "reference": {"type": "string", "description": "레퍼런스 (예: R1, U1)"},
                "value": {"type": "string", "description": "값 (예: 10k)"},
                "footprint": {"type": "string", "description": "Footprint"},
                "x": {"type": "number", "default": 0},
                "y": {"type": "number", "default": 0},
            },
            "required": ["project_name", "lib_id", "reference", "value"]
        }
    },
    {
        "name": "add_wire",
        "description": "회로도에서 두 좌표를 와이어로 연결합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "x1": {"type": "number"}, "y1": {"type": "number"},
                "x2": {"type": "number"}, "y2": {"type": "number"},
            },
            "required": ["project_name", "x1", "y1", "x2", "y2"]
        }
    },
    {
        "name": "add_power_symbol",
        "description": "회로도에 전원 심볼(VDD, GND, +3.3V 등)을 추가합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "power_name": {"type": "string", "description": "전원 이름 (VDD, GND, +3.3V 등)"},
                "x": {"type": "number"}, "y": {"type": "number"},
            },
            "required": ["project_name", "power_name", "x", "y"]
        }
    },
    {
        "name": "add_label",
        "description": "회로도에 네트 레이블을 추가합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "label": {"type": "string"},
                "x": {"type": "number"}, "y": {"type": "number"},
                "angle": {"type": "number", "default": 0},
            },
            "required": ["project_name", "label", "x", "y"]
        }
    },
    {
        "name": "generate_netlist",
        "description": "회로도에서 Netlist를 추출합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_name": {"type": "string"}},
            "required": ["project_name"]
        }
    },
    {
        "name": "create_schematic_from_bom",
        "description": "BOM(부품 목록)으로 회로도를 자동 생성합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "components": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "reference": {"type": "string"},
                            "lib_id": {"type": "string"},
                            "value": {"type": "string"},
                            "footprint": {"type": "string"},
                        },
                        "required": ["reference", "lib_id", "value"]
                    }
                }
            },
            "required": ["project_name", "components"]
        }
    },
    {
        "name": "place_component",
        "description": "PCB에서 특정 컴포넌트를 지정 위치에 배치합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "reference": {"type": "string"},
                "x_mm": {"type": "number"}, "y_mm": {"type": "number"},
                "rotation": {"type": "number", "default": 0},
                "layer": {"type": "string", "default": "F.Cu"},
            },
            "required": ["project_name", "reference", "x_mm", "y_mm"]
        }
    },
    {
        "name": "auto_place_components",
        "description": "PCB 컴포넌트를 기능 블록별로 자동 배치합니다 (MCU 중심, 전원/센서 분리).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "strategy": {
                    "type": "string",
                    "enum": ["grid", "cluster", "hierarchical"],
                    "default": "cluster"
                },
                "margin_mm": {"type": "number", "default": 1.0},
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "set_board_outline",
        "description": "PCB 보드 외형(Edge.Cuts)을 설정합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "shape": {"type": "string", "enum": ["rect", "circle", "rounded_rect"], "default": "rect"},
                "width_mm": {"type": "number"}, "height_mm": {"type": "number"},
                "corner_radius_mm": {"type": "number", "default": 1.0},
            },
            "required": ["project_name", "width_mm", "height_mm"]
        }
    },
    {
        "name": "add_copper_pour",
        "description": "PCB에 구리 채우기(Zone)를 추가합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "net_name": {"type": "string", "description": "예: GND, VDD"},
                "layer": {"type": "string", "default": "B.Cu"},
                "clearance_mm": {"type": "number", "default": 0.2},
            },
            "required": ["project_name", "net_name"]
        }
    },
    {
        "name": "auto_route",
        "description": "Freerouting으로 PCB 트레이스를 자동 라우팅합니다. Java/Freerouting이 없으면 Manhattan 폴백.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "freerouting_jar": {"type": "string", "description": "freerouting.jar 경로 (옵션)"},
                "passes": {"type": "integer", "default": 3},
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "add_trace",
        "description": "수동으로 트레이스를 추가합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "x1_mm": {"type": "number"}, "y1_mm": {"type": "number"},
                "x2_mm": {"type": "number"}, "y2_mm": {"type": "number"},
                "width_mm": {"type": "number", "default": 0.25},
                "layer": {"type": "string", "default": "F.Cu"},
                "net_name": {"type": "string"},
            },
            "required": ["project_name", "x1_mm", "y1_mm", "x2_mm", "y2_mm"]
        }
    },
    {
        "name": "run_drc",
        "description": "PCB DRC(Design Rule Check)를 실행합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_name": {"type": "string"}},
            "required": ["project_name"]
        }
    },
    {
        "name": "export_gerber",
        "description": "PCB를 Gerber 파일로 내보냅니다 (JLCPCB 제출용).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "output_dir": {"type": "string"},
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "export_bom",
        "description": "BOM을 CSV 또는 JSON으로 내보냅니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "format": {"type": "string", "enum": ["csv", "json"], "default": "csv"},
            },
            "required": ["project_name"]
        }
    },
    {
        "name": "save_project",
        "description": "현재 작업을 파일에 저장합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {"project_name": {"type": "string"}},
            "required": ["project_name"]
        }
    },
]


# ─────────────────────────────────────────────
# 도구 실행 핸들러
# ─────────────────────────────────────────────
async def dispatch(name: str, args: dict):
    cli = KiCadCLI()
    default_base = Path.home() / "kicad-projects"

    if name == "create_project":
        project_name = args["name"]
        base = Path(args.get("output_dir", str(default_base)))
        output_dir = base / project_name
        output_dir.mkdir(parents=True, exist_ok=True)

        sch = SchematicManager(output_dir / f"{project_name}.kicad_sch")
        pcb = PCBManager(
            output_dir / f"{project_name}.kicad_pcb",
            width_mm=args.get("board_width_mm", 30),
            height_mm=args.get("board_height_mm", 30),
        )
        sch.create_new()
        pcb.create_new()
        sch.save()
        pcb.save()

        pro_path = output_dir / f"{project_name}.kicad_pro"
        pro_path.write_text(json.dumps({
            "meta": {"filename": f"{project_name}.kicad_pro", "version": 1},
            "board": {}, "schematic": {}, "sheets": [], "text_variables": {}
        }, indent=2))

        _projects[project_name] = {"sch": sch, "pcb": pcb, "dir": output_dir}
        return {
            "success": True, "project": project_name, "path": str(output_dir),
            "files": [f"{project_name}.kicad_pro", f"{project_name}.kicad_sch", f"{project_name}.kicad_pcb"]
        }

    elif name == "open_project":
        proj_path = Path(args["project_path"])
        if proj_path.is_dir():
            pro_files = list(proj_path.glob("*.kicad_pro"))
            if not pro_files:
                raise FileNotFoundError(f"{proj_path}에 .kicad_pro 파일이 없습니다.")
            proj_path = pro_files[0]
        project_name = proj_path.stem
        project_dir = proj_path.parent

        sch = SchematicManager(project_dir / f"{project_name}.kicad_sch")
        pcb = PCBManager(project_dir / f"{project_name}.kicad_pcb")
        if sch.file_path.exists():
            sch.load()
        if pcb.file_path.exists():
            pcb.load()
        _projects[project_name] = {"sch": sch, "pcb": pcb, "dir": project_dir}
        return {"success": True, "project": project_name,
                "symbols": sch.get_symbol_count(), "footprints": pcb.get_footprint_count()}

    elif name == "get_project_info":
        proj = _get_project(args["project_name"])
        sch, pcb = proj["sch"], proj["pcb"]
        return {
            "project": args["project_name"], "dir": str(proj["dir"]),
            "schematic": {"symbols": sch.get_symbol_count(), "wires": sch.get_wire_count()},
            "pcb": {"footprints": pcb.get_footprint_count(), "tracks": pcb.get_track_count(),
                    "board_size_mm": pcb.get_board_size()},
        }

    elif name == "add_symbol":
        proj = _get_project(args["project_name"])
        return proj["sch"].add_symbol(
            args["lib_id"], args["reference"], args["value"],
            args.get("footprint", ""), args.get("x", 0), args.get("y", 0)
        )

    elif name == "add_wire":
        proj = _get_project(args["project_name"])
        proj["sch"].add_wire(args["x1"], args["y1"], args["x2"], args["y2"])
        return {"success": True}

    elif name == "add_power_symbol":
        proj = _get_project(args["project_name"])
        return proj["sch"].add_power_symbol(args["power_name"], args["x"], args["y"])

    elif name == "add_label":
        proj = _get_project(args["project_name"])
        proj["sch"].add_label(args["label"], args["x"], args["y"], args.get("angle", 0))
        return {"success": True, "label": args["label"]}

    elif name == "generate_netlist":
        proj = _get_project(args["project_name"])
        nl = proj["sch"].generate_netlist()
        return {"success": True, "components": len(nl["components"]),
                "nets": len(nl["nets"]), "netlist": nl}

    elif name == "create_schematic_from_bom":
        proj = _get_project(args["project_name"])
        placed = proj["sch"].auto_place_bom(args["components"])
        proj["sch"].save()
        return {"success": True, "placed_count": placed, "total": len(args["components"])}

    elif name == "place_component":
        proj = _get_project(args["project_name"])
        return proj["pcb"].place_component(
            args["reference"], args["x_mm"], args["y_mm"],
            args.get("rotation", 0), args.get("layer", "F.Cu")
        )

    elif name == "auto_place_components":
        proj = _get_project(args["project_name"])
        netlist = proj["sch"].generate_netlist()
        result = proj["pcb"].auto_place(
            netlist, strategy=args.get("strategy", "cluster"),
            margin_mm=args.get("margin_mm", 1.0)
        )
        proj["pcb"].save()
        return {"success": True, **result}

    elif name == "set_board_outline":
        proj = _get_project(args["project_name"])
        proj["pcb"].set_board_outline(
            args.get("shape", "rect"), args["width_mm"], args["height_mm"],
            args.get("corner_radius_mm", 1.0)
        )
        proj["pcb"].save()
        return {"success": True, "shape": args.get("shape", "rect"),
                "size_mm": [args["width_mm"], args["height_mm"]]}

    elif name == "add_copper_pour":
        proj = _get_project(args["project_name"])
        proj["pcb"].add_copper_pour(
            args["net_name"], args.get("layer", "B.Cu"), args.get("clearance_mm", 0.2)
        )
        proj["pcb"].save()
        return {"success": True, "zone": args["net_name"]}

    elif name == "auto_route":
        proj = _get_project(args["project_name"])
        router = Router()
        result = await router.freeroute(
            proj["pcb"],
            freerouting_jar=args.get("freerouting_jar"),
            passes=args.get("passes", 3)
        )
        return {"success": True, **result}

    elif name == "add_trace":
        proj = _get_project(args["project_name"])
        proj["pcb"].add_trace(
            args["x1_mm"], args["y1_mm"], args["x2_mm"], args["y2_mm"],
            width_mm=args.get("width_mm", 0.25),
            layer=args.get("layer", "F.Cu"),
            net_name=args.get("net_name", "")
        )
        proj["pcb"].save()
        return {"success": True}

    elif name == "run_drc":
        proj = _get_project(args["project_name"])
        proj["pcb"].save()
        return cli.run_drc(proj["pcb"].file_path)

    elif name == "export_gerber":
        proj = _get_project(args["project_name"])
        proj["pcb"].save()
        out = Path(args.get("output_dir", str(proj["dir"] / "gerber")))
        return cli.export_gerber(proj["pcb"].file_path, out)

    elif name == "export_bom":
        proj = _get_project(args["project_name"])
        return proj["sch"].export_bom(args.get("format", "csv"), proj["dir"])

    elif name == "save_project":
        proj = _get_project(args["project_name"])
        proj["sch"].save()
        proj["pcb"].save()
        return {"success": True,
                "saved": [str(proj["sch"].file_path), str(proj["pcb"].file_path)]}

    else:
        raise ValueError(f"알 수 없는 도구: {name}")


# ─────────────────────────────────────────────
# MCP JSON-RPC 2.0 (stdio, 표준 라이브러리만 사용)
# ─────────────────────────────────────────────
def send(obj: dict):
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def handle_request(req: dict):
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    try:
        if method == "initialize":
            send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "kicad-mcp", "version": "1.0.0"}
                }
            })

        elif method in ("notifications/initialized", "notifications/cancelled"):
            pass  # 알림은 응답 불필요

        elif method == "tools/list":
            send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"tools": TOOLS}
            })

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = await dispatch(tool_name, arguments)
                send({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text",
                                     "text": json.dumps(result, ensure_ascii=False, indent=2)}]
                    }
                })
            except Exception as e:
                send({
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {
                        "content": [{"type": "text",
                                     "text": json.dumps({"success": False, "error": str(e),
                                                         "tool": tool_name}, ensure_ascii=False)}],
                        "isError": True
                    }
                })

        elif method == "ping":
            send({"jsonrpc": "2.0", "id": req_id, "result": {}})

        else:
            if req_id is not None:  # 알림은 id가 없음
                send(make_error(req_id, -32601, f"Method not found: {method}"))

    except Exception as e:
        if req_id is not None:
            send(make_error(req_id, -32603, f"Internal error: {e}"))


async def main():
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    while True:
        try:
            line = await reader.readline()
            if not line:
                break
            line = line.decode("utf-8").strip()
            if not line:
                continue
            req = json.loads(line)
            await handle_request(req)
        except json.JSONDecodeError as e:
            send(make_error(None, -32700, f"Parse error: {e}"))
        except Exception as e:
            send(make_error(None, -32603, f"Internal error: {e}"))


if __name__ == "__main__":
    asyncio.run(main())
