"""JSON report generator."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.logging import get_logger
from src.models.rooms import Room

logger = get_logger("report.json")


class JSONReport:
    """Generates a structured JSON report of the complete takeoff."""

    def generate(self, rooms: list[Room], quality_report: dict, totals: dict, output_path: Path) -> Path:
        """Write the full report as JSON.

        Args:
            rooms: All processed rooms.
            quality_report: DXF quality analysis report.
            totals: Project-wide totals dict.
            output_path: Destination file path.

        Returns:
            Path to the written file.
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "engine_version": "1.0.0",
            "quality_analysis": {
                "suitability_score": quality_report.get("suitability_score", 0),
                "reconstruction_confidence": quality_report.get("reconstruction_confidence", 0),
                "verdict": quality_report.get("verdict", "Unknown"),
                "drawing_units": quality_report.get("drawing_units", "unknown"),
                "dxf_version": quality_report.get("dxf_version", ""),
            },
            "totals": totals,
            "rooms": [
                {
                    "name": room.name,
                    "confidence": round(room.confidence, 2),
                    "confidence_factors": room.confidence_factors.to_dict() if room.confidence_factors else {},
                    "measurements_used": room.measurements_used,
                    "centroid": [round(c, 3) for c in room.centroid],
                    "bounding_box": [round(b, 3) for b in room.bounding_box],
                    "gross_area_m2": round(room.gross_area_m2, 3),
                    "perimeter_m": round(room.perimeter_m, 3),
                    "excluded_area_m2": round(room.excluded_area_m2, 3),
                    "setback_area_m2": round(room.setback_area_m2, 3),
                    "net_heatable_area_m2": round(room.net_heatable_area_m2, 3),
                    "strip_count": room.strip_count,
                    "total_linear_m": round(room.total_linear_m, 3),
                    "mat_area_m2": round(room.mat_area_m2, 3),
                    "coverage_pct": round(room.coverage_pct, 1),
                    "labels": [
                        {"text": lbl.text, "distance_m": round(lbl.distance_m, 3)}
                        for lbl in room.labels
                    ],
                    "exclusions": [
                        {
                            "reason": exc.reason,
                            "area_m2": round(exc.area_m2, 3),
                            "source_type": exc.source_type,
                        }
                        for exc in room.exclusions
                    ],
                    "strip_data": {
                        "count": room.strip_count,
                        "individual_lengths_m": [round(s.length_m, 3) for s in room.strips],
                    },
                    "calculation": room.calculation.to_dict() if room.calculation else {},
                }
                for room in rooms
            ],
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info("JSON report written to %s", output_path)
        return output_path
