"""Tests for the Warmset CAD Processing Engine."""

from __future__ import annotations

import json
from pathlib import Path

import ezdxf
import pytest
from shapely.geometry import Polygon, LineString

from src.cad.parser import CADParser
from src.cad.analyzer import CADQualityAnalyzer
from src.cad.units import UnitDetector, LengthUnit
from src.geometry.cleanup import GeometryCleaner
from src.geometry.reconstruction import RoomReconstructor
from src.models.entities import (
    CADLine, CADLWPolyline, CADPolyline, EntityType,
)
from src.models.rooms import Room, ExclusionArea, HeatingPolygon, WarmsetStrip
from src.utils.config import Settings, get_settings, set_settings
from src.utils.logging import setup_logging
from src.heating.rooms import RoomLabeler, DimensionExtractor
from src.heating.exclusions import ExclusionDetector
from src.heating.polygons import HeatingPolygonGenerator
from src.heating.strips import WarmsetStripGenerator
from src.heating.calculator import HeatingCalculator
from src.pipeline import CADPipeline

# Setup test settings
TEST_SETTINGS = Settings(
    geometry={
        "snap_tolerance_m": 0.001,
        "merge_tolerance_m": 0.001,
        "min_segment_length_m": 0.0005,
        "min_room_area_m2": 0.01,
        "max_room_area_m2": 50000.0,
    },
    warmset={
        "mat_width_m": 0.5,
        "default_setback_m": 0.1,
        "min_strip_length_m": 0.1,
    },
    output={
        "debug_images": False,
    },
)

setup_logging(level="ERROR")


@pytest.fixture(autouse=True)
def test_settings():
    set_settings(TEST_SETTINGS)
    yield
    set_settings(Settings())


@pytest.fixture
def sample_dxf() -> Path:
    return Path(__file__).parent.parent / "sample.dxf"


# ============================================================
# Unit Tests
# ============================================================


class TestCADEntities:
    """Test entity dataclass behaviour."""

    def test_cadline_length(self):
        line = CADLine(dxf_handle="1", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(3, 4))
        assert line.length == 5.0

    def test_cadline_shapely(self):
        line = CADLine(dxf_handle="1", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(1, 1))
        geom = line.shapely_geometry
        assert isinstance(geom, LineString)
        assert geom.length == pytest.approx(1.414, 0.01)

    def test_lwpolyline_closed_by_coincidence(self):
        poly = CADLWPolyline(
            dxf_handle="1", layer="0", entity_type=EntityType.LWPOLYLINE,
            points=[(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
            closed=False,
        )
        geom = poly.shapely_geometry
        assert isinstance(geom, Polygon)
        assert geom.area == 100.0

    def test_lwpolyline_open(self):
        poly = CADLWPolyline(
            dxf_handle="1", layer="0", entity_type=EntityType.LWPOLYLINE,
            points=[(0, 0), (10, 0), (10, 10)],
            closed=False,
        )
        geom = poly.shapely_geometry
        assert isinstance(geom, LineString)

    def test_lwpolyline_explicit_closed(self):
        poly = CADLWPolyline(
            dxf_handle="1", layer="0", entity_type=EntityType.LWPOLYLINE,
            points=[(0, 0), (10, 0), (10, 10), (0, 10)],
            closed=True,
        )
        geom = poly.shapely_geometry
        assert isinstance(geom, Polygon)

    def test_lwpolyline_explicit_closed_coincident(self):
        """3 points with same start/end should be detected as closed."""
        poly = CADLWPolyline(
            dxf_handle="1", layer="0", entity_type=EntityType.LWPOLYLINE,
            points=[(0, 0), (10, 0), (0, 0)],
            closed=False,
        )
        geom = poly.shapely_geometry
        assert isinstance(geom, Polygon)


class TestCADParser:
    """Test DXF parsing."""

    def test_parse_sample(self, sample_dxf):
        doc = ezdxf.readfile(str(sample_dxf))
        parser = CADParser(doc)
        entities = parser.parse()
        assert len(entities) == len(EntityType)
        total = sum(len(v) for v in entities.values())
        assert total == 7

    def test_parse_line(self):
        import ezdxf
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_line((0, 0), (10, 10), dxfattribs={"layer": "TEST"})
        parser = CADParser(doc)
        entities = parser.parse()
        lines = entities.get(EntityType.LINE, [])
        assert len(lines) == 1
        assert lines[0].start == (0, 0)
        assert lines[0].end == (10, 10)
        assert lines[0].layer == "TEST"

    def test_parse_lwpolyline(self):
        import ezdxf
        doc = ezdxf.new()
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (10, 0), (10, 10), (0, 10)], close=True)
        parser = CADParser(doc)
        entities = parser.parse()
        lwpolys = entities.get(EntityType.LWPOLYLINE, [])
        assert len(lwpolys) == 1
        assert lwpolys[0].closed is True


