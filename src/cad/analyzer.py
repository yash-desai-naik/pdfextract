"""DXF Quality Analyzer — inspects a DXF and generates a health report."""

from __future__ import annotations

from typing import Optional

import ezdxf
from shapely.geometry import LineString, Polygon
from shapely import wkt

from src.utils.logging import get_logger

logger = get_logger("cad.analyzer")


class QualityReport:
    """Structured quality report for a DXF drawing."""

    def __init__(self):
        self.dxf_version: str = ""
        self.drawing_units: str = "unknown"
        self.line_count: int = 0
        self.lwpolyline_count: int = 0
        self.polyline_count: int = 0
        self.hatch_count: int = 0
        self.insert_count: int = 0
        self.text_count: int = 0
        self.mtext_count: int = 0
        self.dimension_count: int = 0
        self.arc_count: int = 0
        self.circle_count: int = 0
        self.spline_count: int = 0
        self.ellipse_count: int = 0
        self.closed_polygons: int = 0
        self.open_polylines: int = 0
        self.disconnected_segments: int = 0
        self.duplicate_entities: int = 0
        self.tiny_fragments: int = 0
        self.reconstruction_confidence: float = 0.0
        self.suitability_score: float = 0.0
        self.verdict: str = "Unknown"
        self.warnings: list[str] = []

    def to_dict(self) -> dict:
        return {
            "dxf_version": self.dxf_version,
            "drawing_units": self.drawing_units,
            "line_count": self.line_count,
            "lwpolyline_count": self.lwpolyline_count,
            "polyline_count": self.polyline_count,
            "hatch_count": self.hatch_count,
            "insert_count": self.insert_count,
            "text_count": self.text_count,
            "mtext_count": self.mtext_count,
            "dimension_count": self.dimension_count,
            "arc_count": self.arc_count,
            "circle_count": self.circle_count,
            "spline_count": self.spline_count,
            "ellipse_count": self.ellipse_count,
            "total_entities": (
                self.line_count + self.lwpolyline_count + self.polyline_count
                + self.hatch_count + self.insert_count + self.text_count
                + self.mtext_count + self.dimension_count + self.arc_count
                + self.circle_count + self.spline_count + self.ellipse_count
            ),
            "closed_polygons": self.closed_polygons,
            "open_polylines": self.open_polylines,
            "disconnected_segments": self.disconnected_segments,
            "duplicate_entities": self.duplicate_entities,
            "tiny_fragments": self.tiny_fragments,
            "reconstruction_confidence": round(self.reconstruction_confidence, 1),
            "suitability_score": round(self.suitability_score, 1),
            "verdict": self.verdict,
            "warnings": self.warnings,
        }


