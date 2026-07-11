import os
import sys
import tempfile
import shutil
import json
from zipfile import ZipFile
from pathlib import Path

import streamlit as st
import fitz
from PIL import Image, ImageDraw
import pandas as pd

try:
    from streamlit_drawable_canvas import st_canvas
except ImportError:
    st_canvas = None

sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

try:
    from converter import PDF2DXFConverter
except ImportError:
    st.error("Could not import converter. Make sure 'src/converter.py' exists.")
    st.stop()

from src.utils.logging import setup_logging
from src.models.rooms import Room, ExclusionArea
from src.heating.polygons import HeatingPolygonGenerator
from src.heating.strips import WarmsetStripGenerator
from src.heating.calculator import HeatingCalculator
from src.report.json_report import JSONReport
from src.report.xlsx_report import XLSXReport
from src.report.pdf_report import PDFReport

setup_logging(level="ERROR")

st.set_page_config(
    page_title="Warmset CAD Engine",
    page_icon="🔥",
    layout="wide",
    menu_items={'Get Help': None, 'Report a bug': None, 'About': None}
)

hide_menu = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
"""
st.markdown(hide_menu, unsafe_allow_html=True)

tab_convert, tab_takeoff = st.tabs(["📐 PDF → DXF", "🔥 Warmset Takeoff"])

# ============================================================
# TAB 1: PDF → DXF Converter (existing functionality)
# ============================================================

with tab_convert:
    st.title("📐 PDF to DXF Converter")
    st.markdown("Convert PDF drawings to DXF format.")

    uploaded_files = st.file_uploader("Choose PDF file(s)", type="pdf", accept_multiple_files=True, key="conv_files")

    with st.sidebar:
        st.header("Extract Content")
        include_geom = st.checkbox("Geometry", True)
        include_text = st.checkbox("Text", True)
        st.header("Filter")
        skip_curves = st.checkbox("Skip Curves", False)
        min_size = st.number_input("Min Size (pts)", 0.0, 99999.0, 0.0, 1.0)
        st.header("Pages")
        all_pages = st.checkbox("All pages", True)
        if not all_pages:
            c1, c2 = st.columns(2)
            pg_from = c1.number_input("From", 1, 99999, 1)
            pg_to = c2.number_input("To", 1, 99999, 99999)
        else:
            pg_from, pg_to = 1, 99999

    if "crop_rect" not in st.session_state:
        st.session_state.crop_rect = None

    if uploaded_files:
        st.markdown("### Preview & Crop")
        preview_name = st.selectbox("File", [f.name for f in uploaded_files])
        file_obj = next(f for f in uploaded_files if f.name == preview_name)
        file_obj.seek(0)

        try:
            doc = fitz.open(stream=file_obj.read(), filetype="pdf")
            total = len(doc)
            page_num = st.number_input("Page", 1, total, 1) - 1
            page = doc[page_num]
            pw, ph = page.rect.width, page.rect.height

            enable_crop = st.checkbox("Crop region")
            if enable_crop and st_canvas is not None:
                scale = min(1.0, 700.0 / pw)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                canvas = st_canvas(
                    fill_color="rgba(255,0,0,0.3)", stroke_width=2,
                    stroke_color="red", background_image=img,
                    update_streamlit=True, height=img.height, width=img.width,
                    drawing_mode="rect", key="crop_canvas",
                )
                if canvas.json_data and canvas.json_data["objects"]:
                    obj = canvas.json_data["objects"][-1]
                    x, y = obj["left"], obj["top"]
                    w, h = obj["width"] * obj["scaleX"], obj["height"] * obj["scaleY"]
                    x1, x2 = min(x, x + w), max(x, x + w)
                    y1, y2 = min(y, y + h), max(y, y + h)
                    crop = (
                        max(0, x1 / scale), max(0, y1 / scale),
                        min(pw, x2 / scale), min(ph, y2 / scale),
                    )
                    st.session_state.crop_rect = crop if crop[0] < crop[2] and crop[1] < crop[3] else None
            elif enable_crop:
                st.warning("Install streamlit-drawable-canvas for crop UI.")

            doc.close()
        except Exception as e:
            st.error(f"Preview error: {e}")
        finally:
            file_obj.seek(0)

        if st.button("Convert to DXF"):
            with st.spinner("Converting..."):
                with tempfile.TemporaryDirectory() as tmpdir:
                    prog = st.progress(0)
                    for idx, f_obj in enumerate(uploaded_files):
                        inpath = os.path.join(tmpdir, f_obj.name)
                        with open(inpath, "wb") as f:
                            f.write(f_obj.getbuffer())
                        base = os.path.splitext(f_obj.name)[0]
                        outpath = os.path.join(tmpdir, f"{base}.dxf")
                        try:
                            d = fitz.open(inpath)
                            n = len(d)
                            d.close()
                            p1 = max(1, pg_from)
                            p2 = min(n, pg_to)
                            pages = list(range(p1 - 1, p2))
                            if pages:
                                PDF2DXFConverter(inpath).convert(
                                    outpath, pages=pages,
                                    crop_rect=st.session_state.crop_rect,
                                    min_size=min_size, skip_curves=skip_curves,
                                    include_geom=include_geom, include_text=include_text,
                                )
                        except Exception as e:
                            st.error(f"Error: {e}")
                        prog.progress((idx + 1) / len(uploaded_files))

                    dxfs = [f for f in os.listdir(tmpdir) if f.endswith(".dxf")]
                    if not dxfs:
                        st.error("No DXF generated.")
                    elif len(dxfs) == 1:
                        with open(os.path.join(tmpdir, dxfs[0]), "rb") as f:
                            st.download_button("Download DXF", f, dxfs[0], "application/dxf")
                        st.success("Done!")
                    else:
                        zippath = os.path.join(tmpdir, "dxfs.zip")
                        with ZipFile(zippath, "w") as z:
                            for f in dxfs:
                                z.write(os.path.join(tmpdir, f), f)
                        with open(zippath, "rb") as f:
                            st.download_button("Download All (ZIP)", f, "dxfs.zip", "application/zip")
                        st.success(f"{len(dxfs)} files generated.")

# ============================================================
# TAB 2: Warmset Takeoff (interactive room tracing)
# ============================================================

with tab_takeoff:
    st.title("🔥 Warmset Takeoff")
    st.markdown("Trace rooms and exclusions on your plan, then generate a heating report.")

    uploaded = st.file_uploader("Upload PDF or DXF", type=["pdf", "dxf"], key="takeoff_file")

    if uploaded:
        suffix = os.path.splitext(uploaded.name)[1].lower()
        tmpdir = tempfile.mkdtemp()
        tmppath = os.path.join(tmpdir, f"input{suffix}")
        with open(tmppath, "wb") as f:
            f.write(uploaded.getbuffer())

        # ---- Render display image ----
        pixel_to_mm = None
        bounds = None
        unit_to_m = None

        if suffix == ".pdf":
            doc = fitz.open(tmppath)
            page = doc[0]
            pw, ph = page.rect.width, page.rect.height
            display_scale = min(1.0, 1000.0 / pw)
            pix = page.get_pixmap(matrix=fitz.Matrix(display_scale, display_scale), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pixel_to_mm = 1.0 / display_scale * 25.4 / 72.0
            doc.close()
        else:
            import ezdxf
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from src.cad.units import UnitDetector

            doc = ezdxf.readfile(tmppath)
            detector = UnitDetector(doc)
            unit = detector.detect()
            unit_to_m = unit.to_metres
            msp = doc.modelspace()

            # Collect all coordinates directly (avoid bbox() which fails on most types)
            xs, ys = [], []
            for e in msp:
                try:
                    t = e.dxftype()
                    if t == "LINE":
                        xs += [e.dxf.start.x, e.dxf.end.x]
                        ys += [e.dxf.start.y, e.dxf.end.y]
                    elif t == "LWPOLYLINE":
                        for p in e.get_points("xy"):
                            xs.append(p[0]); ys.append(p[1])
                    elif t == "CIRCLE":
                        xs.append(e.dxf.center.x - e.dxf.radius)
                        xs.append(e.dxf.center.x + e.dxf.radius)
                        ys.append(e.dxf.center.y - e.dxf.radius)
                        ys.append(e.dxf.center.y + e.dxf.radius)
                    elif t == "ARC":
                        xs.append(e.dxf.center.x - e.dxf.radius)
                        xs.append(e.dxf.center.x + e.dxf.radius)
                        ys.append(e.dxf.center.y - e.dxf.radius)
                        ys.append(e.dxf.center.y + e.dxf.radius)
                    elif t == "MTEXT":
                        xs.append(e.dxf.insert.x); ys.append(e.dxf.insert.y)
                    elif t == "TEXT":
                        xs.append(e.dxf.insert.x); ys.append(e.dxf.insert.y)
                except Exception:
                    pass

            if not xs:
                st.error("Could not determine drawing extents")
                st.stop()

            minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
            margin = (maxx - minx) * 0.05 or 10
            bounds = (minx - margin, maxx + margin, miny - margin, maxy + margin)

            fig, ax = plt.subplots(figsize=(12, 9))
            ax.set_xlim(bounds[0], bounds[1])
            ax.set_ylim(bounds[2], bounds[3])
            ax.set_aspect("equal")
            ax.axis("off")

            for e in msp:
                try:
                    t = e.dxftype()
                    if t == "LINE":
                        ax.plot([e.dxf.start.x, e.dxf.end.x], [e.dxf.start.y, e.dxf.end.y],
                                "k-", lw=0.3, alpha=0.6)
                    elif t == "LWPOLYLINE":
                        pts = e.get_points("xy")
                        px = [p[0] for p in pts] + [pts[0][0]]
                        py = [p[1] for p in pts] + [pts[0][1]]
                        ax.plot(px, py, "k-", lw=0.3, alpha=0.6)
                    elif t in ("CIRCLE", "ARC"):
                        c = e.dxf.center
                        ax.plot(c.x, c.y, "k.", markersize=1, alpha=0.3)
                except Exception:
                    pass

            from io import BytesIO
            buf = BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
            buf.seek(0)
            img = Image.open(buf).copy()
            buf.close()
            plt.close(fig)

        # ---- Canvas for tracing ----
        st.markdown("### 1. Trace Rooms")
        st.markdown(
            "Select **freeform** or **polygon** mode, then draw on the plan. "
            "Each shape becomes a room or exclusion below."
        )

        draw_mode = st.radio(
            "Draw mode", ["polygon", "freeform", "rect"],
            horizontal=True, index=0,
        )

        canvas_result = st_canvas(
            fill_color="rgba(0, 200, 0, 0.12)",
            stroke_width=3,
            stroke_color="#00CC00",
            background_image=img,
            update_streamlit=True,
            height=min(img.height, 800),
            width=min(img.width, 1200),
            drawing_mode=draw_mode,
            key="trace_canvas",
        )

        # ---- Extract shapes from canvas (with change detection to avoid key conflicts) ----
        if "rooms" not in st.session_state:
            st.session_state.rooms = []
            st.session_state.canvas_hash = None

        # Compute hash of current canvas to detect changes
        import hashlib
        current_hash = None
        if canvas_result and canvas_result.json_data:
            raw = json.dumps(canvas_result.json_data.get("objects", []), sort_keys=True)
            current_hash = hashlib.md5(raw.encode()).hexdigest()

        if current_hash and current_hash != st.session_state.canvas_hash:
            objects = canvas_result.json_data.get("objects", [])
            new_rooms = []

            for obj in objects:
                obj_type = obj.get("type", "")
                raw_pts = None

                if obj_type == "polygon" and "points" in obj:
                    raw_pts = obj["points"]
                elif obj_type == "path" and "path" in obj:
                    pts = []
                    for cmd in obj["path"]:
                        if len(cmd) >= 3:
                            pts.append((cmd[1], cmd[2]))
                    if len(pts) >= 3:
                        raw_pts = [{"x": p[0], "y": p[1]} for p in pts]
                elif obj_type == "rect" and "left" in obj:
                    x, y = obj["left"], obj["top"]
                    w = obj["width"] * obj.get("scaleX", 1)
                    h = obj["height"] * obj.get("scaleY", 1)
                    raw_pts = [
                        {"x": x, "y": y}, {"x": x + w, "y": y},
                        {"x": x + w, "y": y + h}, {"x": x, "y": y + h},
                    ]

                if raw_pts and len(raw_pts) >= 3:
                    if pixel_to_mm is not None:
                        verts = [(p["x"] * pixel_to_mm, p["y"] * pixel_to_mm) for p in raw_pts]
                    elif bounds is not None:
                        iw, ih = img.width, img.height
                        bx0, bx1, by0, by1 = bounds
                        dx = (bx1 - bx0) / iw
                        dy = (by1 - by0) / ih
                        verts = [(bx0 + p["x"] * dx, by0 + p["y"] * dy) for p in raw_pts]
                    else:
                        verts = [(p["x"], p["y"]) for p in raw_pts]

                    from shapely.geometry import Polygon as SPolygon
                    try:
                        poly = SPolygon(verts)
                        if poly.is_valid and poly.area > 0.01:
                            if pixel_to_mm is not None:
                                area_m = poly.area / 1_000_000
                                verts_m = [(x / 1000, y / 1000) for x, y in verts]
                            elif unit_to_m is not None:
                                area_m = poly.area * (unit_to_m ** 2)
                                verts_m = [(x * unit_to_m, y * unit_to_m) for x, y in verts]
                            else:
                                area_m = poly.area
                                verts_m = verts

                            new_rooms.append({
                                "name": "",
                                "vertices": verts_m,
                                "area_m2": round(area_m, 2),
                                "is_exclusion": False,
                            })
                    except Exception:
                        pass

            if new_rooms or (current_hash != st.session_state.canvas_hash):
                st.session_state.rooms = new_rooms
                st.session_state.canvas_hash = current_hash

        st.caption(f"**{len(st.session_state.rooms)}** shape(s) on canvas")

        # ---- Room labels ----
        if st.session_state.rooms:
            st.markdown("### 2. Label Rooms")
            st.markdown("Name each room and mark islands/cabinets as **Exclusion**.")

            for i, room in enumerate(st.session_state.rooms):
                cols = st.columns([3, 1, 0.5])
                uid = f"{st.session_state.canvas_hash or 'nocanvas'}_{i}"
                with cols[0]:
                    room["name"] = cols[0].text_input(
                        f"Shape {i+1} ({room['area_m2']} m²)",
                        value=room["name"], key=f"name_{uid}",
                    )
                with cols[1]:
                    room["is_exclusion"] = cols[1].checkbox(
                        "Exclusion", value=room["is_exclusion"], key=f"excl_{uid}",
                    )
                with cols[2]:
                    if cols[2].button("✕", key=f"del_{uid}"):
                        st.session_state.rooms.pop(i)
                        st.rerun()

        # ---- Room labels ----
        if st.session_state.rooms:
            st.markdown("### 2. Label Rooms")

            for i, room in enumerate(st.session_state.rooms):
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1:
                    name = c1.text_input(
                        f"Room {i+1} ({room['area_m2']} m²)",
                        value=room["name"],
                        key=f"name_{i}",
                    )
                    st.session_state.rooms[i]["name"] = name
                with c2:
                    excl = c2.checkbox("Exclusion", value=room["is_exclusion"], key=f"excl_{i}")
                    st.session_state.rooms[i]["is_exclusion"] = excl
                with c3:
                    if c3.button("🗑", key=f"del_{i}"):
                        st.session_state.rooms.pop(i)
                        st.rerun()

        # ---- Run engine ----
        if st.session_state.rooms:
            st.markdown("### 3. Generate Report")

            if st.button("🔥 Run Warmset Engine", type="primary"):
                with st.spinner("Calculating..."):
                    engine_rooms = []

                    for r in st.session_state.rooms:
                        from shapely.geometry import Polygon as SPolygon
                        poly = SPolygon(r["vertices"])
                        if r["is_exclusion"]:
                            continue
                        room = Room(
                            name=r["name"] or "Unknown",
                            polygon=poly,
                            centroid=(poly.centroid.x, poly.centroid.y),
                            bounding_box=poly.bounds,
                            confidence=0.95,
                            gross_area_m2=poly.area,
                        )
                        # Add other rooms as exclusions if marked
                        for other in st.session_state.rooms:
                            if other["is_exclusion"] and other["name"]:
                                try:
                                    other_poly = SPolygon(other["vertices"])
                                    if other_poly.intersects(poly) or poly.contains(other_poly):
                                        room.exclusions.append(ExclusionArea(
                                            polygon=other_poly,
                                            reason=other["name"],
                                            source_type="manual",
                                        ))
                                except Exception:
                                    pass
                        engine_rooms.append(room)

                    if not engine_rooms:
                        st.error("No rooms to process (all marked as exclusion?)")
                        st.stop()

                    # Run pipeline
                    poly_gen = HeatingPolygonGenerator()
                    strip_gen = WarmsetStripGenerator()
                    calculator = HeatingCalculator()

                    engine_rooms = poly_gen.generate(engine_rooms)
                    engine_rooms = strip_gen.generate(engine_rooms)
                    engine_rooms = calculator.calculate(engine_rooms)
                    totals = calculator.totals(engine_rooms)

                    quality = {
                        "suitability_score": 95, "reconstruction_confidence": 95,
                        "verdict": "User-traced geometry", "drawing_units": "m", "dxf_version": "N/A",
                    }

                    # Save reports
                    outdir = Path(tmpdir) / "reports"
                    outdir.mkdir(exist_ok=True)
                    JSONReport().generate(engine_rooms, quality, totals, outdir / "report.json")
                    XLSXReport().generate(engine_rooms, totals, outdir / "report.xlsx")
                    PDFReport().generate(engine_rooms, totals, quality, outdir / "report.pdf")

                    st.success(f"✅ Takeoff complete — {len(engine_rooms)} rooms processed")
                    st.balloons()

                    # ---- Results ----
                    st.markdown("### Results")

                    # Summary table
                    rows = []
                    for room in engine_rooms:
                        rows.append({
                            "Room": room.name,
                            "Gross m²": round(room.gross_area_m2, 2),
                            "Excluded m²": round(room.excluded_area_m2, 2),
                            "Setback m²": round(room.setback_area_m2, 2),
                            "Net m²": round(room.net_heatable_area_m2, 2),
                            "Strips": room.strip_count,
                            "Linear m": round(room.total_linear_m, 1),
                            "Mat m²": round(room.mat_area_m2, 2),
                            "Coverage": f"{room.coverage_pct:.0f}%",
                        })
                    df = pd.DataFrame(rows)
                    st.dataframe(df, use_container_width=True, hide_index=True)

                    # Totals
                    tc1, tc2, tc3, tc4 = st.columns(4)
                    tc1.metric("Total Gross", f"{totals['total_gross_area_m2']:.1f} m²")
                    tc2.metric("Total Net", f"{totals['total_net_heatable_area_m2']:.1f} m²")
                    tc3.metric("Total Mat", f"{totals['total_mat_area_m2']:.1f} m²")
                    tc4.metric("Total Linear", f"{totals['total_linear_m']:.0f} m")

                    # Per-room breakdown
                    with st.expander("📋 Detailed breakdown per room", expanded=True):
                        for room in engine_rooms:
                            if room.calculation:
                                st.text(room.calculation.to_text_block(room.name))
                            st.divider()

                    # Download buttons
                    d1, d2, d3, d4 = st.columns(4)
                    with open(outdir / "report.json") as f:
                        d1.download_button("📄 JSON", f, "report.json", "application/json")
                    with open(outdir / "report.xlsx", "rb") as f:
                        d2.download_button("📊 Excel", f, "report.xlsx",
                                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    with open(outdir / "report.pdf", "rb") as f:
                        d3.download_button("📕 PDF Report", f, "report.pdf", "application/pdf")

                    # Save trace data for reuse
                    trace_data = {
                        "rooms": [
                            {
                                "name": r["name"],
                                "vertices": [[round(v, 4) for v in vert] for vert in r["vertices"]],
                                "is_exclusion": r["is_exclusion"],
                                "area_m2": r["area_m2"],
                            }
                            for r in st.session_state.rooms
                        ]
                    }
                    trace_json = json.dumps(trace_data, indent=2)
                    d4.download_button("📋 Traced Rooms (JSON)", trace_json, "traced_rooms.json", "application/json")

                    # Clear button
                    if st.button("🔄 Start Over"):
                        st.session_state.rooms = []
                        st.rerun()

    st.markdown("---")
    st.caption("Trace rooms → Warmset engine calculates setbacks, strips, and coverage.")
