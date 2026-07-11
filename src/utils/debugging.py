"""Debug visualization generation for each stage of the pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from shapely.geometry import Polygon, MultiPolygon, LineString, MultiLineString, Point
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from src.utils.config import get_settings
from src.utils.logging import get_logger
from src.models.rooms import Room, ExclusionArea, HeatingPolygon, WarmsetStrip

logger = get_logger("utils.debugging")


class DebugVisualizer:
    """Generates colour-coded debug images for each pipeline stage."""

    def __init__(self, output_dir: Optional[Path] = None):
        settings = get_settings()
        self.output_dir = output_dir or settings.output.debug_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.rooms: list[Room] = []
        self.bounds: tuple[float, float, float, float] | None = None

    def set_rooms(self, rooms: list[Room]) -> None:
        self.rooms = rooms
        if rooms:
            xs = []
            ys = []
            for r in rooms:
                if r.polygon is not None:
                    xs.extend([r.polygon.bounds[0], r.polygon.bounds[2]])
                    ys.extend([r.polygon.bounds[1], r.polygon.bounds[3]])
            if xs and ys:
                margin = 0.5
                self.bounds = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)

    def _setup_plot(self, title: str) -> tuple[plt.Figure, plt.Axes]:
        fig, ax = plt.subplots(1, 1, figsize=(14, 10))
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.set_aspect("equal")
        if self.bounds:
            ax.set_xlim(self.bounds[0], self.bounds[2])
            ax.set_ylim(self.bounds[1], self.bounds[3])
        ax.grid(True, alpha=0.3)
        return fig, ax

    def _plot_polygon(self, ax: plt.Axes, geom, color: str = "blue", alpha: float = 0.3, label: Optional[str] = None, edgecolor: Optional[str] = None) -> None:
        if geom is None:
            return
        if isinstance(geom, MultiPolygon):
            for g in geom.geoms:
                self._plot_polygon(ax, g, color, alpha, label, edgecolor)
            return
        if not isinstance(geom, Polygon):
            return
        xs, ys = geom.exterior.xy
        ax.fill(xs, ys, alpha=alpha, fc=color, ec=edgecolor or color, linewidth=1.0)
        if label:
            centroid = geom.centroid
            ax.text(centroid.x, centroid.y, label, fontsize=8, ha="center", va="center",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7, edgecolor="gray"))

    def _plot_line(self, ax: plt.Axes, geom, color: str = "blue", linewidth: float = 0.5, alpha: float = 1.0) -> None:
        if geom is None:
            return
        if isinstance(geom, MultiLineString):
            for g in geom.geoms:
                self._plot_line(ax, g, color, linewidth, alpha)
            return
        if isinstance(geom, LineString):
            xs, ys = geom.xy
            ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha)
        elif isinstance(geom, Point):
            ax.plot(geom.x, geom.y, "o", color=color, markersize=3, alpha=alpha)

    def save_original(self, entities: list, filename: str = "original.png") -> Path:
        """Visualise all original geometry entities."""
        fig, ax = self._setup_plot("Original CAD Geometry")
        for ent in entities:
            g = ent.shapely_geometry if hasattr(ent, "shapely_geometry") else None
            if g is not None:
                if hasattr(g, "exterior"):
                    self._plot_polygon(ax, g, "lightgray", 0.1, edgecolor="gray")
                else:
                    self._plot_line(ax, g, "blue", 0.5)
        path = self.output_dir / filename
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved debug image: %s", path)
        return path

    def save_rooms(self, filename: str = "rooms.png") -> Path:
        """Visualise detected rooms with names."""
        fig, ax = self._setup_plot("Detected Rooms")
        colors = plt.cm.tab20.colors
        for i, room in enumerate(self.rooms):
            color = colors[i % len(colors)]
            self._plot_polygon(ax, room.polygon, color, 0.3, room.name, edgecolor="black")
            if room.polygon is not None:
                cx, cy = room.polygon.centroid.x, room.polygon.centroid.y
                label = f"{room.name}\n{room.gross_area_m2:.1f}m²"
                ax.text(cx, cy, label, fontsize=7, ha="center", va="center",
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="white", alpha=0.8, edgecolor="gray"))
        path = self.output_dir / filename
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved debug image: %s", path)
        return path

    def save_heating(self, filename: str = "heating.png") -> Path:
        """Visualise heating polygons."""
        fig, ax = self._setup_plot("Heating Areas (with setbacks)")
        colors = plt.cm.Set2.colors
        for i, room in enumerate(self.rooms):
            color = colors[i % len(colors)]
            if room.heating_polygon and room.heating_polygon.polygon:
                self._plot_polygon(ax, room.heating_polygon.polygon, color, 0.5, edgecolor="darkgreen")
            # Also show exclusions in red
            for exc in room.exclusions:
                self._plot_polygon(ax, exc.polygon, "red", 0.5)
        red_patch = mpatches.Patch(color="red", alpha=0.5, label="Exclusions")
        green_patch = mpatches.Patch(color="green", alpha=0.3, label="Heated Area")
        ax.legend(handles=[green_patch, red_patch], loc="upper right")
        path = self.output_dir / filename
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved debug image: %s", path)
        return path

    def save_strips(self, filename: str = "strips.png") -> Path:
        """Visualise Warmset strips."""
        fig, ax = self._setup_plot("Warmset Strip Layout")
        for room in self.rooms:
            for strip in room.strips:
                if strip.geometry is not None:
                    self._plot_line(ax, strip.geometry, "orange", 2.0)
            # Show heating polygon outline
            if room.heating_polygon and room.heating_polygon.polygon:
                self._plot_polygon(ax, room.heating_polygon.polygon, "none", 0, edgecolor="darkgreen")
        orange_patch = mpatches.Patch(color="orange", label="Warmset Strips (500mm)")
        ax.legend(handles=[orange_patch], loc="upper right")
        path = self.output_dir / filename
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved debug image: %s", path)
        return path

    def save_labels(self, filename: str = "labels.png") -> Path:
        """Visualise room labels and dimensions."""
        fig, ax = self._setup_plot("Room Labels & Dimensions")
        for room in self.rooms:
            if room.polygon is not None:
                self._plot_polygon(ax, room.polygon, "lightblue", 0.15, edgecolor="gray")
            for label in room.labels:
                ax.plot(label.position[0], label.position[1], "r*", markersize=8)
                ax.text(label.position[0], label.position[1] + 0.2, label.text, fontsize=6,
                        ha="center", va="bottom", color="darkred",
                        bbox=dict(boxstyle="round,pad=0.1", facecolor="white", alpha=0.7))
        path = self.output_dir / filename
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved debug image: %s", path)
        return path

    def save_quality(self, report: dict, filename: str = "quality.png") -> Path:
        """Generate a compact quality-score dashboard."""
        fig, ax = self._setup_plot("DXF Quality Analysis")
        ax.axis("off")

        score = report.get("suitability_score", 0)
        confidence = report.get("reconstruction_confidence", 0)

        # Progress bar for score
        ax.barh(0, score, height=0.4, color="#2ecc71" if score >= 70 else "#f39c12" if score >= 40 else "#e74c3c")
        ax.text(score + 1, 0, f"{score:.0f}%", va="center", fontsize=12, fontweight="bold")
        ax.set_yticks([0])
        ax.set_yticklabels(["Suitability"])
        ax.set_xlim(0, 100)

        info_lines = [
            f"DXF Version: {report.get('dxf_version', 'N/A')}",
            f"Drawing Units: {report.get('drawing_units', 'N/A')}",
            f"Reconstruction Confidence: {confidence:.0f}%",
            f"Total Entities: {report.get('total_entities', 0)}",
            f"Closed Polygons: {report.get('closed_polygons', 0)}",
            f"Open Polylines: {report.get('open_polylines', 0)}",
            f"Disconnected Segments: {report.get('disconnected_segments', 0)}",
            f"Duplicate Entities: {report.get('duplicate_entities', 0)}",
            f"Tiny Fragments: {report.get('tiny_fragments', 0)}",
        ]
        verdict = report.get("verdict", "Unknown")
        for i, line in enumerate(info_lines):
            ax.text(0, -1 - i, line, fontsize=9, fontfamily="monospace", va="top")
        ax.text(50, -1 - len(info_lines) - 1, verdict, fontsize=11, ha="center",
                fontweight="bold", color="#2ecc71" if confidence >= 70 else "#e74c3c")

        path = self.output_dir / filename
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)
        logger.info("Saved debug image: %s", path)
        return path

    def save_all(self, entities: list, quality_report: dict) -> list[Path]:
        """Generate all debug images."""
        paths = []
        paths.append(self.save_original(entities))
        paths.append(self.save_quality(quality_report))
        if self.rooms:
            paths.append(self.save_rooms())
            paths.append(self.save_heating())
            paths.append(self.save_strips())
            paths.append(self.save_labels())
        return paths
