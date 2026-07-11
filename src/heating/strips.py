"""Warmset Strip Generator — lays out 500 mm wide heating mats within heating polygons.

Algorithm:
    1. Determine dominant room direction (longest axis of heating polygon).
    2. Generate parallel lines every 500 mm across the polygon.
    3. Clip lines against the heating polygon.
    4. Merge small strips where practical.
    5. Return strips with lengths and positions.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, Point
from shapely import set_precision

from src.models.rooms import Room, WarmsetStrip, HeatingPolygon
from src.utils.logging import get_logger
from src.utils.config import get_settings

logger = get_logger("heating.strips")


class WarmsetStripGenerator:
    """Generates and lays out Warmset heating strips."""

    def __init__(self):
        settings = get_settings()
        self.mat_width = settings.warmset.mat_width_m
        self.min_strip_length = settings.warmset.min_strip_length_m
        self.max_gap = settings.warmset.max_strip_gap_m
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def generate(self, rooms: list[Room]) -> list[Room]:
        """Generate Warmset strips for all rooms with valid heating polygons."""
        for room in rooms:
            if room.heating_polygon is None or not room.heating_polygon.is_valid:
                room.strip_count = 0
                room.total_linear_m = 0.0
                room.mat_area_m2 = 0.0
                room.coverage_pct = 0.0
                continue

            try:
                strips, total_length, coverage = self._generate_room_strips(room)
                room.strips = strips
                room.strip_count = len(strips)
                room.total_linear_m = total_length
                room.mat_area_m2 = total_length * self.mat_width
                room.coverage_pct = coverage
                room.net_heatable_area_m2 = room.mat_area_m2  # Mat area = net heatable
            except Exception as exc:
                self._warnings.append(f"Strip generation failed for {room.name}: {exc}")
                logger.warning("Strip generation failed for %s: %s", room.name, exc)
                room.strip_count = 0
                room.total_linear_m = 0.0
                room.mat_area_m2 = 0.0
                room.coverage_pct = 0.0

        total_strips = sum(r.strip_count for r in rooms)
        logger.info("Generated %d strips across %d rooms", total_strips, len(rooms))
        return rooms

    def _generate_room_strips(self, room: Room) -> tuple[list[WarmsetStrip], float, float]:
        """Generate strips for a single room.

        Returns:
            Tuple of (strips, total_length_m, coverage_pct).
        """
        heating_poly = room.heating_polygon.polygon
        if heating_poly is None or heating_poly.is_empty:
            return [], 0.0, 0.0

        # Get the polygon to work with (use largest component if MultiPolygon)
        if isinstance(heating_poly, MultiPolygon):
            poly = max(heating_poly.geoms, key=lambda g: g.area)
        else:
            poly = heating_poly

        if poly is None or poly.is_empty:
            return [], 0.0, 0.0

        # Determine dominant direction
        angle = self._dominant_direction(poly)

        # Get bounding box
        minx, miny, maxx, maxy = poly.bounds
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2

        # Calculate diagonal length (for creating long enough lines)
        diag = math.hypot(maxx - minx, maxy - miny)

        # Number of strips
        perp_angle = angle + math.pi / 2
        strip_spacing = self.mat_width

        # Generate strips
        strips: list[WarmsetStrip] = []
        index = 0

        # Start from one side of the bounding box
        max_dim = max(maxx - minx, maxy - miny)
        num_strips = int(math.ceil(max_dim / strip_spacing)) + 2

        for i in range(-1, num_strips + 1):
            offset = (i - num_strips / 2) * strip_spacing

            # Create a line perpendicular to dominant direction
            # The line extends along dominant direction
            p1x = cx + math.cos(perp_angle) * offset - math.cos(angle) * diag
            p1y = cy + math.sin(perp_angle) * offset - math.sin(angle) * diag
            p2x = cx + math.cos(perp_angle) * offset + math.cos(angle) * diag
            p2y = cy + math.sin(perp_angle) * offset + math.sin(angle) * diag

            line = LineString([(p1x, p1y), (p2x, p2y)])

            # Clip against heating polygon
            clipped = line.intersection(poly)

            if clipped is None or clipped.is_empty:
                continue

            # Process single line or multi-line result
            if isinstance(clipped, LineString):
                length = clipped.length
                if length >= self.min_strip_length:
                    coords = list(clipped.coords)
                    strips.append(WarmsetStrip(
                        index=index,
                        length_m=length,
                        geometry=clipped,
                        start_point=coords[0],
                        end_point=coords[-1],
                        clipped=True,
                    ))
                    index += 1
            elif isinstance(clipped, MultiLineString):
                for geom in clipped.geoms:
                    if geom.length >= self.min_strip_length:
                        coords = list(geom.coords)
                        strips.append(WarmsetStrip(
                            index=index,
                            length_m=geom.length,
                            geometry=geom,
                            start_point=coords[0],
                            end_point=coords[-1],
                            clipped=True,
                        ))
                        index += 1

        # Merge adjacent strips that are very close
        strips = self._merge_adjacent(strips)

        total_length = sum(s.length_m for s in strips)
        net_area = poly.area
        coverage = min(100.0, (total_length * self.mat_width) / net_area * 100) if net_area > 0 else 0.0

        return strips, total_length, coverage

    def _dominant_direction(self, polygon: Polygon) -> float:
        """Determine the dominant direction of a polygon.

        Uses Principal Component Analysis (PCA) on the boundary points
        to find the longest axis.
        """
        boundary = polygon.exterior
        coords = list(boundary.coords)

        if len(coords) < 3:
            return 0.0

        # Convert to numpy array
        points = np.array(coords)

        # Center the points
        center = points.mean(axis=0)
        centered = points - center

        # Covariance matrix
        cov = np.cov(centered.T)

        # Eigendecomposition
        try:
            eigvals, eigvecs = np.linalg.eig(cov)
            # Principal direction (largest eigenvector)
            idx = np.argmax(eigvals)
            direction = math.atan2(eigvecs[1, idx], eigvecs[0, idx])
            return direction
        except Exception:
            return 0.0

    def _merge_adjacent(self, strips: list[WarmsetStrip]) -> list[WarmsetStrip]:
        """Merge strips that are very close to each other."""
        if len(strips) < 2:
            return strips

        # Sort by position
        indexed_strips = list(enumerate(strips))
        indexed_strips.sort(key=lambda x: (x[1].start_point[0] + x[1].end_point[0]) / 2)

        merged: list[WarmsetStrip] = []
        current = indexed_strips[0][1]

        for _, next_strip in indexed_strips[1:]:
            # Check distance between strips
            gap = math.hypot(
                current.end_point[0] - next_strip.start_point[0],
                current.end_point[1] - next_strip.start_point[1],
            )
            if gap <= self.max_gap:
                # Merge: extend current to include next
                merged_length = current.length_m + next_strip.length_m
                merged_geom = LineString([current.start_point, next_strip.end_point])
                current = WarmsetStrip(
                    index=current.index,
                    length_m=merged_length,
                    geometry=merged_geom,
                    start_point=current.start_point,
                    end_point=next_strip.end_point,
                    clipped=True,
                )
            else:
                merged.append(current)
                current = next_strip

        merged.append(current)
        return merged
