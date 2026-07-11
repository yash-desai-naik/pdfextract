"""Spatial indexing utilities using R-tree (from shapely/rtree)."""

from __future__ import annotations

from typing import Any, Optional

from shapely.geometry import Point, Polygon, LineString, MultiPoint
from shapely import STRtree

from src.utils.logging import get_logger
from src.models.entities import CADText, CADMText

logger = get_logger("geometry.spatial")


class SpatialIndex:
    """An R-tree spatial index for efficient nearest-neighbour and containment queries.

    All coordinates are in metres (converted internally before insertion).
    """

    def __init__(self):
        self._geometries: list = []
        self._tree: Optional[STRtree] = None
        self._dirty: bool = False

    def insert(self, geometry, data: Any = None) -> None:
        """Insert a Shapely geometry with optional associated data."""
        if geometry is None or geometry.is_empty:
            return
        self._geometries.append((geometry, data))
        self._dirty = True

    def insert_many(self, geometries_with_data: list[tuple]) -> None:
        """Insert multiple (geometry, data) tuples."""
        for geom, data in geometries_with_data:
            self.insert(geom, data)
        self.build()

    def build(self) -> None:
        """Build the R-tree index."""
        if not self._geometries:
            self._tree = None
            return
        geoms = [g for g, _ in self._geometries]
        self._tree = STRtree(geoms)
        self._dirty = False

    def query(self, geometry) -> list[Any]:
        """Return all data items whose geometry intersects the query geometry."""
        if self._dirty:
            self.build()
        if self._tree is None:
            return []
        raw_results = self._tree.query(geometry, predicate="intersects")
        # Map back to data items
        results = []
        geoms = [g for g, _ in self._geometries]
        for r in raw_results:
            for g, d in self._geometries:
                if g.equals(r):
                    results.append(d)
                    break
        return results

    def nearest(self, point: Point, k: int = 1) -> list[tuple[Any, float]]:
        """Find the k nearest geometries to a point.

        Uses a buffer-expansion approach for multi-nearest queries.
        Falls back to exhaustive search if the index doesn't support k-nearest.

        Returns:
            List of (data, distance) tuples sorted by distance.
        """
        if self._dirty:
            self.build()
        if self._tree is None:
            return []

        results = []
        # First try: use tree.nearest for the single nearest
        try:
            nearest_geom = self._tree.nearest(point)
            if nearest_geom is not None:
                for g, d in self._geometries:
                    if g.equals(nearest_geom):
                        dist = g.distance(point)
                        results.append((d, dist))
                        break
        except Exception:
            pass

        # For k > 1, use query with expanding buffer
        if k > 1:
            buffer_sizes = [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 50.0]
            for buf in buffer_sizes:
                if len(results) >= k:
                    break
                try:
                    candidates = self._tree.query(point.buffer(buf), predicate="intersects")
                    seen = set(id(r) for _, r in results)
                    for g in candidates:
                        gid = id(g)
                        if gid not in seen:
                            for g2, d in self._geometries:
                                if g2.equals(g):
                                    dist = g2.distance(point)
                                    results.append((d, dist))
                                    seen.add(gid)
                                    break
                except Exception:
                    pass

        results.sort(key=lambda x: x[1])
        return results[:k]


def nearest_text(
    point: Point,
    texts: list[CADText | CADMText],
    max_distance: float = 2.0,
) -> list[tuple[str, float]]:
    """Find text entities near a point within max_distance.

    Args:
        point: The query point.
        texts: List of text entities to search.
        max_distance: Maximum search radius in metres.

    Returns:
        List of (text_content, distance) sorted by distance.
    """
    index = SpatialIndex()
    for t in texts:
        pos = Point(t.position)
        content = t.content.strip()
        if content:
            index.insert(pos, content)

    results = index.nearest(point, k=10)
    return [(r[0], r[1]) for r in results if r[1] <= max_distance]


def cluster_points(points: list[tuple[float, float]], tolerance: float = 0.01) -> list[list[tuple[float, float]]]:
    """Cluster nearby points within a tolerance.

    Uses a simple distance-based clustering.
    """
    if not points:
        return []

    clustered: list[list[tuple[float, float]]] = []
    assigned = set()

    for i, p in enumerate(points):
        if i in assigned:
            continue
        cluster = [p]
        assigned.add(i)
        for j, q in enumerate(points):
            if j in assigned:
                continue
            dx = p[0] - q[0]
            dy = p[1] - q[1]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= tolerance:
                cluster.append(q)
                assigned.add(j)
        clustered.append(cluster)
    return clustered
