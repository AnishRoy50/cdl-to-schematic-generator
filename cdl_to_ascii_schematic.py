#!/usr/bin/env python3
"""
CDL Netlist to ASCII Schematic Converter -- backward-compatible entry point.

This file is a thin wrapper around the ``cdl_to_schematic`` package.
All logic now lives in the modular package structure::

    cdl_to_schematic/
    +-- models/          Data model (Component, MOSFET, Net, Subckt, ...)
    +-- parser/          CDL/SPICE netlist parser
    +-- layout/          CMOS topology detection & placement engine
    +-- renderer/        ASCII character-grid renderer
    +-- builder.py       Orchestrates parse -> layout -> render
    +-- cli.py           argparse CLI interface

Usage (unchanged)::

    python cdl_to_ascii_schematic.py input.cdl output.txt
    python -m cdl_to_schematic       input.cdl output.txt
"""

from cli import main

if __name__ == "__main__":
    main()
