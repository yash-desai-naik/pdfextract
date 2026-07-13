import os

import ezdxf
import fitz  # PyMuPDF
from ezdxf.math import Vec3

from src.cad.scale_resolver import PDF_POINT_TO_MM, ScaleResolver


def clip_line_to_rect(x1, y1, x2, y2, rect):
    INSIDE = 0
    LEFT = 1
    RIGHT = 2
    BOTTOM = 4
    TOP = 8

    def compute_code(x, y):
        code = INSIDE
        if x < rect.x0:
            code |= LEFT
        elif x > rect.x1:
            code |= RIGHT
        if y < rect.y0:
            code |= BOTTOM
        elif y > rect.y1:
            code |= TOP
        return code

    code1 = compute_code(x1, y1)
    code2 = compute_code(x2, y2)

    while True:
        if code1 == 0 and code2 == 0:
            return (x1, y1, x2, y2)
        if code1 & code2:
            return None

        code_out = code1 if code1 != 0 else code2
        if code_out & TOP:
            x = x1 + (x2 - x1) * (rect.y1 - y1) / (y2 - y1)
            y = rect.y1
        elif code_out & BOTTOM:
            x = x1 + (x2 - x1) * (rect.y0 - y1) / (y2 - y1)
            y = rect.y0
        elif code_out & RIGHT:
            y = y1 + (y2 - y1) * (rect.x1 - x1) / (x2 - x1)
            x = rect.x1
        elif code_out & LEFT:
            y = y1 + (y2 - y1) * (rect.x0 - x1) / (x2 - x1)
            x = rect.x0

        if code_out == code1:
            x1, y1 = x, y
            code1 = compute_code(x1, y1)
        else:
            x2, y2 = x, y
            code2 = compute_code(x2, y2)


