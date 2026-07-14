"""API routes for DXF rendering — server-side SVG generation, no entity soup to browser."""

import io
import math
import os

import ezdxf
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

router = APIRouter()


@router.get("/dxf/layers")
async def get_layers(path: str = Query(...)):
    """Return all layer names with entity counts from a DXF file."""
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise HTTPException(400, f"Cannot read DXF: {e}")

    msp = doc.modelspace()
    layer_counts: dict[str, int] = {}
    for e in msp:
        try:
            layer = e.dxf.layer or "0"
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
        except Exception:
            pass

    layers = [
        {"name": name, "count": count}
        for name, count in sorted(layer_counts.items(), key=lambda x: -x[1])
    ]
    return {"layers": layers, "total": sum(lc.values())}


@router.get("/dxf/render")
async def render_dxf(
    path: str = Query(...),
    width: int = 2000,
    height: int = 1500,
    layers: str = "",  # comma-separated, empty = all
):
    """Render a DXF file to SVG. Returns SVG string directly — browser loads as image."""
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise HTTPException(400, f"Cannot read DXF: {e}")

    msp = doc.modelspace()
    layer_filter: set[str] | None = (
        {l.strip() for l in layers.split(",") if l.strip()} if layers else None
    )

    from src.cad.units import UnitDetector

    detector = UnitDetector(doc)
    detector.detect()

    # Collect all geometry and compute bounds (with dedup)
    seen_lines: set[str] = set()
    seen_texts: set[str] = set()
    lines: list[str] = []
    texts: list[str] = []
    xs, ys = [], []
    R = 5  # rounding precision (5 mm) — merges near-duplicate lines

    for e in msp:
        try:
            if layer_filter is not None:
                ent_layer = e.dxf.layer or "0"
                if ent_layer not in layer_filter:
                    continue
            t = e.dxftype()
            if t == "LINE":
                x1, y1, x2, y2 = e.dxf.start.x, e.dxf.start.y, e.dxf.end.x, e.dxf.end.y
                key = f"{round(x1, R)},{round(y1, R)}-{round(x2, R)},{round(y2, R)}"
                if key in seen_lines:
                    continue
                seen_lines.add(key)
                xs += [x1, x2]
                ys += [y1, y2]
                lines.append(f"M{x1},{-y1}L{x2},{-y2}")
            elif t == "LWPOLYLINE":
                pts = e.get_points("xy")
                key = "|".join(f"{round(p[0], R)},{round(p[1], R)}" for p in pts[:4])
                if key in seen_lines:
                    continue
                seen_lines.add(key)
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                d = "M" + "L".join(f"{p[0]},{-p[1]}" for p in pts)
                if e.closed:
                    d += "Z"
                lines.append(d)
            elif t == "CIRCLE":
                c = e.dxf.center
                r = e.dxf.radius
                xs += [c.x - r, c.x + r]
                ys += [c.y - r, c.y + r]
            elif t == "MTEXT":
                x, y, txt = e.dxf.insert.x, e.dxf.insert.y, e.dxf.text[:60]
                key = f"{round(x, R)},{round(y, R)}|{txt}"
                if key in seen_texts:
                    continue
                seen_texts.add(key)
                texts.append(
                    f'<text x="{x}" y="{-y}" fill="#64748b" '
                    f'font-size="{max(e.dxf.char_height or 3, 1)}" '
                    f'font-family="monospace">{_escape(txt)}</text>'
                )
        except Exception:
            pass

    if not xs:
        raise HTTPException(400, "No geometry found in DXF")

    # Negate Y bounds: DXF Y-up maps to SVG Y-down
    margin = (max(xs) - min(xs)) * 0.05 or 10
    xmin, xmax = min(xs) - margin, max(xs) + margin
    ymin_neg, ymax_neg = -max(ys) - margin, -min(ys) + margin
    vw, vh = xmax - xmin, ymax_neg - ymin_neg

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{xmin} {ymin_neg} {vw} {vh}" '
        f'width="{width}" height="{height}">\n'
        f'<rect width="100%" height="100%" fill="#1e293b"/>\n'
        f'<g fill="none" stroke="#475569" stroke-width="{max(vw / 3000, 0.3)}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n'
        f"{''.join(f'<path d="{d}" />' for d in lines)}\n"
        f"</g>\n"
        f"{''.join(texts)}\n"
        f"</svg>"
    )

    return HTMLResponse(content=svg, media_type="image/svg+xml")


@router.get("/dxf/bounds")
async def get_dxf_bounds(path: str = Query(...)):
    """Return only bounds + unit info (lightweight, no entity soup)."""
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise HTTPException(400, f"Cannot read DXF: {e}")

    msp = doc.modelspace()
    from src.cad.units import UnitDetector

    detector = UnitDetector(doc)
    unit = detector.detect()

    xs, ys = [], []
    for e in msp:
        try:
            t = e.dxftype()
            if t == "LINE":
                xs += [e.dxf.start.x, e.dxf.end.x]
                ys += [e.dxf.start.y, e.dxf.end.y]
            elif t == "LWPOLYLINE":
                for p in e.get_points("xy"):
                    xs.append(p[0])
                    ys.append(p[1])
            elif t == "CIRCLE":
                xs += [e.dxf.center.x - e.dxf.radius, e.dxf.center.x + e.dxf.radius]
                ys += [e.dxf.center.y - e.dxf.radius, e.dxf.center.y + e.dxf.radius]
        except Exception:
            pass

    if not xs:
        raise HTTPException(400, "No geometry")

    margin = (max(xs) - min(xs)) * 0.05 or 10
    return {
        "bounds": [
            min(xs) - margin,
            min(ys) - margin,
            max(xs) + margin,
            max(ys) + margin,
        ],
        "unit": unit.label,
        "unit_to_m": unit.to_metres,
    }


@router.get("/dxf/download")
async def download_dxf(path: str = Query(...)):
    """Serve the DXF file for download."""
    if not os.path.exists(path):
        raise HTTPException(404, "DXF file not found")
    return FileResponse(
        path,
        media_type="application/dxf",
        filename=os.path.basename(path),
        headers={
            "Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'
        },
    )


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
