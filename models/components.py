"""Circuit component data models.

Defines the abstract base class `Component` and concrete subclasses for
each supported device type: MOSFET, SubcktInstance, Resistor, Capacitor,
Diode, and BJT.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from .enums import ComponentType, MOSType


# ── Abstract base ──────────────────────────────────────────────────────────

class Component(ABC):
    """Abstract base class for all circuit components."""

    def __init__(self, name: str, comp_type: ComponentType) -> None:
        self.name = name
        self.comp_type = comp_type
        self.params: Dict[str, str] = {}

    @abstractmethod
    def get_terminals(self) -> Dict[str, str]:
        """Return mapping of terminal-role -> net-name."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"


# ── MOSFET ─────────────────────────────────────────────────────────────────

class MOSFET(Component):
    """MOSFET component.

    CDL format::

        M<name> <drain> <gate> <source> <bulk> <model> [params...]
    """

    def __init__(
        self,
        name: str,
        drain: str,
        gate: str,
        source: str,
        bulk: str,
        model: str,
        mos_type: MOSType = MOSType.UNKNOWN,
        params: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name, ComponentType.MOSFET)
        self.drain = drain
        self.gate = gate
        self.source = source
        self.bulk = bulk
        self.model = model
        self.mos_type = mos_type
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"D": self.drain, "G": self.gate, "S": self.source, "B": self.bulk}


# ── Subcircuit Instance ────────────────────────────────────────────────────

class SubcktInstance(Component):
    """Hierarchical subcircuit instantiation (X prefix)."""

    def __init__(
        self,
        name: str,
        subckt_name: str,
        connections: Dict[str, str],
        params: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name, ComponentType.SUBCKT_INST)
        self.subckt_name = subckt_name
        self.connections = connections  # pin -> net
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return dict(self.connections)


# ── Resistor ───────────────────────────────────────────────────────────────

class Resistor(Component):
    """Resistor component (R prefix)."""

    def __init__(
        self, name: str, pos: str, neg: str,
        params: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name, ComponentType.RESISTOR)
        self.pos = pos
        self.neg = neg
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"P": self.pos, "N": self.neg}


# ── Capacitor ──────────────────────────────────────────────────────────────

class Capacitor(Component):
    """Capacitor component (C prefix)."""

    def __init__(
        self, name: str, pos: str, neg: str,
        params: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name, ComponentType.CAPACITOR)
        self.pos = pos
        self.neg = neg
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"P": self.pos, "N": self.neg}


# ── Diode ──────────────────────────────────────────────────────────────────

class Diode(Component):
    """Diode component (D prefix)."""

    def __init__(
        self, name: str, anode: str, cathode: str,
        params: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name, ComponentType.DIODE)
        self.anode = anode
        self.cathode = cathode
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        return {"A": self.anode, "K": self.cathode}


# ── BJT ────────────────────────────────────────────────────────────────────

class BJT(Component):
    """BJT component (Q prefix)."""

    def __init__(
        self,
        name: str,
        collector: str,
        base: str,
        emitter: str,
        substrate: str = "",
        model: str = "",
        params: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(name, ComponentType.BJT)
        self.collector = collector
        self.base = base
        self.emitter = emitter
        self.substrate = substrate
        self.model = model
        if params:
            self.params = params

    def get_terminals(self) -> Dict[str, str]:
        terminals = {"C": self.collector, "B": self.base, "E": self.emitter}
        if self.substrate:
            terminals["S"] = self.substrate
        return terminals
