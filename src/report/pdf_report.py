"""PDF report generator using ReportLab."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image, HRFlowable,
)

from src.utils.logging import get_logger
from src.models.rooms import Room

logger = get_logger("report.pdf")


class PDFReport:
    """Generates a formatted PDF report of the Warmset heating takeoff."""

    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _setup_styles(self) -> None:
        """Add custom paragraph styles."""
        self.styles.add(ParagraphStyle(
            name="ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            spaceAfter=6,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#2C3E50"),
        ))
        self.styles.add(ParagraphStyle(
            name="ReportSubtitle",
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=colors.HexColor("#7F8C8D"),
        ))
        self.styles.add(ParagraphStyle(
            name="SectionTitle",
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor("#2C3E50"),
        ))
        self.styles.add(ParagraphStyle(
            name="CellStyle",
            fontName="Helvetica",
            fontSize=8,
            leading=10,
        ))
        self.styles.add(ParagraphStyle(
            name="CellBold",
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
        ))

    def generate(self, rooms: list[Room], totals: dict, quality_report: dict, output_path: Path,
                 debug_image_paths: Optional[list[Path]] = None) -> Path:
        """Generate a formatted PDF report.

        Args:
            rooms: All processed rooms.
            totals: Project-wide totals.
            quality_report: DXF quality analysis results.
            output_path: Destination .pdf path.
            debug_image_paths: Optional list of debug image paths to include.

        Returns:
            Path to the written file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
        )

        elements = []

        # --- Title ---
        elements.append(Paragraph("Warmset Heating Takeoff Report", self.styles["ReportTitle"]))
        elements.append(Paragraph("Automated CAD Processing Engine", self.styles["ReportSubtitle"]))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#2C3E50")))
        elements.append(Spacer(1, 10))

        # --- Quality Summary ---
        elements.append(Paragraph("DXF Quality Analysis", self.styles["SectionTitle"]))
        quality_data = [
            ["Metric", "Value"],
            ["DXF Version", str(quality_report.get("dxf_version", "N/A"))],
            ["Drawing Units", str(quality_report.get("drawing_units", "N/A"))],
            ["Suitability Score", f"{quality_report.get('suitability_score', 0):.0f}%"],
            ["Reconstruction Confidence", f"{quality_report.get('reconstruction_confidence', 0):.0f}%"],
            ["Verdict", str(quality_report.get("verdict", "Unknown"))],
        ]
        quality_table = Table(quality_data, colWidths=[150, 250])
        quality_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8F9FA")]),
        ]))
        elements.append(quality_table)
        elements.append(Spacer(1, 12))

        # --- Totals Summary ---
        elements.append(Paragraph("Project Summary", self.styles["SectionTitle"]))
        total_data = [
            ["Metric", "Value"],
            ["Total Gross Area", f"{totals.get('total_gross_area_m2', 0):.2f} m²"],
            ["Total Excluded Area", f"{totals.get('total_excluded_area_m2', 0):.2f} m²"],
            ["Total Setback Area", f"{totals.get('total_setback_area_m2', 0):.2f} m²"],
            ["Total Net Heatable Area", f"{totals.get('total_net_heatable_area_m2', 0):.2f} m²"],
            ["Total Mat Area", f"{totals.get('total_mat_area_m2', 0):.2f} m²"],
            ["Total Linear Metres", f"{totals.get('total_linear_m', 0):.2f} m"],
            ["Total Strips", str(totals.get("total_strips", 0))],
            ["Number of Rooms", str(totals.get("room_count", 0))],
        ]
        total_table = Table(total_data, colWidths=[150, 250])
        total_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#27AE60")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#E8F8F5")]),
        ]))
        elements.append(total_table)
        elements.append(Spacer(1, 12))

        # --- Room Breakdown ---
        elements.append(Paragraph("Room-by-Room Breakdown", self.styles["SectionTitle"]))
        elements.append(Spacer(1, 6))

        # Table header
        headers = ["Room", "Gross (m²)", "Excluded (m²)", "Net (m²)", "Strips", "Linear (m)", "Mat (m²)", "Cov. (%)"]
        room_rows = [headers]
        for room in rooms:
            room_rows.append([
                room.name,
                f"{room.gross_area_m2:.2f}",
                f"{room.excluded_area_m2:.2f}",
                f"{room.net_heatable_area_m2:.2f}",
                str(room.strip_count),
                f"{room.total_linear_m:.1f}",
                f"{room.mat_area_m2:.2f}",
                f"{room.coverage_pct:.0f}%",
            ])

        # Add totals row
        room_rows.append([
            "TOTAL",
            f"{totals.get('total_gross_area_m2', 0):.2f}",
            f"{totals.get('total_excluded_area_m2', 0):.2f}",
            f"{totals.get('total_net_heatable_area_m2', 0):.2f}",
            str(totals.get("total_strips", 0)),
            f"{totals.get('total_linear_m', 0):.1f}",
            f"{totals.get('total_mat_area_m2', 0):.2f}",
            "",
        ])

        col_widths = [60, 50, 55, 50, 35, 50, 50, 40]
        room_table = Table(room_rows, colWidths=[w * mm for w in col_widths])
        room_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -2), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F8F9FA")]),
            # Totals row styling
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#D5F5E3")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("GRID", (0, -1), (-1, -1), 0.5, colors.grey),
        ]))
        elements.append(room_table)

        # --- Debug Images (if available) ---
        if debug_image_paths:
            elements.append(PageBreak())
            elements.append(Paragraph("Visualisations", self.styles["SectionTitle"]))
            elements.append(Spacer(1, 6))
            for img_path in debug_image_paths:
                if img_path.exists():
                    try:
                        elements.append(Paragraph(img_path.stem.replace("_", " ").title(), self.styles["SectionTitle"]))
                        elements.append(Image(str(img_path), width=460, height=320))
                        elements.append(Spacer(1, 8))
                    except Exception:
                        logger.warning("Could not embed image: %s", img_path)

        # Build PDF
        doc.build(elements)
        logger.info("PDF report written to %s", output_path)
        return output_path
