"""CAD Parser — extracts all useful entities from a DXF into typed dataclasses.

All downstream code must use the typed dataclasses from models/entities.py
and must never access DXF entities directly.
"""

from __future__ import annotations

from typing import Optional

import ezdxf
from ezdxf.math import Vec3

from src.models.entities import (
    CADLine, CADLWPolyline, CADPolyline, CADArc, CADCircle,
    CDAEllipse, CADSpline, CADHatch, CADText, CADMText,
    CADDimension, CADInsert, CADBlock, CADAttrib,
    EntityType,
)
from src.utils.logging import get_logger

logger = get_logger("cad.parser")


class CADParser:
    """Parse an ezdxf Drawing into typed CAD entity dataclasses.

    Usage:
        parser = CADParser(doc)
        entities = parser.parse()
        # entities is a dict keyed by EntityType with lists of typed objects
    """

    def __init__(self, doc: ezdxf.document.Drawing):
        self.doc = doc
        self.msp = doc.modelspace()

    def parse(self) -> dict[EntityType, list]:
        """Parse the entire model space into typed entities.

        Returns:
            A dict mapping EntityType to a list of typed entity objects.
        """
        result: dict[EntityType, list] = {t: [] for t in EntityType}

        for dxf_entity in self.msp:
            try:
                entity = self._parse_single(dxf_entity)
                if entity is not None:
                    result[entity.entity_type].append(entity)
            except Exception as exc:
                logger.warning(
                    "Failed to parse %s (handle=%s): %s",
                    dxf_entity.dxftype(), dxf_entity.dxf.handle, exc,
                )

        # Also process INSERT entities recursively for nested geometry
        inserts = list(result[EntityType.INSERT])
        for ins in inserts:
            self._expand_insert(ins)

        logger.info(
            "Parsed %d entities from DXF",
            sum(len(v) for v in result.values()),
        )
        return result

    def parse_blocks(self) -> dict[str, CADBlock]:
        """Parse all BLOCK definitions.

        Returns:
            Dict mapping block_name to CADBlock.
        """
        blocks: dict[str, CADBlock] = {}
        for block_def in self.doc.blocks:
            name = block_def.name
            if name.startswith("*"):
                continue  # Skip anonymous blocks (*Model_Space, *Paper_Space)
            entities: list = []
            for e in block_def:
                ent = self._parse_single(e)
                if ent is not None:
                    entities.append(ent)
            base = (0.0, 0.0)
            bp = block_def.block_usage if hasattr(block_def, "block_usage") else block_def.block
            try:
                base = (bp.dxf.base_point.x, bp.dxf.base_point.y)
            except Exception:
                pass
            blocks[name] = CADBlock(
                dxf_handle=block_def.block.dxf.handle if hasattr(block_def.block.dxf, "handle") else "block",
                layer="0",
                entity_type=EntityType.BLOCK,
                block_name=name,
                entities=entities,
                base_point=base,
            )
        return blocks

    def _parse_single(self, e) -> Optional:
        """Parse a single ezdxf entity into a typed dataclass."""
        dtype = e.dxftype()
        layer = e.dxf.layer if hasattr(e.dxf, "layer") else "0"
        handle = e.dxf.handle if hasattr(e.dxf, "handle") else ""

        common = {
            "dxf_handle": handle,
            "layer": layer,
            "linetype": getattr(e.dxf, "linetype", None),
            "color": getattr(e.dxf, "color", None) or e.color if hasattr(e, "color") else None,
        }

        if dtype == "LINE":
            return CADLine(
                entity_type=EntityType.LINE,
                start=(e.dxf.start.x, e.dxf.start.y),
                end=(e.dxf.end.x, e.dxf.end.y),
                **common,
            )

        elif dtype == "LWPOLYLINE":
            pts = e.get_points("xy")
            bulges = list(e.get_bulge_values()) if hasattr(e, "get_bulge_values") else []
            widths = [(w0, w1) for w0, w1 in e.get_width_values()] if hasattr(e, "get_width_values") else []
            return CADLWPolyline(
                entity_type=EntityType.LWPOLYLINE,
                points=pts,
                closed=e.closed,
                bulges=bulges,
                widths=widths,
                **common,
            )

        elif dtype == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
            return CADPolyline(
                entity_type=EntityType.POLYLINE,
                points=pts,
                closed=e.closed,
                **common,
            )

        elif dtype == "ARC":
            return CADArc(
                entity_type=EntityType.ARC,
                center=(e.dxf.center.x, e.dxf.center.y),
                radius=e.dxf.radius,
                start_angle=e.dxf.start_angle,
                end_angle=e.dxf.end_angle,
                extrusion=(e.dxf.extrusion.x, e.dxf.extrusion.y, e.dxf.extrusion.z),
                **common,
            )

        elif dtype == "CIRCLE":
            return CADCircle(
                entity_type=EntityType.CIRCLE,
                center=(e.dxf.center.x, e.dxf.center.y),
                radius=e.dxf.radius,
                extrusion=(e.dxf.extrusion.x, e.dxf.extrusion.y, e.dxf.extrusion.z),
                **common,
            )

        elif dtype == "ELLIPSE":
            return CDAEllipse(
                entity_type=EntityType.ELLIPSE,
                center=(e.dxf.center.x, e.dxf.center.y),
                major_axis=(e.dxf.major_axis.x, e.dxf.major_axis.y),
                ratio=e.dxf.ratio,
                start_param=e.dxf.start_param,
                end_param=e.dxf.end_param,
                extrusion=(e.dxf.extrusion.x, e.dxf.extrusion.y, e.dxf.extrusion.z),
                **common,
            )

        elif dtype == "SPLINE":
            ctrl = [_to_xyz(p) for p in e.control_points] if e.control_points else []
            fit = [_to_xyz(p) for p in e.fit_points] if e.fit_points else []
            deg = getattr(e, 'degree', None) or getattr(e.dxf, 'degree', 3)
            knots = list(e.knots) if hasattr(e, 'knots') and e.knots else []
            return CADSpline(
                entity_type=EntityType.SPLINE,
                control_points=ctrl,
                fit_points=fit,
                degree=deg,
                closed=e.closed,
                knots=knots,
                **common,
            )

        elif dtype == "HATCH":
            paths = []
            for path in e.paths:
                pts = [(v[0], v[1]) for v in path.vertices] if hasattr(path, "vertices") else []
                if pts:
                    paths.append(pts)
            pattern = e.dxf.pattern_name if hasattr(e.dxf, "pattern_name") else None
            return CADHatch(
                entity_type=EntityType.HATCH,
                boundary_paths=paths,
                closed=True,
                solid_fill=(e.dxf.solid_fill == 1) if hasattr(e.dxf, "solid_fill") else False,
                pattern_name=pattern,
                **common,
            )

        elif dtype == "TEXT":
            return CADText(
                entity_type=EntityType.TEXT,
                content=e.dxf.text,
                position=(e.dxf.insert.x, e.dxf.insert.y),
                height=e.dxf.height,
                rotation=e.dxf.rotation if hasattr(e.dxf, "rotation") else 0.0,
                width_factor=e.dxf.width if hasattr(e.dxf, "width") else 1.0,
                **common,
            )

        elif dtype == "MTEXT":
            w = e.dxf.width if hasattr(e.dxf, "width") else None
            return CADMText(
                entity_type=EntityType.MTEXT,
                content=e.dxf.text,
                position=(e.dxf.insert.x, e.dxf.insert.y),
                char_height=e.dxf.char_height,
                rotation=e.dxf.rotation if hasattr(e.dxf, "rotation") else 0.0,
                width=w,
                **common,
            )

        elif dtype == "DIMENSION":
            dim_type = e.dxf.dimtype if hasattr(e.dxf, "dimtype") else 0
            text = e.dxf.dimtext if hasattr(e.dxf, "dimtext") else None
            meas = e.get_measurement() if hasattr(e, "get_measurement") else None
            anchor = (e.dxf.dim_line_defining_point.x, e.dxf.dim_line_defining_point.y) if hasattr(e.dxf, "dim_line_defining_point") else (0.0, 0.0)
            text_pos = (e.dxf.text_midpoint.x, e.dxf.text_midpoint.y) if hasattr(e.dxf, "text_midpoint") else (0.0, 0.0)
            return CADDimension(
                entity_type=EntityType.DIMENSION,
                dim_type=dim_type,
                dim_text=text,
                measurement=meas,
                dim_line_anchor=anchor,
                text_position=text_pos,
                rotation=e.dxf.rotation if hasattr(e.dxf, "rotation") else 0.0,
                **common,
            )

        elif dtype == "INSERT":
            attribs = []
            for attr in e.attribs if hasattr(e, "attribs") else []:
                if hasattr(attr.dxf, "tag"):
                    attribs.append(CADAttrib(
                        dxf_handle=attr.dxf.handle if hasattr(attr.dxf, "handle") else "",
                        layer=attr.dxf.layer if hasattr(attr.dxf, "layer") else "0",
                        entity_type=EntityType.ATTRIB,
                        content=attr.dxf.text if hasattr(attr.dxf, "text") else "",
                        position=(attr.dxf.insert.x, attr.dxf.insert.y) if hasattr(attr.dxf, "insert") else (0.0, 0.0),
                        height=attr.dxf.height if hasattr(attr.dxf, "height") else 2.5,
                        tag=attr.dxf.tag if hasattr(attr.dxf, "tag") else "",
                    ))
            return CADInsert(
                entity_type=EntityType.INSERT,
                block_name=e.dxf.name if hasattr(e.dxf, "name") else "",
                position=(e.dxf.insert.x, e.dxf.insert.y),
                scale_x=e.dxf.xscale if hasattr(e.dxf, "xscale") else 1.0,
                scale_y=e.dxf.yscale if hasattr(e.dxf, "yscale") else 1.0,
                rotation=e.dxf.rotation if hasattr(e.dxf, "rotation") else 0.0,
                attribs=attribs,
                **common,
            )

        # Skip unsupported types silently
        return None

    def _expand_insert(self, insert: CADInsert) -> None:
        """Populate nested_entities on an INSERT by resolving its block definition."""
        try:
            block = self.doc.blocks.get(insert.block_name)
            if block is None:
                return
            for e in block:
                ent = self._parse_single(e)
                if ent is not None:
                    insert.nested_entities.append(ent)
        except Exception:
            pass


def _to_xyz(point) -> tuple[float, float, float]:
    """Convert a point (Vec3, tuple, or list) to (x, y, z)."""
    if hasattr(point, 'x'):
        return (point.x, point.y, point.z if hasattr(point, 'z') else 0.0)
    if isinstance(point, (tuple, list)):
        if len(point) >= 3:
            return (float(point[0]), float(point[1]), float(point[2]))
        elif len(point) == 2:
            return (float(point[0]), float(point[1]), 0.0)
    return (0.0, 0.0, 0.0)
