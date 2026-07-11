"""Room, exclusion, and heating-layout data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from shapely.geometry import Polygon, MultiPolygon


class MeasurementSource(Enum):
    """Indicates whether a measurement is explicit, calculated, or estimated."""

    EXPLICIT = auto()
    CALCULATED = auto()
    ESTIMATED = auto()


@dataclass
class DimensionInfo:
    """Stores one dimension with its source."""

    value_m: float = 0.0
    source: MeasurementSource = MeasurementSource.ESTIMATED
    label: Optional[str] = None

    def __str__(self) -> str:
        tag = self.source.name.lower()
        return f"{self.value_m:.3f}m [{tag}]"


@dataclass
class ConfidenceFactors:
    """Breakdown of measurable factors that contribute to room confidence.

    confidence = sum of all factors (capped at 1.0).
    """

    closed_polygon_found: float = 0.0  # +0.30
    room_label_matched: float = 0.0    # +0.20
    dimensions_verified: float = 0.0   # +0.20
    no_broken_walls: float = 0.0       # +0.15
    no_self_intersections: float = 0.0 # +0.10
    no_inferred_geometry: float = 0.0  # +0.05

    @property
    def total(self) -> float:
        return min(1.0, (
            self.closed_polygon_found
            + self.room_label_matched
            + self.dimensions_verified
            + self.no_broken_walls
            + self.no_self_intersections
            + self.no_inferred_geometry
        ))

    def to_dict(self) -> dict[str, float]:
        return {
            "closed_polygon_found": round(self.closed_polygon_found, 2),
            "room_label_matched": round(self.room_label_matched, 2),
            "dimensions_verified": round(self.dimensions_verified, 2),
            "no_broken_walls": round(self.no_broken_walls, 2),
            "no_self_intersections": round(self.no_self_intersections, 2),
            "no_inferred_geometry": round(self.no_inferred_geometry, 2),
            "total": round(self.total, 2),
        }


@dataclass
class RoomCalculation:
    """Traceable breakdown of a room's area calculation.

    Every value should be explainable from the CAD geometry.
    """

    gross_area_m2: float = 0.0
    exclusion_breakdown: list[dict] = field(default_factory=list)  # [{label, area_m2, reason}]
    total_excluded_m2: float = 0.0
    setback_distance_m: float = 0.0
    setback_area_m2: float = 0.0
    net_heatable_area_m2: float = 0.0
    mat_width_m: float = 0.5
    strip_count: int = 0
    strip_lengths_m: list[float] = field(default_factory=list)
    total_linear_m: float = 0.0
    mat_area_m2: float = 0.0
    coverage_pct: float = 0.0

    def to_text_block(self, room_name: str) -> str:
        """Return a human-readable breakdown suitable for CLI / PDF."""
        lines = [f"{room_name}", "─" * 40]
        lines.append(f"  Gross polygon:       {self.gross_area_m2:>8.2f} m²")

        if self.exclusion_breakdown:
            for exc in self.exclusion_breakdown:
                label = exc.get("reason") or exc.get("label") or "Exclusion"
                area = exc.get("area_m2", 0)
                lines.append(f"  Less {label:16s}  {area:>8.2f} m²")

        lines.append(f"  Total exclusions:    {self.total_excluded_m2:>8.2f} m²")
        lines.append(f"  Wall setback ({self.setback_distance_m*1000:.0f} mm):  {self.setback_area_m2:>8.2f} m²")
        lines.append("  " + "─" * 33)
        lines.append(f"  Net heatable area:   {self.net_heatable_area_m2:>8.2f} m²")
        lines.append("")
        lines.append(f"  {self.strip_count} strips × {self.mat_width_m*1000:.0f} mm wide")
        if self.strip_lengths_m:
            lengths_str = ", ".join(f"{l:.1f}" for l in self.strip_lengths_m[:8])
            if len(self.strip_lengths_m) > 8:
                lengths_str += f", ... (+{len(self.strip_lengths_m)-8} more)"
            lines.append(f"  Lengths:             {lengths_str} m")
        lines.append(f"  Total linear:        {self.total_linear_m:>8.1f} m")
        lines.append(f"  Mat area:            {self.mat_area_m2:>8.2f} m²")
        lines.append(f"  Coverage:            {self.coverage_pct:>7.1f}%")
        lines.append("")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "gross_area_m2": round(self.gross_area_m2, 3),
            "exclusion_breakdown": [
                {
                    "label": e.get("reason") or e.get("label", "Exclusion"),
                    "area_m2": round(e.get("area_m2", 0), 3),
                }
                for e in self.exclusion_breakdown
            ],
            "total_excluded_m2": round(self.total_excluded_m2, 3),
            "setback_distance_m": round(self.setback_distance_m, 3),
            "setback_area_m2": round(self.setback_area_m2, 3),
            "net_heatable_area_m2": round(self.net_heatable_area_m2, 3),
            "strip_count": self.strip_count,
            "strip_lengths_m": [round(l, 3) for l in self.strip_lengths_m],
            "total_linear_m": round(self.total_linear_m, 3),
            "mat_area_m2": round(self.mat_area_m2, 3),
            "coverage_pct": round(self.coverage_pct, 1),
        }


@dataclass
class RoomLabel:
    """A text label found near a room."""

    text: str = ""
    position: tuple[float, float] = (0.0, 0.0)
    confidence: float = 1.0
    distance_m: float = 0.0


@dataclass
class ExclusionArea:
    """An area that should be excluded from heating."""

    polygon: Polygon | None = None
    reason: str = ""
    source_type: str = ""  # e.g. "block", "polyline", "hatch", "layer"
    label: Optional[str] = None

    @property
    def area_m2(self) -> float:
        if self.polygon is None:
            return 0.0
        return self.polygon.area


@dataclass
class HeatingPolygon:
    """The installable heating area after setbacks and exclusions."""

    polygon: Polygon | MultiPolygon | None = None
    setback_applied: bool = False
    setback_distance_m: float = 0.0

    @property
    def area_m2(self) -> float:
        if self.polygon is None:
            return 0.0
        return self.polygon.area

    @property
    def is_valid(self) -> bool:
        if self.polygon is None:
            return False
        return self.polygon.is_valid and not self.polygon.is_empty


@dataclass
class WarmsetStrip:
    """A single Warmset heating mat strip (500 mm wide)."""

    index: int = 0
    length_m: float = 0.0
    geometry: LineString | None = None  # noqa: F821
    start_point: tuple[float, float] = (0.0, 0.0)
    end_point: tuple[float, float] = (0.0, 0.0)
    clipped: bool = False


@dataclass
class Room:
    """A detected room with all its properties and heating data."""

    name: str = "Unknown"
    polygon: Polygon | None = None
    centroid: tuple[float, float] = (0.0, 0.0)
    bounding_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    confidence: float = 0.0
    confidence_factors: Optional[ConfidenceFactors] = None

    # Labels
    labels: list[RoomLabel] = field(default_factory=list)

    # Dimensions
    width: DimensionInfo = field(default_factory=lambda: DimensionInfo())
    length: DimensionInfo = field(default_factory=lambda: DimensionInfo())

    # Areas (kept for backward compat, use calculation for detail)
    gross_area_m2: float = 0.0
    excluded_area_m2: float = 0.0
    setback_area_m2: float = 0.0
    net_heatable_area_m2: float = 0.0
    mat_area_m2: float = 0.0

    # Exclusions
    exclusions: list[ExclusionArea] = field(default_factory=list)

    # Heating
    heating_polygon: Optional[HeatingPolygon] = None
    strips: list[WarmsetStrip] = field(default_factory=list)
    strip_count: int = 0
    total_linear_m: float = 0.0
    coverage_pct: float = 0.0

    # Measurements
    measurements_used: str = ""

    # Traceable calculation breakdown
    calculation: Optional[RoomCalculation] = None

    @property
    def perimeter_m(self) -> float:
        if self.polygon is None:
            return 0.0
        return self.polygon.length


@dataclass
class CADDrawing:
    """Top-level container for a complete parsed CAD drawing."""

    filename: str = ""
    units: str = "unknown"
    entities: dict[str, list] = field(default_factory=dict)
    rooms: list[Room] = field(default_factory=list)
    quality_report: Optional[dict] = None

    @property
    def total_gross_area_m2(self) -> float:
        return sum(r.gross_area_m2 for r in self.rooms)

    @property
    def total_excluded_area_m2(self) -> float:
        return sum(r.excluded_area_m2 for r in self.rooms)

    @property
    def total_net_heatable_area_m2(self) -> float:
        return sum(r.net_heatable_area_m2 for r in self.rooms)

    @property
    def total_mat_area_m2(self) -> float:
        return sum(r.mat_area_m2 for r in self.rooms)

    @property
    def total_linear_m(self) -> float:
        return sum(r.total_linear_m for r in self.rooms)