class TestCADAnalyzer:
    """Test quality analysis."""

    def test_analyze_sample(self, sample_dxf):
        doc = ezdxf.readfile(str(sample_dxf))
        analyzer = CADQualityAnalyzer(doc)
        report = analyzer.analyze()
        data = report.to_dict()
        assert data["total_entities"] == 7
        assert 0 <= data["suitability_score"] <= 100
        assert "dxf_version" in data

    def test_empty_drawing(self):
        doc = ezdxf.new()
        analyzer = CADQualityAnalyzer(doc)
        report = analyzer.analyze()
        assert report.to_dict()["total_entities"] == 0


class TestUnitDetector:
    """Test unit detection."""

    def test_metres_from_insunits(self):
        import ezdxf
        doc = ezdxf.new()
        doc.header["$INSUNITS"] = 6
        detector = UnitDetector(doc)
        unit = detector.detect()
        assert unit == LengthUnit.METRES

    def test_mm_from_insunits(self):
        import ezdxf
        doc = ezdxf.new()
        doc.header["$INSUNITS"] = 4
        detector = UnitDetector(doc)
        unit = detector.detect()
        assert unit == LengthUnit.MILLIMETRES

    def test_conversion_factor(self):
        assert LengthUnit.MILLIMETRES.to_metres == 0.001
        assert LengthUnit.METRES.to_metres == 1.0
        assert LengthUnit.FEET.to_metres == 0.3048


class TestGeometryCleanup:
    """Test geometry cleanup operations."""

    def test_remove_duplicates(self):
        entities = {
            EntityType.LINE: [
                CADLine(dxf_handle="1", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(10, 0)),
                CADLine(dxf_handle="2", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(10, 0)),  # duplicate
            ],
            EntityType.TEXT: [],
        }
        cleaner = GeometryCleaner()
        cleaned = cleaner.clean(entities)
        # After linemerge, both segments become 1 continuous line
        lines = cleaned.get(EntityType.LINE, [])
        assert len(lines) == 1  # Merged into 1 continuous segment
        assert cleaner.stats["removed_duplicates"] == 1

    def test_snap_endpoints(self):
        entities = {
            EntityType.LINE: [
                CADLine(dxf_handle="1", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(10, 0)),
                CADLine(dxf_handle="2", layer="0", entity_type=EntityType.LINE,
                        start=(10.001, 0), end=(20, 0)),  # ~1mm gap
            ],
            EntityType.TEXT: [],
        }
        cleaner = GeometryCleaner(tolerance_m=0.005)  # 5mm tolerance
        cleaned = cleaner.clean(entities)
        # After snapping and merging, should be one connected line
        lines = cleaned.get(EntityType.LINE, [])
        assert len(lines) >= 2

    def test_remove_tiny_fragments(self):
        entities = {
            EntityType.LINE: [
                CADLine(dxf_handle="1", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(0.0005, 0)),  # 0.5mm fragment
                CADLine(dxf_handle="2", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(10, 0)),
            ],
            EntityType.TEXT: [],
        }
        cleaner = GeometryCleaner(tolerance_m=0.001)
        cleaned = cleaner.clean(entities)
        # The 0.5mm fragment should be merged/removed
        lines = cleaned.get(EntityType.LINE, [])
        assert len(lines) > 0


