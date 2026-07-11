"""Detect areas that should be excluded from heating.

Detects:
    - Kitchen cabinetry / islands
    - Built-in wardrobes (BIR, WIR)
    - Vanities
    - Baths
    - Permanent appliances
    - Built-in storage
    - Fixed joinery

These may appear as blocks, closed polylines, hatches, or specific layers.
"""

from __future__ import annotations

from typing import Optional

from shapely.geometry import Point, Polygon, MultiPolygon, LineString
from shapely import set_precision

from src.models.entities import EntityType, CADInsert, CADHatch, CADLWPolyline, CADPolyline, CADText, CADMText
from src.models.rooms import Room, ExclusionArea
from src.geometry.spatial import SpatialIndex
from src.utils.logging import get_logger
from src.utils.config import get_settings

logger = get_logger("heating.exclusions")


class ExclusionDetector:
    """Detect exclusion areas within rooms.

    Strategy:
        1. Find all closed polylines and hatches inside rooms.
        2. Identify blocks that represent cabinetry/joinery.
        3. Use text labels to classify exclusion type.
        4. Buffer exclusions by a small margin for installation tolerance.
    """

    def __init__(self):
        settings = get_settings()
        self.exclusion_buffer = settings.detection.exclusion_buffer_m
        self.hatch_as_exclusion = settings.detection.hatch_as_exclusion
        self.exclusion_keywords = [k.upper() for k in settings.detection.exclusion_keywords]
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def detect_all(
        self,
        rooms: list[Room],
        entities: dict[EntityType, list],
    ) -> list[Room]:
        """Run all exclusion detection strategies on every room.

        Args:
            rooms: List of detected rooms.
            entities: The parsed CAD entities.

        Returns:
            Rooms with exclusions populated.
        """
        # Pre-build candidate exclusion geometries
        candidates: list[tuple[Polygon, str, str]] = []

        # 1. Hatches (SOLID filled → often represent cabinetry)
        if self.hatch_as_exclusion:
            for hatch in entities.get(EntityType.HATCH, []):
                g = hatch.shapely_geometry
                if g is not None and not g.is_empty and g.area > 0.01:
                    candidates.append((g, "hatch", hatch.pattern_name or "solid"))

        # 2. Closed polylines (small interior polygons)
        for lwp in entities.get(EntityType.LWPOLYLINE, []):
            g = lwp.shapely_geometry
            if isinstance(g, Polygon) and g.area > 0.01 and g.area < 10.0:
                candidates.append((g, "polyline", ""))

        for pl in entities.get(EntityType.POLYLINE, []):
            g = pl.shapely_geometry
            if isinstance(g, Polygon) and g.area > 0.01 and g.area < 10.0:
                candidates.append((g, "polyline", ""))

        # 3. Insert blocks
        for ins in entities.get(EntityType.INSERT, []):
            g = ins.shapely_geometry
            if g is not None and not g.is_empty and g.area > 0.01 and g.area < 10.0:
                label = self._classify_block(ins)
                candidates.append((g, "block", label))

        # 4. Text labels that indicate exclusions
        exclusion_label_positions = self._find_exclusion_labels(entities)

        # Now match candidates to rooms
        for room in rooms:
            if room.polygon is None:
                continue

            room_poly = room.polygon
            for poly, source_type, label in candidates:
                if not poly.is_valid:
                    poly = poly.buffer(0)

                # Check if candidate is within the room
                if room_poly.contains(poly) or room_poly.intersection(poly).area > poly.area * 0.5:
                    # Buffer the exclusion slightly
                    buffered = poly.buffer(self.exclusion_buffer)
                    if buffered is not None and not buffered.is_empty:
                        # Clip to room boundary
                        clipped = buffered.intersection(room_poly)
                        if clipped is not None and not clipped.is_empty and clipped.area > 0.01:
                            reason = label or f"Unknown ({source_type})"
                            room.exclusions.append(ExclusionArea(
                                polygon=clipped if isinstance(clipped, (Polygon, MultiPolygon))
                                else Polygon() if isinstance(clipped, LineString) else None,
                                reason=reason,
                                source_type=source_type,
                                label=label or None,
                            ))

            # Also add exclusion labels inside the room
            for pos, label in exclusion_label_positions:
                point = Point(pos)
                if room_poly.contains(point):
                    # Create small exclusion bubble around label
                    exclusion_poly = point.buffer(0.3).intersection(room_poly)
                    if exclusion_poly is not None and not exclusion_poly.is_empty and exclusion_poly.area > 0.01:
                        room.exclusions.append(ExclusionArea(
                            polygon=exclusion_poly if isinstance(exclusion_poly, (Polygon, MultiPolygon)) else None,
                            reason=label,
                            source_type="label",
                        ))

            # Merge overlapping exclusions
            self._merge_exclusions(room)

            # Calculate total excluded area
            room.excluded_area_m2 = sum(e.area_m2 for e in room.exclusions) if room.exclusions else 0.0

        logger.info("Detected exclusions across %d rooms", len(rooms))
        return rooms

    def _classify_block(self, insert: CADInsert) -> str:
        """Classify a block reference based on its name and attributes."""
        name = insert.block_name.upper()
        for keyword in self.exclusion_keywords:
            if keyword in name:
                return keyword.title()

        # Check ATTRIB values
        for attr in insert.attribs:
            val = attr.content.upper()
            for keyword in self.exclusion_keywords:
                if keyword in val:
                    return keyword.title()

        return ""

    def _find_exclusion_labels(self, entities: dict[EntityType, list]) -> list[tuple[tuple[float, float], str]]:
        """Find text that labels exclusion zones (e.g., "BIR", "PANTRY")."""
        results: list[tuple[tuple[float, float], str]] = []

        for t in entities.get(EntityType.TEXT, []):
            content = t.content.strip().upper()
            if content in self.exclusion_keywords:
                results.append((t.position, content.title()))

        for mt in entities.get(EntityType.MTEXT, []):
            content = mt.content.strip().upper()
            if content in self.exclusion_keywords:
                results.append((mt.position, content.title()))

        return results

    def _merge_exclusions(self, room: Room) -> None:
        """Merge overlapping exclusion polygons."""
        if len(room.exclusions) < 2:
            return

        polygons = [e.polygon for e in room.exclusions if e.polygon is not None]
        if not polygons:
            return

        from shapely.ops import unary_union

        try:
            merged = unary_union(polygons)
            if isinstance(merged, Polygon):
                room.exclusions = [ExclusionArea(
                    polygon=merged,
                    reason="Merged exclusion",
                    source_type="merged",
                )]
            elif isinstance(merged, MultiPolygon):
                room.exclusions = []
                for i, geom in enumerate(merged.geoms):
                    room.exclusions.append(ExclusionArea(
                        polygon=geom,
                        reason=f"Merged exclusion {i + 1}",
                        source_type="merged",
                    ))
        except Exception as exc:
            logger.warning("Failed to merge exclusions: %s", exc)
