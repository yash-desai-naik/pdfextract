"""API routes for PDF → DXF conversion."""

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

logger = logging.getLogger("warmset.convert")
router = APIRouter()


@router.post("/convert")
async def convert_pdf(file: UploadFile = File(...)):
    """Upload a PDF, convert to DXF, return the DXF path."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")

    logger.info("Converting PDF: %s (%d bytes)", file.filename, file.size or 0)

    tmpdir = Path(tempfile.mkdtemp(prefix="warmset_"))
    pdf_path = tmpdir / "input.pdf"
    dxf_path = tmpdir / "output.dxf"

    content = await file.read()
    pdf_path.write_bytes(content)
    logger.info("Saved PDF to %s (%d bytes)", pdf_path, len(content))

    try:
        from src.cad.scale_resolver import ScaleResolver
        from src.converter import PDF2DXFConverter

        logger.info("Loading PDF...")
        conv = PDF2DXFConverter(str(pdf_path))
        conv.load_pdf()
        logger.info("PDF loaded: %d pages", len(conv.doc))

        # Resolve scale
        logger.info("Resolving scale...")
        page_text = conv.doc[0].get_text()
        scale = ScaleResolver().resolve_from_text(page_text)
        logger.info("Scale: 1:%s (%s)", scale.scale_ratio, scale.confidence)

        logger.info("Converting page 0 to DXF...")
        conv.convert(str(dxf_path), pages=[0], scale_result=scale)
        logger.info("DXF saved to %s", dxf_path)

        # Verify DXF has content
        import ezdxf

        verify_doc = ezdxf.readfile(str(dxf_path))
        msp = verify_doc.modelspace()
        entity_count = sum(1 for _ in msp)
        logger.info("DXF verification: %d entities", entity_count)

        return {
            "status": "ok",
            "dxf_path": str(dxf_path),
            "pdf_path": str(pdf_path),
            "filename": file.filename,
            "scale": scale.to_dict(),
            "entity_count": entity_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Conversion failed")
        raise HTTPException(500, f"Conversion failed: {e}")
