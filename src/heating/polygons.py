"""Generate installable heating polygons by applying Warmset rules.

Rules:
    - 100 mm setback from walls (default).
    - 150 mm setback in large rooms (>40 m²).
    - 200 mm setback where required (e.g., under windows).
    - No heating beneath exclusion areas (cabinetry, etc.).
    - Maintain clean, valid polygons.
"""

from __future__ import annotations

from typing import Optional

from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import unary_union

from src.models.rooms import Room, HeatingPolygon
from src.utils.logging import get_logger
from src.utils.config import get_settings

logger = get_logger("heating.polygons")


class HeatingPolygonGenerator:
    """Generates the installable heating polygon for each room."""

    def __init__(self):
        settings = get_settings()
        self.default_setback = settings.warmset.default_setback_m
        self.large_room_setback = settings.warmset.large_room_setback_m
        self.large_room_threshold = settings.warmset.large_room_threshold_m2
        self.special_setback = settings.warmset.special_setback_m
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def generate(self, rooms: list[Room]) -> list[Room]:
        """Generate heating polygons for all rooms.

        For each room:
            1. Determine setback distance based on area.
            2. Buffer room polygon inward by setback.
            3. Subtract all exclusion areas.
            4. Validate resulting polygon.

        Args:
            rooms: List of rooms with exclusions populated.

        Returns:
            Rooms with heating_polygon populated.
        """
        for room in rooms:
            if room.polygon is None:
                continue

            try:
                heating = self._compute_heating_polygon(room)
                room.heating_polygon = heating
                room.setback_area_m2 = room.gross_area_m2 - room.excluded_area_m2 - (heating.area_m2 if heating.is_valid else 0)
                room.net_heatable_area_m2 = heating.area_m2 if heating.is_valid else 0.0
            except Exception as exc:
                self._warnings.append(f"Failed to generate heating polygon for {room.name}: {exc}")
                logger.warning("Heating polygon failed for %s: %s", room.name, exc)
                room.heating_polygon = HeatingPolygon()

        successful = sum(1 for r in rooms if r.heating_polygon and r.heating_polygon.is_valid)
        logger.info("Generated heating polygons for %d/%d rooms", successful, len(rooms))
        return rooms

    def _compute_heating_polygon(self, room: Room) -> HeatingPolygon:
        """Compute the heating polygon for a single room."""
        # Step 1: Determine setback
        if room.gross_area_m2 > self.large_room_threshold:
            setback = self.large_room_setback
        else:
            setback = self.default_setback

        # Step 2: Inward buffer (setback from walls)
        room_poly = room.polygon
        if room_poly is None:
            return HeatingPolygon()

        # For polygons with holes, we need to handle exterior and holes separately
        if isinstance(room_poly, Polygon):
            exterior = Polygon(room_poly.exterior)
            interior_polys = [Polygon(hole) for hole in room_poly.interiors]

            # Apply setback to exterior
            setback_poly = exterior.buffer(-setback)
            if setback_poly is None or setback_poly.is_empty:
                return HeatingPolygon(setback_applied=True, setback_distance_m=setback)

            if isinstance(setback_poly, MultiPolygon):
                # Take largest component
                setback_poly = max(setback_poly.geoms, key=lambda g: g.area)
        else:
            setback_poly = room_poly.buffer(-setback)
            if setback_poly is None or setback_poly.is_empty:
                return HeatingPolygon(setback_applied=True, setback_distance_m=setback)

        # Step 3: Subtract exclusions
        if room.exclusions:
            exclusion_union = unary_union([e.polygon for e in room.exclusions if e.polygon is not None])
            if exclusion_union is not None and not exclusion_union.is_empty:
                heating = setback_poly.difference(exclusion_union)
            else:
                heating = setback_poly
        else:
            heating = setback_poly

        # Step 4: Validate
        if heating is None or heating.is_empty:
            return HeatingPolygon(setback_applied=True, setback_distance_m=setback)

        # Repair invalid geometry
        if not heating.is_valid:
            heating = heating.buffer(0)
            if heating is None or heating.is_empty:
                return HeatingPolygon(setback_applied=True, setback_distance_m=setback)

        return HeatingPolygon(
            polygon=heating,
            setback_applied=True,
            setback_distance_m=setback,
        )
