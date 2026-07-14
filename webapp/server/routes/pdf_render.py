"""API route to render a PDF page as a clean SVG (vector, zoomable)."""

import os

import fitz
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/pdf/render")
async def render_pdf_svg(
    path: str = Query(...),
    width: int = 2000,
    height: int = 1500,
    page: int = 0,
):
    """Render a PDF page as SVG — vector, zoomable, no pixelation.

    Extracts clean vector paths via PyMuPDF's get_drawings(), which gives
    the actual page content without the redundant overlapping entities
    that the DXF conversion produces.
    """
    if not os.path.exists(path):
        raise HTTPException(404, "PDF not found")

    try:
        doc = fitz.open(path)
    except Exception as e:
        raise HTTPException(400, f"Cannot open PDF: {e}")

    if page >= len(doc):
        doc.close()
        raise HTTPException(400, f"Page {page} out of range ({len(doc)} pages)")

    pg = doc[page]
    pw, ph = pg.rect.width, pg.rect.height  # PDF points

    # Build SVG from get_drawings() — clean vector paths
    paths = pg.get_drawings()
    svg_paths: list[str] = []
    texts: list[str] = []
    xs, ys = [0, pw], [0, ph]

    for path in paths:
        try:
            for item in path["items"]:
                cmd = item[0]
                if cmd == "l":  # line
                    p1, p2 = item[1], item[2]
                    xs += [p1[0], p2[0]]
                    ys += [p1[1], p2[1]]
                    svg_paths.append(f"M{p1[0]},{p1[1]}L{p2[0]},{p2[1]}")
                elif cmd == "re":  # rectangle
                    r = item[1]
                    x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
                    xs += [x0, x1]
                    ys += [y0, y1]
                    svg_paths.append(f"M{x0},{y0}L{x1},{y0}L{x1},{y1}L{x0},{y1}Z")
                elif cmd == "c":  # cubic bezier
                    pts = item[1:5]
                    for p in pts:
                        xs.append(p[0])
                        ys.append(p[1])
                    svg_paths.append(
                        f"M{pts[0][0]},{pts[0][1]}"
                        f"C{pts[1][0]},{pts[1][1]} "
                        f"{pts[2][0]},{pts[2][1]} "
                        f"{pts[3][0]},{pts[3][1]}"
                    )
                elif cmd == "qu":  # quadratic bezier
                    pts = item[1:4]
                    for p in pts:
                        xs.append(p[0])
                        ys.append(p[1])
                    svg_paths.append(
                        f"M{pts[0][0]},{pts[0][1]}"
                        f"Q{pts[1][0]},{pts[1][1]} "
                        f"{pts[2][0]},{pts[2][1]}"
                    )
        except Exception:
            pass

    # Add text
    text_blocks = pg.get_text("dict").get("blocks", [])
    for block in text_blocks:
        if block.get("type") == 0:
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    txt = span.get("text", "").strip()
                    if not txt:
                        continue
                    x, y = span.get("origin", (0, 0))
                    size = span.get("size", 10)
                    texts.append(
                        f'<text x="{x}" y="{y}" fill="#94a3b8" '
                        f'font-size="{size}" font-family="monospace">'
                        f"{_escape(txt[:80])}</text>"
                    )

    # SVG viewBox preserves PDF coordinates (Y-down, same as SVG)
    margin = (max(xs) - min(xs)) * 0.02 or 10
    vb_x, vb_y = min(xs) - margin, min(ys) - margin
    vb_w = max(xs) - min(xs) + 2 * margin
    vb_h = max(ys) - min(ys) + 2 * margin

    stroke_w = max(vb_w / 3000, 0.3)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{vb_x} {vb_y} {vb_w} {vb_h}" '
        f'width="{width}" height="{height}">\n'
        f'<rect width="100%" height="100%" fill="#1e293b"/>\n'
        f'<g fill="none" stroke="#64748b" stroke-width="{stroke_w}" '
        f'stroke-linecap="round" stroke-linejoin="round">\n'
        + "\n".join(f'<path d="{d}"/>' for d in svg_paths)
        + f"\n</g>\n"
        + "\n".join(texts)
        + "\n</svg>"
    )

    doc.close()
    return HTMLResponse(content=svg, media_type="image/svg+xml")


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
