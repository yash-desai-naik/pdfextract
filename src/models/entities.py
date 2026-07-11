"""Typed dataclass models for all DXF entities extracted from a CAD drawing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

from shapely.geometry import Point as ShapelyPoint, Polygon, MultiPolygon, LineString, MultiLineString


class EntityType(Enum):
    """Enumeration of all supported DXF entity types."""

    LINE = auto()
    LWPOLYLINE = auto()
    POLYLINE = auto()
    ARC = auto()
    CIRCLE = auto()
    ELLIPSE = auto()
    SPLINE = auto()
    HATCH = auto()
    TEXT = auto()
    MTEXT = auto()
    DIMENSION = auto()
    INSERT = auto()
    BLOCK = auto()
    ATTRIB = auto()


@dataclass
class CADEntity:
    """Base class for all CAD entities.

    Every entity carries its original DXF handle, layer, and
    the entity type for downstream dispatch.
    """

    dxf_handle: str
    layer: str
    entity_type: EntityType
    linetype: Optional[str] = None
    color: Optional[int] = None
    lineweight: Optional[int] = None

    @property
    def shapely_geometry(self) -> Optional[ShapelyPoint | Polygon | MultiPolygon | LineString | MultiLineString]:
        """Return a Shapely representation of this entity, if applicable."""
        return None


@dataclass
class CADLine(CADEntity):
    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)

    @property
    def length(self) -> float:
        dx = self.end[0] - self.start[0]
        dy = self.end[1] - self.start[1]
        return (dx * dx + dy * dy) ** 0.5

    @property
    def shapely_geometry(self) -> LineString:
        return LineString([self.start, self.end])


@dataclass
class CADLWPolyline(CADEntity):
    """A lightweight polyline with optional width and bulge data."""

    points: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False
    bulges: list[float] = field(default_factory=list)
    widths: list[tuple[float, float]] = field(default_factory=list)

    @property
    def shapely_geometry(self) -> LineString | Polygon:
        points = self.points
        if len(points) >= 3:
            is_effectively_closed = self.closed or self._check_closed(points)
            if is_effectively_closed:
                return Polygon(points)
        return LineString(points)

    @staticmethod
    def _check_closed(points: list[tuple[float, float]]) -> bool:
        if not points or len(points) < 3:
            return False
        first = points[0]
        last = points[-1]
        return (abs(first[0] - last[0]) < 1e-9 and abs(first[1] - last[1]) < 1e-9)


@dataclass
class CADPolyline(CADEntity):
    """A heavy polyline."""

    points: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False

    @property
    def shapely_geometry(self) -> LineString | Polygon:
        points = self.points
        if len(points) >= 3:
            first = points[0]
            last = points[-1]
            is_effectively_closed = (
                self.closed
                or (abs(first[0] - last[0]) < 1e-9 and abs(first[1] - last[1]) < 1e-9)
            )
            if is_effectively_closed:
                return Polygon(points)
        return LineString(points)


@dataclass
class CADArc(CADEntity):
    center: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    start_angle: float = 0.0
    end_angle: float = 0.0
    extrusion: tuple[float, float, float] = (0.0, 0.0, 1.0)

    @property
    def shapely_geometry(self) -> Optional[LineString]:
        """Approximate arc as a line string with 32 segments."""
        import math

        if self.radius <= 0:
            return None
        steps = 32
        sweep = self.end_angle - self.start_angle
        if sweep <= 0:
            sweep += 2 * math.pi
        points = []
        for i in range(steps + 1):
            angle = self.start_angle + sweep * i / steps
            x = self.center[0] + self.radius * math.cos(angle)
            y = self.center[1] + self.radius * math.sin(angle)
            points.append((x, y))
        return LineString(points)


@dataclass
class CADCircle(CADEntity):
    center: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    extrusion: tuple[float, float, float] = (0.0, 0.0, 1.0)

    @property
    def shapely_geometry(self) -> Optional[Polygon]:
        if self.radius <= 0:
            return None
        return self.center_point.buffer(self.radius, quad_segs=32)

    @property
    def center_point(self) -> ShapelyPoint:
        return ShapelyPoint(self.center)


@dataclass
class CDAEllipse(CADEntity):
    center: tuple[float, float] = (0.0, 0.0)
    major_axis: tuple[float, float] = (1.0, 0.0)
    ratio: float = 1.0
    start_param: float = 0.0
    end_param: float = 2 * 3.141592653589793
    extrusion: tuple[float, float, float] = (0.0, 0.0, 1.0)

    @property
    def shapely_geometry(self) -> Optional[Polygon | LineString]:
        from shapely import affinity
        import math

        if self.ratio <= 0:
            return None
        a = (self.major_axis[0] ** 2 + self.major_axis[1] ** 2) ** 0.5
        b = a * self.ratio
        if a <= 0 or b <= 0:
            return None
        angle = math.atan2(self.major_axis[1], self.major_axis[0])
        # Build a circle and scale + rotate
        circle = ShapelyPoint(0, 0).buffer(1.0, quad_segs=32)
        ellipse = affinity.scale(circle, a, b)
        ellipse = affinity.rotate(ellipse, angle, origin=(0, 0), use_radians=True)
        ellipse = affinity.translate(ellipse, self.center[0], self.center[1])

        is_full = abs(self.end_param - self.start_param) >= 2 * math.pi - 1e-9
        if is_full:
            return ellipse
        return None  # Partial ellipses not approximated


@dataclass
class CADSpline(CADEntity):
    control_points: list[tuple[float, float, float]] = field(default_factory=list)
    fit_points: list[tuple[float, float, float]] = field(default_factory=list)
    degree: int = 3
    closed: bool = False
    knots: list[float] = field(default_factory=list)

    @property
    def shapely_geometry(self) -> Optional[LineString | Polygon]:
        pts = [(p[0], p[1]) for p in (self.fit_points if self.fit_points else self.control_points)]
        if len(pts) < 2:
            return None
        if self.closed and len(pts) >= 3:
            return Polygon(pts)
        return LineString(pts)


@dataclass
class CADHatch(CADEntity):
    """A hatch with its boundary paths."""

    boundary_paths: list[list[tuple[float, float]]] = field(default_factory=list)
    closed: bool = True
    solid_fill: bool = False
    pattern_name: Optional[str] = None

    @property
    def shapely_geometry(self) -> Optional[Polygon | MultiPolygon]:
        polygons = []
        for path in self.boundary_paths:
            if len(path) >= 3:
                polygons.append(Polygon(path))
        if not polygons:
            return None
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)


@dataclass
class CADText(CADEntity):
    content: str = ""
    position: tuple[float, float] = (0.0, 0.0)
    height: float = 2.5
    rotation: float = 0.0
    width_factor: float = 1.0

    @property
    def shapely_geometry(self) -> ShapelyPoint:
        return ShapelyPoint(self.position)


@dataclass
class CADMText(CADEntity):
    content: str = ""
    position: tuple[float, float] = (0.0, 0.0)
    char_height: float = 2.5
    rotation: float = 0.0
    width: Optional[float] = None

    @property
    def shapely_geometry(self) -> ShapelyPoint:
        return ShapelyPoint(self.position)


@dataclass
class CADDimension(CADEntity):
    """Represents a DIMENSION entity."""

    dim_type: int = 0
    dim_text: Optional[str] = None
    measurement: Optional[float] = None
    dim_line_anchor: tuple[float, float] = (0.0, 0.0)
    text_position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    linear_factor: float = 1.0

    @property
    def shapely_geometry(self) -> ShapelyPoint:
        return ShapelyPoint(self.text_position)


@dataclass
class CADInsert(CADEntity):
    """An INSERT (block reference)."""

    block_name: str = ""
    position: tuple[float, float] = (0.0, 0.0)
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    attribs: list[CADAttrib] = field(default_factory=list)
    nested_entities: list[CADEntity] = field(default_factory=list)

    @property
    def shapely_geometry(self) -> Optional[Polygon | MultiPolygon]:
        """Return bounding box as polygon for exclusion detection."""
        if not self.nested_entities:
            return None
        from shapely import MultiPoint

        all_points = []
        for ent in self.nested_entities:
            g = ent.shapely_geometry
            if g is not None:
                all_points.extend(list(g.coords) if hasattr(g, "coords") else [])
        if len(all_points) < 3:
            return None
        return MultiPoint(all_points).convex_hull


@dataclass
class CADBlock(CADEntity):
    """A BLOCK definition (not a reference)."""

    block_name: str = ""
    entities: list[CADEntity] = field(default_factory=list)
    base_point: tuple[float, float] = (0.0, 0.0)


@dataclass
class CADAttrib(CADEntity):
    content: str = ""
    position: tuple[float, float] = (0.0, 0.0)
    height: float = 2.5
    tag: str = ""
    rotation: float = 0.0

    @property
    def shapely_geometry(self) -> ShapelyPoint:
        return ShapelyPoint(self.position)
