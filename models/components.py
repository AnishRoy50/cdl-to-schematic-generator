"""Circuit component data models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Optional

from .enums import ComponentType, MOSType


class Component(ABC):
    """Abstract base class for all circuit components."""

    def __init__(self, name: str, comp_type: ComponentType,
                 params: Optional[Dict[str, str]] = None) -> None:
        self.name = name
        self.comp_type = comp_type
        self.params: Dict[str, str] = params or {}

    @abstractmethod
    def get_terminals(self) -> Dict[str, str]: ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.name})"


class MOSFET(Component):
    """MOSFET: M<name> D G S B model [params...]"""

    def __init__(self, name: str, drain: str, gate: str, source: str,
                 bulk: str, model: str, mos_type: MOSType = MOSType.UNKNOWN,
                 params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, ComponentType.MOSFET, params)
        self.drain, self.gate, self.source, self.bulk = drain, gate, source, bulk
        self.model = model
        self.mos_type = mos_type

    def get_terminals(self) -> Dict[str, str]:
        return {"D": self.drain, "G": self.gate, "S": self.source, "B": self.bulk}


class SubcktInstance(Component):
    """Hierarchical subcircuit instantiation (X prefix)."""

    def __init__(self, name: str, subckt_name: str, connections: Dict[str, str],
                 params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, ComponentType.SUBCKT_INST, params)
        self.subckt_name = subckt_name
        self.connections = connections

    def get_terminals(self) -> Dict[str, str]:
        return dict(self.connections)


class Resistor(Component):
    """Resistor (R prefix)."""

    def __init__(self, name: str, pos: str, neg: str,
                 params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, ComponentType.RESISTOR, params)
        self.pos, self.neg = pos, neg

    def get_terminals(self) -> Dict[str, str]:
        return {"P": self.pos, "N": self.neg}


class Capacitor(Component):
    """Capacitor (C prefix)."""

    def __init__(self, name: str, pos: str, neg: str,
                 params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, ComponentType.CAPACITOR, params)
        self.pos, self.neg = pos, neg

    def get_terminals(self) -> Dict[str, str]:
        return {"P": self.pos, "N": self.neg}


class Diode(Component):
    """Diode (D prefix)."""

    def __init__(self, name: str, anode: str, cathode: str,
                 params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, ComponentType.DIODE, params)
        self.anode, self.cathode = anode, cathode

    def get_terminals(self) -> Dict[str, str]:
        return {"A": self.anode, "K": self.cathode}


class BJT(Component):
    """BJT (Q prefix)."""

    def __init__(self, name: str, collector: str, base: str, emitter: str,
                 substrate: str = "", model: str = "",
                 params: Optional[Dict[str, str]] = None) -> None:
        super().__init__(name, ComponentType.BJT, params)
        self.collector, self.base, self.emitter = collector, base, emitter
        self.substrate = substrate
        self.model = model

    def get_terminals(self) -> Dict[str, str]:
        t = {"C": self.collector, "B": self.base, "E": self.emitter}
        if self.substrate:
            t["S"] = self.substrate
        return t
