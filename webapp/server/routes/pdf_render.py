"""API route to render a PDF page as a high-res PNG for the canvas background."""

import os

import fitz
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter()


@router.get("/pdf/render")
async def render_pdf_page(
    path: str = Query(...),
    width: int = 2000,
    height: int = 1500,
    dpi: int = 300,
    page: int = 0,
):
    """Render a PDF page to PNG at the given DPI.

    Higher DPI = sharper when zoomed. Default 300 DPI gives ~3508×2480px
    for A3, which stays sharp at 2-3x zoom.
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
    # Render at requested DPI (72 DPI = 1 pt per pixel)
    # fitz Matrix(zoom, zoom) where zoom = dpi/72
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pix = pg.get_pixmap(matrix=matrix, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()

    return Response(
        content=img_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": "no-cache, max-age=3600",
        },
    )
