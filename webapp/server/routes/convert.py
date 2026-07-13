"""API routes for PDF → DXF conversion."""

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter()


@router.post("/convert")
async def convert_pdf(file: UploadFile = File(...)):
    """Upload a PDF, convert to DXF, return the DXF path."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")

    tmpdir = Path(tempfile.mkdtemp(prefix="warmset_"))
    pdf_path = tmpdir / "input.pdf"
    dxf_path = tmpdir / "output.dxf"

    content = await file.read()
    pdf_path.write_bytes(content)

    try:
        from src.cad.scale_resolver import ScaleResolver
        from src.converter import PDF2DXFConverter

        conv = PDF2DXFConverter(str(pdf_path))
        conv.load_pdf()

        # Resolve scale
        page_text = conv.doc[0].get_text()
        scale = ScaleResolver().resolve_from_text(page_text)
        conv.convert(str(dxf_path), pages=[0], scale_result=scale)

        return {
            "status": "ok",
            "dxf_path": str(dxf_path),
            "filename": file.filename,
            "scale": scale.to_dict(),
            "warnings": conv.warnings if hasattr(conv, "warnings") else [],
        }
    except Exception as e:
        raise HTTPException(500, f"Conversion failed: {e}")
