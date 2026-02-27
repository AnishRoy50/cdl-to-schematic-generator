"""Command-line interface for the CDL-to-schematic converter."""

from __future__ import annotations

import argparse
import logging
import sys

from parser import NetlistParser
from builder import SchematicBuilder

logger = logging.getLogger("cdl2schematic")


def main() -> None:
    """CLI entry point."""
    ap = argparse.ArgumentParser(
        description="Convert a CDL netlist to an ASCII schematic (.txt).",
        epilog="Example: python -m cdl_to_schematic input.cdl output.txt",
    )
    ap.add_argument("input", help="Path to input .cdl netlist file")
    ap.add_argument("output", help="Path to output .txt schematic file")
    ap.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    # Parse
    parser = NetlistParser()
    try:
        circuit = parser.parse_file(args.input)
    except Exception as exc:
        logger.error("Failed to parse input file: %s", exc)
        sys.exit(1)

    # Build schematics
    builder = SchematicBuilder(circuit)
    schematic_text = builder.build_all()

    # Write output
    try:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(schematic_text)
        logger.info("Schematic written to %s", args.output)
    except OSError as exc:
        logger.error("Failed to write output file: %s", exc)
        sys.exit(1)

    print(f"Done. Schematic saved to: {args.output}")
