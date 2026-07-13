"""Extract structured data from raw PDF: sheet info, room table, heating schedule, dimensions.

Produces a JSON sidecar independent of the DXF conversion. This is the ground truth
for room names, printed areas, and scale, used to validate traced/reconstructed geometry.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from src.utils.logging import get_logger

logger = get_logger("extraction.pdf_data_extractor")


@dataclass
class SheetInfo:
    project_name: str | None = None
    client: str | None = None
    address: str | None = None
    drawing_number: str | None = None
    revision: str | None = None
    date: str | None = None
    scale: dict | None = None
    sheet_size: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class RoomInfo:
    name: str = ""
    printed_area_sqm: float | None = None
    printed_volume_cbm: float | None = None
    position_hint: list[float] | None = None  # [x, y] average text position

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class HeatingScheduleEntry:
    room: str = ""
    mat_number: list[str] = field(default_factory=list)
    mat_type: str = ""
    mat_size_sqm: float | None = None
    calculated_wattage_w: float | None = None
    installed_wattage_w: float | None = None
    amps: float | None = None
    cable_length_m: float | None = None
    thermostats_required: int | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class DimensionString:
    value_mm: float = 0.0
    position: list[float] | None = None
    raw_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PdfExtractionResult:
    sheet: SheetInfo = field(default_factory=SheetInfo)
    rooms: list[RoomInfo] = field(default_factory=list)
    heating_schedule: list[HeatingScheduleEntry] = field(default_factory=list)
    dimension_strings: list[DimensionString] = field(default_factory=list)
    legend: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sheet": self.sheet.to_dict(),
            "rooms": [r.to_dict() for r in self.rooms],
            "heating_schedule": [h.to_dict() for h in self.heating_schedule],
            "dimension_strings": [d.to_dict() for d in self.dimension_strings],
            "legend": self.legend,
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Saved PDF extraction to %s", path)

    @classmethod
    def load(cls, path: str) -> PdfExtractionResult:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # Reconstruct from dict (simplified)
        inst = cls()
        if "sheet" in data:
            inst.sheet = SheetInfo(**data["sheet"])
        if "rooms" in data:
            inst.rooms = [RoomInfo(**r) for r in data["rooms"]]
        if "heating_schedule" in data:
            inst.heating_schedule = [
                HeatingScheduleEntry(**h) for h in data["heating_schedule"]
            ]
        if "dimension_strings" in data:
            inst.dimension_strings = [
                DimensionString(**d) for d in data["dimension_strings"]
            ]
        if "legend" in data:
            inst.legend = data["legend"]
        return inst


class PdfDataExtractor:
    """Extract structured data from a PDF page using PyMuPDF text extraction.

    Works on the raw PDF (page.get_text("dict") / "words"), not the DXF.
    Independently produces room names, areas, heating schedules, and scale.
    """

    def __init__(self):
        self._warnings: list[str] = []
        self._all_blocks: list[dict] = []
        self._all_words: list[tuple] = []

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def extract(self, page) -> PdfExtractionResult:
        """Extract all structured data from a single PDF page.

        Args:
            page: fitz.Page object.

        Returns:
            PdfExtractionResult with sheet info, rooms, schedule, etc.
        """
        import fitz

        result = PdfExtractionResult()

        # Get full page text as dict for structured access
        text_dict = page.get_text("dict")
        self._all_blocks = text_dict.get("blocks", [])

        # Get words for fine-grained position info
        self._all_words = page.get_text("words")

        # Extract sheet info (project name, drawing number, etc.)
        result.sheet = self._extract_sheet_info(page, text_dict)

        # Try to extract room area/volume table
        result.rooms = self._extract_room_table(text_dict)

        # Try to extract heating schedule table
        result.heating_schedule = self._extract_heating_schedule(text_dict)

        # Extract dimension strings
        result.dimension_strings = self._extract_dimensions(text_dict)

        # Extract legend entries
        result.legend = self._extract_legend(text_dict)

        logger.info(
            "Extracted: sheet=%s, rooms=%d, schedule=%d, dimensions=%d",
            result.sheet.drawing_number or "?",
            len(result.rooms),
            len(result.heating_schedule),
            len(result.dimension_strings),
        )
        return result

    def _extract_sheet_info(self, page, text_dict: dict) -> SheetInfo:
        """Extract title-block metadata from page text."""
        import fitz

        sheet = SheetInfo()
        page_text = page.get_text()

        # Common title block patterns
        patterns = {
            "project_name": [
                r"(?:project|job|contract)\s*[:\-]\s*(.+?)(?:\n|$)",
                r"(?:project|job)\s+name\s*[:\-]\s*(.+?)(?:\n|$)",
            ],
            "client": [
                r"(?:client|customer)\s*[:\-]\s*(.+?)(?:\n|$)",
            ],
            "address": [
                r"(?:address|site)\s*[:\-]\s*(.+?)(?:\n|$)",
            ],
            "drawing_number": [
                r"(?:drawing\s+no|drawing\s+#|dwg\s+no|dwg\s+#)\s*[:\-]\s*(\S+)",
                r"(?:drg\.?\s*no\.?)\s*[:\-]\s*(\S+)",
            ],
            "revision": [
                r"(?:revision|rev|rev\.)\s*[:\-]\s*(\S+)",
            ],
            "date": [
                r"(?:date|dated)\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            ],
        }

        for attr, pattern_list in patterns.items():
            for pat in pattern_list:
                m = re.search(pat, page_text, re.IGNORECASE | re.MULTILINE)
                if m:
                    setattr(sheet, attr, m.group(1).strip())
                    break

        # Sheet size from page rect
        pw, ph = page.rect.width, page.rect.height
        sheet.sheet_size = self._classify_sheet_size(pw, ph)

        return sheet

    @staticmethod
    def _classify_sheet_size(w: float, h: float) -> str:
        """Classify PDF page dimensions into standard sheet sizes (in points)."""
        # A-series in points (72 dpi)
        sizes = {
            "A0": (2384, 3370),
            "A1": (1684, 2384),
            "A2": (1191, 1684),
            "A3": (842, 1191),
            "A4": (595, 842),
            "A5": (420, 595),
        }
        for name, (sw, sh) in sizes.items():
            if abs(w - sw) < 30 and abs(h - sh) < 30:
                return name
            if abs(w - sh) < 30 and abs(h - sw) < 30:
                return name  # landscape
        return f"{w:.0f}×{h:.0f} pt"

    def _extract_room_table(self, text_dict: dict) -> list[RoomInfo]:
        """Extract room name + area from printed takeoff tables.

        Uses y-coordinate clustering to group text into rows,
        then x-coordinate clustering to identify columns.
        Common column headers: "Descrizione", "mq", "mc", "W".
        """
        blocks = self._all_blocks
        if not blocks:
            return []

        # Collect all text spans with positions
        spans: list[dict] = []
        for block in blocks:
            if block.get("type") != 0:  # text block
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    spans.append(
                        {
                            "text": text,
                            "x": span.get("origin", (0, 0))[0],
                            "y": span.get("origin", (0, 0))[1],
                            "size": span.get("size", 10),
                        }
                    )

        if not spans:
            return []

        # Cluster spans into rows by y-coordinate (within 5pt tolerance)
        rows: list[list[dict]] = []
        y_tolerance = 5
        sorted_spans = sorted(spans, key=lambda s: (-s["y"], s["x"]))

        for span in sorted_spans:
            placed = False
            for row in rows:
                if abs(row[0]["y"] - span["y"]) <= y_tolerance:
                    row.append(span)
                    placed = True
                    break
            if not placed:
                rows.append([span])

        # Sort rows by y (top to bottom)
        rows.sort(key=lambda r: -r[0]["y"])

        # For each row, sort spans left to right
        for row in rows:
            row.sort(key=lambda s: s["x"])

        # Look for rows with area/volume patterns
        rooms = []
        area_pattern = re.compile(
            r"^[\d\s,.]+\s*(?:mq|m[²2]|m2|sqm|m³|mc|m3)$", re.IGNORECASE
        )
        number_pattern = re.compile(r"^[\d\s,.]+$")
        room_keywords = {
            "KITCHEN",
            "LIVING",
            "DINING",
            "BEDROOM",
            "MASTER",
            "STUDY",
            "LAUNDRY",
            "BATHROOM",
            "ENSUITE",
            "PANTRY",
            "STORE",
            "HALL",
            "ENTRY",
            "LOUNGE",
            "FAMILY",
            "MEALS",
            "CORRIDOR",
            "SITTING",
            "OFFICE",
            "RUMPUS",
            "THEATRE",
            "BED",
            "WC",
            "POWDER",
            "FOYER",
        }

        for row in rows:
            row_text = " ".join(s["text"].upper() for s in row)

            # Skip header rows and page numbers
            if any(h in row_text for h in ("DESCRIZIONE", "LOCALE", "AMBIENTE")):
                continue
            if row_text.strip().isdigit():
                continue

            # Check if row has a room name candidate
            name_candidate = None
            area_candidate = None
            volume_candidate = None

            for i, span in enumerate(row):
                upper = span["text"].upper().strip()

                # Room name
                if any(kw in upper for kw in room_keywords) or (
                    len(upper) > 2 and not number_pattern.match(upper)
                ):
                    if name_candidate is None and len(upper) > 1:
                        name_candidate = span["text"].strip()

                # Area (mq/m²)
                if "MQ" in upper or "M²" in upper or "M2" in upper or "SQM" in upper:
                    if i > 0:
                        prev_text = row[i - 1]["text"].strip().replace(",", ".")
                        try:
                            area_candidate = float(prev_text)
                        except ValueError:
                            pass
                elif "MC" in upper or "M³" in upper or "M3" in upper:
                    if i > 0:
                        prev_text = row[i - 1]["text"].strip().replace(",", ".")
                        try:
                            volume_candidate = float(prev_text)
                        except ValueError:
                            pass

            if name_candidate and area_candidate:
                rooms.append(
                    RoomInfo(
                        name=name_candidate.strip().title(),
                        printed_area_sqm=area_candidate,
                        printed_volume_cbm=volume_candidate,
                        position_hint=[row[0]["x"], row[0]["y"]],
                    )
                )

        return rooms

    def _extract_heating_schedule(self, text_dict: dict) -> list[HeatingScheduleEntry]:
        """Extract heating mat schedule from tables.

        Looks for rows with mat numbers (e.g. M21, M22) and associated
        room names, areas, wattages.
        """
        blocks = self._all_blocks
        if not blocks:
            return []

        spans: list[dict] = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    spans.append(
                        {
                            "text": text,
                            "x": span.get("origin", (0, 0))[0],
                            "y": span.get("origin", (0, 0))[1],
                        }
                    )

        # Cluster by y into rows
        rows: list[list[dict]] = []
        y_tolerance = 5
        for span in spans:
            placed = False
            for row in rows:
                if abs(row[0]["y"] - span["y"]) <= y_tolerance:
                    row.append(span)
                    placed = True
                    break
            if not placed:
                rows.append([span])

        rows.sort(key=lambda r: -r[0]["y"])
        for row in rows:
            row.sort(key=lambda s: s["x"])

        # Find rows with mat numbers (M\d+)
        mat_pattern = re.compile(r"^M\d+$", re.IGNORECASE)
        watt_pattern = re.compile(r"^[\d,.]+W?$")
        schedule = []

        for row in rows:
            mat_numbers = []
            room_name = None
            size_val = None
            watt_val = None

            for i, span in enumerate(row):
                text = span["text"].strip()
                upper = text.upper()

                if mat_pattern.match(upper):
                    mat_numbers.append(text)
                elif upper in {
                    "ALLUMINIO",
                    "BLACK",
                    "WHITE",
                    "GREY",
                    "FIBERGLASS",
                    "CARBON",
                    "CRYSTAL",
                }:
                    pass  # material type hint

            # If row has mat numbers, extract adjacent columns
            if mat_numbers:
                row_text = " ".join(s["text"] for s in row)
                numbers = re.findall(r"[\d,.]+", row_text)

                # Try to find area and wattage in the same row
                room_name = row[0]["text"] if row[0]["text"].strip() else None
                if len(numbers) >= 2:
                    try:
                        size_val = float(numbers[-2].replace(",", "."))
                    except ValueError:
                        pass
                    try:
                        watt_val_text = numbers[-1].replace(",", ".")
                        watt_val = float(watt_val_text)
                    except ValueError:
                        pass

                entry = HeatingScheduleEntry(
                    room=room_name or "",
                    mat_number=mat_numbers,
                    mat_size_sqm=size_val,
                    installed_wattage_w=watt_val,
                )
                schedule.append(entry)

        return schedule

    def _extract_dimensions(self, text_dict: dict) -> list[DimensionString]:
        """Extract numeric dimension strings near geometry.

        Looks for numbers that appear to be dimension annotations
        (e.g. "8,316", "990", "5 400") — typically medium-sized text
        positioned near walls.
        """
        dimensions = []
        dim_pattern = re.compile(r"^[\d\s,.]+\s*(?:mm|cm|m)?$", re.IGNORECASE)
        single_num = re.compile(r"^[\d,.]+$")

        for word in self._all_words:
            # word format: (x, y, w, h, text, block_no, line_no, word_no)
            if len(word) >= 5:
                text = str(word[4]).strip()
                x, y = float(word[0]), float(word[1])

                # Filter: must be numeric-only (possibly with comma/space thousands)
                clean = text.replace(",", "").replace(" ", "").replace(".", "")
                if clean.isdigit() and len(clean) >= 2 and len(clean) <= 6:
                    try:
                        value = float(text.replace(",", ".").replace(" ", ""))
                        # Reasonable dimension range: 10mm to 50,000mm
                        if 10 <= value <= 50000:
                            dimensions.append(
                                DimensionString(
                                    value_mm=value,
                                    position=[x, y],
                                    raw_text=text,
                                )
                            )
                    except ValueError:
                        pass

        return dimensions

    def _extract_legend(self, text_dict: dict) -> list[dict]:
        """Extract legend entries (symbol → meaning mappings)."""
        blocks = self._all_blocks
        if not blocks:
            return []

        page_text = " ".join(
            span.get("text", "")
            for block in blocks
            if block.get("type") == 0
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        )

        legends = []
        mat_pattern = re.compile(r"(M\d+)\s*[=\-–:]\s*(.+?)(?:\n|$)", re.IGNORECASE)

        for match in mat_pattern.finditer(page_text):
            legends.append(
                {
                    "symbol": match.group(1).upper(),
                    "meaning": match.group(2).strip().title(),
                }
            )

        return legends

    @staticmethod
    def extract_from_pdf(pdf_path: str, page_num: int = 0) -> PdfExtractionResult:
        """Convenience: open PDF, extract from one page, return result."""
        import fitz

        doc = fitz.open(pdf_path)
        try:
            page = doc[page_num]
            extractor = PdfDataExtractor()
            return extractor.extract(page)
        finally:
            doc.close()
