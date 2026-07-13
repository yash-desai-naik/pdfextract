# Warmset CAD Processing Engine

**Automated underfloor heating takeoff from architectural drawings.**

```
Input: PDF or DXF
         │
         ▼
   Warmset Engine
   (quality check → geometry → rooms → exclusions → setbacks → strips → reports)
         │
         ▼
   Output: JSON + Excel + PDF + debug images
```

## Quick Start

```bash
pip install -r requirements.txt

# Auto-pipeline (native CAD DXFs)
python -m src.main sample.dxf -o ./output

# Interactive tracer (for PDFs or PDF-converted DXFs)
python -m src.tracer "Heating System Plans.pdf"

# Web UI
streamlit run streamlit_app.py
```

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Full system architecture, what was built, issues faced & fixes, what's next
- **[README.md](README.md)** — This file (quick start)
- **[STANDALONE_DOCS.md](STANDALONE_DOCS.md)** — Original CLI docs
- **[QGIS_PLUGIN_DOCS.md](QGIS_PLUGIN_DOCS.md)** — Original QGIS plugin docs

## Repository map

```
src/
├── cad/           DXF parser & quality analyzer
├── geometry/      Snap, cleanup, room reconstruction
├── heating/       Warmset rules: setbacks, strips, exclusions
├── models/        Typed dataclasses (entities, rooms, strips)
├── report/        JSON / XLSX / PDF generators
├── tracer/        Interactive click-to-trace tool
├── utils/         Config, logging, debug visualizations
├── pipeline.py    Orchestrates all 14 stages
├── main.py        CLI entry point
└── converter.py   PDF→DXF (existing)

streamlit_app.py   Web UI (converter + takeoff)
tests/             34 pytest tests
```

## Modes

| Mode | Command | Works with | Accuracy |
|------|---------|-----------|----------|
| **Auto** | `python -m src.main input.dxf` | Native CAD DXFs (closed polylines) | High (95%+) |
| **Tracer CLI** | `python -m src.tracer input.pdf` | Any PDF or DXF | User-defined (100%) |
| **Tracer Web** | `streamlit run streamlit_app.py` | Any PDF or DXF | User-defined (100%) |
| **Reuse** | `--load-traced traced_rooms.json` | Saved coordinates | 100% |

## Tests

```bash
python -m pytest tests/ -v
```
