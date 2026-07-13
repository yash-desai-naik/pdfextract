"""API routes for DXF rendering — server-side SVG generation, no entity soup to browser."""

import io
import math

import ezdxf
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/dxf/render")
async def render_dxf(path: str = Query(...), width: int = 2000, height: int = 1500):
    """Render a DXF file to SVG. Returns SVG string directly — browser loads as image."""
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise HTTPException(400, f"Cannot read DXF: {e}")

    msp = doc.modelspace()

    from src.cad.units import UnitDetector

    detector = UnitDetector(doc)
    detector.detect()

    # Collect all geometry and compute bounds
    lines: list[str] = []
    texts: list[str] = []
    xs, ys = [], []

    for e in msp:
        try:
            t = e.dxftype()
            if t == "LINE":
                xs += [e.dxf.start.x, e.dxf.end.x]
                ys += [e.dxf.start.y, e.dxf.end.y]
                lines.append(
                    f"M{e.dxf.start.x},{e.dxf.start.y}L{e.dxf.end.x},{e.dxf.end.y}"
                )
            elif t == "LWPOLYLINE":
                pts = e.get_points("xy")
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                d = "M" + "L".join(f"{p[0]},{p[1]}" for p in pts)
                if e.closed:
                    d += "Z"
                lines.append(d)
            elif t == "CIRCLE":
                c = e.dxf.center
                r = e.dxf.radius
                xs += [c.x - r, c.x + r]
                ys += [c.y - r, c.y + r]
            elif t == "MTEXT":
                texts.append(
                    f'<text x="{e.dxf.insert.x}" y="{e.dxf.insert.y}" '
                    f'fill="#64748b" font-size="{max(e.dxf.char_height or 3, 1)}" '
                    f'font-family="monospace">{_escape(e.dxf.text[:60])}</text>'
                )
        except Exception:
            pass

    if not xs:
        raise HTTPException(400, "No geometry found in DXF")

    margin = (max(xs) - min(xs)) * 0.05 or 10
    xmin, ymin = min(xs) - margin, min(ys) - margin
    xmax, ymax = max(xs) + margin, max(ys) + margin
    vw, vh = xmax - xmin, ymax - ymin

    # Transform all line coordinates to the SVG viewport
    transformed_lines = []
    for d in lines:
        # Parse path, translate coordinates
        # Simple approach: wrap in a <g> with transform
        transformed_lines.append(f'<path d="{d}" />')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{xmin} {ymin} {vw} {vh}" '
        f'width="{width}" height="{height}">\n'
        f'<rect width="100%" height="100%" fill="#1e293b"/>\n'
        f'<g fill="none" stroke="#475569" stroke-width="{max(vw / 3000, 0.5)}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n'
        f"{''.join(transformed_lines)}\n"
        f"</g>\n{''.join(texts)}\n"
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


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
