"""Application-wide configuration using Pydantic Settings."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class GeometrySettings(BaseModel):
    """Tolerances and thresholds for geometry processing."""

    snap_tolerance_m: float = Field(default=0.002, ge=0, description="Snap tolerance in metres (default 2 mm)")
    merge_tolerance_m: float = Field(default=0.002, ge=0, description="Merge collinear segments tolerance in metres")
    min_segment_length_m: float = Field(default=0.001, ge=0, description="Remove segments shorter than this (1 mm)")
    min_room_area_m2: float = Field(default=0.5, ge=0, description="Minimum room area in m²")
    max_room_area_m2: float = Field(default=50000.0, ge=0, description="Maximum room area in m² (large to handle unit mismatches)")
    simplification_tolerance_m: float = Field(default=0.005, ge=0, description="Douglas-Peucker simplification tolerance")
    intersection_tolerance_m: float = Field(default=0.001, ge=0, description="Tolerance for intersection detection")


class WarmsetSettings(BaseModel):
    """Warmset-specific heating layout rules."""

    mat_width_m: float = Field(default=0.5, description="Warmset mat width (500 mm)")
    default_setback_m: float = Field(default=0.1, description="Default edge setback (100 mm)")
    large_room_setback_m: float = Field(default=0.15, description="Large room setback (150 mm)")
    large_room_threshold_m2: float = Field(default=40.0, description="Rooms above this area get larger setback")
    special_setback_m: float = Field(default=0.2, description="Special setback where required (200 mm)")
    min_strip_length_m: float = Field(default=0.3, description="Minimum strip length to retain (300 mm)")
    max_strip_gap_m: float = Field(default=0.05, description="Max gap to merge adjacent strips (50 mm)")
    coverage_target_pct: float = Field(default=0.85, ge=0, le=1, description="Target coverage fraction")


class DetectionSettings(BaseModel):
    """Settings for room and fixture detection."""

    text_search_radius_m: float = Field(default=2.0, description="Radius to search for text near rooms")
    exclusion_buffer_m: float = Field(default=0.05, description="Buffer around exclusions (50 mm)")
    hatch_as_exclusion: bool = Field(default=True, description="Treat SOLID hatches as exclusions")
    known_room_keywords: list[str] = Field(
        default=[
            "LIVING", "KITCHEN", "DINING", "BEDROOM", "MASTER", "STUDY",
            "LAUNDRY", "GARAGE", "BATHROOM", "ENSUITE", "PANTRY", "STORE",
            "HALL", "ENTRY", "RUMPUS", "WALK IN ROBE", "WALK-IN ROBE", "WIR",
            "FAMILY", "MEALS", "LOUNGE", "THEATRE", "BED", "BED 1", "BED 2",
            "BED 3", "BED 4", "BATH", "WC", "POWDER", "FOYER", "CORRIDOR",
            "SITTING", "OFFICE", "HOME OFFICE",
        ]
    )
    exclusion_keywords: list[str] = Field(
        default=[
            "CABINET", "CUPBOARD", "WARDROBE", "BIR", "WIR", "ROBE",
            "VANITY", "BATH", "SHOWER", "TOILET", "PANTRY", "STORAGE",
            "ISLAND", "BENCH", "APPLIANCE", "FRIDGE", "OVEN", "STOVE",
            "COOKTOP", "SINK", "FURNITURE", "BOOKSHELF",
        ]
    )


class OutputSettings(BaseModel):
    """Output paths and format settings."""

    output_dir: Path = Field(default=Path("."))
    report_json: bool = True
    report_xlsx: bool = True
    report_pdf: bool = True
    debug_images: bool = True
    debug_dir: Path = Field(default=Path("debug"))


class Settings(BaseModel):
    """Top-level application settings."""

    geometry: GeometrySettings = Field(default_factory=GeometrySettings)
    warmset: WarmsetSettings = Field(default_factory=WarmsetSettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    output: OutputSettings = Field(default_factory=OutputSettings)

    @classmethod
    def create(cls, **overrides: dict) -> Settings:
        return cls(**overrides)

    def model_post_init(self, __context) -> None:
        """Ensure output directories exist."""
        self.output.output_dir.mkdir(parents=True, exist_ok=True)
        if self.output.debug_images:
            self.output.debug_dir.mkdir(parents=True, exist_ok=True)


# Global singleton
_global_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the global settings singleton."""
    global _global_settings
    if _global_settings is None:
        _global_settings = Settings()
    return _global_settings


def set_settings(settings: Settings) -> None:
    """Set the global settings singleton (for testing or custom config)."""
    global _global_settings
    _global_settings = settings