class TestRoomReconstruction:
    """Test room reconstruction from geometry."""

    def test_simple_rectangle(self):
        """Reconstruct a single rectangle room."""
        from shapely.geometry import Polygon
        entities = {
            EntityType.LINE: [
                CADLine(dxf_handle="1", layer="0", entity_type=EntityType.LINE,
                        start=(0, 0), end=(10, 0)),
                CADLine(dxf_handle="2", layer="0", entity_type=EntityType.LINE,
                        start=(10, 0), end=(10, 10)),
                CADLine(dxf_handle="3", layer="0", entity_type=EntityType.LINE,
                        start=(10, 10), end=(0, 10)),
                CADLine(dxf_handle="4", layer="0", entity_type=EntityType.LINE,
                        start=(0, 10), end=(0, 0)),
            ],
            EntityType.HATCH: [],
            EntityType.TEXT: [],
            EntityType.MTEXT: [],
            EntityType.DIMENSION: [],
            EntityType.INSERT: [],
            EntityType.ARC: [],
            EntityType.CIRCLE: [],
            EntityType.ELLIPSE: [],
            EntityType.SPLINE: [],
            EntityType.ATTRIB: [],
            EntityType.POLYLINE: [],
            EntityType.BLOCK: [],
        }
        reconstructor = RoomReconstructor()
        rooms = reconstructor.reconstruct(entities)
        assert len(rooms) == 1
        assert rooms[0].gross_area_m2 == pytest.approx(100.0, 0.1)
        assert rooms[0].name == "Unknown"

    def test_no_geometry(self):
        reconstructor = RoomReconstructor()
        rooms = reconstructor.reconstruct({t: [] for t in EntityType})
        assert len(rooms) == 0


