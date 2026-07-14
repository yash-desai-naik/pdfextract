"""API routes for Warmset takeoff calculation — receives traced rooms, returns results."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class RoomData(BaseModel):
    name: str
    vertices: list[list[float]]  # [[x,y], ...] in metres
    exclusions: list[list[list[float]]] = []  # [[[x,y], ...], ...]


class TakeoffRequest(BaseModel):
    rooms: list[RoomData]
    dxf_path: Optional[str] = None


@router.post("/takeoff")
async def calculate_takeoff(req: TakeoffRequest):
    """Run the Warmset pipeline on traced rooms."""
    import logging

    from shapely.geometry import Polygon

    from src.heating.calculator import HeatingCalculator
    from src.heating.polygons import HeatingPolygonGenerator
    from src.heating.strips import WarmsetStripGenerator
    from src.models.rooms import ExclusionArea, Room

    logger = logging.getLogger("warmset.takeoff")
    engine_rooms = []
    for r in req.rooms:
        poly = Polygon(r.vertices)
        logger.info(
            "Room %s: poly area=%.4f, %d exclusions received",
            r.name,
            poly.area,
            len(r.exclusions),
        )
        if not poly.is_valid or poly.area < 0.01:
            logger.warning("Room %s skipped: invalid or too small", r.name)
            continue
        room = Room(
            name=r.name,
            polygon=poly,
            centroid=(poly.centroid.x, poly.centroid.y),
            bounding_box=poly.bounds,
            confidence=0.95,
            gross_area_m2=poly.area,
        )
        for i, exc_verts in enumerate(r.exclusions):
            logger.info("  Exclusion %d: %d vertices", i, len(exc_verts))
            if len(exc_verts) < 3:
                logger.warning("  Exclusion %d: skipped (<3 vertices)", i)
                continue
            exc_poly = Polygon(exc_verts)
            logger.info(
                "  Exclusion %d: valid=%s area=%.4f",
                i,
                exc_poly.is_valid,
                exc_poly.area,
            )
            if exc_poly.is_valid and exc_poly.area > 0.001:
                room.exclusions.append(
                    ExclusionArea(
                        polygon=exc_poly,
                        reason=f"{r.name} exclusion",
                        source_type="manual",
                    )
                )
        engine_rooms.append(room)

    if not engine_rooms:
        raise HTTPException(400, "No valid rooms provided")

    # Run pipeline stages
    poly_gen = HeatingPolygonGenerator()
    strip_gen = WarmsetStripGenerator()
    calculator = HeatingCalculator()

    engine_rooms = poly_gen.generate(engine_rooms)
    engine_rooms = strip_gen.generate(engine_rooms)
    engine_rooms = calculator.calculate(engine_rooms)
    totals = calculator.totals(engine_rooms)

    return {
        "status": "ok",
        "rooms": [
            {
                "name": r.name,
                "gross_area_m2": round(r.gross_area_m2, 2),
                "excluded_area_m2": round(r.excluded_area_m2, 2),
                "net_heatable_area_m2": round(r.net_heatable_area_m2, 2),
                "mat_area_m2": round(r.mat_area_m2, 2),
                "strip_count": r.strip_count,
                "total_linear_m": round(r.total_linear_m, 2),
                "coverage_pct": round(r.coverage_pct * 100, 1),
                "setback_distance_m": round(r.calculation.setback_distance_m, 3)
                if r.calculation
                else 0,
            }
            for r in engine_rooms
        ],
        "totals": {
            k: round(v, 2) if isinstance(v, float) else v for k, v in totals.items()
        },
    }