class PDF2DXFConverter:
    def __init__(self, pdf_path):
        self.pdf_path = pdf_path
        self.doc = None
        self.dxf = None
        self.msp = None
        self.verbose = True
        self._current_scale = None  #: ScaleResult for the page being converted

    def load_pdf(self):
        """Loads the PDF file."""
        if not os.path.exists(self.pdf_path):
            raise FileNotFoundError(f"PDF file not found: {self.pdf_path}")
        self.doc = fitz.open(self.pdf_path)

    def _setup_dxf(self):
        """Initialises the DXF document with correct unit headers and layers."""
        self.dxf = ezdxf.new()
        self.msp = self.dxf.modelspace()

        # Set correct header for millimetre data
        self.dxf.header["$INSUNITS"] = 4  # Millimetres
        self.dxf.header["$MEASUREMENT"] = 1  # Metric

        self.dxf.layers.new(name="PDF_GEOMETRY", dxfattribs={"color": 7})  # White/Black
        self.dxf.layers.new(name="PDF_TEXT", dxfattribs={"color": 1})  # Red

    def convert(
        self,
        output_path,
        pages=None,
        crop_rect=None,
        min_size=0.0,
        skip_curves=False,
        include_geom=True,
        include_text=True,
        scale_result=None,
    ):
        """Convert PDF pages to DXF with per-page scale resolution.

        Args:
            output_path: Path to save the DXF file.
            pages: List of 0-indexed page numbers. None = all.
            scale_result: Pre-resolved ScaleResult. If None, auto-detect per page.
            All other params: unchanged from original.
        """
        if not self.doc:
            self.load_pdf()

        if pages is None:
            pages = range(len(self.doc))

        resolver = ScaleResolver() if scale_result is None else None

        if len(pages) > 1:
            base, ext = os.path.splitext(output_path)
            for page_num in pages:
                if page_num >= len(self.doc):
                    print(f"Warning: Page {page_num} out of range.")
                    continue

                # Resolve scale per page
                if resolver and self.doc:
                    page_text = self.doc[page_num].get_text()
                    ps = resolver.resolve_from_text(page_text, page=page_num)
                else:
                    ps = scale_result or ScaleResolver().resolve_from_text(
                        "", page=page_num
                    )

                self._setup_dxf()
                self._current_scale = ps
                page = self.doc[page_num]
                self._convert_page(
                    page,
                    0,
                    crop_rect,
                    min_size,
                    skip_curves,
                    include_geom,
                    include_text,
                )

                page_output_path = f"{base}_page_{page_num + 1}{ext}"
                self.dxf.saveas(page_output_path)
                if self.verbose:
                    print(f"Saved page {page_num + 1} to {page_output_path}")
                    self._log_scale(ps)
        else:
            self._setup_dxf()
            if pages:
                page_num = pages[0]
                if page_num < len(self.doc):
                    if resolver and self.doc:
                        page_text = self.doc[page_num].get_text()
                        ps = resolver.resolve_from_text(page_text, page=page_num)
                    else:
                        ps = scale_result or ScaleResolver().resolve_from_text(
                            "", page=page_num
                        )
                    self._current_scale = ps
                    self._convert_page(
                        self.doc[page_num],
                        0,
                        crop_rect,
                        min_size,
                        skip_curves,
                        include_geom,
                        include_text,
                    )

            self.dxf.saveas(output_path)
            if self.verbose:
                print(f"DXF saved to {output_path}")
                if self._current_scale:
                    self._log_scale(self._current_scale)

    def _log_scale(self, scale) -> None:
        c = scale.confidence
        r = scale.scale_ratio
        src = scale.source
        if c == "high":
            print(f"  \u2713 Scale: 1:{r} (from {src})")
        elif c == "medium":
            print(f"  ? Scale: 1:{r} (from {src}, medium confidence)")
        else:
            print(f"  \u26a0 Scale: 1:{r} ({c} confidence) — verify manually")

    # ------------------------------------------------------------------ #
    #  Page conversion (scale-aware coordinate transform)                #
    # ------------------------------------------------------------------ #

    def _convert_page(
        self,
        page,
        x_offset,
        crop_rect=None,
        min_size=0.0,
        skip_curves=False,
        include_geom=True,
        include_text=True,
    ):
        """Extract vector graphics and text from a single page, applying scale."""
        page_height = page.rect.height
        mm_per_pt = (
            self._current_scale.mm_per_pdf_point
            if self._current_scale
            else PDF_POINT_TO_MM
        )

        if crop_rect and not isinstance(crop_rect, fitz.Rect):
            crop_rect = fitz.Rect(*crop_rect)

        # 1. Extract Drawings (Vectors)
        if include_geom:
            paths = page.get_drawings()
            for path in paths:
                if crop_rect:
                    path_rect = path.get("rect")
                    if path_rect:
                        if not (
                            path_rect.x0 <= crop_rect.x1
                            and path_rect.x1 >= crop_rect.x0
                            and path_rect.y0 <= crop_rect.y1
                            and path_rect.y1 >= crop_rect.y0
                        ):
                            continue

                for item in path["items"]:
                    cmd = item[0]

                    pass_size_check = True
                    if min_size > 0:
                        bbox_w = bbox_h = 0.0
                        if cmd == "l":
                            bbox_w = abs(item[1][0] - item[2][0])
                            bbox_h = abs(item[1][1] - item[2][1])
                        elif cmd == "c":
                            xs = [pt[0] for pt in item[1:5]]
                            ys = [pt[1] for pt in item[1:5]]
                            bbox_w = max(xs) - min(xs)
                            bbox_h = max(ys) - min(ys)
                        elif cmd == "re":
                            rect = item[1]
                            bbox_w = rect.width
                            bbox_h = rect.height
                        if max(bbox_w, bbox_h) < min_size:
                            pass_size_check = False
                    if not pass_size_check:
                        continue

                    if cmd == "l":  # Line
                        p1 = item[1]
                        p2 = item[2]
                        if crop_rect:
                            clipped = clip_line_to_rect(
                                p1[0], p1[1], p2[0], p2[1], crop_rect
                            )
                            if clipped is None:
                                continue
                            p1, p2 = (clipped[0], clipped[1]), (clipped[2], clipped[3])
                        # Apply scale in transform
                        self.msp.add_line(
                            self._transform_point_scaled(
                                p1, x_offset, page_height, mm_per_pt
                            ),
                            self._transform_point_scaled(
                                p2, x_offset, page_height, mm_per_pt
                            ),
                            dxfattribs={"layer": "PDF_GEOMETRY"},
                        )
                    elif cmd == "c":  # Cubic Bezier
                        if skip_curves:
                            continue
                        if crop_rect:
                            all_inside = True
                            for pt in item[1:5]:
                                if not (
                                    crop_rect.x0 <= pt[0] <= crop_rect.x1
                                    and crop_rect.y0 <= pt[1] <= crop_rect.y1
                                ):
                                    all_inside = False
                                    break
                            if not all_inside:
                                continue
                        p1, p2, p3, p4 = item[1], item[2], item[3], item[4]
                        control_points = [
                            self._transform_point_scaled(
                                p, x_offset, page_height, mm_per_pt
                            )
                            for p in (p1, p2, p3, p4)
                        ]
                        self.msp.add_spline(
                            control_points,
                            degree=3,
                            dxfattribs={"layer": "PDF_GEOMETRY"},
                        )
                    elif cmd == "re":  # Rectangle
                        rect = item[1]
                        p1 = (rect.x0, rect.y0)
                        p2 = (rect.x1, rect.y0)
                        p3 = (rect.x1, rect.y1)
                        p4 = (rect.x0, rect.y1)
                        lines = [(p1, p2), (p2, p3), (p3, p4), (p4, p1)]
                        for pt1, pt2 in lines:
                            if crop_rect:
                                clipped = clip_line_to_rect(
                                    pt1[0], pt1[1], pt2[0], pt2[1], crop_rect
                                )
                                if clipped is None:
                                    continue
                                c_p1 = (clipped[0], clipped[1])
                                c_p2 = (clipped[2], clipped[3])
                            else:
                                c_p1, c_p2 = pt1, pt2
                            self.msp.add_line(
                                self._transform_point_scaled(
                                    c_p1, x_offset, page_height, mm_per_pt
                                ),
                                self._transform_point_scaled(
                                    c_p2, x_offset, page_height, mm_per_pt
                                ),
                                dxfattribs={"layer": "PDF_GEOMETRY"},
                            )

        # 2. Extract Text (scale char_height too)
        if include_text:
            text_dict = (
                page.get_text("dict", clip=crop_rect)
                if crop_rect
                else page.get_text("dict")
            )
            for block in text_dict.get("blocks", []):
                if block.get("type", -1) == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "")
                            if not text.strip():
                                continue
                            size = span.get("size", 10) * mm_per_pt  # scale font size
                            origin = span.get("origin", (0, 0))
                            insert_point = self._transform_point_scaled(
                                origin, x_offset, page_height, mm_per_pt
                            )
                            self.msp.add_mtext(
                                text,
                                dxfattribs={
                                    "char_height": size,
                                    "insert": insert_point,
                                    "attachment_point": 7,  # BottomLeft
                                    "layer": "PDF_TEXT",
                                },
                            )

    def _transform_point_scaled(self, point, x_offset, page_height, mm_per_pt):
        """Transform PDF point → mm, flip Y, apply scale."""
        x, y = point[0], point[1]
        new_y = page_height - y
        return ((x + x_offset) * mm_per_pt, new_y * mm_per_pt)

    def _transform_point(self, point, x_offset, page_height):
        """Original Y-flip transform (no scale) — kept for backward compat."""
        x, y = point[0], point[1]
        return (x + x_offset, page_height - y)


if __name__ == "__main__":
    from cli import main

    main()
