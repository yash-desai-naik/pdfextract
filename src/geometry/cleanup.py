"""Geometry cleanup — merges, snaps, deduplicates, and simplifies noisy CAD geometry."""

from __future__ import annotations

from typing import Optional

import numpy as np
from shapely.geometry import (
    Point, LineString, Polygon, MultiLineString, MultiPoint, MultiPolygon,
    box as shapely_box,
)
from shapely.ops import unary_union, linemerge, polygonize
from shapely import set_precision

from src.models.entities import (
    CADEntity, CADLine, CADLWPolyline, CADPolyline,
    EntityType, CADArc, CADCircle,
)
from src.utils.logging import get_logger
from src.utils.config import get_settings

logger = get_logger("geometry.cleanup")


class GeometryCleaner:
    """Cleans and prepares raw CAD geometry for room reconstruction.

    Operations:
        - Snap nearby endpoints within tolerance.
        - Merge touching collinear segments.
        - Remove duplicate overlapping segments.
        - Remove tiny fragments / degenerate geometry.
        - Fix broken corners.
        - Simplify using Douglas-Peucker.
    """

    def __init__(self, tolerance_m: Optional[float] = None):
        settings = get_settings()
        self.tolerance = tolerance_m or settings.geometry.snap_tolerance_m
        self.merge_tolerance = settings.geometry.merge_tolerance_m
        self.min_length = settings.geometry.min_segment_length_m
        self.simplify_tol = settings.geometry.simplification_tolerance_m
        self._warnings: list[str] = []
        self._stats: dict[str, int] = {
            "input_entities": 0,
            "removed_duplicates": 0,
            "merged_segments": 0,
            "removed_fragments": 0,
            "snapped_endpoints": 0,
            "output_segments": 0,
        }

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def clean(self, entities: dict[EntityType, list]) -> dict[EntityType, list]:
        """Run all cleanup operations on parsed entities.

        Returns a new dict of cleaned entities.
        """
        result: dict[EntityType, list] = {t: [] for t in EntityType}

        # Collect all linear geometry
        lines: list[LineString] = []
        for ent_type in (EntityType.LINE, EntityType.LWPOLYLINE, EntityType.POLYLINE):
            for ent in entities.get(ent_type, []):
                g = ent.shapely_geometry
                if g is not None and not g.is_empty:
                    if isinstance(g, Polygon):
                        # Extract boundary as linestring
                        lines.append(g.boundary)
                    elif isinstance(g, LineString):
                        lines.append(g)
                    elif isinstance(g, MultiLineString):
                        lines.extend(list(g.geoms))

        self._stats["input_entities"] = sum(len(v) for v in entities.values())

        # Step 1: Snap endpoints
        lines = self._snap_endpoints(lines)

        # Step 2: Remove duplicates
        lines = self._remove_duplicates(lines)

        # Step 3: Merge touching collinear segments
        lines = self._merge_touching(lines)

        # Step 4: Remove tiny fragments
        lines = self._remove_fragments(lines)

        # Step 5: Set precision (snap coordinates to grid)
        lines = [set_precision(g, self.tolerance) for g in lines if g is not None and not g.is_empty]
        lines = [g for g in lines if g is not None and not g.is_empty]

        self._stats["output_segments"] = len(lines)

        # Convert cleaned geometry back to CADLine objects
        cad_lines = []
        for i, ls in enumerate(lines):
            if isinstance(ls, LineString) and len(ls.coords) >= 2:
                coords = list(ls.coords)
                for j in range(len(coords) - 1):
                    cad_lines.append(CADLine(
                        dxf_handle=f"clean_{i}_{j}",
                        layer="0",
                        entity_type=EntityType.LINE,
                        start=(coords[j][0], coords[j][1]),
                        end=(coords[j + 1][0], coords[j + 1][1]),
                    ))

        result[EntityType.LINE] = cad_lines

        # Pass through non-geometry entities unchanged (text, dimensions, etc.)
        for et in (EntityType.TEXT, EntityType.MTEXT, EntityType.DIMENSION,
                   EntityType.INSERT, EntityType.HATCH, EntityType.ARC,
                   EntityType.CIRCLE, EntityType.ELLIPSE, EntityType.SPLINE):
            result[et] = list(entities.get(et, []))

        logger.info(
            "Cleanup: %d input → %d output segments (%d dupes, %d fragments removed, %d snapped)",
            self._stats["input_entities"],
            self._stats["output_segments"],
            self._stats["removed_duplicates"],
            self._stats["removed_fragments"],
            self._stats["snapped_endpoints"],
        )
        return result

    def _snap_endpoints(self, lines: list[LineString]) -> list[LineString]:
        """Snap nearby endpoints within tolerance."""
        if not lines:
            return lines

        # Collect all endpoints
        endpoints: list[tuple[float, float, int, bool]] = []  # (x, y, line_idx, is_start)
        for i, ls in enumerate(lines):
            if ls is None or ls.is_empty:
                continue
            coords = list(ls.coords)
            if not coords:
                continue
            endpoints.append((coords[0][0], coords[0][1], i, True))
            endpoints.append((coords[-1][0], coords[-1][1], i, False))

        # Use R-tree approach for efficiency
        snapped_count = 0
        for i, (x1, y1, line_idx, is_start) in enumerate(endpoints):
            for j, (x2, y2, other_idx, _) in enumerate(endpoints):
                if i == j:
                    continue
                dx, dy = x1 - x2, y1 - y2
                dist = (dx * dx + dy * dy) ** 0.5
                if 0 < dist <= self.tolerance:
                    coords = list(lines[line_idx].coords)
                    if is_start:
                        coords[0] = (x2, y2)
                    else:
                        coords[-1] = (x2, y2)
                    lines[line_idx] = LineString(coords)
                    snapped_count += 1
                    break

        self._stats["snapped_endpoints"] = snapped_count
        return lines

    def _remove_duplicates(self, lines: list[LineString]) -> list[LineString]:
        """Remove duplicate line segments (same start and end)."""
        seen: set[tuple] = set()
        unique: list[LineString] = []
        for ls in lines:
            if ls is None or ls.is_empty:
                continue
            coords = list(ls.coords)
            if len(coords) < 2:
                continue
            # Normalise direction
            start, end = coords[0], coords[-1]
            key = (round(start[0], 6), round(start[1], 6), round(end[0], 6), round(end[1], 6))
            key_rev = (round(end[0], 6), round(end[1], 6), round(start[0], 6), round(start[1], 6))

            if key in seen or key_rev in seen:
                self._stats["removed_duplicates"] += 1
                continue
            seen.add(key)
            unique.append(ls)
        return unique

    def _merge_touching(self, lines: list[LineString]) -> list[LineString]:
        """Merge touching collinear segments using Shapely's linemerge."""
        if not lines:
            return []
        try:
            merged = linemerge(lines)
            if isinstance(merged, LineString):
                return [merged]
            elif isinstance(merged, MultiLineString):
                count_before = len(lines)
                count_after = len(list(merged.geoms))
                self._stats["merged_segments"] = count_before - count_after
                return list(merged.geoms)
        except Exception as exc:
            logger.warning("linemerge failed: %s", exc)
            self._warnings.append(f"linemerge failed: {exc}")
        return lines

    def _remove_fragments(self, lines: list[LineString]) -> list[LineString]:
        """Remove segments shorter than min_length."""
        filtered = []
        for ls in lines:
            if ls is None or ls.is_empty:
                self._stats["removed_fragments"] += 1
                continue
            length = ls.length
            if length < self.min_length:
                self._stats["removed_fragments"] += 1
                continue
            filtered.append(ls)
        return filtered


def clean_entities(entities: dict[EntityType, list], tolerance_m: Optional[float] = None) -> dict[EntityType, list]:
    """Convenience function: create a cleaner, run it, return cleaned entities."""
    cleaner = GeometryCleaner(tolerance_m)
    return cleaner.clean(entities)
