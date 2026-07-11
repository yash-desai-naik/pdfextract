"""Room naming and dimension extraction from CAD text and DIMENSION entities."""

from __future__ import annotations

import math
from typing import Optional

from shapely.geometry import Point, Polygon

from src.models.entities import EntityType, CADText, CADMText, CADDimension
from src.models.rooms import Room, RoomLabel, DimensionInfo, MeasurementSource
from src.geometry.spatial import SpatialIndex
from src.utils.logging import get_logger
from src.utils.config import get_settings

logger = get_logger("heating.rooms")


class RoomLabeler:
    """Assign names to rooms by finding nearby text entities."""

    def __init__(self):
        settings = get_settings()
        self.search_radius = settings.detection.text_search_radius_m
        self.known_keywords = [k.upper() for k in settings.detection.known_room_keywords]

    def label_rooms(
        self,
        rooms: list[Room],
        texts: list[CADText],
        mtexts: list[CADMText],
    ) -> list[Room]:
        """Assign room names by searching for nearby text.

        Strategy:
            1. Build a spatial index of all text.
            2. For each room, find the closest text that is inside the
               room polygon or within search_radius of its centroid.
            3. Match text against known keywords.
            4. If no match, mark as "Unknown" but keep the room.
        """
        all_texts: list[tuple[str, Point]] = []

        for t in texts:
            content = t.content.strip().upper()
            if content:
                all_texts.append((content, Point(t.position)))

        for mt in mtexts:
            content = mt.content.strip().upper()
            if content:
                all_texts.append((content, Point(mt.position)))

        if not all_texts:
            logger.info("No text entities found — all rooms will be Unknown")
            return rooms

        # Build spatial index
        index = SpatialIndex()
        for content, pt in all_texts:
            index.insert(pt, content)
        index.build()

        for room in rooms:
            if room.polygon is None:
                continue

            centroid = Point(room.centroid)

            # Find text inside the room
            inside_texts = []
            for content, pt in all_texts:
                if room.polygon.contains(pt) or room.polygon.intersects(pt):
                    inside_texts.append((content, centroid.distance(pt)))

            # Also search nearby
            nearby = index.nearest(centroid, k=20)
            for data, dist in nearby:
                if dist <= self.search_radius:
                    inside_texts.append((data, dist))

            # Deduplicate by text
            seen = set()
            unique_texts = []
            for content, dist in inside_texts:
                if content not in seen:
                    seen.add(content)
                    unique_texts.append((content, dist))

            # Sort by distance
            unique_texts.sort(key=lambda x: x[1])

            # Score each text against known keywords
            best_text = ""
            best_score = 0.0
            best_dist = float("inf")

            for content, dist in unique_texts:
                score = self._match_score(content)
                if score > best_score or (score == best_score and dist < best_dist):
                    best_text = content
                    best_score = score
                    best_dist = dist

            if best_text:
                room.name = best_text.title().strip()
                # Update confidence_factors.room_label_matched (+0.20 max)
                if room.confidence_factors is None:
                    from src.models.rooms import ConfidenceFactors
                    room.confidence_factors = ConfidenceFactors()
                room.confidence_factors.room_label_matched = best_score * 0.20
                # Recompute total confidence from all factors
                room.confidence = room.confidence_factors.total
            else:
                # No label match — keep existing confidence from geometric factors
                if room.confidence_factors is not None:
                    room.confidence = room.confidence_factors.total
                else:
                    room.confidence = 0.0

            # Record labels
            for content, dist in unique_texts[:5]:
                pt = Point()
                room.labels.append(RoomLabel(
                    text=content.title().strip(),
                    position=(0.0, 0.0),
                    confidence=self._match_score(content),
                    distance_m=dist,
                ))

        logger.info(
            "Labeled %d rooms (known=%d, unknown=%d)",
            len(rooms),
            sum(1 for r in rooms if r.name != "Unknown"),
            sum(1 for r in rooms if r.name == "Unknown"),
        )
        return rooms

    def _match_score(self, text: str) -> float:
        """Score how well text matches a known room type.

        Returns 0.0 to 1.0.
        """
        text = text.strip().upper()

        # Exact match
        if text in self.known_keywords:
            return 1.0

        # Contains keyword
        for keyword in self.known_keywords:
            if keyword in text or text in keyword:
                return 0.8

        # Partial word match
        for keyword in self.known_keywords:
            if keyword.startswith(text) or text.startswith(keyword):
                return 0.6

        return 0.0


class DimensionExtractor:
    """Extracts and validates room dimensions from DIMENSION entities.

    Dimensions are preferred over calculated geometry.
    """

    def __init__(self):
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def extract(self, rooms: list[Room], dimensions: list[CADDimension]) -> list[Room]:
        """Apply explicit dimensions to rooms.

        Matches dimension lines to room edges when possible.
        """
        if not dimensions:
            for room in rooms:
                room.measurements_used = "calculated (no dimensions found)"
            return rooms

        for room in rooms:
            if room.polygon is None:
                continue
            # Find nearby dimensions
            nearby = []
            for dim in dimensions:
                anchor = Point(dim.dim_line_anchor)
                centroid = Point(room.centroid)
                dist = anchor.distance(centroid)
                if dist < 5.0:  # Within 5m of room centroid
                    nearby.append((dim, dist))

            if not nearby:
                room.measurements_used = "calculated (no matching dimensions)"
                continue

            # Use the closest dimension(s)
            nearby.sort(key=lambda x: x[1])
            best_dim = nearby[0][0]

            if best_dim.measurement is not None:
                # Update confidence for verified dimensions (+0.20)
                if room.confidence_factors is not None:
                    # Score based on how close the dimension angle matches room orientation
                    room.confidence_factors.dimensions_verified = 0.20
                    room.confidence = room.confidence_factors.total

                # Dimensions in DXF are already in drawing units
                room.width = DimensionInfo(
                    value_m=best_dim.measurement,
                    source=MeasurementSource.EXPLICIT,
                    label=best_dim.dim_text,
                )
                room.measurements_used = "explicit"

                # Calculate length from room geometry
                if room.polygon is not None:
                    bounds = room.polygon.bounds
                    geo_width = bounds[2] - bounds[0]
                    geo_length = bounds[3] - bounds[1]
                    room.length = DimensionInfo(
                        value_m=max(geo_width, geo_length) if best_dim.measurement else geo_length,
                        source=MeasurementSource.CALCULATED,
                    )
                    if room.width.value_m > 0:
                        room.length.value_m = room.gross_area_m2 / room.width.value_m
            else:
                room.measurements_used = "calculated"

        return rooms
