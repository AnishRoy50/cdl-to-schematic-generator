"""CDL Netlist to ASCII Schematic Converter.

A modular Python package that reads ``.cdl`` netlist files, detects CMOS
gate topologies, and generates readable ASCII schematics.

Quick usage::

    from cdl_to_schematic import NetlistParser, SchematicBuilder

    circuit = NetlistParser().parse_file("input.cdl")
    print(SchematicBuilder(circuit).build_all())

Or from the command line::

    python -m cdl_to_schematic input.cdl output.txt
"""

from models import (
    ComponentType,
    MOSType,
    Net,
    Component,
    MOSFET,
    SubcktInstance,
    Resistor,
    Capacitor,
    Diode,
    BJT,
    Subckt,
    Circuit,
)
from parser import NetlistParser
from layout import LayoutEngine, CMOSGatePlacement, SingleMOSPlacement, GenericPlacement
from renderer import ASCIIRenderer
from builder import SchematicBuilder

__all__ = [
    # Models
    "ComponentType", "MOSType", "Net", "Component",
    "MOSFET", "SubcktInstance", "Resistor", "Capacitor", "Diode", "BJT",
    "Subckt", "Circuit",
    # Parser
    "NetlistParser",
    # Layout
    "LayoutEngine", "CMOSGatePlacement", "SingleMOSPlacement", "GenericPlacement",
    # Renderer
    "ASCIIRenderer",
    # Builder
    "SchematicBuilder",
]