class CADQualityAnalyzer:
    """Analyse a DXF file and produce a quality report.

    The report helps developers understand the health of a converted
    DXF and decide whether automatic room detection is feasible.
    """

    def __init__(self, doc: ezdxf.document.Drawing):
        self.doc = doc
        self.msp = doc.modelspace()

    def analyze(self) -> QualityReport:
        """Run full analysis and return a QualityReport."""
        report = QualityReport()
        report.dxf_version = self.doc.dxfversion

        # Unit reading
        insunits = self.doc.header.get("$INSUNITS", 0)
        meas = self.doc.header.get("$MEASUREMENT", 1)
        unit_map = {0: "None", 1: "Inches", 2: "Feet", 4: "mm", 5: "cm", 6: "m"}
        report.drawing_units = unit_map.get(insunits, f"Code={insunits}")

        # Count entities
        entity_groups: dict[str, list] = {}
        for e in self.msp:
            dtype = e.dxftype()
            if dtype not in entity_groups:
                entity_groups[dtype] = []
            entity_groups[dtype].append(e)

        report.line_count = len(entity_groups.get("LINE", []))
        report.lwpolyline_count = len(entity_groups.get("LWPOLYLINE", []))
        report.polyline_count = len(entity_groups.get("POLYLINE", []))
        report.hatch_count = len(entity_groups.get("HATCH", []))
        report.insert_count = len(entity_groups.get("INSERT", []))
        report.text_count = len(entity_groups.get("TEXT", []))
        report.mtext_count = len(entity_groups.get("MTEXT", []))
        report.dimension_count = len(entity_groups.get("DIMENSION", []))
        report.arc_count = len(entity_groups.get("ARC", []))
        report.circle_count = len(entity_groups.get("CIRCLE", []))
        report.spline_count = len(entity_groups.get("SPLINE", []))
        report.ellipse_count = len(entity_groups.get("ELLIPSE", []))

        # Analyse polylines
        closed_polys = 0
        open_polys = 0
        for lwp in entity_groups.get("LWPOLYLINE", []):
            if lwp.closed and len(lwp.get_points()) >= 3:
                closed_polys += 1
            else:
                open_polys += 1
        for pl in entity_groups.get("POLYLINE", []):
            if pl.closed and len(list(pl.vertices)) >= 3:
                closed_polys += 1
            else:
                open_polys += 1
        report.closed_polygons = closed_polys
        report.open_polylines = open_polys

        # Detect disconnected segments (gaps between line endpoints)
        report.disconnected_segments = self._count_disconnected(entity_groups)

        # Detect duplicate entities
        report.duplicate_entities = self._count_duplicates(entity_groups)

        # Detect tiny fragments
        report.tiny_fragments = self._count_tiny_fragments(entity_groups)

        # Compute confidence and score
        report.reconstruction_confidence = self._compute_confidence(report)
        report.suitability_score = self._compute_suitability(report)
        report.verdict = self._generate_verdict(report)

        logger.info(
            "Quality analysis: %d entities, score=%.1f%% confidence=%.1f%%",
            report.to_dict()["total_entities"],
            report.suitability_score,
            report.reconstruction_confidence,
        )
        return report

    def _count_disconnected(self, groups: dict[str, list]) -> int:
        """Count endpoints that don't connect to any other endpoint within tolerance."""
        tolerance = 0.005  # 5 mm
        endpoints: list[tuple[float, float]] = []

        for ent in groups.get("LINE", []):
            endpoints.append((ent.dxf.start.x, ent.dxf.start.y))
            endpoints.append((ent.dxf.end.x, ent.dxf.end.y))

        for lwp in groups.get("LWPOLYLINE", []):
            pts = lwp.get_points("xy")
            for pt in pts:
                endpoints.append(pt)

        disconnected = 0
        for i, ep in enumerate(endpoints):
            connected = False
            for j, other in enumerate(endpoints):
                if i == j:
                    continue
                dist = ((ep[0] - other[0]) ** 2 + (ep[1] - other[1]) ** 2) ** 0.5
                if dist <= tolerance:
                    connected = True
                    break
            if not connected:
                disconnected += 1
        return disconnected

    def _count_duplicates(self, groups: dict[str, list]) -> int:
        """Count duplicate entities (same type and same coordinates)."""
        dupes = 0
        for dtype in ("LINE", "LWPOLYLINE"):
            entities = groups.get(dtype, [])
            seen: set[str] = set()
            for e in entities:
                sig = self._signature(e)
                if sig in seen:
                    dupes += 1
                else:
                    seen.add(sig)
        return dupes

    def _signature(self, entity) -> str:
        """Create a hashable signature for duplicate detection."""
        try:
            if entity.dxftype() == "LINE":
                return (
                    f"L:{entity.dxf.start.x:.4f},{entity.dxf.start.y:.4f}"
                    f"-{entity.dxf.end.x:.4f},{entity.dxf.end.y:.4f}"
                )
            elif entity.dxftype() == "LWPOLYLINE":
                pts = entity.get_points("xy")
                return f"LW:{pts}"
        except Exception:
            return ""

    def _count_tiny_fragments(self, groups: dict[str, list], min_length: float = 0.01) -> int:
        """Count fragments shorter than min_length (10 mm)."""
        count = 0
        for ent in groups.get("LINE", []):
            dx = ent.dxf.start.x - ent.dxf.end.x
            dy = ent.dxf.start.y - ent.dxf.end.y
            length = (dx * dx + dy * dy) ** 0.5
            if 0 < length < min_length:
                count += 1
        return count

    def _compute_confidence(self, report: QualityReport) -> float:
        """Estimate how confidently rooms can be reconstructed (0-100)."""
        score = 50.0  # Baseline

        # Bonus for closed polygons (strong room indicators)
        score += min(report.closed_polygons * 5, 25)

        # Penalty for disconnected segments
        total_ents = report.to_dict()["total_entities"]
        if total_ents > 0:
            disconn_ratio = report.disconnected_segments / max(total_ents, 1)
            score -= min(disconn_ratio * 20, 20)

        # Penalty for duplicates
        score -= min(report.duplicate_entities * 2, 10)

        # Penalty for tiny fragments
        score -= min(report.tiny_fragments * 2, 10)

        # Bonus for hatches (often outline rooms)
        score += min(report.hatch_count * 3, 15)

        # Bonus for dimensions (help validation)
        score += min(report.dimension_count * 2, 10)

        return max(0.0, min(100.0, score))

    def _compute_suitability(self, report: QualityReport) -> float:
        """Overall suitability for automatic takeoff (0-100)."""
        score = self._compute_confidence(report)

        # More weight on closed polygons
        total_ents = report.to_dict()["total_entities"]
        if total_ents > 0:
            poly_ratio = report.closed_polygons / max(total_ents, 1)
            score += min(poly_ratio * 20, 15)

        # Presence of text helps naming
        if report.text_count + report.mtext_count > 0:
            score += 5

        return max(0.0, min(100.0, score))

    def _generate_verdict(self, report: QualityReport) -> str:
        """Generate a human-readable verdict based on scores."""
        score = report.suitability_score
        if score >= 80:
            return "Ready for automatic room detection"
        elif score >= 60:
            return "Suitable with minor manual corrections"
        elif score >= 40:
            return "Requires topology reconstruction"
        else:
            return "Poor quality — manual tracing recommended"
