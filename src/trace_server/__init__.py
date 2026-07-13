"""FastAPI trace server — serves DXF/SVG vector render + interactive trace tool.

Usage:
    python -m src.trace_server
    # Serves on http://localhost:8520
    # Streamlit embeds via iframe
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import ezdxf
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

app = FastAPI(title="Warmset Trace Tool")

templates_dir = str(Path(__file__).parent / "templates")
templates = Jinja2Templates(directory=templates_dir)


# ── In-memory store for loaded drawings ──────────────────────
_drawings: dict[str, dict] = {}  # id -> {dxf_path, entities, bounds, scale}


class DXFEntity(BaseModel):
    type: str  # LINE, LWPOLYLINE, CIRCLE, ARC, TEXT, MTEXT
    points: list[list[float]] = []  # [[x,y], ...]
    center: list[float] = [0, 0]
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    text: str = ""
    position: list[float] = [0, 0]
    height: float = 0.0
    layer: str = "0"


class TracedRoomData(BaseModel):
    name: str
    vertices: list[list[float]]
    exclusions: list[list[list[float]]] = []


class TraceResult(BaseModel):
    drawing_id: str
    rooms: list[TracedRoomData]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the interactive trace tool UI."""
    return templates.TemplateResponse("trace_tool.html", {"request": request})


@app.post("/api/load")
async def load_drawing(path: str = Query(...)):
    """Load a DXF file and return its entities as SVG-friendly data."""
    if not os.path.exists(path):
        raise HTTPException(404, f"File not found: {path}")

    from src.cad.units import UnitDetector

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    # Detect units
    detector = UnitDetector(doc)
    unit = detector.detect()
    unit_to_m = unit.to_metres

    # Collect entities
    entities = []
    xs, ys = [], []

    for e in msp:
        try:
            t = e.dxftype()
            if t == "LINE":
                pts = [[e.dxf.start.x, e.dxf.start.y], [e.dxf.end.x, e.dxf.end.y]]
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                entities.append(
                    DXFEntity(type="LINE", points=pts, layer=e.dxf.layer or "0")
                )
            elif t == "LWPOLYLINE":
                raw = e.get_points("xy")
                pts = [[p[0], p[1]] for p in raw]
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                entities.append(
                    DXFEntity(type="LWPOLYLINE", points=pts, layer=e.dxf.layer or "0")
                )
            elif t == "CIRCLE":
                c = e.dxf.center
                xs += [c.x - e.dxf.radius, c.x + e.dxf.radius]
                ys += [c.y - e.dxf.radius, c.y + e.dxf.radius]
                entities.append(
                    DXFEntity(
                        type="CIRCLE",
                        center=[c.x, c.y],
                        radius=e.dxf.radius,
                        layer=e.dxf.layer or "0",
                    )
                )
            elif t == "MTEXT":
                entities.append(
                    DXFEntity(
                        type="MTEXT",
                        position=[e.dxf.insert.x, e.dxf.insert.y],
                        text=e.dxf.text[:60],
                        height=e.dxf.char_height or 3,
                        layer=e.dxf.layer or "0",
                    )
                )
        except Exception:
            pass

    if not xs:
        raise HTTPException(400, "No geometry found in DXF")

    drawing_id = os.path.basename(path)  # simplified ID

    bounds = [min(xs), max(xs), min(ys), max(ys)]
    margin = (bounds[1] - bounds[0]) * 0.05 or 10
    bounds = [
        bounds[0] - margin,
        bounds[1] + margin,
        bounds[2] - margin,
        bounds[3] + margin,
    ]

    _drawings[drawing_id] = {
        "dxf_path": path,
        "entities": [e.model_dump() for e in entities],
        "bounds": bounds,
        "unit_to_m": unit_to_m,
        "scale": detector.detect().label if hasattr(detector, "detect") else "m",
    }

    dxf_doc = ezdxf.readfile(path)
    msp_ents = dxf_doc.modelspace()
    # Filter to only geometry entities
    geom_entities = []
    for e in msp_ents:
        try:
            t = e.dxftype()
            if t in ("LINE", "LWPOLYLINE", "CIRCLE", "ARC", "MTEXT"):
                geom_entities.append(e)
        except Exception:
            pass

    return JSONResponse(
        {
            "drawing_id": drawing_id,
            "bounds": bounds,
            "unit_to_m": unit_to_m,
            "unit_label": unit.label,
            "entity_count": len(entities),
            "entities": [e.model_dump() for e in entities],
        }
    )


@app.post("/api/save_trace")
async def save_trace(data: TraceResult):
    """Save traced room data from the client."""
    output_dir = Path(tempfile.mkdtemp(prefix="warmset_trace_"))
    trace_path = output_dir / f"{data.drawing_id}_traced.json"

    trace_data = {
        "drawing_id": data.drawing_id,
        "rooms": [r.model_dump() for r in data.rooms],
    }
    with open(trace_path, "w") as f:
        json.dump(trace_data, f, indent=2)

    return JSONResponse(
        {
            "status": "ok",
            "trace_path": str(trace_path),
            "room_count": len(data.rooms),
        }
    )


@app.post("/api/upload")
async def upload_dxf(file: UploadFile = File(...)):
    """Upload a DXF file to the server's temp storage."""
    upload_dir = Path(tempfile.mkdtemp(prefix="warmset_upload_"))
    ext = os.path.splitext(file.filename or "drawing.dxf")[1] or ".dxf"
    save_path = upload_dir / f"drawing{ext}"

    content = await file.read()
    with open(save_path, "wb") as f:
        f.write(content)

    return JSONResponse(
        {
            "status": "ok",
            "path": str(save_path),
            "filename": file.filename or "unknown",
            "size": len(content),
        }
    )


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def main():
    import uvicorn

    print("🔧 Warmset Trace Server: http://localhost:8520")
    uvicorn.run(app, host="0.0.0.0", port=8520, log_level="info")


if __name__ == "__main__":
    main()
