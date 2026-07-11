"""Main processing pipeline — orchestrates the entire CAD → Warmset takeoff flow."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import ezdxf

from src.cad.parser import CADParser
from src.cad.analyzer import CADQualityAnalyzer, QualityReport
from src.cad.units import UnitDetector, LengthUnit
from src.geometry.cleanup import GeometryCleaner
from src.geometry.reconstruction import RoomReconstructor
from src.heating.rooms import RoomLabeler, DimensionExtractor
from src.heating.exclusions import ExclusionDetector
from src.heating.polygons import HeatingPolygonGenerator
from src.heating.strips import WarmsetStripGenerator
from src.heating.calculator import HeatingCalculator
from src.report.json_report import JSONReport
from src.report.xlsx_report import XLSXReport
from src.report.pdf_report import PDFReport
from src.utils.debugging import DebugVisualizer
from src.utils.logging import get_logger, setup_logging
from src.utils.config import Settings, get_settings, set_settings

logger = get_logger("pipeline")


class PipelineResult:
    """Result of a complete pipeline run."""

    def __init__(self):
        self.quality_report: Optional[QualityReport] = None
        self.units: Optional[LengthUnit] = None
        self.rooms: list = []
        self.totals: dict = {}
        self.output_files: dict[str, Path] = {}
        self.debug_images: list[Path] = []
        self.warnings: list[str] = []
        self.success: bool = False


class CADPipeline:
    """Orchestrates the complete Warmset heating takeoff pipeline.

    Flow:
        DXF → Quality Analyzer → Parser → Unit Detection → Geometry Cleanup
        → Room Reconstruction → Room Labeling → Dimension Extraction
        → Exclusion Detection → Heating Polygon → Strip Generator
        → Calculator → Reports → Debug Visualizations
    """

    def __init__(self, settings: Optional[Settings] = None):
        if settings:
            set_settings(settings)
        self.settings = get_settings()
        self._warnings: list[str] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def run(self, dxf_path: str | Path, output_dir: str | Path = ".") -> PipelineResult:
        """Run the complete pipeline on a DXF file.

        Args:
            dxf_path: Path to the input DXF file.
            output_dir: Directory for output files.

        Returns:
            PipelineResult with all outputs.
        """
        result = PipelineResult()
        dxf_path = Path(dxf_path)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Override output settings
        self.settings.output.output_dir = output_dir
        debug_dir = output_dir / "debug"
        self.settings.output.debug_dir = debug_dir
        debug_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 60)
        logger.info("Warmset CAD Pipeline starting")
        logger.info("Input: %s", dxf_path)
        logger.info("Output: %s", output_dir)
        logger.info("=" * 60)

        try:
            # --- Stage 1: Load DXF ---
            logger.info("Stage 1: Loading DXF...")
            doc = ezdxf.readfile(str(dxf_path))
            logger.info("Loaded DXF v%s", doc.dxfversion)

            # --- Stage 2: Quality Analysis ---
            logger.info("Stage 2: Quality analysis...")
            analyzer = CADQualityAnalyzer(doc)
            quality = analyzer.analyze()
            result.quality_report = quality
            result.warnings.extend(quality.warnings)
            logger.info("Quality: score=%.1f%% confidence=%.1f%%",
                        quality.suitability_score, quality.reconstruction_confidence)
            logger.info("Verdict: %s", quality.verdict)

            # --- Stage 3: Unit Detection ---
            logger.info("Stage 3: Unit detection...")
            detector = UnitDetector(doc)
            result.units = detector.detect()
            result.warnings.extend(detector.warnings)
            logger.info("Units: %s (conversion=%.6f m/unit)", result.units.label, result.units.to_metres)

            # --- Stage 4: Parse DXF ---
            logger.info("Stage 4: Parsing entities...")
            parser = CADParser(doc)
            entities = parser.parse()
            blocks = parser.parse_blocks()
            total_ents = sum(len(v) for v in entities.values())
            logger.info("Parsed %d entities from modelspace", total_ents)

            # Convert all coordinates to metres
            conv = result.units.to_metres
            if conv != 1.0:
                entities = self._convert_units(entities, conv)

            # --- Stage 5: Geometry Cleanup ---
            logger.info("Stage 5: Geometry cleanup...")
            cleaner = GeometryCleaner()
            cleaned = cleaner.clean(entities)
            result.warnings.extend(cleaner.warnings)
            logger.info("Cleanup stats: %s", cleaner.stats)

            # --- Stage 6: Room Reconstruction ---
            logger.info("Stage 6: Room reconstruction...")
            reconstructor = RoomReconstructor()
            rooms = reconstructor.reconstruct(cleaned)
            result.warnings.extend(reconstructor.warnings)
            logger.info("Reconstructed %d rooms", len(rooms))
            if not rooms:
                logger.warning("No rooms reconstructed — cannot continue")
                result.success = False
                return result

            # --- Stage 7: Room Labeling ---
            logger.info("Stage 7: Room labeling...")
            labeler = RoomLabeler()
            rooms = labeler.label_rooms(
                rooms,
                entities.get(EntityType.TEXT, []),  # noqa: F821
                entities.get(EntityType.MTEXT, []),  # noqa: F821
            )

            # --- Stage 8: Dimension Extraction ---
            logger.info("Stage 8: Dimension extraction...")
            extractor = DimensionExtractor()
            rooms = extractor.extract(rooms, entities.get(EntityType.DIMENSION, []))  # noqa: F821
            result.warnings.extend(extractor.warnings)

            # --- Stage 9: Exclusion Detection ---
            logger.info("Stage 9: Exclusion detection...")
            excluder = ExclusionDetector()
            rooms = excluder.detect_all(rooms, entities)
            result.warnings.extend(excluder.warnings)
            total_excluded = sum(r.excluded_area_m2 for r in rooms)
            logger.info("Total excluded area: %.3f m²", total_excluded)

            # --- Stage 10: Heating Polygon ---
            logger.info("Stage 10: Heating polygon generation...")
            poly_gen = HeatingPolygonGenerator()
            rooms = poly_gen.generate(rooms)
            result.warnings.extend(poly_gen.warnings)
            valid_polys = sum(1 for r in rooms if r.heating_polygon and r.heating_polygon.is_valid)
            logger.info("Valid heating polygons: %d/%d", valid_polys, len(rooms))

            # --- Stage 11: Strip Generation ---
            logger.info("Stage 11: Warmset strip generation...")
            strip_gen = WarmsetStripGenerator()
            rooms = strip_gen.generate(rooms)
            result.warnings.extend(strip_gen.warnings)
            total_strips = sum(r.strip_count for r in rooms)
            total_linear = sum(r.total_linear_m for r in rooms)
            logger.info("Generated %d strips (%.1f linear metres)", total_strips, total_linear)

            # --- Stage 12: Final Calculations ---
            logger.info("Stage 12: Final calculations...")
            calculator = HeatingCalculator()
            rooms = calculator.calculate(rooms)
            result.rooms = rooms
            result.totals = calculator.totals(rooms)

            # --- Stage 13: Debug Visualizations ---
            if self.settings.output.debug_images:
                logger.info("Stage 13: Generating debug visualizations...")
                visualizer = DebugVisualizer(debug_dir)
                visualizer.set_rooms(rooms)
                all_entities = []
                for ent_list in entities.values():
                    all_entities.extend(ent_list)
                result.debug_images = visualizer.save_all(
                    all_entities,
                    quality.to_dict(),
                )
            else:
                result.debug_images = []

            # --- Stage 14: Reports ---
            logger.info("Stage 14: Generating reports...")

            basename = dxf_path.stem

            if self.settings.output.report_json:
                json_path = output_dir / f"{basename}_report.json"
                reporter = JSONReport()
                result.output_files["json"] = reporter.generate(rooms, quality.to_dict(), result.totals, json_path)

            if self.settings.output.report_xlsx:
                xlsx_path = output_dir / f"{basename}_report.xlsx"
                xreporter = XLSXReport()
                result.output_files["xlsx"] = xreporter.generate(rooms, result.totals, xlsx_path)

            if self.settings.output.report_pdf:
                pdf_path = output_dir / f"{basename}_report.pdf"
                preporter = PDFReport()
                result.output_files["pdf"] = preporter.generate(
                    rooms, result.totals, quality.to_dict(), pdf_path,
                    debug_image_paths=result.debug_images,
                )

            result.success = True
            logger.info("=" * 60)
            logger.info("Pipeline completed successfully")
            logger.info("Output files: %s", {k: str(v) for k, v in result.output_files.items()})
            logger.info("=" * 60)

        except Exception as exc:
            logger.exception("Pipeline failed: %s", exc)
            result.warnings.append(f"Pipeline failed: {exc}")
            result.success = False

        return result

    def _convert_units(self, entities: dict, factor: float) -> dict:
        """Convert all entity coordinates by a scaling factor."""
        import copy

        from src.models.entities import (
            CADLine, CADLWPolyline, CADPolyline, CADArc, CADCircle,
            CDAEllipse, CADSpline, CADText, CADMText, CADDimension, CADInsert,
        )

        converted = {}
        for entity_type, ent_list in entities.items():
            converted_list = []
            for ent in ent_list:
                scaled = copy.copy(ent)

                if isinstance(ent, CADLine):
                    scaled.start = (ent.start[0] * factor, ent.start[1] * factor)
                    scaled.end = (ent.end[0] * factor, ent.end[1] * factor)
                elif isinstance(ent, CADLWPolyline):
                    scaled.points = [(x * factor, y * factor) for x, y in ent.points]
                elif isinstance(ent, CADPolyline):
                    scaled.points = [(x * factor, y * factor) for x, y in ent.points]
                elif isinstance(ent, CADArc):
                    scaled.center = (ent.center[0] * factor, ent.center[1] * factor)
                    scaled.radius *= factor
                elif isinstance(ent, CADCircle):
                    scaled.center = (ent.center[0] * factor, ent.center[1] * factor)
                    scaled.radius *= factor
                elif isinstance(ent, CDAEllipse):
                    scaled.center = (ent.center[0] * factor, ent.center[1] * factor)
                    scaled.major_axis = (ent.major_axis[0] * factor, ent.major_axis[1] * factor)
                elif isinstance(ent, CADSpline):
                    scaled.control_points = [(x * factor, y * factor, z) for x, y, z in ent.control_points]
                    scaled.fit_points = [(x * factor, y * factor, z) for x, y, z in ent.fit_points]
                elif isinstance(ent, CADText):
                    scaled.position = (ent.position[0] * factor, ent.position[1] * factor)
                    scaled.height *= factor
                elif isinstance(ent, CADMText):
                    scaled.position = (ent.position[0] * factor, ent.position[1] * factor)
                    scaled.char_height *= factor
                elif isinstance(ent, CADDimension):
                    scaled.dim_line_anchor = (ent.dim_line_anchor[0] * factor, ent.dim_line_anchor[1] * factor)
                    scaled.text_position = (ent.text_position[0] * factor, ent.text_position[1] * factor)
                    if scaled.measurement is not None:
                        scaled.measurement *= factor
                elif isinstance(ent, CADInsert):
                    scaled.position = (ent.position[0] * factor, ent.position[1] * factor)
                elif isinstance(ent, CADHatch):
                    scaled.boundary_paths = [
                        [(x * factor, y * factor) for x, y in path]
                        for path in ent.boundary_paths
                    ]

                converted_list.append(scaled)
            converted[entity_type] = converted_list

        return converted


# Avoid circular import at module level
from src.models.entities import EntityType
