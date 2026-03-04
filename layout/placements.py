"""Placement data-classes consumed by the ASCII renderer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from models import Component, MOSFET


@dataclass
class CMOSGatePlacement:
    """A CMOS logic gate with complementary pull-up and pull-down networks."""
    pullup_mos: List[MOSFET]
    pulldown_mos: List[MOSFET]
    pullup_topology: str       # "parallel", "series", or "parallel_series"
    pulldown_topology: str     # "parallel", "series", or "parallel_series"
    pullup_chains: List[List[MOSFET]]   # independent series chains
    pulldown_chains: List[List[MOSFET]]
    output_net: str
    supply_net: str
    ground_net: str
    wc_mid: int                # centre wire column


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
