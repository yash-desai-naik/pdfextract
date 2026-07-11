"""Automatic detection of drawing units from DXF content."""

from __future__ import annotations

from enum import Enum
from typing import Optional

import ezdxf
from shapely.geometry import Polygon

from src.utils.logging import get_logger

logger = get_logger("cad.units")


class LengthUnit(Enum):
    """Supported length units with their metre conversion factors."""

    MILLIMETRES = ("mm", 0.001)
    CENTIMETRES = ("cm", 0.01)
    METRES = ("m", 1.0)
    FEET = ("ft", 0.3048)
    INCHES = ("in", 0.0254)
    UNKNOWN = ("unknown", 1.0)

    def __init__(self, label: str, to_metres: float):
        self.label = label
        self.to_metres = to_metres

    @classmethod
    def from_ezdxf_units(cls, insunits: int) -> LengthUnit:
        """Map ezdxf $INSUNITS codes to LengthUnit.

        See DXF reference for INSUNITS codes.
        """
        mapping = {
            1: cls.INCHES,       # Inches
            2: cls.FEET,         # Feet
            4: cls.MILLIMETRES,  # mm
            5: cls.CENTIMETRES,  # cm
            6: cls.METRES,       # m
        }
        return mapping.get(insunits, cls.UNKNOWN)

    @classmethod
    def from_measurement(cls, measurement: int) -> LengthUnit:
        """Map $MEASUREMENT header variable: 0 = Imperial, 1 = Metric."""
        if measurement == 1:
            return cls.MILLIMETRES
        return cls.FEET

    def convert_to_metres(self, value: float) -> float:
        return value * self.to_metres


class UnitDetector:
    """Detects drawing units from the DXF header and geometry extent.

    Strategy:
        1. Read $INSUNITS header variable (most reliable).
        2. Fall back to $MEASUREMENT (0=imperial, 1=metric).
        3. Heuristic: bounding-box size suggests units.
    """

    def __init__(self, doc: ezdxf.document.Drawing):
        self.doc = doc
        self._unit: Optional[LengthUnit] = None
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def detect(self) -> LengthUnit:
        """Run detection heuristics and return the best guess.

        Uses:
            1. $INSUNITS header variable
            2. $LIMMAX / $EXTMAX to check for unit mismatch
            3. $MEASUREMENT (0=imperial, 1=metric)
            4. Heuristic: bounding-box size suggests units
        """
        # First, read the drawing limits to check for unit mismatch
        limmax = self._read_limits()

        # Level 1: INSUNITS header
        insunits = self.doc.header.get("$INSUNITS", 0)
        if insunits and insunits != 0:
            unit = LengthUnit.from_ezdxf_units(insunits)
            if unit != LengthUnit.UNKNOWN:
                # Sanity check: if LIMITS suggest millimetres but INSUNITS says metres, override
                if limmax is not None:
                    limit_unit = self._sanity_check_limits(limmax, unit)
                    if limit_unit is not None and limit_unit != unit:
                        logger.warning(
                            "LIMITS (%.0f) suggest %s but INSUNITS says %s — overriding to %s",
                            limmax, limit_unit.label, unit.label, limit_unit.label,
                        )
                        self._warnings.append(
                            f"Unit override: INSUNITS={unit.label}, LIMITS suggest {limit_unit.label}"
                        )
                        self._unit = limit_unit
                        return limit_unit

                logger.info("Detected units from $INSUNITS: %s (code=%d)", unit.label, insunits)
                self._unit = unit
                return unit

        # Level 2: MEASUREMENT header
        measurement = self.doc.header.get("$MEASUREMENT", 1)
        unit = LengthUnit.from_measurement(measurement)
        logger.info("Detected units from $MEASUREMENT: %s (code=%d)", unit.label, measurement)
        self._unit = unit

        # Level 3: Heuristic based on geometry extent
        extent = self._compute_extent()
        if extent is not None:
            heuristic = self._heuristic_units(extent)
            if heuristic != unit:
                logger.warning(
                    "Unit heuristic (%s) suggests %s but header says %s — using heuristic",
                    extent, heuristic.label, unit.label,
                )
                self._unit = heuristic
                return heuristic

        return unit

    def _read_limits(self) -> Optional[float]:
        """Read the actual drawing extent for unit sanity checks.

        Uses the entity bounding-box extent (not LIMMAX which is often
        the ezdxf default of 420x297). Only checks geometry extent.
        """
        try:
            # Use the computed geometry extent if available
            extent = self._compute_extent()
            if extent is not None and extent > 0:
                return extent
        except Exception:
            pass
        return None

    @staticmethod
    def _sanity_check_limits(limit_max: float, current_unit: LengthUnit) -> Optional[LengthUnit]:
        """Check if the drawing limits contradict the declared units.

        Paper sizes in millimetres: A4=297, A3=420, A2=594, A1=841, A0=1189
        If limits match paper sizes in mm but units say metres, override.
        """
        paper_sizes_mm = [297, 420, 594, 841, 1189, 594, 841, 1189]
        paper_sizes_cm = [29.7, 42, 59.4, 84.1, 118.9]
        paper_sizes_m = [0.297, 0.42, 0.594, 0.841, 1.189]
        paper_sizes_ft = [1.0, 1.4, 2.0, 2.8, 3.9]
        paper_sizes_in = [11.7, 16.5, 23.4, 33.1, 46.8]

        # Check if LIMITS suggests millimetres
        for size in paper_sizes_mm:
            if abs(limit_max - size) / max(size, 1) < 0.05:
                if current_unit == LengthUnit.METRES:
                    return LengthUnit.MILLIMETRES
                break

        # Check if LIMITS suggests centimetres
        for size in paper_sizes_cm:
            if abs(limit_max - size) / max(size, 1) < 0.05:
                if current_unit == LengthUnit.METRES:
                    return LengthUnit.CENTIMETRES
                break

        return None

    def _compute_extent(self) -> Optional[float]:
        """Compute the maximum extent of all geometry in model space."""
        try:
            msp = self.doc.modelspace()
            all_points = []
            for e in msp:
                try:
                    bbox = e.bbox()
                    if bbox is not None:
                        all_points.append(bbox.extmin)
                        all_points.append(bbox.extmax)
                except Exception:
                    pass
            if not all_points:
                return None
            xs = [p[0] for p in all_points]
            ys = [p[1] for p in all_points]
            if not xs:
                return None
            return max(max(xs) - min(xs), max(ys) - min(ys))
        except Exception:
            return None

    def _heuristic_units(self, extent: float) -> LengthUnit:
        """Guess units from the overall drawing extent in metres-equivalent."""
        # Typical house plan extents:
        #   mm:  5000-30000
        #   cm:  500-3000
        #   m:   5-30
        #   ft:  15-100
        #   in:  200-1200
        if extent > 10000:
            return LengthUnit.MILLIMETRES
        if extent > 1000:
            return LengthUnit.CENTIMETRES
        if extent > 100:
            return LengthUnit.FEET
        if extent > 20:
            return LengthUnit.METRES
        return LengthUnit.INCHES

    def conversion_factor(self) -> float:
        """Return the factor to convert drawing units to metres."""
        if self._unit is None:
            self.detect()
        return self._unit.to_metres