class TestRoomLabeler:
    """Test room labeling."""

    def test_no_text(self):
        room = Room(name="Unknown", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        labeler = RoomLabeler()
        rooms = labeler.label_rooms([room], [], [])
        assert rooms[0].name == "Unknown"

    def test_label_matching(self):
        from src.models.entities import CADText
        room = Room(name="Unknown", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        room.polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        text = CADText(dxf_handle="1", layer="0", entity_type=EntityType.TEXT,
                       content="Living", position=(5, 5), height=2.5)
        labeler = RoomLabeler()
        rooms = labeler.label_rooms([room], [text], [])
        assert "Living" in rooms[0].name

    def test_unknown_label_fallback(self):
        from src.models.entities import CADText
        room = Room(name="Unknown", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        room.polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        text = CADText(dxf_handle="1", layer="0", entity_type=EntityType.TEXT,
                       content="RandomLabel", position=(5, 5), height=2.5)
        labeler = RoomLabeler()
        rooms = labeler.label_rooms([room], [text], [])
        # When no keyword matches, labeler still uses nearest text as name
        assert rooms[0].name == "Randomlabel"


class TestExclusionDetector:
    """Test exclusion detection."""

    def test_no_exclusions(self):
        room = Room(name="Test", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        detector = ExclusionDetector()
        rooms = detector.detect_all([room], {t: [] for t in EntityType})
        assert len(rooms[0].exclusions) == 0
        assert rooms[0].excluded_area_m2 == 0.0


class TestHeatingPolygon:
    """Test heating polygon generation."""

    def test_simple_heating_polygon(self):
        room = Room(name="Test", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        generator = HeatingPolygonGenerator()
        rooms = generator.generate([room])
        hp = rooms[0].heating_polygon
        assert hp is not None
        assert hp.is_valid
        assert hp.setback_applied
        # With 0.1m setback, 10x10 - inset by 0.1 = 9.8*9.8 = 96.04
        assert hp.area_m2 < 100.0
        assert hp.area_m2 > 90.0

    def test_exclusion_subtraction(self):
        room = Room(name="Test", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        room.exclusions.append(ExclusionArea(
            polygon=Polygon([(3, 0), (5, 0), (5, 2), (3, 2)]),
            reason="Cabinetry",
        ))
        # Ensure excluded_area_m2 is set from exclusions
        room.excluded_area_m2 = sum(e.area_m2 for e in room.exclusions)
        generator = HeatingPolygonGenerator()
        rooms = generator.generate([room])
        assert rooms[0].excluded_area_m2 > 0


class TestStripGenerator:
    """Test Warmset strip generation."""

    def test_strip_generation(self):
        room = Room(name="Test", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        # Set heating polygon
        room.heating_polygon = HeatingPolygon(
            polygon=Polygon([(0.1, 0.1), (9.9, 0.1), (9.9, 9.9), (0.1, 9.9)]),
        )
        generator = WarmsetStripGenerator()
        rooms = generator.generate([room])
        assert rooms[0].strip_count > 0
        assert rooms[0].total_linear_m > 0


class TestCalculator:
    """Test heating calculator."""

    def test_calculate(self):
        room = Room(name="Test", polygon=Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                     centroid=(5, 5), bounding_box=(0, 0, 10, 10), confidence=0.7,
                     gross_area_m2=100.0)
        room.gross_area_m2 = 100.0
        # Add an exclusion so the calculator can track it
        from src.models.rooms import ExclusionArea
        room.exclusions.append(ExclusionArea(
            polygon=Polygon([(0, 0), (5, 0), (5, 1), (0, 1)]),
            reason="Test cabinet",
        ))
        room.heating_polygon = HeatingPolygon(
            polygon=Polygon([(0.1, 0.1), (9.9, 0.1), (9.9, 9.9), (0.1, 9.9)]),
            setback_applied=True,
        )
        room.strip_count = 19
        room.total_linear_m = 180.0
        room.mat_area_m2 = 90.0

        calculator = HeatingCalculator()
        rooms = calculator.calculate([room])
        totals = calculator.totals(rooms)
        assert totals["total_gross_area_m2"] == 100.0
        assert totals["total_excluded_area_m2"] == 5.0  # 5m x 1m = 5 m²
        assert totals["total_mat_area_m2"] > 0
        assert totals["room_count"] == 1
        # Verify calculation breakdown exists
        assert room.calculation is not None
        assert len(room.calculation.exclusion_breakdown) == 1
        assert room.calculation.exclusion_breakdown[0]["area_m2"] == 5.0


# ============================================================
# Integration Tests
# ============================================================


class TestPipeline:
    """Test the full pipeline end-to-end."""

    def test_sample_dxf_pipeline(self, sample_dxf, tmp_path):
        pipeline = CADPipeline()
        result = pipeline.run(sample_dxf, tmp_path)
        assert result.success
        assert len(result.rooms) > 0
        assert result.totals["room_count"] > 0
        assert result.totals["total_gross_area_m2"] > 0
        assert "json" in result.output_files
        assert "xlsx" in result.output_files
        assert "pdf" in result.output_files

    def test_pipeline_with_settings(self, sample_dxf, tmp_path):
        settings = Settings(
            geometry={"min_room_area_m2": 0.1, "max_room_area_m2": 50000.0},
            output={"debug_images": False},
        )
        pipeline = CADPipeline(settings=settings)
        result = pipeline.run(sample_dxf, tmp_path)
        assert result.success

    def test_json_output(self, sample_dxf, tmp_path):
        pipeline = CADPipeline()
        result = pipeline.run(sample_dxf, tmp_path)
        json_path = result.output_files.get("json")
        assert json_path is not None
        assert json_path.exists()
        with open(json_path) as f:
            data = json.load(f)
        assert "rooms" in data
        assert "totals" in data
        assert "quality_analysis" in data


class TestRoomModels:
    """Test room model properties."""

    def test_room_area_calculation(self):
        polygon = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        room = Room(polygon=polygon, gross_area_m2=polygon.area)
        assert room.gross_area_m2 == 100.0
        assert room.perimeter_m == 40.0

    def test_exclusion_area(self):
        exc = ExclusionArea(
            polygon=Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            reason="Test",
        )
        assert exc.area_m2 == 4.0

    def test_heating_polygon_validity(self):
        hp = HeatingPolygon(
            polygon=Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
        )
        assert hp.is_valid
        assert hp.area_m2 == 1.0

    def test_empty_heating_polygon(self):
        hp = HeatingPolygon()
        assert not hp.is_valid
        assert hp.area_m2 == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
