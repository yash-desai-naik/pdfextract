"""Interactive room tracer — click-to-trace polygons from a PDF/DXF visual reference.

Usage:
    python -m src.tracer input.pdf
    python -m src.tracer input.dxf
    python -m src.tracer input.pdf --load-traced traced_rooms.json  (reuse saved trace)

Controls:
    Left-click  : add vertex
    Right-click : close polygon → prompts for room name
    'e' key     : toggle exclusion mode (trace island/cabinet inside room)
    'u' key     : undo last vertex
    'r' key     : delete last room
    'q' key     : finish tracing → runs Warmset engine
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.backend_bases import MouseButton, KeyEvent, MouseEvent
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.logging import setup_logging, get_logger

setup_logging(level="INFO")
logger = get_logger("tracer")


class TracedRoom:
    """A room traced by the user, with optional exclusion sub-polygons."""

    def __init__(self, name: str = "Unknown"):
        self.name = name
        self.vertices: list[tuple[float, float]] = []
        self.exclusions: list[list[tuple[float, float]]] = []
        self._active_exclusion: Optional[list[tuple[float, float]]] = None

    def close_exclusion(self) -> bool:
        if self._active_exclusion and len(self._active_exclusion) >= 3:
            self.exclusions.append(list(self._active_exclusion))
            self._active_exclusion = None
            return True
        self._active_exclusion = None
        return False

    @property
    def area(self) -> float:
        if len(self.vertices) < 3:
            return 0.0
        from shapely.geometry import Polygon
        return Polygon(self.vertices).area

    def to_polygon(self):
        from shapely.geometry import Polygon
        if len(self.vertices) < 3:
            return None
        return Polygon(self.vertices)

    def exclusion_polygons(self):
        from shapely.geometry import Polygon
        return [Polygon(e) for e in self.exclusions if len(e) >= 3]


class InteractiveTracer:
    """Matplotlib interactive polygon tracer.

    Converts pixel coordinates on screen back to real-world metres.
    """

    def __init__(self, input_path: str):
        self.input_path = Path(input_path)
        self.rooms: list[TracedRoom] = []
        self._current: Optional[TracedRoom] = None
        self._exclusion_mode = False
        self._img: Optional[np.ndarray] = None
        self._fig: Optional[plt.Figure] = None
        self._ax: Optional[plt.Axes] = None

        # Coordinate mapping: user clicks in image pixels,
        # we convert to metres for the engine.
        self._pixel_to_metres: Optional[float] = None  # constant scale (PDF)
        self._dxf_bounds: Optional[tuple] = None  # bounds-based mapping (DXF)
        self._img_size: Optional[tuple[int, int]] = None

    # ---- Loading ----

    def load(self) -> None:
        suffix = self.input_path.suffix.lower()
        if suffix == ".pdf":
            self._load_pdf()
        elif suffix == ".dxf":
            self._load_dxf()
        else:
            raise ValueError(f"Unsupported: {suffix}")

    def _load_pdf(self) -> None:
        import fitz
        doc = fitz.open(str(self.input_path))
        page = doc[0]
        zoom = 150 / 72  # pixels per PDF point
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if img.shape[2] == 4:
            img = img[:, :, :3]
        self._img = img
        self._img_size = (img.shape[1], img.shape[0])
        # PDF points → mm: 1 pt = 25.4/72 mm
        # pixel at zoom → point = pixel / zoom → mm = point * 25.4/72 → m = mm / 1000
        self._pixel_to_metres = 1.0 / zoom * 25.4 / 72 / 1000.0
        self._dxf_bounds = None
        logger.info("PDF loaded: %s (%d×%d)  pixel→m = %.8f",
                    self.input_path, img.shape[1], img.shape[0], self._pixel_to_metres)

    def _load_dxf(self) -> None:
        import ezdxf
        doc = ezdxf.readfile(str(self.input_path))
        msp = doc.modelspace()

        from src.cad.units import UnitDetector
        detector = UnitDetector(doc)
        unit = detector.detect()
        logger.info("DXF units: %s → m factor = %.6f", unit.label, unit.to_metres)

        xs, ys = [], []
        for e in msp:
            try:
                b = e.bbox()
                if b:
                    xs += [b.extmin.x, b.extmax.x]
                    ys += [b.extmin.y, b.extmax.y]
            except Exception:
                pass
        if not xs:
            raise ValueError("Empty DXF")

        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        m = (maxx - minx) * 0.05 or 10
        bounds = (minx - m, maxx + m, miny - m, maxy + m)

        fig, ax = plt.subplots(figsize=(14, 10))
        ax.set_xlim(bounds[0], bounds[1])
        ax.set_ylim(bounds[2], bounds[3])
        ax.set_aspect("equal")
        ax.grid(True, alpha=0.3)

        for e in msp:
            try:
                if e.dxftype() == "LINE":
                    ax.plot([e.dxf.start.x, e.dxf.end.x],
                            [e.dxf.start.y, e.dxf.end.y], "k-", lw=0.3, alpha=0.6)
                elif e.dxftype() == "LWPOLYLINE":
                    pts = e.get_points("xy")
                    px = [p[0] for p in pts] + [pts[0][0]]
                    py = [p[1] for p in pts] + [pts[0][1]]
                    ax.plot(px, py, "k-", lw=0.3, alpha=0.6)
                elif e.dxftype() == "MTEXT":
                    t = e.dxf.text[:30].replace("\n", " ")
                    ax.text(e.dxf.insert.x, e.dxf.insert.y, t, fontsize=4, alpha=0.4)
            except Exception:
                pass

        fig.canvas.draw()
        buf = fig.canvas.buffer_rgba()
        img = np.asarray(buf)[:, :, :3]
        plt.close(fig)

        self._img = img
        self._img_size = (img.shape[1], img.shape[0])
        self._dxf_bounds = bounds
        self._dxf_unit_to_m = unit.to_metres
        self._pixel_to_metres = None  # DXF uses bounds, not constant scale
        logger.info("DXF loaded: %s  bounds=(%.0f, %.0f, %.0f, %.0f)",
                    self.input_path, *bounds)

    # ---- Coordinate conversion ----

    def _to_metres(self, px_x: float, px_y: float) -> tuple[float, float]:
        """Convert image pixel coordinates to metres."""
        if self._pixel_to_metres is not None:
            # PDF: constant scale
            return (px_x * self._pixel_to_metres, px_y * self._pixel_to_metres)
        elif self._dxf_bounds is not None and self._img_size is not None:
            # DXF: map pixel → drawing coord → metres
            img_w, img_h = self._img_size
            bx0, bx1, by0, by1 = self._dxf_bounds
            dx = (bx1 - bx0) / img_w
            dy = (by1 - by0) / img_h
            drawing_x = bx0 + px_x * dx
            drawing_y = by0 + px_y * dy
            return (drawing_x * self._dxf_unit_to_m, drawing_y * self._dxf_unit_to_m)
        return (px_x, px_y)  # fallback: raw pixels

    # ---- Interactive loop ----

    def run(self) -> list[TracedRoom]:
        if self._img is None:
            raise RuntimeError("No image loaded. Call load() first.")

        self._fig, self._ax = plt.subplots(figsize=(16, 12))
        self._ax.imshow(self._img, origin="upper")
        self._ax.set_title(
            "Left: vertex | Right: close room | 'e': exclusion | 'u': undo | 'r': remove | 'q': finish",
            fontsize=9, fontfamily="monospace",
        )
        self._ax.grid(True, alpha=0.3, color="blue")

        self._fig.canvas.mpl_connect("button_press_event", self._on_click)
        self._fig.canvas.mpl_connect("key_press_event", self._on_key)

        plt.tight_layout()
        plt.show(block=True)
        return self.rooms

    def _on_click(self, event: MouseEvent) -> None:
        if event.inaxes != self._ax:
            return
        # Convert pixel position to metres
        pt_m = self._to_metres(event.xdata, event.ydata)

        if event.button is MouseButton.LEFT:
            if self._current is None:
                self._current = TracedRoom()
                self._exclusion_mode = False
            if self._exclusion_mode:
                if self._current._active_exclusion is None:
                    self._current._active_exclusion = []
                self._current._active_exclusion.append(pt_m)
            else:
                self._current.vertices.append(pt_m)
            self._redraw()

        elif event.button is MouseButton.RIGHT:
            if self._current is None:
                return
            if self._exclusion_mode:
                self._current.close_exclusion()
                self._exclusion_mode = False
                self._redraw()
                return
            if len(self._current.vertices) < 3:
                return
            name = input(f"  Room name [{len(self._current.vertices)} pts, "
                         f"{self._current.area:.2f} m²]: ").strip() or "Unknown"
            self._current.name = name
            self.rooms.append(self._current)
            self._current = None
            self._exclusion_mode = False
            self._redraw()

    def _on_key(self, event: KeyEvent) -> None:
        if event.key == "e":
            if self._current is not None and len(self._current.vertices) >= 3:
                self._exclusion_mode = not self._exclusion_mode
                if not self._exclusion_mode and self._current._active_exclusion:
                    self._current.close_exclusion()
                print(f"  Exclusion {'ON' if self._exclusion_mode else 'OFF'}")
                self._redraw()
        elif event.key == "u":
            if self._current is not None:
                if self._exclusion_mode and self._current._active_exclusion:
                    self._current._active_exclusion.pop()
                elif not self._exclusion_mode and self._current.vertices:
                    self._current.vertices.pop()
                self._redraw()
        elif event.key == "r":
            if self.rooms:
                print(f"  Removed: {self.rooms.pop().name}")
            elif self._current is not None:
                self._current = None
                self._exclusion_mode = False
            self._redraw()
        elif event.key == "q":
            if self._current is not None and len(self._current.vertices) >= 3:
                self._current.name = input(f"  Name [{self._current.area:.1f} m²]: ").strip() or "Unknown"
                self.rooms.append(self._current)
                self._current = None
            plt.close(self._fig)

    def _redraw(self) -> None:
        ax = self._ax
        for l in ax.lines[:]: l.remove()
        for c in ax.collections[:]: c.remove()
        for t in ax.texts[:]: t.remove()
        for p in ax.patches[:]: p.remove()

        # Completed rooms
        for i, room in enumerate(self.rooms):
            color = plt.cm.tab10(i % 10)
            poly = room.to_polygon()
            if poly:
                xs, ys = poly.exterior.xy
                ax.fill(xs, ys, alpha=0.25, fc=color, ec="lime", lw=2)
                cx, cy = poly.centroid.x, poly.centroid.y
                ax.text(cx, cy, f"{room.name}\n{poly.area:.1f}m²", fontsize=8,
                        ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.3", fc="white", alpha=0.8, ec=color))
            for exc in room.exclusion_polygons():
                xs, ys = exc.exterior.xy
                ax.fill(xs, ys, alpha=0.5, fc="red", ec="darkred", lw=1.5, hatch="///")

        # Current room
        if self._current is not None:
            verts = self._current.vertices
            if verts:
                xs, ys = zip(*verts)
                ax.scatter(xs, ys, c="lime", s=30, zorder=5)
                ax.fill(xs, ys, alpha=0.15, fc="lime", ec="lime", lw=2)
                for i in range(len(verts) - 1):
                    ax.plot([verts[i][0], verts[i + 1][0]],
                            [verts[i][1], verts[i + 1][1]], "lime", lw=2)

            if self._exclusion_mode and self._current._active_exclusion:
                ev = self._current._active_exclusion
                if ev:
                    xs, ys = zip(*ev)
                    ax.scatter(xs, ys, c="red", s=30, zorder=5, marker="x")
                    ax.fill(xs, ys, alpha=0.3, fc="red", ec="red", lw=2, hatch="///")

        nv = len(self._current.vertices) if self._current else 0
        ne = len(self._current.exclusions) if self._current else 0
        mode = "EXCL" if self._exclusion_mode else "ROOM"
        ax.set_title(
            f"[{mode}] verts={nv} excl={ne} rooms={len(self.rooms)}",
            fontsize=9, fontfamily="monospace",
        )
        self._fig.canvas.draw_idle()


def run_engine(rooms: list[TracedRoom], output_dir: Path) -> None:
    """Feed traced rooms (already in metres) into the Warmset engine."""
    from src.models.rooms import Room, ExclusionArea
    from src.heating.polygons import HeatingPolygonGenerator
    from src.heating.strips import WarmsetStripGenerator
    from src.heating.calculator import HeatingCalculator
    from src.report.json_report import JSONReport
    from src.report.xlsx_report import XLSXReport
    from src.report.pdf_report import PDFReport

    output_dir.mkdir(parents=True, exist_ok=True)

    engine_rooms = []
    for traced in rooms:
        poly = traced.to_polygon()
        if poly is None:
            continue
        area = poly.area
        room = Room(
            name=traced.name,
            polygon=poly,
            centroid=(poly.centroid.x, poly.centroid.y),
            bounding_box=poly.bounds,
            confidence=0.95,
            gross_area_m2=area,
        )
        for exc_poly in traced.exclusion_polygons():
            room.exclusions.append(ExclusionArea(
                polygon=exc_poly,
                reason=f"{traced.name} — user exclusion",
                source_type="manual",
            ))
        engine_rooms.append(room)

    # Run engine
    poly_gen = HeatingPolygonGenerator()
    strip_gen = WarmsetStripGenerator()
    calculator = HeatingCalculator()

    engine_rooms = poly_gen.generate(engine_rooms)
    engine_rooms = strip_gen.generate(engine_rooms)
    engine_rooms = calculator.calculate(engine_rooms)
    totals = calculator.totals(engine_rooms)

    # Reports
    quality = {"suitability_score": 95, "reconstruction_confidence": 95,
               "verdict": "User-traced geometry", "drawing_units": "m", "dxf_version": "N/A"}
    JSONReport().generate(engine_rooms, quality, totals, output_dir / "report.json")
    XLSXReport().generate(engine_rooms, totals, output_dir / "report.xlsx")
    PDFReport().generate(engine_rooms, totals, quality, output_dir / "report.pdf")

    # Save trace for reuse
    trace_data = {
        "rooms": [{
            "name": r.name,
            "area_m2": round(r.area, 3),
            "vertices": [(round(x, 4), round(y, 4)) for x, y in r.vertices],
            "exclusions": [[(round(x, 4), round(y, 4)) for x, y in e] for e in r.exclusions],
        } for r in rooms]
    }
    with open(output_dir / "traced_rooms.json", "w") as f:
        json.dump(trace_data, f, indent=2)

    # Summary
    print(f"\n{'=' * 55}")
    print(f"  Warmset Takeoff Complete")
    print(f"{'=' * 55}")
    for room in engine_rooms:
        print()
        if room.calculation:
            print(room.calculation.to_text_block(room.name))
        else:
            print(f"  {room.name}: {room.gross_area_m2:.2f} m², "
                  f"{room.strip_count} strips, {room.total_linear_m:.1f} m")

    import json as _json
    print(f"\n  TOTALS")
    for k, v in totals.items():
        print(f"    {k}: {v}")
    print(f"\n  Reports: {output_dir}/")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"Not found: {path}")
        sys.exit(1)

    load_traced = None
    if "--load-traced" in sys.argv:
        idx = sys.argv.index("--load-traced")
        if idx + 1 < len(sys.argv):
            load_traced = sys.argv[idx + 1]

    if load_traced:
        with open(load_traced) as f:
            data = json.load(f)
        rooms = []
        for r in data["rooms"]:
            traced = TracedRoom(r["name"])
            traced.vertices = [(v[0], v[1]) for v in r["vertices"]]
            traced.exclusions = [[(v[0], v[1]) for v in e] for e in r.get("exclusions", [])]
            rooms.append(traced)
        print(f"Loaded {len(rooms)} rooms from {load_traced}")
    else:
        tracer = InteractiveTracer(path)
        tracer.load()
        rooms = tracer.run()
        if not rooms:
            print("No rooms traced.")
            sys.exit(1)

    run_engine(rooms, Path("tracer_output"))


if __name__ == "__main__":
    main()
