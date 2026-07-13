# Warmset CAD Processing Engine

**Automated underfloor heating takeoff from architectural drawings.**

```
PDF ──► DXF ──► Quality Analyzer ──► Geometry Cleanup
      ──► Room Detection ──► Exclusions ──► Setbacks
      ──► Warmset Strips ──► Report (JSON / XLSX / PDF)
```

---

## Table of Contents

1. [Why this exists](#1-why-this-exists)
2. [Architecture](#2-architecture)
3. [What we built](#3-what-we-built)
4. [Issues faced & fixes](#4-issues-faced--fixes)
5. [How to run](#5-how-to-run)
6. [Known limitations](#6-known-limitations)
7. [What's next](#7-whats-next)

---

## 1. Why this exists

Warmset Australia needed a tool that:

- Takes an architectural floor plan (PDF or DXF)
- Automatically detects rooms and their boundaries
- Calculates the installable heating area per room
- Applies Warmset-specific rules:
  - 500 mm wide heating mats
  - 100–200 mm wall setbacks depending on room size
  - Subtractions for exclusions (islands, cabinets, WIRs, baths)
- Lays out strips and computes linear metres, mat area, coverage %
- Generates a quote-ready report (JSON, Excel, PDF)

The existing codebase had a working PDF→DXF converter. Everything after that — room detection, geometry processing, heating calculations, reporting — needed to be built.

---

## 2. Architecture

```
src/
├── cad/              DXF parsing & quality analysis
│   ├── parser.py     ezdxf → typed dataclass entities
│   ├── analyzer.py   DXF health scoring (0–100%)
│   └── units.py      Auto-detect mm/cm/m/ft/in
├── geometry/         Spatial processing
│   ├── cleanup.py    Snap/merge/deduplicate/remove fragments
│   ├── reconstruction.py  Polygonize rooms via Shapely
│   └── spatial.py    STRtree spatial index
├── heating/          Warmset-specific logic
│   ├── rooms.py      Room naming via keyword matching & dimension extraction
│   ├── exclusions.py Detect cabinetry, WIRs, islands, baths
│   ├── polygons.py   Apply 100/150/200 mm setbacks
│   ├── strips.py     500 mm Warmset mat layout via PCA
│   └── calculator.py Per-room & project-wide metrics
├── models/           Typed dataclasses
│   ├── entities.py   CAD entities (Line, LWPolyline, Text, etc.)
│   └── rooms.py      Room, Exclusion, Strip, Calculation breakdown
├── report/           Output generators
│   ├── json_report.py
│   ├── xlsx_report.py    openpyxl (3 sheets)
│   └── pdf_report.py     reportlab (formatted)
├── tracer/           Interactive manual tracing fallback
│   ├── __init__.py   matplotlib click-to-trace tool
│   └── __main__.py
├── utils/
│   ├── config.py     Pydantic Settings
│   ├── logging.py    Structured logging
│   └── debugging.py  Matplotlib debug visualizations
├── pipeline.py       Orchestrates all 14 stages
├── main.py           CLI entry point
└── converter.py      Existing PDF→DXF (unchanged)

streamlit_app.py      Web UI: PDF→DXF + Warmset takeoff with tracing
tests/
└── test_pipeline.py  34 tests
```

### Data flow

```
Input: PDF or DXF
         │
PDF ─────┤
         │ existing PDF2DXFConverter
         ▼
       DXF
         │
   ┌─────┴─────┐
   │           │
   ▼           ▼
Quality     CAD Parser
Analyzer    (typed dataclasses)
   │           │
   │      Unit Detection
   │      (mm/cm/m/ft/in → m)
   │           │
   │      Geometry Cleanup
   │      (snap, dedup, merge, remove fragments)
   │           │
   │      Room Reconstruction
   │      (Shapely polygonization)
   │           │
   │      Room Labeling
   │      (spatial keyword matching)
   │           │
   │      Dimension Extraction
   │      (DIMENSION entities)
   │           │
   │      Exclusion Detection
   │      (blocks, hatches, closed polylines)
   │           │
   │      Heating Polygon
   │      (wall setbacks preserving holes)
   │           │
   │      Warmset Strip Generator
   │      (500 mm strips via PCA direction)
   │           │
   │      Calculator
   │      (gross → excl → setback → net → strips)
   │           │
   └─────┬─────┘
         │
    Reports: JSON / XLSX / PDF
    Debug:   original.png / rooms.png / heating.png / strips.png
```

---

## 3. What we built

### Stage 1 – DXF Quality Analyzer

Scans a DXF and produces a structured report:

- Entity counts (LINE, LWPOLYLINE, HATCH, TEXT, MTEXT, etc.)
- Closed vs open polylines
- Disconnected segments, duplicates, tiny fragments
- Reconstruction confidence (0–100%)
- Suitability score + human-readable verdict

**Why**: Before processing a DXF, we need to know if it's clean (native CAD) or noisy (PDF-converted). A 95% score means "ready for auto-detection". A 25% score means "will need manual tracing".

### Stage 2 – CAD Parser

Extracts every useful DXF entity into typed Python dataclasses:

- LINE → `CADLine(start, end, layer)`
- LWPOLYLINE → `CADLWPolyline(points, closed)`
- SPLINE, ARC, CIRCLE, ELLIPSE → typed models
- TEXT, MTEXT, DIMENSION → typed text models
- INSERT (block refs) → `CADInsert(block_name, nested_entities)`
- HATCH → `CADHatch(boundary_paths)`

Every entity carries a `.shapely_geometry` property so downstream code never touches raw DXF objects.

**Why**: Raw ezdxf entities are coupled to the DXF format. Typed dataclasses decouple the engine from the input format — tomorrow we could add a DWG or SVG parser and the rest of the engine wouldn't change.

### Stage 3 – Unit Detection

Reads `$INSUNITS` and `$MEASUREMENT` from the DXF header. If the drawing limits (420×297 = A3) suggest mm but INSUNITS says metres, it overrides with a warning.

Converts everything internally to metres via a `LengthUnit` enum.

**Why**: PDF-converted DXFs commonly have wrong INSUNITS values. A plan drawn in mm that says "metres" produces areas 1,000,000× too large if not corrected.

### Stage 4 – Geometry Cleanup

Architectural DXFs — especially PDF-converted ones — contain noisy geometry:

| Operation | Method | Perf |
|-----------|--------|------|
| Snap endpoints | STRtree (O(n log n)) | Replaced original O(n²) |
| Remove duplicates | Set-based hashing | O(n) |
| Merge collinear | Skip if >5000 segments | Avoids hang on large files |
| Remove tiny fragments | Length filter | O(n) |
| Set precision | Shapely `set_precision` | O(n) |

**Why**: PDF-converted DXFs have overlapping lines, tiny fragments, and near-miss endpoints. Without cleanup, polygonization fails or produces thousands of noise polygons.

### Stage 5 – Room Reconstruction

Uses Shapely's `polygonize()` + `unary_union` to build closed polygons from linework:

1. Collect all line segments from cleaned geometry
2. `unary_union` → merge into planar graph
3. `polygonize` → extract all possible polygons
4. Filter by area (0.5–50,000 m²)
5. Sort by size (largest first)

Detects closed-by-coincidence polylines (same start/end point even if `closed=False` — common in PDF output).

### Stage 6 – Room Labeling

Matches text entities to rooms using a spatial index:

1. Build STRtree of all TEXT/MTEXT positions
2. For each room, find text inside or near its polygon
3. Score text against known keywords (LIVING, KITCHEN, BEDROOM 1, etc.)
4. Assign best match as room name

Unknown rooms are still kept — they just get named "Unknown".

### Stage 7 – Dimension Extraction

Reads `DIMENSION` entities and matches them to rooms by proximity. Records whether values are `EXPLICIT` (from DIMENSION), `CALCULATED` (from geometry), or `ESTIMATED`.

### Stage 8 – Exclusion Detection

Detects areas that should not be heated:

- Kitchen islands (closed polyline inside kitchen)
- Built-in wardrobes (BIR, WIR text labels)
- Cabinetry (closed polylines on FURNITURE layer)
- Baths, showers
- Hatches (SOLID fill patterns)

Each exclusion is stored as a `Shapely Polygon` with a `reason` string.

### Stage 9 – Heating Polygon

Applies Warmset rules to each room:

1. Determine setback distance:
   - Default: 100 mm
   - Large rooms (>40 m²): 150 mm
2. Buffer the room polygon inward by the setback
3. Preserve holes (e.g., stair openings, island cutouts)
4. Subtract all exclusion polygons
5. Validate resulting geometry

**Critical fix**: Early versions extracted only the exterior ring for setback, losing polygon holes. The fix uses `room_polygon.buffer(-setback)` on the full polygon (exterior + interior rings), which Shapely handles correctly.

### Stage 10 – Warmset Strip Generator

Lays out 500 mm wide heating mats:

1. Determine dominant room direction via PCA on polygon boundary
2. Generate parallel lines every 500 mm across the bounding box
3. Clip lines against the heating polygon
4. Filter strips shorter than 300 mm
5. Merge adjacent strips with gaps < 50 mm

Returns per-room: strip count, individual lengths, total linear metres, mat area.

### Stage 11 – Confidence Scoring

Every room gets a confidence score from measurable factors:

| Factor | Max | What it measures |
|--------|----:|------------------|
| Closed polygon found | 0.30 | Polygon was successfully reconstructed |
| Room label matched | 0.20 | Text label matched a known room keyword |
| Dimensions verified | 0.20 | DIMENSION entities found near the room |
| No broken walls | 0.15 | Polygon complexity (vertex count) |
| No self-intersections | 0.10 | Polygon is valid (no bow-tie shapes) |
| No inferred geometry | 0.05 | All geometry from DXF, none estimated |

A kitchen with a label and simple rectangle gets ~0.80. An unlabeled complex polygon gets ~0.45. The old system just assigned 1.00 or 0.30 with no explanation.

### Stage 12 – Traceable Calculation Breakdown

Every room now exposes a `RoomCalculation`:

```
Kitchen
  Gross polygon:           16.00 m²
  Less Kitchen—exclusion    0.81 m²     ← island: 900×900 mm
  Total exclusions:         0.81 m²
  Wall setback (100 mm):    1.56 m²
  ─────────────────────────────────
  Net heatable area:       13.63 m²
  14 strips × 500 mm wide
  Lengths:   0.4, 0.6, 0.6, 1.5, ...
  Total linear:             27.3 m
  Mat area:                13.66 m²
  Coverage:               100.0%
```

Every number is traceable back to a CAD entity or user input. Nothing is estimated without being flagged.

### Stage 13 – Reports

| Format | Library | Content |
|--------|---------|---------|
| JSON | stdlib `json` | Full structured data, per-room breakdown, confidence factors, calculation chain |
| XLSX | openpyxl | 3 sheets: takeoff table, summary, exclusions |
| PDF | reportlab | Formatted tables, summary metrics, embedded debug images |

### Stage 14 – Debug Visualizations

Six matplotlib images automatically generated:

| Image | Content |
|-------|---------|
| `original.png` | Raw CAD geometry overlay |
| `quality.png` | Quality score dashboard |
| `rooms.png` | Detected rooms with names & areas |
| `heating.png` | Heating polygons (green) + exclusions (red) |
| `strips.png` | Warmset strip layout (orange) |
| `labels.png` | Room labels & dimension markers |

### Stage 15 – Interactive Tracer (Manual Fallback)

For PDF-converted DXFs where auto-detection is unreliable (25% quality score), the tracer lets users click wall corners to define rooms:

**CLI version**: `python -m src.tracer input.pdf`
```
Controls:
  Left-click  : add vertex
  Right-click : close polygon → prompts for room name
  'e' key     : toggle exclusion mode (trace island/cabinet)
  'u' key     : undo last vertex
  'q' key     : finish → runs full Warmset engine
```

**Web UI version**: `streamlit run streamlit_app.py` → 🔥 Warmset Takeoff tab
- Polygon / freeform / rect drawing modes
- Live room list with names, areas, exclusion toggle
- Runs engine → shows results table + per-room breakdown
- Download buttons for JSON, XLSX, PDF reports
- Export traced coordinates for reuse (`--load-traced`)

Coordinates are converted from pixels to real-world metres via the PDF's point scale or DXF bounds.

---

## 4. Issues faced & fixes

### Issue 1: PDF-converted DXFs have no closed polygons

**Problem**: The KatDesign PDF→DXF conversion produces 32,000 individual LINE entities with zero closed polylines. Room detection via polygonization finds only noise.

**Fix**: Added two paths:
1. The quality analyzer detects this (25% score → "manual tracing recommended")
2. The interactive tracer lets users trace rooms manually, bypassing auto-detection entirely

**Lesson**: For commercial use, the engine needs both modes — auto for native CAD, manual tracing for PDF. No converter in 2026 can reconstruct room topology from PDF vector paths.

### Issue 2: Unit detection was wrong for PDF-converted DXFs

**Problem**: The DXF header said `$INSUNITS=6` (metres) but the drawing was actually in millimetres. A 200×100 mm rectangle became 20,000 m².

**Fix**: Added `$LIMMAX`/`$EXTMAX` sanity check. If the drawing extent matches standard paper sizes (420×297 = A3 in mm) but INSUNITS says metres, we override to mm with a warning.

### Issue 3: O(n²) algorithms on 32K-line DXFs

**Problem**: Endpoint snapping and disconnected-segment counting used nested loops. On 32K lines (64K endpoints), this was ~2 billion iterations — took minutes.

**Fix**: Replaced both with STRtree (Shapely 2.x R-tree). O(n²) → O(n log n). Cleanup now takes ~2 seconds instead of timing out.

### Issue 4: Shapely 2.1 STRtree API change

**Problem**: `STRtree.query()` returns integer indices in Shapely 2.1, not geometry objects. `STRtree.nearest()` accepts only 1 argument, not `k`.

**Fix**: Updated all STRtree usage to map indices back to data arrays. For multi-nearest queries, implemented a buffer-expansion fallback.

### Issue 5: Polygon holes lost during setback

**Problem**: `HeatingPolygonGenerator` extracted only the exterior ring for the wall setback, discarding holes (e.g., kitchen island cutouts). Net heatable area exceeded gross area.

**Fix**: Applied `room_polygon.buffer(-setback)` on the full polygon including interior rings. Shapely correctly shrinks the exterior and expands the holes simultaneously.

### Issue 6: Coordinate cleanup order

**Problem**: Running geometry cleanup after unit conversion (mm→m) made tolerances incorrect. A 2 mm snap tolerance became effectively 2 metres after mm→m conversion, collapsing all geometry.

**Fix**: Run geometry cleanup in native drawing units, then convert coordinates to metres afterward. Tolerance settings are scaled by the unit conversion factor during cleanup.

### Issue 7: Linemerge hangs on large datasets

**Problem**: `shapely.ops.linemerge` on 20K+ segments took minutes.

**Fix**: Skip linemerge entirely when segment count exceeds 5,000. The snap + dedup + precision operations do enough cleanup for polygonization to work.

### Issue 8: Confidence was meaningless (always 1.00 or 0.30)

**Problem**: The old system assigned `confidence = 1.00` if a keyword matched, else `0.30`. No traceability, no nuance.

**Fix**: Implemented `ConfidenceFactors` with 6 measurable components. Each factor is computed from actual geometry (polygon validity, vertex count, label match score, dimension proximity, etc.). Confidence is the sum, capped at 1.00. Every room's JSON report includes the full breakdown.

### Issue 9: No traceable calculation chain

**Problem**: The engine output "Kitchen = 14 m²" with no way to verify how that number was derived.

**Fix**: Added `RoomCalculation` dataclass with the full chain: gross → exclusions (per-item breakdown) → setback → net heatable → strip count → individual lengths → total linear → mat area → coverage %. The CLI and all reports show this chain.

### Issue 10: Streamlit canvas render issues

**Problem**: `matplotlib.figure.canvas.buffer_rgba()` returns a `memoryview` that PIL's `Image.fromarray()` can't accept. `tostring_rgb()` doesn't exist on all matplotlib versions.

**Fix**: Use `fig.savefig(buf, format='png')` with a `BytesIO` target, then `Image.open()`.

### Issue 11: Streamlit duplicate widget keys

**Problem**: Every Streamlit rerun re-extracted shapes from the canvas and created new room widgets with keys `name_0`, `name_1`, etc., conflicting with the previous render's widgets.

**Fix**: Hash the canvas JSON data with MD5 and use the hash as part of each widget's key. Rooms are only rebuilt when the canvas actually changes.

---

## 5. How to run

### Install

```bash
pip install -r requirements.txt
```

### CLI — Automatic pipeline (native CAD DXFs only)

```bash
# From DXF
python -m src.main sample.dxf -o ./output

# From PDF (converts to DXF first)
python -m src.main sample.pdf -o ./output

# Verbose
python -m src.main sample.dxf -o ./output -v
```

### CLI — Interactive tracer (for PDF-converted DXFs)

```bash
python -m src.tracer "Heating System Plans.pdf"
```

### Web UI

```bash
streamlit run streamlit_app.py
```

Opens at `http://localhost:8501` with two tabs:
- **📐 PDF → DXF** — convert PDFs to DXF with crop
- **🔥 Warmset Takeoff** — trace rooms, run engine, download reports

### Re-run without retracing

```bash
python -m src.tracer input.pdf --load-traced tracer_output/traced_rooms.json
```

### Tests

```bash
python -m pytest tests/ -v
```

---

## 6. Known limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| PDF-converted DXFs lack closed room polygons | Auto-detection fails (25% score) | Use interactive tracer |
| Exclusion detection is incomplete | Islands inside holes in polygonized geometry aren't linked as exclusions | Trace them manually as exclusion polygons |
| No multi-page PDF support in takeoff tab | Only processes first page | Use converter tab to split pages first |
| Freeform path extraction is approximate | Only uses M/L command coordinates, ignores curve control points | Use polygon mode instead of freeform |
| No DWG support | Can't read native AutoCAD files | Convert to DXF in AutoCAD first |

---

## 7. What's next

### Short term (days)

1. **Fix freeform path extraction** — Handle `Q` and `C` path commands properly so freehand drawing produces accurate polygons
2. **Add SVG export** — Save traced rooms as SVG overlay on the plan image for visual verification
3. **Room list persistence** — Autosave traced rooms so browser refresh doesn't lose work

### Medium term (weeks)

4. **Streamlit UI polish** — Better UX for the takeoff tab: zoom, pan, color-coded rooms, real-time area updates
5. **Warmset zone grouping** — Allow grouping rooms into heating zones with shared controls
6. **Quote generator** — Add pricing rules (mat cost, installation cost per m²) and output a quote PDF
7. **Multi-unit support** — Handle plans with multiple units (like this 3-unit development), trace per-unit

### Long term (months)

8. **AI-assisted room detection** — Train a segmentation model on floor plans to auto-detect rooms from PDF images
9. **Native DWG support** — Add `ezdxf` DWG reading or integrate ODA File Converter
10. **PDF direct processing** — Extract room polygons directly from PDF vector paths (wall-pair detection) without going through DXF
11. **Cloud API** — Package the engine as a FastAPI service for browser-based uploads
12. **Integration with Warmset CRM** — Push takeoff data directly into Warmset's quoting system

### If I were starting today

The single highest-value change would be **building the Streamlit web UI first** instead of the matplotlib tracer. The matplotlib approach works but requires a local display, while Streamlit works in any browser. Everything else — the engine, the geometry, the reports — would stay the same.

---

## File reference

| File | Lines | Purpose |
|------|------:|---------|
| `src/converter.py` | 262 | PDF→DXF (existing, untouched) |
| `src/pipeline.py` | 265 | Orchestrates all 14 stages |
| `src/main.py` | 115 | CLI entry point |
| `src/cad/parser.py` | 289 | DXF→typed entities |
| `src/cad/analyzer.py` | 215 | Quality scoring |
| `src/cad/units.py` | 160 | Unit detection |
| `src/geometry/cleanup.py` | 220 | Snap/dedup/merge |
| `src/geometry/reconstruction.py` | 170 | Polygonize rooms |
| `src/geometry/spatial.py` | 130 | STRtree index |
| `src/heating/polygons.py` | 120 | Setback generation |
| `src/heating/strips.py` | 175 | Warmset strip layout |
| `src/heating/exclusions.py` | 175 | Detect islands/cabinets |
| `src/heating/rooms.py` | 230 | Labeling & dimensions |
| `src/heating/calculator.py` | 130 | Metrics & breakdown |
| `src/models/entities.py` | 200 | Typed CAD entities |
| `src/models/rooms.py` | 180 | Room/exclusion/strip models |
| `src/report/json_report.py` | 90 | JSON output |
| `src/report/xlsx_report.py` | 130 | Excel output |
| `src/report/pdf_report.py` | 130 | PDF output |
| `src/utils/config.py` | 90 | Pydantic settings |
| `src/utils/logging.py` | 50 | Structured logging |
| `src/utils/debugging.py` | 180 | Matplotlib debug images |
| `src/tracer/__init__.py` | 360 | Interactive click-to-trace |
| `streamlit_app.py` | ~510 | Web UI (converter + takeoff) |
| `tests/test_pipeline.py` | 450 | 34 pytest tests |
