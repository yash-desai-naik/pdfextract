"""Reconstruct room-boundary polygons from disconnected LINE/SPLINE soup.

Takes flat linework (e.g. from PDF-converted DXF), snaps endpoints,
builds a planar graph, and extracts closed polygons via shapely's polygonize.
"""

from __future__ import annotations

from typing import Optional

import networkx as nx
from shapely import ops, wkt
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import polygonize, unary_union

from src.utils.logging import get_logger

logger = get_logger("geometry.topology_builder")


class TopologyBuilder:
    """Reconstruct closed polygons from disconnected line segments.

    Typical input: a DXF with thousands of LINE entities but zero LWPOLYLINE
    (i.e. a PDF-converted file). This module snaps nearby endpoints and uses
    shapely's polygonize to extract closed loops.
    """

    def __init__(self, snap_tolerance: float = 0.005):
        """
        Args:
            snap_tolerance: Distance in drawing units (already in metres after
                            scale resolution). Default 5 mm.
        """
        self.snap_tolerance = snap_tolerance
        self._warnings: list[str] = []
        self._stats: dict = {
            "input_segments": 0,
            "after_snap": 0,
            "candidate_polygons": 0,
            "valid_rooms": 0,
            "discarded_noise": 0,
            "discarded_too_small": 0,
            "discarded_too_large": 0,
        }

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def build(
        self,
        segments: list[LineString],
        min_area_m2: float = 1.0,
        max_area_m2: float = 500.0,
    ) -> list[Polygon]:
        """Build room polygons from line segments.

        Steps:
            1. Snap nearby endpoints within tolerance.
            2. Merge collinear segments.
            3. polygonize to extract closed loops.
            4. Filter by plausible room area.

        Args:
            segments: List of LineString segments (in metres).
            min_area_m2: Minimum room area filter.
            max_area_m2: Maximum room area filter.

        Returns:
            List of valid room Polygon candidates.
        """
        if not segments:
            self._warnings.append("No input segments provided")
            return []

        self._stats["input_segments"] = len(segments)

        # Step 1: Snap nearby endpoints
        snapped = self._snap_endpoints(segments)
        self._stats["after_snap"] = len(snapped)

        # Step 2: Merge collinear segments
        merged = self._merge_collinear(snapped)

        # Step 3: Polygonize
        polygons = self._polygonize(merged)
        self._stats["candidate_polygons"] = len(polygons)

        # Step 4: Filter by area
        rooms = self._filter_rooms(polygons, min_area_m2, max_area_m2)
        self._stats["valid_rooms"] = len(rooms)

        logger.info(
            "Topology: %d segments → %d snapped → %d merged → %d candidates → %d rooms",
            len(segments),
            len(snapped),
            len(merged),
            self._stats["candidate_polygons"],
            len(rooms),
        )
        return rooms

    def _snap_endpoints(self, segments: list[LineString]) -> list[LineString]:
        """Snap endpoints within tolerance to each other.

        Uses a graph-based approach:
            1. Collect all endpoints as nodes.
            2. Cluster nodes within tolerance.
            3. Replace each cluster with its centroid.
            4. Rebuild segments from snapped endpoints.
        """
        if not segments:
            return []

        from shapely import STRtree

        # Collect all unique endpoints
        endpoints: list[Point] = []
        seg_endpoints: list[tuple[int, int]] = []  # indices into endpoints list
        for seg in segments:
            coords = list(seg.coords)
            if len(coords) < 2:
                continue
            start_idx = len(endpoints)
            endpoints.append(Point(coords[0]))
            seg_endpoints.append(len(endpoints) - 1)
            endpoints.append(Point(coords[-1]))
            seg_endpoints.append(len(endpoints) - 1)

        if not endpoints:
            return []

        # Cluster using STRtree
        tree = STRtree(endpoints)
        clusters: list[list[int]] = []  # each cluster is list of endpoint indices
        assigned = set()

        for i, ep in enumerate(endpoints):
            if i in assigned:
                continue
            cluster = [i]
            assigned.add(i)
            buf = ep.buffer(self.snap_tolerance)
            try:
                nearby = tree.query(buf, predicate="intersects")
            except Exception:
                nearby = []

            for j in nearby:
                j_idx = int(j)
                if (
                    j_idx not in assigned
                    and ep.distance(endpoints[j_idx]) <= self.snap_tolerance
                ):
                    cluster.append(j_idx)
                    assigned.add(j_idx)

            if len(cluster) > 1:
                clusters.append(cluster)
            else:
                clusters.append([i])

        # Build snap map: old index → new coordinate
        snap_map: dict[int, tuple[float, float]] = {}
        for cluster in clusters:
            cx = sum(endpoints[idx].x for idx in cluster) / len(cluster)
            cy = sum(endpoints[idx].y for idx in cluster) / len(cluster)
            for idx in cluster:
                snap_map[idx] = (cx, cy)

        # Rebuild segments
        snapped_segments = []
        for s_idx in range(0, len(seg_endpoints), 2):
            if s_idx + 1 >= len(seg_endpoints):
                continue
            start_pt = snap_map.get(seg_endpoints[s_idx])
            end_pt = snap_map.get(seg_endpoints[s_idx + 1])
            if start_pt and end_pt:
                line = LineString([start_pt, end_pt])
                if line.length > self.snap_tolerance:
                    snapped_segments.append(line)

        return snapped_segments

    def _merge_collinear(self, segments: list[LineString]) -> list[LineString]:
        """Merge collinear adjacent segments into longer ones.

        Uses linemerge via unary_union for efficiency.
        """
        if not segments:
            return []

        try:
            merged = unary_union(segments)
        except Exception as exc:
            self._warnings.append(f"unary_union failed: {exc}")
            return segments

        if merged.geom_type == "LineString":
            return [merged]
        elif merged.geom_type == "MultiLineString":
            return list(merged.geoms)
        elif merged.geom_type == "GeometryCollection":
            # Extract linestrings from collection
            result = []
            for geom in merged.geoms:
                if geom.geom_type == "LineString":
                    result.append(geom)
                elif geom.geom_type == "MultiLineString":
                    result.extend(list(geom.geoms))
            return result
        return segments

    def _polygonize(self, segments: list[LineString]) -> list[Polygon]:
        """Extract closed polygons from linework using shapely polygonize."""
        if not segments:
            return []

        try:
            result = polygonize(segments)
        except Exception as exc:
            self._warnings.append(f"polygonize failed: {exc}")
            return []

        polygons = []
        for geom in result.geoms if hasattr(result, "geoms") else [result]:
            if geom.geom_type == "Polygon" and geom.is_valid and not geom.is_empty:
                polygons.append(geom)
        return polygons

    def _filter_rooms(
        self,
        polygons: list[Polygon],
        min_area_m2: float,
        max_area_m2: float,
    ) -> list[Polygon]:
        """Filter polygons by plausible room area and basic shape checks."""
        valid = []
        for poly in polygons:
            area = poly.area
            if area < min_area_m2:
                self._stats["discarded_too_small"] += 1
                continue
            if area > max_area_m2:
                self._stats["discarded_too_large"] += 1
                continue

            # Skip very narrow polygons (wall fragments, annotation boxes)
            if not self._is_room_shape(poly):
                self._stats["discarded_noise"] += 1
                continue

            valid.append(poly)

        return valid

    @staticmethod
    def _is_room_shape(poly: Polygon) -> bool:
        """Basic shape heuristic: rooms should not be extremely skinny."""
        try:
            bounds = poly.bounds
            w = bounds[2] - bounds[0]
            h = bounds[3] - bounds[1]
            if w <= 0 or h <= 0:
                return False
            aspect = max(w, h) / min(w, h)
            # Skip excessively long thin shapes (e.g. dimension lines, walls)
            if aspect > 20 and poly.area < 5.0:
                return False
            return True
        except Exception:
            return True  # keep if unsure

    @staticmethod
    def segments_from_entities(entities: dict) -> list[LineString]:
        """Extract LineString segments from parsed CAD entities."""
        from src.models.entities import CADLine, CADLWPolyline, CADSpline, EntityType

        segments = []

        for ent in entities.get(EntityType.LINE, []):
            if isinstance(ent, CADLine):
                segments.append(LineString([ent.start, ent.end]))

        for lwp in entities.get(EntityType.LWPOLYLINE, []):
            if isinstance(lwp, CADLWPolyline) and len(lwp.points) >= 2:
                pts = lwp.points
                for i in range(len(pts) - 1):
                    segments.append(LineString([pts[i], pts[i + 1]]))
                if lwp.closed and len(pts) >= 3:
                    segments.append(LineString([pts[-1], pts[0]]))

        for spline in entities.get(EntityType.SPLINE, []):
            if isinstance(spline, CADSpline) and len(spline.fit_points) >= 2:
                pts = [(x, y) for x, y, z in spline.fit_points]
                for i in range(len(pts) - 1):
                    segments.append(LineString([pts[i], pts[i + 1]]))
                if spline.closed and len(pts) >= 3:
                    segments.append(LineString([pts[-1], pts[0]]))

        return segments
