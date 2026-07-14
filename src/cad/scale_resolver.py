"""Resolve drawing scale from PDF content — one authoritative factor per page.

Produces mm_per_pdf_point used by converter, tracer, and Streamlit UI.
Never falls back silently to "assume 1:1".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from src.utils.logging import get_logger

logger = get_logger("cad.scale_resolver")

# PDF point → mm: 1 pt = 25.4/72 mm
PDF_POINT_TO_MM = 25.4 / 72.0


@dataclass
class ScaleResult:
    """Structured scale detection result for one page."""

    scale_ratio: int = 1  # e.g. 100 for 1:100
    mm_per_pdf_point: float = PDF_POINT_TO_MM
    source: str = (
        "default"  # title_block_regex | dimension_crosscheck | manual | default
    )
    confidence: str = "low"  # high | medium | low
    raw_match: str = ""
    page: int = 0

    @property
    def mm_per_unit(self) -> float:
        """Return mm per drawing unit (PDF point)."""
        return self.mm_per_pdf_point

    @property
    def scale_denominator(self) -> int:
        """Return the denominator of the scale (e.g. 100 from 1:100)."""
        return self.scale_ratio

    def to_dict(self) -> dict:
        return {
            "scale_ratio": self.scale_ratio,
            "mm_per_pdf_point": self.mm_per_pdf_point,
            "source": self.source,
            "confidence": self.confidence,
            "raw_match": self.raw_match,
            "page": self.page,
        }


# Scale patterns: case-insensitive, tolerant of different whitespace and colon variants
SCALE_PATTERNS = [
    re.compile(r"scale\s*1\s*[:\uFF1A]\s*(\d+)", re.IGNORECASE),
    re.compile(r"scale\s*1\s*/\s*(\d+)", re.IGNORECASE),
    re.compile(r"1\s*[:\uFF1A]\s*(\d+)\s*@", re.IGNORECASE),
    re.compile(r"drawing\s+is\s+1\s*[:\uFF1A]\s*(\d+)", re.IGNORECASE),
    re.compile(r"scale\s*\\[\uFF1A]\s*1\s*/\s*(\d+)", re.IGNORECASE),
    re.compile(r"not\s+to\s+scale", re.IGNORECASE),  # negative match
    # Bare ratios: "1:50", "1 : 100" (no keyword prefix)
    re.compile(r"(?:^|\\s)1\s*[:：]\s*(\d+)(?:$|\\s)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"1\s*[:：]\s*(\d+)", re.IGNORECASE),
]


class ScaleResolver:
    """Detect and resolve the drawing scale from PDF page content.

    Priority:
        1. Title-block regex scan
        2. Optional dimension cross-check (validation)
        3. Manual calibration fallback
    """

    def __init__(self):
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def resolve_from_text(self, page_text: str, page: int = 0) -> ScaleResult:
        """Scan extracted page text for scale annotations.

        Args:
            page_text: Full text of the PDF page (from page.get_text()).
            page: 0-based page number.

        Returns:
            ScaleResult with the best detected scale or low-confidence default.
        """
        # Check for "NOT TO SCALE" first
        has_not_to_scale = bool(
            re.search(r"not\s+to\s+scale", page_text, re.IGNORECASE)
        )

        # Try all patterns
        matches = []
        for pattern in SCALE_PATTERNS:
            for match in pattern.finditer(page_text):
                if pattern.groups == 0:  # NOT TO SCALE has no capture group
                    continue
                try:
                    ratio = int(match.group(1))
                    matches.append((ratio, match.group(0)))
                except (ValueError, IndexError):
                    continue

        if not matches:
            result = ScaleResult(
                scale_ratio=1,
                mm_per_pdf_point=PDF_POINT_TO_MM,
                source="default",
                confidence="low",
                raw_match="",
                page=page,
            )
            if has_not_to_scale:
                self._warnings.append(
                    f"Page {page + 1}: marked 'NOT TO SCALE' — manual calibration required"
                )
            else:
                self._warnings.append(
                    f"Page {page + 1}: no scale annotation found — manual calibration required"
                )
            return result

        # Use the most common ratio (handles pages with multiple scale refs)
        ratio_counts: dict[int, int] = {}
        for ratio, _ in matches:
            ratio_counts[ratio] = ratio_counts.get(ratio, 0) + 1

        best_ratio = max(ratio_counts, key=ratio_counts.get)
        best_raw = next(m for m in matches if m[0] == best_ratio)[1]

        mm_per_pt = PDF_POINT_TO_MM * best_ratio

        result = ScaleResult(
            scale_ratio=best_ratio,
            mm_per_pdf_point=mm_per_pt,
            source="title_block_regex",
            confidence="high" if not has_not_to_scale else "medium",
            raw_match=best_raw,
            page=page,
        )

        known_ratios = {1, 5, 10, 20, 25, 50, 75, 100, 125, 200, 250, 500, 1000}
        if best_ratio not in known_ratios:
            self._warnings.append(
                f"Page {page + 1}: unusual scale ratio 1:{best_ratio} — verify manually"
            )
            result.confidence = "medium"

        logger.info(
            "Page %d: scale 1:%d detected (%s) from '%s'",
            page + 1,
            best_ratio,
            result.confidence,
            best_raw,
        )
        return result

    def crosscheck_with_dimension(
        self,
        scale: ScaleResult,
        known_length_mm: float,
        measured_length_raw: float,
    ) -> ScaleResult:
        """Validate scale against a known dimension.

        Args:
            scale: Current scale result.
            known_length_mm: The real-world length in mm (e.g. from a dimension string).
            measured_length_raw: The same length measured in raw PDF points.

        Returns:
            Updated ScaleResult with confidence raised if consistent.
        """
        if measured_length_raw <= 0:
            return scale

        inferred_ratio = round(
            known_length_mm / (measured_length_raw * PDF_POINT_TO_MM)
        )

        if (
            scale.confidence == "high"
            and abs(inferred_ratio - scale.scale_ratio) / max(scale.scale_ratio, 1)
            < 0.1
        ):
            scale.confidence = "high"
            scale.source = "dimension_crosscheck"
            return scale

        if abs(inferred_ratio - scale.scale_ratio) / max(scale.scale_ratio, 1) > 0.2:
            self._warnings.append(
                f"Scale mismatch: title block says 1:{scale.scale_ratio} "
                f"but dimension suggests 1:{inferred_ratio} — manual verification needed"
            )
            scale.confidence = "low"

        return scale

    def manual_calibrate(
        self,
        pixel_distance: float,
        real_distance_mm: float,
        display_scale: float,
    ) -> ScaleResult:
        """Derive scale from user-provided calibration (click two points, enter distance).

        Args:
            pixel_distance: Distance in pixels between two user-clicked points.
            real_distance_mm: The real-world distance the user entered, in mm.
            display_scale: The zoom/display scale used to render the page (pixels per PDF point).

        Returns:
            ScaleResult derived from calibration.
        """
        if pixel_distance <= 0:
            return ScaleResult(
                confidence="low", source="manual", raw_match="calibration failed"
            )

        # pixel_distance → PDF points → mm_per_point
        pdf_pt_distance = pixel_distance / display_scale
        mm_per_pt = real_distance_mm / pdf_pt_distance

        scale_ratio = round(mm_per_pt / PDF_POINT_TO_MM)

        result = ScaleResult(
            scale_ratio=max(1, scale_ratio),
            mm_per_pdf_point=mm_per_pt,
            source="manual",
            confidence="high",
            raw_match=f"User calibration: {real_distance_mm:.0f}mm over {pixel_distance:.0f}px",
        )
        logger.info(
            "Manual calibration: %.0f mm = %.1f px → mm_per_pt=%.4f → 1:%d",
            real_distance_mm,
            pixel_distance,
            mm_per_pt,
            result.scale_ratio,
        )
        return result

    @staticmethod
    def mm_to_metres(mm_per_pdf_point: float, value_in_pdf_points: float) -> float:
        """Convert a value from PDF points to metres using resolved scale."""
        return value_in_pdf_points * mm_per_pdf_point / 1000.0

    @staticmethod
    def points_to_mm(mm_per_pdf_point: float, value_in_pdf_points: float) -> float:
        """Convert PDF points to millimetres."""
        return value_in_pdf_points * mm_per_pdf_point
