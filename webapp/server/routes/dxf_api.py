"""API routes for DXF geometry serving — returns entities as GeoJSON for the editor."""

import json

import ezdxf
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/dxf/entities")
async def get_dxf_entities(path: str = Query(...)):
    """Return DXF entities as a GeoJSON FeatureCollection for the frontend editor."""
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        raise HTTPException(400, f"Cannot read DXF: {e}")

    msp = doc.modelspace()

    from src.cad.units import UnitDetector

    detector = UnitDetector(doc)
    unit = detector.detect()

    # Compute bounds
    xs, ys = [], []
    features = []

    for e in msp:
        try:
            t = e.dxftype()
            if t == "LINE":
                xs += [e.dxf.start.x, e.dxf.end.x]
                ys += [e.dxf.start.y, e.dxf.end.y]
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [e.dxf.start.x, e.dxf.start.y],
                                [e.dxf.end.x, e.dxf.end.y],
                            ],
                        },
                        "properties": {"type": "LINE", "layer": e.dxf.layer or "0"},
                    }
                )
            elif t == "LWPOLYLINE":
                pts = e.get_points("xy")
                xs += [p[0] for p in pts]
                ys += [p[1] for p in pts]
                coords = [[p[0], p[1]] for p in pts]
                if e.closed:
                    coords.append(coords[0])
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": {
                            "type": "LWPOLYLINE",
                            "closed": e.closed,
                            "layer": e.dxf.layer or "0",
                        },
                    }
                )
            elif t == "CIRCLE":
                c = e.dxf.center
                xs += [c.x - e.dxf.radius, c.x + e.dxf.radius]
                ys += [c.y - e.dxf.radius, c.y + e.dxf.radius]
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [c.x, c.y]},
                        "properties": {
                            "type": "CIRCLE",
                            "radius": e.dxf.radius,
                            "layer": e.dxf.layer or "0",
                        },
                    }
                )
            elif t == "MTEXT":
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [e.dxf.insert.x, e.dxf.insert.y],
                        },
                        "properties": {
                            "type": "MTEXT",
                            "text": e.dxf.text[:80],
                            "height": e.dxf.char_height or 3,
                            "layer": e.dxf.layer or "0",
                        },
                    }
                )
        except Exception:
            pass

    if not xs:
        raise HTTPException(400, "No geometry found in DXF")

    margin = (max(xs) - min(xs)) * 0.05 or 10
    bounds = [min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin]

    return {
        "type": "FeatureCollection",
        "features": features,
        "bounds": bounds,
        "unit": unit.label,
        "unit_to_m": unit.to_metres,
        "entity_count": len(features),
    }
