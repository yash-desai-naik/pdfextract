"""HeatingCalculator — computes all area and coverage metrics per room."""

from __future__ import annotations

from typing import Optional

from src.models.rooms import Room, HeatingPolygon
from src.utils.logging import get_logger

logger = get_logger("heating.calculator")


class HeatingCalculator:
    """Computes final heating metrics for each room and the entire project."""

    def __init__(self):
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def calculate(self, rooms: list[Room]) -> list[Room]:
        """Run all calculations for every room.

        This should be called after strip generation to finalise metrics.
        """
        for room in rooms:
            self._calculate_room(room)

        total_gross = sum(r.gross_area_m2 for r in rooms)
        total_net = sum(r.net_heatable_area_m2 for r in rooms)
        total_mat = sum(r.mat_area_m2 for r in rooms)
        logger.info(
            "Calculations complete: gross=%.2f m², net=%.2f m², mat=%.2f m²",
            total_gross, total_net, total_mat,
        )
        return rooms

    def _calculate_room(self, room: Room) -> None:
        """Compute all metrics for a single room."""
        # Gross area — already set by reconstruction
        if room.gross_area_m2 <= 0 and room.polygon is not None:
            room.gross_area_m2 = room.polygon.area

        # Excluded area — already set by exclusion detector
        if room.excluded_area_m2 <= 0:
            room.excluded_area_m2 = sum(e.area_m2 for e in room.exclusions)

        # Heating polygon area
        heat_area = 0.0
        if room.heating_polygon and room.heating_polygon.is_valid:
            heat_area = room.heating_polygon.area_m2
            room.setback_area_m2 = max(
                0.0,
                room.gross_area_m2 - room.excluded_area_m2 - heat_area,
            )
        else:
            room.setback_area_m2 = room.gross_area_m2 - room.excluded_area_m2

        # Net heatable area
        room.net_heatable_area_m2 = heat_area

        # Mat area (from strips)
        if room.strip_count > 0 and room.total_linear_m > 0:
            room.mat_area_m2 = room.total_linear_m * 0.5  # 500 mm wide mats
        else:
            room.mat_area_m2 = 0.0

        # Coverage
        if room.net_heatable_area_m2 > 0:
            room.coverage_pct = min(100.0, (room.mat_area_m2 / room.net_heatable_area_m2) * 100)
        else:
            room.coverage_pct = 0.0

    def totals(self, rooms: list[Room]) -> dict[str, float]:
        """Compute total project-wide metrics."""
        return {
            "total_gross_area_m2": round(sum(r.gross_area_m2 for r in rooms), 3),
            "total_excluded_area_m2": round(sum(r.excluded_area_m2 for r in rooms), 3),
            "total_setback_area_m2": round(sum(r.setback_area_m2 for r in rooms), 3),
            "total_net_heatable_area_m2": round(sum(r.net_heatable_area_m2 for r in rooms), 3),
            "total_mat_area_m2": round(sum(r.mat_area_m2 for r in rooms), 3),
            "total_linear_m": round(sum(r.total_linear_m for r in rooms), 3),
            "total_strips": sum(r.strip_count for r in rooms),
            "room_count": len(rooms),
        }

    def summary(self, rooms: list[Room]) -> list[dict]:
        """Generate a per-room summary list suitable for reports."""
        return [
            {
                "room": room.name,
                "measurements_used": room.measurements_used,
                "gross_area_m2": round(room.gross_area_m2, 3),
                "excluded_area_m2": round(room.excluded_area_m2, 3),
                "setback_area_m2": round(room.setback_area_m2, 3),
                "net_heatable_area_m2": round(room.net_heatable_area_m2, 3),
                "strip_count": room.strip_count,
                "linear_m": round(room.total_linear_m, 3),
                "mat_area_m2": round(room.mat_area_m2, 3),
                "coverage_pct": round(room.coverage_pct, 1),
                "confidence": round(room.confidence, 2),
                "perimeter_m": round(room.perimeter_m, 3),
            }
            for room in rooms
        ]
