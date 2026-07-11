"""Room Reconstruction — builds closed polygons from cleaned geometry.

Uses NetworkX for graph connectivity and Shapely for polygonization.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx
from shapely.geometry import Point, Polygon, LineString, MultiLineString, MultiPolygon
from shapely.ops import polygonize, unary_union
from shapely import set_precision

from src.models.entities import EntityType
from src.models.rooms import Room
from src.utils.logging import get_logger
from src.utils.config import get_settings

logger = get_logger("geometry.reconstruction")


class RoomReconstructor:
    """Reconstructs room polygons from cleaned line work.

    Pipeline:
        1. Build a graph from all line segments.
        2. Extract cycles (closed paths) from the planar graph.
        3. Convert cycles to Shapely polygons.
        4. Filter by area and validity.
        5. Assign containment hierarchy (rooms inside rooms).
    """

    def __init__(self, tolerance_m: Optional[float] = None):
        settings = get_settings()
        self.tolerance = tolerance_m or settings.geometry.snap_tolerance_m
        self.min_area = settings.geometry.min_room_area_m2
        self.max_area = settings.geometry.max_room_area_m2
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def reconstruct(self, cleaned_entities: dict[EntityType, list]) -> list[Room]:
        """Reconstruct rooms from cleaned geometry.

        Args:
            cleaned_entities: The output of GeometryCleaner.clean().

        Returns:
            A list of Room objects sorted by area (largest first).
        """
        # Collect all line geometry
        segments: list[LineString] = []
        for ent in cleaned_entities.get(EntityType.LINE, []):
            g = ent.shapely_geometry
            if g is not None and not g.is_empty:
                segments.append(set_precision(g, self.tolerance))

        # Also add hatch boundaries
        for ent in cleaned_entities.get(EntityType.HATCH, []):
            g = ent.shapely_geometry
            if g is not None and not g.is_empty:
                if isinstance(g, Polygon):
                    segments.append(set_precision(g.boundary, self.tolerance))
                elif isinstance(g, MultiPolygon):
                    for geom in g.geoms:
                        segments.append(set_precision(geom.boundary, self.tolerance))

        if not segments:
            logger.warning("No segments available for room reconstruction")
            return []

        # Build a planar graph
        graph = nx.Graph()
        for seg in segments:
            if seg is None or seg.is_empty:
                continue
            coords = list(seg.coords)
            for i in range(len(coords) - 1):
                p1 = (round(coords[i][0], 6), round(coords[i][1], 6))
                p2 = (round(coords[i + 1][0], 6), round(coords[i + 1][1], 6))
                graph.add_edge(p1, p2)

        # Polygonize using Shapely
        polygons = self._polygonize(segments)

        # Filter and create Room objects
        rooms = []
        for poly in polygons:
            if poly is None or poly.is_empty or not poly.is_valid:
                continue
            if isinstance(poly, MultiPolygon):
                for geom in poly.geoms:
                    room = self._polygon_to_room(geom)
                    if room is not None:
                        rooms.append(room)
            else:
                room = self._polygon_to_room(poly)
                if room is not None:
                    rooms.append(room)

        # Sort by area descending
        rooms.sort(key=lambda r: r.gross_area_m2, reverse=True)

        logger.info("Reconstructed %d rooms from %d segments", len(rooms), len(segments))
        return rooms

    def _polygonize(self, segments: list[LineString]) -> list[Polygon]:
        """Polygonize a set of line segments.

        Uses shapely.ops.polygonize which returns all possible polygons
        from a planar graph of linework.

        Also tries unary_union for enclosed areas.
        """
        # Method 1: polygonize on the merged linework
        try:
            merged = unary_union(segments)
            if merged is None or merged.is_empty:
                return []

            if isinstance(merged, Polygon):
                polys = [merged]
            elif isinstance(merged, MultiPolygon):
                polys = list(merged.geoms)
            elif isinstance(merged, (LineString, MultiLineString)):
                # polygonize the linework
                result = list(polygonize(merged))
                polys = [p for p in result if isinstance(p, Polygon)]
            else:
                polys = []
        except Exception as exc:
            logger.warning("Unary union polygonize failed: %s", exc)
            self._warnings.append(f"Unary union failed: {exc}")
            # Fallback: direct polygonize
            try:
                result = list(polygonize(segments))
                polys = [p for p in result if isinstance(p, Polygon)]
            except Exception as exc2:
                logger.warning("Direct polygonize also failed: %s", exc2)
                self._warnings.append(f"Direct polygonize failed: {exc2}")
                return []

        return polys

    def _polygon_to_room(self, polygon: Polygon) -> Optional[Room]:
        """Convert a Shapely Polygon to a Room, subject to filtering."""
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty:
            return None

        area = polygon.area
        if area < self.min_area or area > self.max_area:
            return None

        centroid = (polygon.centroid.x, polygon.centroid.y)
        bounds = polygon.bounds  # minx, miny, maxx, maxy

        return Room(
            name="Unknown",
            polygon=polygon,
            centroid=centroid,
            bounding_box=bounds,
            confidence=0.7,  # Baseline confidence — increased by labels
            gross_area_m2=area,
        )

    def _find_cycles(self, graph: nx.Graph) -> list[list[tuple[float, float]]]:
        """Extract minimal cycles from the graph using cycle basis.

        This is a secondary method that can supplement polygonization.
        """
        cycles = []
        try:
            # Use cycle basis for small graphs
            if graph.number_of_nodes() < 2000:
                basis = nx.cycle_basis(graph)
                for cycle in basis:
                    if len(cycle) >= 3:
                        # Convert to ordered coordinates
                        cycles.append(cycle)
        except Exception as exc:
            logger.warning("Cycle basis extraction failed: %s", exc)

        return cycles
