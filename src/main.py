"""CLI entry point for the Warmset CAD Processing Engine.

Usage:
    python -m src.main input.dxf
    python -m src.main input.pdf   (converts to DXF first)
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.logging import setup_logging, get_logger
from src.utils.config import Settings
from src.pipeline import CADPipeline


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 = success, 1 = error).
    """
    parser = argparse.ArgumentParser(
        description="Warmset CAD Processing Engine — converts DXF/PDF to heating takeoff",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py input.dxf
  python main.py input.pdf
  python main.py input.dxf -o ./output
  python main.py input.dxf --verbose
        """,
    )
    parser.add_argument("input", help="Path to input DXF or PDF file")
    parser.add_argument("-o", "--output", default=".", help="Output directory (default: current dir)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    # Setup logging
    level = "DEBUG" if args.verbose else "INFO"
    setup_logging(level=level)
    logger = get_logger("main")

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        return 1

    output_dir = Path(args.output)

    # If input is PDF, convert to DXF first using the existing converter
    dxf_path = input_path
    if input_path.suffix.lower() in (".pdf",):
        logger.info("Converting PDF to DXF (using existing converter)...")
        try:
            from src.converter import PDF2DXFConverter

            dxf_path = output_dir / f"{input_path.stem}_converted.dxf"
            converter = PDF2DXFConverter(str(input_path))
            converter.convert(str(dxf_path))
            logger.info("PDF converted to DXF: %s", dxf_path)
        except Exception as exc:
            logger.error("PDF conversion failed: %s", exc)
            return 1

    # Run the CAD pipeline
    try:
        pipeline = CADPipeline()
        result = pipeline.run(dxf_path, output_dir)

        if result.success:
            print()
            print("=" * 60)
            print("  W ARMSET   PIPELINE   COMPLETE")
            print("=" * 60)
            print()
            print(f"  Rooms detected:      {len(result.rooms)}")
            print(f"  Total gross area:    {result.totals.get('total_gross_area_m2', 0):.2f} m²")
            print(f"  Total net heatable:  {result.totals.get('total_net_heatable_area_m2', 0):.2f} m²")
            print(f"  Total mat area:      {result.totals.get('total_mat_area_m2', 0):.2f} m²")
            print(f"  Total linear metres: {result.totals.get('total_linear_m', 0):.1f} m")
            print(f"  Total strips:        {result.totals.get('total_strips', 0)}")
            print(f"  Quality score:       {result.quality_report.suitability_score:.0f}%")
            print()
            print("  Output files:")

            for name, path in result.output_files.items():
                print(f"    [{name}] {path}")
            if result.debug_images:
                for img in result.debug_images:
                    print(f"    [debug] {img}")
            print()

            # Print warnings
            if result.warnings:
                print("  Warnings:")
                for w in result.warnings[:10]:
                    print(f"    ⚠ {w}")
                if len(result.warnings) > 10:
                    print(f"    ... and {len(result.warnings) - 10} more")
                print()

            return 0
        else:
            logger.error("Pipeline did not complete successfully")
            for w in result.warnings:
                logger.warning("  %s", w)
            return 1

    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
