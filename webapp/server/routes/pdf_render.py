"""API route to render a PDF page as a clean PNG image for the canvas background."""

import io
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
    page: int = 0,
):
    """Render a PDF page to PNG at the given pixel size.

    This is MUCH cleaner than converting PDF→DXF→SVG because PyMuPDF
    renders the page directly with proper anti-aliasing, no overlapping
    vector artifacts.
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
    pw, ph = pg.rect.width, pg.rect.height
    # Scale to fill requested dimensions while maintaining aspect ratio
    scale = min(width / pw, height / ph)
    matrix = fitz.Matrix(scale, scale)
    pix = pg.get_pixmap(matrix=matrix, alpha=False)
    img_bytes = pix.tobytes("png")
    doc.close()

    return Response(
        content=img_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "no-cache",
        },
    )
