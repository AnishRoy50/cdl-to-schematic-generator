"""Placement data-classes consumed by the ASCII renderer.

Each placement type describes *what* to draw and *where* (wire-column
position).  The :class:`~cdl_to_schematic.layout.engine.LayoutEngine`
produces a list of these objects; the
:class:`~cdl_to_schematic.renderer.ascii_renderer.ASCIIRenderer` consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from models import Component, MOSFET


@dataclass
class CMOSGatePlacement:
    """A CMOS logic gate with complementary pull-up and pull-down networks.

    Handles inverters, NAND, NOR, and arbitrary CMOS topologies by
    classifying pull-up (PMOS) and pull-down (NMOS) networks as
    ``"parallel"`` or ``"series"``.
    """
    pullup_mos: List[MOSFET]       # PMOS transistors (pull-up network)
    pulldown_mos: List[MOSFET]     # NMOS transistors (pull-down network)
    pullup_topology: str           # "parallel" or "series"
    pulldown_topology: str         # "parallel" or "series"
    output_net: str
    supply_net: str
    ground_net: str
    wc_mid: int                    # centre wire column


@dataclass
class SingleMOSPlacement:
    """A standalone MOSFET (not part of any recognised CMOS gate)."""
    mos: MOSFET
    wc: int


@dataclass
class GenericPlacement:
    """A non-MOSFET component (subcircuit instance, R, C, etc.)."""
    comp: Component
    wc: int
