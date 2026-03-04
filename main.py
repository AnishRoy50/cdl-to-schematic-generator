from __future__ import annotations

import argparse
import logging
import sys

from parser import NetlistParser
from builder import SchematicBuilder

logger = logging.getLogger("cdl2schematic")


def main():
    ap = argparse.ArgumentParser(
        description="Convert a CDL netlist to an ASCII schematic (.txt).")
    ap.add_argument("input", help="Path to input .cdl netlist file")
    ap.add_argument("output", help="Path to output .txt schematic file")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="Enable verbose (DEBUG) logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s")

    try:
        circuit = NetlistParser().parse_file(args.input)
        text = SchematicBuilder(circuit).build_all()
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Done. Schematic saved to: {args.output}")
    except Exception as exc:
        logger.error("Failed: %s", exc)
        sys.exit(1)


main()
