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
    """A single 500 mm wide heating mat strip."""

    index: int = 0
    length_m: float = 0.0
    geometry: LineString | None = None  # noqa: F821
    start_point: tuple[float, float] = (0.0, 0.0)
    end_point: tuple[float, float] = (0.0, 0.0)
    clipped: bool = False  # True if clipped against heating polygon


@dataclass
class Room:
    """A detected room with all its properties and heating data."""

    name: str = "Unknown"
    polygon: Polygon | None = None
    centroid: tuple[float, float] = (0.0, 0.0)
    bounding_box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # minx, miny, maxx, maxy
    confidence: float = 0.0

    # Labels
    labels: list[RoomLabel] = field(default_factory=list)

    # Dimensions
    width: DimensionInfo = field(default_factory=lambda: DimensionInfo())
    length: DimensionInfo = field(default_factory=lambda: DimensionInfo())

    # Areas
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

    # Strips data
    strip_count: int = 0
    total_linear_m: float = 0.0
    coverage_pct: float = 0.0

    # Dimensions used
    measurements_used: str = ""

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
